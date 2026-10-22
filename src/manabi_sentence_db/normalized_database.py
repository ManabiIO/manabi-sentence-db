"""Compile normalized v2 JSONL into a relational SQLite database, offline."""

import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from .serialization import DataError, canonical_json

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


def build_normalized_database(archive_path: Path, output: Path):
    if output.exists() or output.is_symlink():
        raise DataError("Choose a fresh SQLite output path")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".normalized-db-", dir=output.parent) as temporary:
        staged = Path(temporary) / "corpus.sqlite"
        with sqlite3.connect(staged) as db, zipfile.ZipFile(archive_path) as archive:
            db.executescript(DDL)
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("schema_version") != 2:
                raise DataError("Expected normalized corpus v2")
            db.execute(
                "INSERT INTO metadata VALUES (?,?)", ("manifest", canonical_json(manifest).decode())
            )
            for table in ("works", "sentences", "occurrences", "translations", "references"):
                name = table + ".jsonl"
                digest = hashlib.sha256()
                with archive.open(name) as stream:
                    for line in stream:
                        digest.update(line)
                        row = json.loads(line)
                        metadata = canonical_json(row).decode()
                        if table == "works":
                            db.execute(
                                "INSERT INTO works VALUES (?,?,?,?,?,?,?)",
                                tuple(
                                    row[k] for k in ("id", "source_id", "language", "title", "url")
                                )
                                + (row["license"]["id"], metadata),
                            )
                        elif table == "sentences":
                            db.execute(
                                "INSERT INTO sentences VALUES (?,?,?,?)",
                                tuple(row[k] for k in ("id", "language", "text", "text_sha256")),
                            )
                        elif table == "occurrences":
                            db.execute(
                                "INSERT INTO occurrences VALUES (?,?,?,?,?)",
                                tuple(row[k] for k in ("id", "sentence_id", "work_id", "ordinal"))
                                + (metadata,),
                            )
                        elif table == "translations":
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
                            db.execute(
                                "INSERT INTO external_references VALUES (?,?)",
                                (row["id"], metadata),
                            )
                if digest.hexdigest() != manifest["members"][name]:
                    raise DataError("Normalized member digest mismatch")
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise DataError("Broken normalized foreign key")
            db.commit()
            if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise DataError("Invalid normalized SQLite")
        db.close()
        os.replace(staged, output)
    return output
