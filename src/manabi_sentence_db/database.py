"""Compile validated canonical YAML into a portable, relational SQLite database."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path

from .build import iter_records, verify_build
from .licenses import validate_license
from .serialization import DataError, read_json, safe_relative

DDL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = DELETE;
PRAGMA user_version = 1;
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;
CREATE TABLE licenses(id TEXT PRIMARY KEY, url TEXT NOT NULL, notice TEXT) STRICT;
CREATE TABLE sources(id TEXT PRIMARY KEY, language TEXT NOT NULL, config_json TEXT NOT NULL) STRICT;
CREATE TABLE snapshots(id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id), manifest_json TEXT NOT NULL) STRICT;
CREATE TABLE documents(
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
    snapshot_id TEXT NOT NULL REFERENCES snapshots(id), native_id TEXT NOT NULL,
    language TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL,
    license_id TEXT REFERENCES licenses(id), attribution_text TEXT NOT NULL,
    attribution_url TEXT NOT NULL, revision_json TEXT, tags_json TEXT NOT NULL,
    transformations_json TEXT NOT NULL, UNIQUE(source_id,native_id)
) STRICT;
CREATE TABLE sentences(
    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0), language TEXT NOT NULL, text TEXT NOT NULL,
    text_sha256 TEXT NOT NULL, native_id TEXT, review_state TEXT NOT NULL,
    generation_json TEXT, tags_json TEXT NOT NULL, content_flags_json TEXT NOT NULL,
    UNIQUE(document_id,ordinal)
) STRICT;
CREATE TABLE translations(
    id TEXT PRIMARY KEY, sentence_id TEXT NOT NULL REFERENCES sentences(id),
    language TEXT NOT NULL, text TEXT NOT NULL, text_sha256 TEXT NOT NULL,
    source_url TEXT NOT NULL, native_id TEXT, license_id TEXT NOT NULL REFERENCES licenses(id),
    attribution_text TEXT NOT NULL, attribution_url TEXT NOT NULL,
    generation_json TEXT, alignment TEXT
) STRICT;
CREATE TABLE external_references(
    document_id TEXT PRIMARY KEY REFERENCES documents(id), selector_type TEXT NOT NULL,
    locator_json TEXT NOT NULL
) STRICT;
CREATE TABLE sentence_tags(
    sentence_id TEXT NOT NULL REFERENCES sentences(id), tag TEXT NOT NULL,
    PRIMARY KEY(sentence_id,tag)
) STRICT;
CREATE TABLE sentence_content_flags(
    sentence_id TEXT NOT NULL REFERENCES sentences(id), flag TEXT NOT NULL,
    PRIMARY KEY(sentence_id,flag)
) STRICT;
CREATE TABLE sentence_context(
    sentence_id TEXT PRIMARY KEY REFERENCES sentences(id),
    source_range_json TEXT, source_unit_json TEXT
) STRICT;
CREATE INDEX sentence_text_hash ON sentences(language,text_sha256);
CREATE INDEX sentence_document ON sentences(document_id,ordinal);
CREATE INDEX translation_sentence ON translations(sentence_id,language);
CREATE INDEX document_source ON documents(source_id,language);
CREATE INDEX tag_lookup ON sentence_tags(tag,sentence_id);
CREATE INDEX flag_lookup ON sentence_content_flags(flag,sentence_id);
"""


def _json(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _license(connection, value):
    validate_license(value)
    existing = connection.execute(
        "SELECT url,notice FROM licenses WHERE id=?", (value["id"],)
    ).fetchone()
    values = (value["url"], value.get("notice"))
    if existing is not None and existing != values:
        raise DataError(f"Conflicting notices for license {value['id']}")
    connection.execute("INSERT OR IGNORE INTO licenses VALUES (?,?,?)", (value["id"], *values))


def build_database(
    build: Path, output: Path, *, source_id: str | None = None, catalog: dict | None = None
) -> Path:
    catalog = catalog or verify_build(build)
    if output.exists():
        raise DataError(f"Database already exists: {output}. Choose a new path.")
    output.parent.mkdir(parents=True, exist_ok=True)
    sources = [
        entry["source"]
        for entry in catalog["sources"]
        if source_id is None or entry["source"]["id"] == source_id
    ]
    if not sources:
        raise DataError(f"Source is absent from this build: {source_id}")
    allowed_sources = {source["id"] for source in sources}
    descriptor, temporary = tempfile.mkstemp(prefix=f".{output.name}-", dir=output.parent)
    os.close(descriptor)
    staging = Path(temporary)
    connection = None
    try:
        connection = sqlite3.connect(staging)
        connection.executescript(DDL)
        connection.execute("INSERT INTO metadata VALUES ('catalog',?)", (_json(catalog),))
        connection.execute(
            "INSERT INTO metadata VALUES ('sqlite_version',?)", (sqlite3.sqlite_version,)
        )
        for source in sources:
            _license(connection, source["license"])
            connection.execute(
                "INSERT INTO sources VALUES (?,?,?)",
                (source["id"], source["language"], _json(source)),
            )
        for snapshot in catalog["snapshots"]:
            if snapshot["source_id"] not in allowed_sources:
                continue
            manifest = read_json(safe_relative(build, snapshot["manifest"]))
            connection.execute(
                "INSERT INTO snapshots VALUES (?,?,?)",
                (snapshot["snapshot_id"], snapshot["source_id"], _json(manifest)),
            )
        for record in iter_records(build, catalog, source_id):
            license_id = None
            if record["kind"] == "document":
                _license(connection, record["license"])
                license_id = record["license"]["id"]
            connection.execute(
                "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record["id"],
                    record["source_id"],
                    record["snapshot_id"],
                    record["native_id"],
                    record["language"],
                    record["title"],
                    record["url"],
                    license_id,
                    record["attribution"]["text"],
                    record["attribution"]["url"],
                    _json(record["revision"]) if "revision" in record else None,
                    _json(record["tags"]),
                    _json(record.get("transformations", [])),
                ),
            )
            if record["kind"] == "reference":
                connection.execute(
                    "INSERT INTO external_references VALUES (?,?,?)",
                    (record["id"], record["locator"]["type"], _json(record["locator"])),
                )
                continue
            for sentence in record["sentences"]:
                connection.execute(
                    "INSERT INTO sentences VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        sentence["id"],
                        record["id"],
                        sentence["ordinal"],
                        record["language"],
                        sentence["text"],
                        sentence["text_sha256"],
                        sentence.get("native_id"),
                        sentence["review_state"],
                        _json(sentence["generation"]) if "generation" in sentence else None,
                        _json(sentence["tags"]),
                        _json(sentence["content_flags"]),
                    ),
                )
                connection.executemany(
                    "INSERT INTO sentence_tags VALUES (?,?)",
                    [(sentence["id"], tag) for tag in sentence["tags"]],
                )
                connection.executemany(
                    "INSERT INTO sentence_content_flags VALUES (?,?)",
                    [(sentence["id"], flag) for flag in sentence["content_flags"]],
                )
                if "source_range" in sentence or "source_unit" in sentence:
                    connection.execute(
                        "INSERT INTO sentence_context VALUES (?,?,?)",
                        (sentence["id"],
                         _json(sentence["source_range"]) if "source_range" in sentence else None,
                         _json(sentence["source_unit"]) if "source_unit" in sentence else None),
                    )
                    for translation in sentence.get("source_unit", {}).get("translations", []):
                        _license(connection, translation["license"])
                for translation in sentence["translations"]:
                    _license(connection, translation["license"])
                    connection.execute(
                        "INSERT INTO translations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            translation["id"],
                            sentence["id"],
                            translation["language"],
                            translation["text"],
                            translation["text_sha256"],
                            translation["source_url"],
                            translation.get("native_id"),
                            translation["license"]["id"],
                            translation["attribution"]["text"],
                            translation["attribution"]["url"],
                            _json(translation["generation"])
                            if "generation" in translation
                            else None,
                            translation.get("alignment"),
                        ),
                    )
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise DataError("SQLite foreign-key validation failed")
        connection.commit()
        connection.execute("PRAGMA optimize")
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise DataError("SQLite integrity validation failed")
        connection.close()
        connection = None
        os.replace(staging, output)
        return output
    except sqlite3.Error as exc:
        raise DataError(f"SQLite build failed: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()
        staging.unlink(missing_ok=True)

