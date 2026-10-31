"""Compile normalized v2 JSONL into a relational SQLite database, offline."""

import hashlib
import os
import sqlite3
import tempfile
import unicodedata
import zipfile
from contextlib import closing
from pathlib import Path

from .licenses import validate_rights
from .serialization import DataError, canonical_json, parse_json
from .validation import validate_record, validate_source_unit

DDL = """
PRAGMA foreign_keys=ON;
PRAGMA user_version=2;
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL) STRICT;
CREATE TABLE works(id TEXT PRIMARY KEY,source_id TEXT NOT NULL,language TEXT NOT NULL,title TEXT NOT NULL,url TEXT NOT NULL,license_id TEXT NOT NULL,metadata_json TEXT NOT NULL) STRICT;
CREATE TABLE sentences(id TEXT PRIMARY KEY,language TEXT NOT NULL,text TEXT NOT NULL,text_sha256 TEXT NOT NULL,UNIQUE(language,text_sha256)) STRICT;
CREATE TABLE occurrences(id TEXT PRIMARY KEY,sentence_id TEXT NOT NULL REFERENCES sentences(id),work_id TEXT NOT NULL REFERENCES works(id),ordinal INTEGER NOT NULL,metadata_json TEXT NOT NULL,UNIQUE(work_id,ordinal)) STRICT;
CREATE INDEX occurrence_sentence ON occurrences(sentence_id);
CREATE TABLE translations(id TEXT PRIMARY KEY,sentence_id TEXT NOT NULL REFERENCES sentences(id),occurrence_id TEXT NOT NULL REFERENCES occurrences(id),language TEXT NOT NULL,text TEXT NOT NULL,license_id TEXT NOT NULL,metadata_json TEXT NOT NULL) STRICT;
CREATE INDEX translation_sentence ON translations(sentence_id,language);
CREATE TABLE external_references(id TEXT PRIMARY KEY,metadata_json TEXT NOT NULL) STRICT;
"""


TABLES = ("works", "sentences", "occurrences", "translations", "references")
MAX_RECORD_BYTES = 32 * 1024 * 1024  # Same bound as canonical documents.


def _object(data: bytes) -> dict:
    try:
        value = parse_json(data)
    except (ValueError, UnicodeError) as exc:
        raise DataError(f"Invalid normalized JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise DataError("Normalized records must be JSON objects")
    return value


def _manifest(archive: zipfile.ZipFile) -> dict:
    if len(set(archive.namelist())) != len(archive.namelist()):
        raise DataError("Duplicate ZIP members")
    if archive.getinfo("manifest.json").file_size > MAX_RECORD_BYTES:
        raise DataError("Oversized normalized manifest")
    manifest = _object(archive.read("manifest.json"))
    if manifest.get("schema_version") != 2 or manifest.get("kind") != "normalized-corpus":
        raise DataError("Expected normalized corpus v2")
    members, counts = manifest.get("members"), manifest.get("counts")
    if not isinstance(members, dict) or set(members) != {t + ".jsonl" for t in TABLES}:
        raise DataError("Invalid normalized member inventory")
    if not isinstance(counts, dict) or set(counts) != set(TABLES):
        raise DataError("Invalid normalized table counts")
    for table in TABLES:
        if type(counts[table]) is not int or counts[table] < 0:
            raise DataError("Invalid normalized table count")
        digest = members[table + ".jsonl"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise DataError("Invalid normalized member digest")
    return manifest


def _rows(archive: zipfile.ZipFile, table: str, manifest: dict):
    name, digest, count = table + ".jsonl", hashlib.sha256(), 0
    with archive.open(name) as stream:
        while line := stream.readline(MAX_RECORD_BYTES + 1):
            if len(line) > MAX_RECORD_BYTES:
                raise DataError("Normalized record exceeds size bound")
            digest.update(line)
            count += 1
            yield _object(line)
    if digest.hexdigest() != manifest["members"][name]:
        raise DataError("Normalized member digest mismatch")
    if count != manifest["counts"][table]:
        raise DataError("Normalized table count mismatch")


def _check_text(row: dict, *, sentence: bool = False) -> None:
    text, language = row.get("text"), row.get("language")
    if not isinstance(text, str) or not text or not isinstance(language, str) or not language:
        raise DataError("Invalid normalized text or language")
    if unicodedata.normalize("NFC", text) != text:
        raise DataError("Normalized text must be NFC")
    if row.get("text_sha256") != hashlib.sha256(text.encode("utf-8")).hexdigest():
        raise DataError("Normalized text hash mismatch")
    if sentence and row.get("id") != "s_" + hashlib.sha256(
        canonical_json([language, text])
    ).hexdigest():
        raise DataError("Normalized sentence identity mismatch")


def _provenance(archive, manifest, db):
    """Preserve optional canonical provenance, verifying refinement bindings.

    Standalone normalized archives predate embedded canonical catalogs. Keep
    supporting those, but never discard or accept an incomplete refinement.
    """
    from .refinement import PARENT_PATH, verify_refinement

    names = set(archive.namelist())

    def read_member(name):
        if name not in names:
            raise DataError("Missing normalized provenance: " + name)
        if archive.getinfo(name).file_size > MAX_RECORD_BYTES:
            raise DataError("Oversized normalized provenance: " + name)
        with archive.open(name) as stream:
            value = stream.read(MAX_RECORD_BYTES + 1)
        if len(value) > MAX_RECORD_BYTES:
            raise DataError("Oversized normalized provenance: " + name)
        return value

    if "catalog.json" not in names:
        if PARENT_PATH in names:
            raise DataError("Refinement parent requires its canonical catalog")
        return
    catalog = _object(read_member("catalog.json"))
    if catalog.get("build_id") != manifest.get("build_id"):
        raise DataError("Normalized manifest/catalog build identity differs")
    options = catalog.get("options", {})
    if not isinstance(options, dict):
        raise DataError("Invalid normalized canonical options")
    parent_records = []

    def checked_parent(entry):
        raw = read_member(entry["path"])
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise DataError("Normalized refinement parent checksum differs")
        parent_records.append(_object(raw))
        return zipfile.Path(archive, entry["path"])

    if ("refinement" in options or "refinement_parent" in catalog or PARENT_PATH in names):
        if "refinement" not in options or "refinement_parent" not in catalog:
            raise DataError("Incomplete normalized refinement receipt")
        verify_refinement(catalog, checked_parent)
    db.execute("INSERT INTO metadata VALUES (?,?)", ("catalog", canonical_json(catalog).decode()))
    if parent_records:
        db.execute("INSERT INTO metadata VALUES (?,?)",
                   ("refinement_parent_catalog", canonical_json(parent_records[0]).decode()))


def build_normalized_database(archive_path: Path, output: Path):
    if output.exists() or output.is_symlink():
        raise DataError("Choose a fresh SQLite output path")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".normalized-db-", dir=output.parent) as temporary:
        staged = Path(temporary) / "corpus.sqlite"
        with closing(sqlite3.connect(staged)) as db, zipfile.ZipFile(archive_path) as archive:
            db.executescript(DDL)
            manifest = _manifest(archive)
            db.execute(
                "INSERT INTO metadata VALUES (?,?)", ("manifest", canonical_json(manifest).decode())
            )
            _provenance(archive, manifest, db)
            for table in TABLES:
                for row in _rows(archive, table, manifest):
                    # Sentence rows store their text/hash in typed columns;
                    # serializing the complete row would be discarded below.
                    metadata = canonical_json(row).decode() if table != "sentences" else None
                    if table == "works":
                        validate_rights(row, source_url_key="url")
                        db.execute(
                            "INSERT INTO works VALUES (?,?,?,?,?,?,?)",
                            tuple(
                                row[k] for k in ("id", "source_id", "language", "title", "url")
                            )
                            + (row["license"]["id"], metadata),
                        )
                    elif table == "sentences":
                        _check_text(row, sentence=True)
                        db.execute(
                            "INSERT INTO sentences VALUES (?,?,?,?)",
                            tuple(row[k] for k in ("id", "language", "text", "text_sha256")),
                        )
                    elif table == "occurrences":
                        if "source_unit" in row:
                            sentence = db.execute(
                                "SELECT text FROM sentences WHERE id=?", (row["sentence_id"],)
                            ).fetchone()
                            if sentence is None:
                                raise DataError("Source-unit occurrence refers to a missing sentence")
                            validate_source_unit(row["source_unit"], sentence[0])
                        db.execute(
                            "INSERT INTO occurrences VALUES (?,?,?,?,?)",
                            tuple(row[k] for k in ("id", "sentence_id", "work_id", "ordinal"))
                            + (metadata,),
                        )
                    elif table == "translations":
                        validate_rights(row, source_url_key="source_url")
                        _check_text(row)
                        db.execute(
                            "INSERT INTO translations VALUES (?,?,?,?,?,?,?)",
                            tuple(
                                row[k]
                                for k in (
                                    "id",
                                    "sentence_id",
                                    "occurrence_id",
                                    "language",
                                    "text",
                                )
                            )
                            + (row["license"]["id"], metadata),
                        )
                    else:
                        if row.get("kind") != "reference":
                            raise DataError("Expected normalized reference record")
                        validate_record(row)
                        db.execute(
                            "INSERT INTO external_references VALUES (?,?)",
                            (row["id"], metadata),
                        )
            if db.execute(
                "SELECT 1 FROM occurrences o JOIN sentences s ON s.id=o.sentence_id "
                "JOIN works w ON w.id=o.work_id WHERE s.language != w.language LIMIT 1"
            ).fetchone():
                raise DataError("Occurrence sentence language does not match its work")
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise DataError("Broken normalized foreign key")
            if db.execute(
                "SELECT 1 FROM translations t JOIN occurrences o ON o.id=t.occurrence_id "
                "WHERE t.sentence_id != o.sentence_id LIMIT 1"
            ).fetchone():
                raise DataError("Translation does not match its occurrence's sentence")
            if db.execute(
                "SELECT 1 FROM translations t JOIN occurrences o ON o.id=t.occurrence_id "
                "WHERE json_type(o.metadata_json, '$.source_unit') IS NOT NULL LIMIT 1"
            ).fetchone():
                raise DataError("Split source-unit translations are not sentence-aligned")
            db.commit()
            if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise DataError("Invalid normalized SQLite")
        os.replace(staged, output)
    return output

