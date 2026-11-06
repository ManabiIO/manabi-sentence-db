"""Select complete works from an existing normalized ZIP without raw extraction.

Only identity and ownership columns enter SQLite. Bulk records remain compressed
until streamed into the final normalized v2 ZIP; selected records are unchanged.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import tempfile
import zipfile
from contextlib import ExitStack, closing
from pathlib import Path

import zstandard

from .licenses import validate_rights
from .normalized import sentence_identity
from .normalized_database import (
    MAX_RECORD_BYTES,
    TABLES,
    _check_text,
    _manifest,
    _provenance,
    _rows,
)
from .serialization import DataError, canonical_json, digest_json, sha256_file
from .validation import validate_source_unit

MAX_SELECTED_WORKS = 80_000
MAX_MANIFEST_BYTES = 4 * 1024 * 1024

_DDL = """
PRAGMA journal_mode=OFF;
PRAGMA temp_store=FILE;
PRAGMA cache_size=-2048;
CREATE TABLE works(id TEXT PRIMARY KEY, language TEXT, selected INTEGER NOT NULL);
CREATE TABLE sentences(id TEXT PRIMARY KEY, language TEXT NOT NULL, seen INTEGER NOT NULL);
CREATE TABLE occurrences(id TEXT PRIMARY KEY, sentence_id TEXT NOT NULL,
    work_id TEXT NOT NULL, ordinal INTEGER, selected INTEGER NOT NULL,
    source_unit INTEGER NOT NULL, previous_id TEXT, next_id TEXT);
CREATE UNIQUE INDEX selected_ordinal ON occurrences(work_id,ordinal) WHERE selected=1;
CREATE TABLE translations(id TEXT PRIMARY KEY);
"""


def _identity(value):
    if not isinstance(value, str) or not value.strip():
        raise DataError("Normalized identity must be a nonempty string")
    return value


def _signature(path):
    value = path.stat()
    if not stat.S_ISREG(value.st_mode):
        raise DataError("Normalized input must be a regular file")
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _selection(value, manifest):
    if (not isinstance(value, dict)
            or set(value) != {"schema_version", "build_id", "work_ids"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or not isinstance(manifest.get("build_id"), str) or not manifest["build_id"]
            or value["build_id"] != manifest["build_id"]):
        raise DataError("Work selection must bind schema version 1 to this exact build")
    ids = value["work_ids"]
    if (not isinstance(ids, list) or not 1 <= len(ids) <= MAX_SELECTED_WORKS
            or any(not isinstance(item, str) or not item.strip() or len(item) > 256
                   for item in ids) or len(set(ids)) != len(ids)):
        raise DataError("Work selection requires 1..80000 unique, nonempty work-ID strings")
    return {**value, "work_ids": sorted(ids)}


def _inventory(archive):
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise DataError("Duplicate ZIP members")
    for member in archive.infolist():
        name = member.filename
        if (not name or "\\" in name or ":" in name or name.startswith("/")
                or any(part in {"", ".", ".."} for part in name.split("/"))
                or any(ord(char) < 32 or ord(char) == 127 for char in name)
                or stat.S_IFMT(member.external_attr >> 16) not in (0, stat.S_IFREG)):
            raise DataError("Unsafe normalized ZIP member: " + name)
        if name not in {table + ".jsonl" for table in TABLES}:
            if member.file_size > MAX_RECORD_BYTES:
                raise DataError("Oversized normalized provenance: " + name)
    required = {"manifest.json", *(table + ".jsonl" for table in TABLES)}
    if not required.issubset(names):
        raise DataError("Missing normalized ZIP members")


def _zip_info(name):
    member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    member.compress_type = zipfile.ZIP_DEFLATED
    member.create_system = 3
    member.external_attr = 0o100644 << 16
    return member


def _write_archive(root, incoming, manifest):
    """Copy ancillary bytes directly, including all snapshot/lineage receipts."""
    staged = root / "corpus.zip"
    logical = {table + ".jsonl" for table in TABLES}
    with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6) as outgoing:
        for table in TABLES:
            name, digest = table + ".jsonl", hashlib.sha256()
            with zstandard.open(root / (name + ".zst"), "rb") as source:
                with outgoing.open(_zip_info(name), "w", force_zip64=True) as target:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        target.write(chunk)
                        digest.update(chunk)
            if digest.hexdigest() != manifest["members"][name]:
                raise DataError("Normalized selection staging bytes changed")
        outgoing.writestr(_zip_info("manifest.json"), canonical_json(manifest), compresslevel=6)
        # Provenance validation uses zipfile.Path, whose FastLookup can add
        # implied directory names to namelist(). Only physical file entries
        # have byte ranges and belong in the normalized output.
        ancillary = {member.filename for member in incoming.infolist()} - logical - {"manifest.json"}
        for name in sorted(ancillary):
            with incoming.open(name) as source:
                with outgoing.open(_zip_info(name), "w", force_zip64=True) as target:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        target.write(chunk)
    return staged


def select_normalized_works(archive_path: Path, output: Path, *, work_selection,
                            progress=None) -> Path:
    """Export whole selected works from one normalized v2 archive, offline.

    Selection binds the original build ID and 1..80000 unique work IDs. All
    five logical input members are streamed and verified, including discarded
    records. Ancillary members retain their original bytes. No source quality
    assessment or canonical/raw corpus access occurs. ``progress`` accepts text.
    """
    notify = progress or (lambda message: None)
    archive_path, output = Path(archive_path).resolve(strict=True), Path(output).absolute()
    if output.is_symlink() or output.resolve() != output:
        raise DataError("Use a canonical normalized output path outside symlinks")
    if output.exists():
        raise DataError("Choose a fresh normalized output path")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.parent.resolve() != output.parent:
        raise DataError("Use a canonical normalized output parent")
    signature = _signature(archive_path)
    notify("Hashing normalized input ZIP")
    input_digest = sha256_file(archive_path)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            _inventory(archive)
            original = _manifest(archive)
            selection = _selection(work_selection, original)
            selected = set(selection["work_ids"])
            with tempfile.TemporaryDirectory(prefix=".normalized-selection-",
                                             dir=output.parent) as temporary:
                root = Path(temporary)
                with closing(sqlite3.connect(root / "identities.sqlite")) as db, ExitStack() as stack:
                    db.executescript(_DDL)
                    # Existing receipt validation does not access raw/canonical sources.
                    # Keep provenance metadata out of the disk identity ledger as well.
                    with closing(sqlite3.connect(":memory:")) as provenance:
                        provenance.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)")
                        _provenance(archive, original, provenance)
                    handles = {table: stack.enter_context(zstandard.open(
                        root / (table + ".jsonl.zst"), "wb",
                        cctx=zstandard.ZstdCompressor(level=3, write_checksum=True),
                    )) for table in TABLES}
                    counts = dict.fromkeys(TABLES, 0)
                    digests = {table: hashlib.sha256() for table in TABLES}

                    def write(table, row):
                        data = canonical_json(row) + b"\n"
                        if len(data) > MAX_RECORD_BYTES:
                            raise DataError("Normalized selected record exceeds size bound")
                        handles[table].write(data)
                        digests[table].update(data)
                        counts[table] += 1

                    notify("Selecting normalized whole works")
                    for row in _rows(archive, "works", original):
                        identity = _identity(row.get("id"))
                        keep = identity in selected
                        language = row.get("language") if keep else None
                        if keep:
                            for key in ("source_id", "language", "title"):
                                _identity(row.get(key))
                            validate_rights(row, source_url_key="url")
                        db.execute("INSERT INTO works VALUES (?,?,?)", (identity, language, keep))
                        if keep:
                            write("works", row)
                    if counts["works"] != len(selected):
                        raise DataError("Selected works absent from normalized archive")

                    notify("Selecting normalized occurrences and context")
                    for row in _rows(archive, "occurrences", original):
                        identity, work, sentence = (_identity(row.get(key))
                                                    for key in ("id", "work_id", "sentence_id"))
                        keep = work in selected
                        ordinal, previous, following = None, None, None
                        unit = "source_unit" in row
                        if keep:
                            ordinal = row.get("ordinal")
                            if type(ordinal) is not int or ordinal < 0:
                                raise DataError("Invalid normalized occurrence ordinal")
                            previous, following = row.get("previous_id"), row.get("next_id")
                            for link in (previous, following):
                                if link is not None:
                                    _identity(link)
                            language = db.execute("SELECT language FROM works WHERE id=?",
                                                  (work,)).fetchone()[0]
                            known = db.execute("SELECT language FROM sentences WHERE id=?",
                                               (sentence,)).fetchone()
                            if known and known[0] != language:
                                raise DataError("Occurrence sentence language does not match its work")
                            db.execute("INSERT OR IGNORE INTO sentences VALUES (?,?,0)",
                                       (sentence, language))
                            if unit:
                                value = row["source_unit"]
                                if not isinstance(value, dict):
                                    raise DataError("Invalid source-unit metadata")
                                # Validate the unit before using its offsets; its fragment
                                # identity must equal the independently verified sentence.
                                text = value.get("text")
                                if (not isinstance(text, str) or type(value.get("start")) is not int
                                        or type(value.get("end")) is not int):
                                    raise DataError("Invalid source-unit metadata")
                                fragment = text[value["start"]:value["end"]]
                                validate_source_unit(value, fragment)
                                if sentence_identity(language, fragment) != sentence:
                                    raise DataError("Source-unit fragment does not match its sentence")
                            write("occurrences", row)
                        db.execute("INSERT INTO occurrences VALUES (?,?,?,?,?,?,?,?)",
                                   (identity, sentence, work, ordinal, keep, unit, previous, following))
                    if db.execute("SELECT 1 FROM occurrences o LEFT JOIN occurrences n "
                                  "ON n.id=o.next_id WHERE o.selected=1 AND o.next_id IS NOT NULL "
                                  "AND (n.id IS NULL OR n.work_id!=o.work_id OR n.ordinal!=o.ordinal+1) "
                                  "UNION ALL SELECT 1 FROM occurrences o LEFT JOIN occurrences p "
                                  "ON p.id=o.previous_id WHERE o.selected=1 AND o.previous_id IS NOT NULL "
                                  "AND (p.id IS NULL OR p.work_id!=o.work_id OR p.ordinal!=o.ordinal-1) "
                                  "LIMIT 1").fetchone():
                        raise DataError("Broken normalized occurrence context link")

                    notify("Selecting referenced normalized sentences")
                    for row in _rows(archive, "sentences", original):
                        known = db.execute("SELECT language,seen FROM sentences WHERE id=?",
                                           (_identity(row.get("id")),)).fetchone()
                        if known is None:
                            continue
                        if known[1]:
                            raise DataError("Duplicate selected sentence identity")
                        _check_text(row, sentence=True)
                        if known[0] != row["language"]:
                            raise DataError("Occurrence sentence language does not match its work")
                        db.execute("UPDATE sentences SET seen=1 WHERE id=?", (row["id"],))
                        write("sentences", row)
                    if db.execute("SELECT 1 FROM sentences WHERE seen=0 LIMIT 1").fetchone():
                        raise DataError("Selected occurrence refers to a missing sentence")

                    notify("Selecting owned normalized translations")
                    for row in _rows(archive, "translations", original):
                        identity = _identity(row.get("id"))
                        db.execute("INSERT INTO translations VALUES (?)", (identity,))
                        owner_id, sentence = row.get("occurrence_id"), row.get("sentence_id")
                        if owner_id is not None:
                            _identity(owner_id)
                        _identity(sentence)
                        owner = db.execute("SELECT sentence_id,selected,source_unit FROM occurrences "
                                           "WHERE id=?", (owner_id,)).fetchone()
                        if owner is None:
                            if db.execute("SELECT 1 FROM sentences WHERE id=?", (sentence,)).fetchone():
                                raise DataError("Selected translation refers to a missing occurrence")
                            continue
                        if owner[0] != sentence:
                            raise DataError("Translation does not match its occurrence's sentence")
                        if not owner[1]:
                            # Shared sentence identity does not transfer translation rights.
                            continue
                        if owner[2]:
                            raise DataError("Split source-unit translations are not sentence-aligned")
                        validate_rights(row, source_url_key="source_url")
                        _check_text(row)
                        write("translations", row)
                    for _ in _rows(archive, "references", original):
                        pass  # Whole-work selection deliberately excludes references.
                    for handle in handles.values():
                        handle.close()
                    manifest = {**original, "scope": "sample", "counts": counts,
                                "members": {table + ".jsonl": digests[table].hexdigest()
                                            for table in TABLES},
                                "work_selection": selection,
                                "work_selection_sha256": digest_json(selection),
                                "normalized_selection_provenance": {
                                    "schema_version": 1, "input_zip_sha256": input_digest}}
                    if len(canonical_json(manifest)) > MAX_MANIFEST_BYTES:
                        raise DataError("Oversized normalized selection manifest")
                notify("Writing verified normalized selection ZIP")
                staged = _write_archive(root, archive, manifest)
                if _signature(archive_path) != signature:
                    raise DataError("Normalized input ZIP changed during selection")
                with staged.open("rb") as stream:
                    os.fsync(stream.fileno())
                # Hard-link publication is atomic and refuses a concurrently created
                # destination. TemporaryDirectory removes only task-owned staging.
                try:
                    os.link(staged, output)
                except FileExistsError as exc:
                    raise DataError("Choose a fresh normalized output path") from exc
                directory = os.open(output.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        return output
    except (sqlite3.IntegrityError, zipfile.BadZipFile, KeyError) as exc:
        raise DataError("Invalid normalized archive or duplicate identity: " + str(exc)) from exc
