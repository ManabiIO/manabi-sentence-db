"""Refine Wikipedia occurrences offline, without expanding bulk text onto disk."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import zipfile
import zlib
from collections import Counter
from contextlib import ExitStack, closing
from pathlib import Path

import zstandard

from . import wikipedia_quality
from .licenses import validate_rights
from .normalized import sentence_identity
from .normalized_database import TABLES, _check_text, _manifest, _provenance, _rows
from .normalized_selection import (
    MAX_MANIFEST_BYTES,
    MAX_RECORD_BYTES,
    _identity,
    _inventory,
    _signature,
    _write_archive,
)
from .serialization import DataError, canonical_json, sha256_file
from .validation import validate_record, validate_source_unit

_DDL = """
PRAGMA journal_mode=OFF;
PRAGMA temp_store=FILE;
PRAGMA cache_size=-2048;
CREATE TABLE works(id TEXT PRIMARY KEY, language TEXT, targeted INTEGER);
CREATE TABLE sentences(id TEXT PRIMARY KEY, language TEXT, rejected INTEGER, reason TEXT);
CREATE TABLE occurrences(id TEXT PRIMARY KEY, sentence_id TEXT, work_id TEXT,
 ordinal INTEGER, previous_id TEXT, next_id TEXT, unit INTEGER, kept INTEGER);
CREATE UNIQUE INDEX ordinal ON occurrences(work_id,ordinal);
CREATE INDEX sentence_owner ON occurrences(sentence_id,kept);
CREATE INDEX work_owner ON occurrences(work_id,kept);
CREATE TABLE targets(id TEXT PRIMARY KEY);
CREATE TABLE translations(id TEXT PRIMARY KEY);
CREATE TABLE refs(id TEXT PRIMARY KEY);
"""


MAX_REFINEMENT_DEPTH = 16


def _validate_receipt(receipt, build_id, depth=1):
    """Validate bounded normalized lineage without reinterpreting canonical ancestry."""
    required = {
        "schema_version", "transform", "input_zip_sha256", "original_build_id",
        "input_manifest_sha256", "policy_version", "policy_sha256", "implementation_sha256",
        "input_counts", "output_counts", "rejected_occurrences_by_reason",
    }
    if (depth > MAX_REFINEMENT_DEPTH or not isinstance(receipt, dict)
            or set(receipt) not in (required, required | {"parent_receipt", "parent_receipt_sha256"})
            or type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1
            or receipt.get("transform") != "normalized-wikipedia-refinement-v1"
            or receipt.get("original_build_id") != build_id):
        raise DataError("Invalid or excessive normalized refinement lineage")
    _identity(receipt.get("policy_version"))
    for key in ("input_zip_sha256", "input_manifest_sha256", "policy_sha256",
                "implementation_sha256", "parent_receipt_sha256"):
        if key in receipt:
            value = receipt[key]
            if (not isinstance(value, str) or len(value) != 64
                    or any(char not in "0123456789abcdef" for char in value)):
                raise DataError("Invalid normalized refinement receipt digest")
    for key in ("input_counts", "output_counts"):
        value = receipt[key]
        if (not isinstance(value, dict) or set(value) != set(TABLES)
                or any(type(n) is not int or n < 0 for n in value.values())):
            raise DataError("Invalid normalized refinement receipt counts")
    before, after = receipt["input_counts"], receipt["output_counts"]
    reasons = receipt["rejected_occurrences_by_reason"]
    if (not isinstance(reasons, dict)
            or any(not isinstance(k, str) or not k.strip() or type(v) is not int or v <= 0
                   for k, v in reasons.items())
            or any(after[t] > before[t] for t in TABLES)
            or after["references"] != before["references"]
            or sum(reasons.values()) != before["occurrences"] - after["occurrences"]):
        raise DataError("Inconsistent normalized refinement receipt counts")
    if "parent_receipt" in receipt:
        parent = receipt["parent_receipt"]
        if hashlib.sha256(canonical_json(parent)).hexdigest() != receipt["parent_receipt_sha256"]:
            raise DataError("Normalized refinement parent receipt checksum differs")
        _validate_receipt(parent, build_id, depth + 1)


def refine_normalized_wikipedia(archive_path: Path, output: Path, *, progress=None) -> Path:
    """Apply current Japanese Wikipedia gates; retain independent ownership.

    All input rows are hash/count checked and structurally validated before
    publication. SQLite contains identities, ownership and decisions only. Re-read
    verified ZIP streams supply output text to checksum-enabled zstd staging.
    Canonical build/catalog ancestry remains original; the manifest records this
    distinct normalized transformation without claiming human review.
    """
    notify = progress or (lambda message: None)
    archive_path = Path(archive_path).resolve(strict=True)
    output = Path(output).absolute()
    if output.is_symlink() or output.resolve() != output or output.exists():
        raise DataError("Choose a fresh canonical normalized output path")
    output.parent.mkdir(parents=True, exist_ok=True)
    signature = _signature(archive_path)
    notify("Hashing normalized refinement input")
    input_digest = sha256_file(archive_path)
    policy_digest = sha256_file(Path(wikipedia_quality.__file__))
    implementation_digest = sha256_file(Path(__file__))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            _inventory(archive)
            if archive.getinfo("manifest.json").file_size > MAX_MANIFEST_BYTES:
                raise DataError("Oversized normalized refinement manifest")
            original = _manifest(archive)
            _identity(original.get("build_id"))
            prior_receipt = original.get("normalized_refinement_provenance")
            if "normalized_refinement_provenance" in original:
                _validate_receipt(prior_receipt, original["build_id"])
                if prior_receipt["output_counts"] != original["counts"] and "work_selection" not in original:
                    raise DataError("Normalized refinement receipt does not describe input counts")
            with tempfile.TemporaryDirectory(prefix=".normalized-refinement-",
                                             dir=output.parent) as temporary:
                root = Path(temporary)
                with closing(sqlite3.connect(root / "identities.sqlite")) as db:
                    db.executescript(_DDL)
                    with closing(sqlite3.connect(":memory:")) as provenance:
                        provenance.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)")
                        _provenance(archive, original, provenance)
                    notify("Validating normalized identities and current Wikipedia policy")
                    for row in _rows(archive, "works", original):
                        for key in ("id", "source_id", "language", "title"):
                            _identity(row.get(key))
                        validate_rights(row, source_url_key="url")
                        db.execute("INSERT INTO works VALUES (?,?,?)", (
                            row["id"], row["language"], row["language"].split("-", 1)[0] == "ja"
                            and row["source_id"].startswith("wikipedia-")))
                    # Identify targeted ownership before looking at text. Shared text
                    # is assessed once and the decision applies only to those owners.
                    for row in _rows(archive, "occurrences", original):
                        if db.execute("SELECT 1 FROM works WHERE id=? AND targeted=1",
                                      (_identity(row.get("work_id")),)).fetchone():
                            db.execute("INSERT OR IGNORE INTO targets VALUES (?)",
                                       (_identity(row.get("sentence_id")),))
                    for row in _rows(archive, "sentences", original):
                        _identity(row.get("id"))
                        _check_text(row, sentence=True)
                        reason = (wikipedia_quality.assess_wikipedia_sentence(row["text"])[0]
                                  if db.execute("SELECT 1 FROM targets WHERE id=?",
                                                (row["id"],)).fetchone() else None)
                        db.execute("INSERT INTO sentences VALUES (?,?,?,?)",
                                   (row["id"], row["language"], reason is not None, reason))
                    reasons = Counter()
                    for row in _rows(archive, "occurrences", original):
                        identity, sentence, work = (_identity(row.get(key))
                                                   for key in ("id", "sentence_id", "work_id"))
                        owner = db.execute("SELECT language,targeted FROM works WHERE id=?",
                                           (work,)).fetchone()
                        text = db.execute("SELECT language,rejected,reason FROM sentences WHERE id=?",
                                          (sentence,)).fetchone()
                        if owner is None or text is None or owner[0] != text[0]:
                            raise DataError("Missing normalized reference or mismatched language")
                        ordinal = row.get("ordinal")
                        if type(ordinal) is not int or not 0 <= ordinal <= 9223372036854775807:
                            raise DataError("Invalid normalized occurrence ordinal")
                        links = (row.get("previous_id"), row.get("next_id"))
                        for link in links:
                            if link is not None:
                                _identity(link)
                        unit = "source_unit" in row
                        if unit:
                            value = row["source_unit"]
                            if not isinstance(value, dict):
                                raise DataError("Invalid source-unit metadata")
                            source_text, start, end = (value.get(k) for k in ("text", "start", "end"))
                            if (not isinstance(source_text, str) or type(start) is not int
                                    or type(end) is not int):
                                raise DataError("Invalid source-unit metadata")
                            fragment = source_text[start:end]
                            validate_source_unit(value, fragment)
                            if sentence_identity(owner[0], fragment) != sentence:
                                raise DataError("Source-unit fragment differs from owned sentence")
                        kept = not (owner[1] and text[1])
                        if not kept:
                            reasons[text[2]] += 1
                        db.execute("INSERT INTO occurrences VALUES (?,?,?,?,?,?,?,?)",
                                   (identity, sentence, work, ordinal, *links, unit, kept))
                    for column, offset in (("previous_id", -1), ("next_id", 1)):
                        if db.execute(f"SELECT 1 FROM occurrences o LEFT JOIN occurrences n "
                                      f"ON n.id=o.{column} WHERE o.{column} IS NOT NULL AND "
                                      "(n.id IS NULL OR n.work_id!=o.work_id OR "
                                      "n.ordinal!=o.ordinal+?) LIMIT 1", (offset,)).fetchone():
                            raise DataError("Broken normalized occurrence context link")
                    for row in _rows(archive, "translations", original):
                        db.execute("INSERT INTO translations VALUES (?)", (_identity(row.get("id")),))
                        sentence = _identity(row.get("sentence_id"))
                        owner = db.execute("SELECT sentence_id,unit FROM occurrences WHERE id=?",
                                           (_identity(row.get("occurrence_id")),)).fetchone()
                        if owner is None or owner[0] != sentence or owner[1]:
                            raise DataError("Invalid normalized translation ownership")
                        validate_rights(row, source_url_key="source_url")
                        _check_text(row)
                    for row in _rows(archive, "references", original):
                        db.execute("INSERT INTO refs VALUES (?)", (_identity(row.get("id")),))
                        if row.get("kind") != "reference":
                            raise DataError("Expected normalized reference record")
                        validate_record(row)
                    if db.execute("SELECT 1 FROM sentences s WHERE NOT EXISTS "
                                  "(SELECT 1 FROM occurrences o WHERE o.sentence_id=s.id) "
                                  "LIMIT 1").fetchone():
                        raise DataError("Unowned normalized sentence has no occurrence rights context")
                    counts = dict.fromkeys(TABLES, 0)
                    digests = {table: hashlib.sha256() for table in TABLES}
                    with ExitStack() as stack:
                        handles = {table: stack.enter_context(zstandard.open(
                            root / (table + ".jsonl.zst"), "wb",
                            cctx=zstandard.ZstdCompressor(level=3, write_checksum=True)))
                                   for table in TABLES}
                        notify("Staging refined normalized members in compressed form")
                        for table in TABLES:
                            for row in _rows(archive, table, original):
                                if table == "works":
                                    targeted = db.execute("SELECT targeted FROM works WHERE id=?",
                                                          (row["id"],)).fetchone()[0]
                                    keep = not targeted or db.execute(
                                        "SELECT 1 FROM occurrences WHERE work_id=? AND kept=1 LIMIT 1",
                                        (row["id"],)).fetchone()
                                elif table == "sentences":
                                    keep = db.execute("SELECT 1 FROM occurrences WHERE sentence_id=? "
                                                      "AND kept=1 LIMIT 1", (row["id"],)).fetchone()
                                elif table in ("occurrences", "translations"):
                                    owner = row["id"] if table == "occurrences" else row["occurrence_id"]
                                    keep = db.execute("SELECT kept FROM occurrences WHERE id=?",
                                                      (owner,)).fetchone()[0]
                                    if keep and table == "occurrences":
                                        row = dict(row)
                                        for key in ("previous_id", "next_id"):
                                            if row.get(key) is not None and not db.execute(
                                                "SELECT kept FROM occurrences WHERE id=?",
                                                (row[key],)).fetchone()[0]:
                                                row[key] = None
                                else:
                                    keep = True
                                if keep:
                                    data = canonical_json(row) + b"\n"
                                    if len(data) > MAX_RECORD_BYTES:
                                        raise DataError("Oversized refined normalized record")
                                    handles[table].write(data)
                                    digests[table].update(data)
                                    counts[table] += 1
                    receipt = {
                        "schema_version": 1, "transform": "normalized-wikipedia-refinement-v1",
                        "input_zip_sha256": input_digest, "original_build_id": original["build_id"],
                        "input_manifest_sha256": hashlib.sha256(canonical_json(original)).hexdigest(),
                        "policy_version": wikipedia_quality.WIKIPEDIA_QUALITY_VERSION,
                        "policy_sha256": policy_digest,
                        "implementation_sha256": implementation_digest,
                        "input_counts": original["counts"], "output_counts": counts,
                        "rejected_occurrences_by_reason": dict(sorted(reasons.items())),
                    }
                    if prior_receipt is not None:
                        receipt["parent_receipt"] = prior_receipt
                        receipt["parent_receipt_sha256"] = hashlib.sha256(
                            canonical_json(prior_receipt)).hexdigest()
                    _validate_receipt(receipt, original["build_id"])
                    manifest = {**original, "counts": counts,
                                "members": {t + ".jsonl": digests[t].hexdigest() for t in TABLES},
                                "normalized_refinement_provenance": receipt}
                    if len(canonical_json(manifest)) > MAX_MANIFEST_BYTES:
                        raise DataError("Oversized normalized refinement manifest")
                    staged = _write_archive(root, archive, manifest)
                    if _signature(archive_path) != signature or sha256_file(archive_path) != input_digest:
                        raise DataError("Normalized input changed during refinement")
                    if (sha256_file(Path(wikipedia_quality.__file__)) != policy_digest
                            or sha256_file(Path(__file__)) != implementation_digest):
                        raise DataError("Normalized refinement implementation changed during run")
                    with staged.open("rb") as stream:
                        os.fsync(stream.fileno())
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
    except (sqlite3.IntegrityError, zipfile.BadZipFile, KeyError, EOFError, RuntimeError,
            NotImplementedError, zlib.error) as exc:
        raise DataError("Invalid normalized refinement archive: " + str(exc)) from exc
