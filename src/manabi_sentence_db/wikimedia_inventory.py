"""Reusable, body-free Wikimedia metadata for large, disjoint source cohorts.

The snapshot is verified once when indexing. Later selections verify the small
metadata artifact and retain the exact snapshot binding; building still verifies
the original source through the ordinary extraction/rights gates.
"""

import fcntl
import os
import re
import sqlite3
import stat
from collections import Counter
from contextlib import closing, contextmanager
from pathlib import Path

import zstandard

from .document_selection import validate_selection
from .serialization import (
    DataError,
    atomic_replace_file,
    canonical_json,
    digest_json,
    parse_json,
    read_json,
    require_new_directory,
    sha256_file,
    write_json,
)
from .snapshot import verify_snapshot
from .wikimedia import _api_pages, _snapshot_path, _xml_pages
from .wikimedia_selection import (
    POLICY,
    _implementation_sha256,
    _limits,
    page_metadata,
    sample_pages,
)

KIND = "wikimedia-metadata-index-v1"
CHECKPOINT_BATCH_PAGES = 1000


def _signature(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _input_signature(path):
    info = path.stat()
    # Device/inode can change when a Docker bind mount is recreated. Times and
    # size remain attached to the host file and detect edit-and-restore cycles.
    return [info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def _manifest_inputs(snapshot, manifest):
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        return None
    paths = [snapshot]
    for entry in manifest["files"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            return None
        try:
            paths.append(_snapshot_path(snapshot.parent, entry["path"]))
        except (OSError, ValueError):
            return None
    return paths


def _secure_regular_file(path, *, required=False):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if required:
            raise DataError(f"Required SQLite path is missing: {path.name}")
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise DataError(f"Unsafe symlink or hardlink alias: {path.name}")
    return info.st_dev, info.st_ino


def _check_index_paths(output, *, database_identity=None, require_database=False):
    database = _secure_regular_file(output / "metadata.sqlite", required=require_database)
    if database_identity is not None and database != database_identity:
        raise DataError("Wikimedia metadata database path changed during indexing")
    _secure_regular_file(output / "metadata.sqlite-journal")
    _secure_regular_file(output / "metadata.sqlite-wal")
    _secure_regular_file(output / "metadata.sqlite-shm")
    _secure_regular_file(output / ".manifest.json.part")
    _secure_regular_file(output / ".index.lock", required=True)
    manifest = output / "manifest.json"
    if manifest.exists() or manifest.is_symlink():
        raise DataError("Wikimedia completion manifest appeared during indexing")
    return database


def _canonical(path):
    path = Path(path).absolute()
    if path.resolve(strict=True) != path:
        raise DataError("Use canonical metadata/selection paths outside symlinks")
    return path


def _fresh_output(output):
    output = Path(output).absolute()
    if output.is_symlink() or output.parent.resolve() != output.parent:
        raise DataError("Use an output directory outside symlinks")
    if output.exists():
        raise DataError("Use a fresh metadata/selection output directory")
    require_new_directory(output)
    output.mkdir(mode=0o700)
    return output


def _content_entries(manifest):
    return [r for r in manifest["files"] if r["role"] in {"mediawiki-xml", "mediawiki-api"}]


def _file_pages(path, role):
    return _xml_pages(path) if role == "mediawiki-xml" else _api_pages(path)


@contextmanager
def _producer_lock(output):
    path = output / ".index.lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        info = os.fstat(descriptor)
        path_info = os.lstat(path)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (info.st_dev, info.st_ino) != (path_info.st_dev, path_info.st_ino)):
            raise DataError("Unsafe Wikimedia index lock")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _checkpoint(db, *, file_index, page_ordinal, counts):
    try:
        db.execute("UPDATE checkpoint SET file_index=?, page_ordinal=?, counts_json=? WHERE singleton=1",
                    (file_index, page_ordinal, canonical_json(dict(counts))))
        if db.execute("SELECT changes()").fetchone()[0] != 1:
            raise DataError("Wikimedia checkpoint disappeared")
        db.commit()
    except sqlite3.OperationalError as exc:
        if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL:
            raise DataError("Metadata index storage budget exhausted or disk capacity unavailable") from exc
        raise


def _load_checkpoint(db, *, manifest_sha256, producer, snapshot_id, max_index_bytes,
                     input_signatures, entries):
    try:
        row = db.execute("SELECT manifest_sha256,producer,snapshot_id,file_count,file_index,"
                         "page_ordinal,counts_json,input_signatures,max_index_bytes "
                         "FROM checkpoint WHERE singleton=1").fetchone()
    except sqlite3.DatabaseError as exc:
        raise DataError("Incomplete metadata index has no resumable checkpoint; use a fresh output") from exc
    if row is None:
        raise DataError("Incomplete metadata index has no resumable checkpoint; use a fresh output")
    (stored_manifest, stored_producer, stored_snapshot, file_count, file_index,
     page_ordinal, counts_json, stored_signatures, cap) = row
    if (stored_manifest != manifest_sha256 or stored_producer != canonical_json(list(producer))
            or stored_snapshot != snapshot_id or file_count != len(entries)
            or stored_signatures != canonical_json(input_signatures)):
        raise DataError("Wikimedia checkpoint input or producer identity mismatch")
    if cap != max_index_bytes:
        raise DataError("Wikimedia checkpoint storage cap mismatch; use its original cap")
    if (type(file_index) is not int or not 0 <= file_index <= len(entries)
            or type(page_ordinal) is not int or page_ordinal < 0
            or (file_index == len(entries) and page_ordinal != 0)):
        raise DataError("Invalid Wikimedia checkpoint cursor")
    try:
        values = parse_json(counts_json)
    except (TypeError, ValueError) as exc:
        raise DataError("Invalid Wikimedia checkpoint counters") from exc
    if (not isinstance(values, dict)
            or any(not isinstance(key, str) or type(value) is not int or value < 0
                   for key, value in values.items())):
        raise DataError("Invalid Wikimedia checkpoint counters")
    counts = Counter(values)
    if (counts["records"] != db.execute("SELECT count(*) FROM pages").fetchone()[0]
            or counts["records"] > counts["pages_seen"]
            or page_ordinal > counts["pages_seen"]):
        raise DataError("Wikimedia checkpoint rows and counters disagree")
    return file_index, page_ordinal, counts


def _initialize_index(db, *, manifest_sha256, producer, snapshot_id, entries,
                      input_signatures, max_index_bytes):
    _configure_database(db, max_index_bytes)
    db.executescript("""
        CREATE TABLE pages(native_id TEXT PRIMARY KEY, fingerprint BLOB NOT NULL,
            revision_id TEXT NOT NULL, title TEXT NOT NULL,
            source_characters INTEGER NOT NULL, categories BLOB NOT NULL) WITHOUT ROWID;
        CREATE TABLE checkpoint(singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            manifest_sha256 TEXT NOT NULL, producer BLOB NOT NULL, snapshot_id TEXT NOT NULL,
            file_count INTEGER NOT NULL, file_index INTEGER NOT NULL, page_ordinal INTEGER NOT NULL,
            counts_json BLOB NOT NULL, input_signatures BLOB NOT NULL, max_index_bytes INTEGER);
    """)
    db.execute("INSERT INTO checkpoint VALUES (1,?,?,?,?,?,?,?,?,?)", (
        manifest_sha256, canonical_json(list(producer)), snapshot_id, len(entries), 0, 0,
        canonical_json({}), canonical_json(input_signatures), max_index_bytes,
    ))
    db.commit()


def _configure_database(db, max_index_bytes):
    db.execute("PRAGMA journal_mode=DELETE")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA cache_size=-4096")
    db.execute("PRAGMA mmap_size=0")
    if max_index_bytes is not None:
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        pages = max_index_bytes // page_size
        actual = db.execute(f"PRAGMA max_page_count={pages}").fetchone()[0]
        if actual != pages:
            raise DataError("Cannot enforce metadata index storage budget")


def _resume_output(output):
    output = _canonical(output)
    if not output.is_dir():
        raise DataError("--resume requires an existing incomplete metadata directory")
    manifest = output / "manifest.json"
    if manifest.exists() or manifest.is_symlink():
        raise DataError("A completed metadata cache cannot be resumed")
    path = output / "metadata.sqlite"
    if not path.is_file() or path.resolve(strict=True) != path:
        raise DataError("--resume requires an existing regular metadata database")
    _secure_regular_file(path, required=True)
    _secure_regular_file(output / "metadata.sqlite-journal")
    _secure_regular_file(output / "metadata.sqlite-wal")
    _secure_regular_file(output / "metadata.sqlite-shm")
    _secure_regular_file(output / ".manifest.json.part")
    _secure_regular_file(output / ".index.lock")
    return output


def index_wikimedia_metadata(snapshot, output, *, progress=None, max_index_bytes=None, resume=False):
    # Validate before verifying a potentially multi-gigabyte snapshot or creating output.
    if max_index_bytes is not None and (
            type(max_index_bytes) is not int or max_index_bytes < 8192):
        raise DataError("Metadata index budget must be an integer of at least 8192 bytes")
    snapshot = _canonical(snapshot)
    output = _resume_output(output) if resume else Path(output).absolute()
    if not resume and (output.is_symlink() or output.parent.resolve() != output.parent):
        raise DataError("Use an output directory outside symlinks")
    manifest_signature_before = _input_signature(snapshot)
    manifest_hash_before = sha256_file(snapshot)
    manifest_before = read_json(snapshot)
    if (_input_signature(snapshot) != manifest_signature_before
            or sha256_file(snapshot) != manifest_hash_before):
        raise DataError("Snapshot manifest changed during initial verification")
    inputs_before = _manifest_inputs(snapshot, manifest_before)
    if inputs_before is None:
        inputs_before = []
    input_signatures_before = [_input_signature(path) for path in inputs_before]
    manifest = verify_snapshot(snapshot)
    if manifest != manifest_before:
        raise DataError("Snapshot manifest changed during initial verification")
    if (manifest["source"]["adapter"] != "wikimedia"
            or manifest["source"]["language"].split("-", 1)[0] != "ja"):
        raise DataError("Metadata indexing supports Japanese Wikimedia only")
    inputs = _manifest_inputs(snapshot, manifest)
    if inputs is None or not inputs_before:
        raise DataError("Cannot establish snapshot input identities before verification")
    input_signatures = [_input_signature(path) for path in inputs]
    manifest_sha256 = sha256_file(snapshot)
    if (manifest_hash_before != manifest_sha256
            or manifest_signature_before != _input_signature(snapshot)
            or input_signatures_before != input_signatures):
        raise DataError("Wikimedia snapshot changed during initial verification")
    if not resume:
        output = _fresh_output(output)
    producer = (sha256_file(Path(__file__)), _implementation_sha256())
    entries = _content_entries(manifest)
    if not entries:
        raise DataError("Snapshot has no Wikimedia content files")
    path = output / "metadata.sqlite"
    compressor = zstandard.ZstdCompressor(level=6)
    with _producer_lock(output):
        if resume:
            _check_index_paths(output, require_database=True)
        elif path.exists() or path.is_symlink():
            raise DataError("Use a fresh metadata database path")
        manifest_path = output / "manifest.json"
        if resume and (manifest_path.exists() or manifest_path.is_symlink()):
            raise DataError("A completed metadata cache cannot be resumed")
        with closing(sqlite3.connect(path)) as db:
            database_identity = _check_index_paths(output, require_database=True)

            def assert_inputs_unchanged():
                if input_signatures != [_input_signature(source) for source in inputs]:
                    raise DataError("Wikimedia snapshot inputs changed since verified checkpoint")
                _check_index_paths(output, database_identity=database_identity,
                                  require_database=True)

            if resume:
                file_index, page_ordinal, counts = _load_checkpoint(
                    db, manifest_sha256=manifest_sha256, producer=producer,
                    snapshot_id=manifest["snapshot_id"], max_index_bytes=max_index_bytes,
                    input_signatures=input_signatures, entries=entries,
                )
                _configure_database(db, max_index_bytes)
                if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise DataError("Wikimedia metadata index integrity failure")
            else:
                assert_inputs_unchanged()
                try:
                    _initialize_index(db, manifest_sha256=manifest_sha256, producer=producer,
                                      snapshot_id=manifest["snapshot_id"], entries=entries,
                                      input_signatures=input_signatures,
                                      max_index_bytes=max_index_bytes)
                except sqlite3.OperationalError as exc:
                    if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL:
                        raise DataError(
                            "Metadata index storage budget exhausted or disk capacity unavailable"
                        ) from exc
                    raise
                assert_inputs_unchanged()
                file_index, page_ordinal, counts = 0, 0, Counter()

            def commit_cursor(next_file, next_ordinal, next_counts):
                assert_inputs_unchanged()
                _checkpoint(db, file_index=next_file, page_ordinal=next_ordinal,
                            counts=next_counts)
                # A mutation after the pre-commit check still poisons resume:
                # the persisted baseline is compared on every later invocation.
                assert_inputs_unchanged()
                if progress:
                    progress(f"Metadata checkpoint file={min(next_file + 1, len(entries))}/{len(entries)} "
                             f"page={next_ordinal} records={next_counts['records']}")

            for index in range(file_index, len(entries)):
                entry = entries[index]
                if progress:
                    progress("Metadata indexing " + entry["path"])
                source_path = _snapshot_path(snapshot.parent, entry["path"])
                start_ordinal = page_ordinal if index == file_index else 0
                ordinal = 0
                batch_pages = 0
                try:
                    for page in _file_pages(source_path, entry["role"]):
                        ordinal += 1
                        if ordinal <= start_ordinal:
                            continue
                        counts["pages_seen"] += 1
                        row = page_metadata(page, counts)
                        if row is not None:
                            fingerprint = bytes.fromhex(row["fingerprint"])
                            previous = db.execute("SELECT fingerprint FROM pages WHERE native_id=?",
                                                  (row["native_id"],)).fetchone()
                            if previous is not None:
                                if previous[0] != fingerprint:
                                    raise DataError("Conflicting Wikimedia page identity in metadata index")
                                counts["exact_duplicates"] += 1
                            else:
                                _check_index_paths(output, database_identity=database_identity,
                                                  require_database=True)
                                db.execute("INSERT INTO pages VALUES (?,?,?,?,?,?)", (
                                    row["native_id"], fingerprint, row["revision_id"], row["title"],
                                    row["source_characters"],
                                    compressor.compress(canonical_json(row["categories"])),
                                ))
                                counts["records"] += 1
                        batch_pages += 1
                        if batch_pages >= CHECKPOINT_BATCH_PAGES:
                            commit_cursor(index, ordinal, counts)
                            batch_pages = 0
                except sqlite3.OperationalError as exc:
                    if (max_index_bytes is not None and
                            getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL):
                        raise DataError(
                            "Metadata index storage budget exhausted or disk capacity unavailable"
                        ) from exc
                    raise
                if ordinal < start_ordinal:
                    raise DataError("Wikimedia checkpoint cursor exceeds the raw shard")
                commit_cursor(index + 1, 0, counts)
                page_ordinal = 0
            if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise DataError("Wikimedia metadata index integrity failure")
        if producer != (sha256_file(Path(__file__)), _implementation_sha256()):
            raise DataError("Metadata implementation changed while indexing")
        assert_inputs_unchanged()
        if not counts["records"]:
            raise DataError("No valid Wikimedia metadata to index")
        if max_index_bytes is not None and path.stat().st_size > max_index_bytes:
            raise DataError("Metadata index exceeded its storage budget")
        staged = output / ".manifest.json.part"
        if staged.is_symlink() or (staged.exists() and not staged.is_file()):
            raise DataError("Unsafe staged Wikimedia metadata manifest")
        if (output / "manifest.json").exists() or (output / "manifest.json").is_symlink():
            raise DataError("Wikimedia completion manifest appeared during indexing")
        write_json(staged, {
            "schema_version": 1, "kind": KIND, "source_id": manifest["source_id"],
            "snapshot_id": manifest["snapshot_id"], "snapshot_scope": manifest["mode"],
            "snapshot_manifest_sha256": sha256_file(snapshot),
            "producer_sha256": list(producer), "records": counts["records"], "counts": dict(counts),
            "bytes": path.stat().st_size, "sha256": sha256_file(path),
            "contains_article_bodies": False,
            "max_index_bytes": max_index_bytes,
        })
        assert_inputs_unchanged()
        atomic_replace_file(staged, manifest_path)
    return output


def _read_cache(cache):
    cache = _canonical(cache)
    manifest_path = _canonical(cache / "manifest.json")
    path = _canonical(cache / "metadata.sqlite")
    before = _signature(path)
    manifest_before = _signature(manifest_path)
    manifest = read_json(manifest_path)
    if (not isinstance(manifest, dict)
            or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1
            or manifest.get("kind") != KIND
            or manifest.get("contains_article_bodies") is not False
            or type(manifest.get("records")) is not int or manifest["records"] < 1
            or not isinstance(manifest.get("snapshot_id"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", manifest["snapshot_id"])):
        raise DataError("Invalid Wikimedia metadata manifest")
    if path.stat().st_size != manifest.get("bytes") or sha256_file(path) != manifest.get("sha256"):
        raise DataError("Wikimedia metadata checksum mismatch")
    if before != _signature(path) or manifest_before != _signature(manifest_path):
        raise DataError("Wikimedia metadata changed during verification")
    return path, manifest, before


def _excluded(paths, manifest):
    synthetic = [{"source_id": manifest["source_id"], "snapshot_id": manifest["snapshot_id"],
                  "source": {"adapter": "wikimedia"}}]
    result = set()
    receipts = []
    for path in paths:
        path = _canonical(path)
        value = read_json(path)
        result.update(validate_selection(value, synthetic))
        receipts.append(digest_json(value))
    return result, receipts


def _rows(db):
    decoder = zstandard.ZstdDecompressor()
    for identity, fingerprint, revision, title, size, blob in db.execute(
        "SELECT native_id,fingerprint,revision_id,title,source_characters,categories FROM pages "
        "ORDER BY native_id COLLATE BINARY"
    ):
        if (not isinstance(blob, bytes)
                or not 0 <= zstandard.frame_content_size(blob) <= 16 * 1024**2):
            raise DataError("Oversized or invalid Wikimedia categories frame")
        categories = parse_json(decoder.decompress(blob, max_output_size=16 * 1024**2))
        if (not isinstance(categories, list) or not all(isinstance(c, str) for c in categories)
                or not isinstance(identity, str) or not re.fullmatch(r"[1-9][0-9]*", identity)
                or not isinstance(fingerprint, bytes) or len(fingerprint) != 32
                or not isinstance(revision, str) or not revision or not isinstance(title, str)
                or not title or type(size) is not int or size < 0):
            raise DataError("Invalid Wikimedia metadata row")
        yield {"native_id": identity, "revision_id": revision, "title": title,
               "source_characters": size, "categories": categories,
               "fingerprint": fingerprint.hex()}


def select_wikimedia_metadata(cache, output, *, per_topic=1000, general=2000,
                              seed="", exclude_selections=(), progress=None):
    limits = _limits(per_topic, general)
    if not isinstance(seed, str) or len(seed) > 200:
        raise DataError("Selection seed must be at most 200 characters")
    path, manifest, before = _read_cache(cache)
    excluded, receipts = _excluded(exclude_selections, manifest)
    output = _fresh_output(output)
    producer = (sha256_file(Path(__file__)), _implementation_sha256())
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        db.execute("PRAGMA cache_size=-4096")
        db.execute("PRAGMA mmap_size=0")
        rows, counts = sample_pages(_rows(db), snapshot_id=manifest["snapshot_id"],
            per_topic=per_topic, general=general, seed=seed, exclude_ids=excluded,
            progress=progress, metadata=True, ordered_unique_metadata=True)
    if counts["pages_seen"] != manifest["records"] or _signature(path) != before:
        raise DataError("Wikimedia metadata changed during selection")
    if producer != (sha256_file(Path(__file__)), _implementation_sha256()):
        raise DataError("Metadata selection implementation changed during scan")
    if not rows:
        raise DataError("No new Wikimedia pages matched nonzero selection quotas")
    selection = {"schema_version": 1, "source_id": manifest["source_id"],
                 "snapshot_id": manifest["snapshot_id"],
                 "page_ids": [r["native_id"] for r in rows]}
    write_json(output / "selection-report.json", {
        "policy": POLICY, "implementation_sha256": _implementation_sha256(),
        "metadata_sha256": manifest["sha256"], "metadata_kind": KIND,
        "selection_sha256": digest_json(selection), "snapshot_scope": manifest["snapshot_scope"],
        "quotas": limits, "seed": seed, "counts": counts,
        "excluded_page_ids": len(excluded), "excluded_selection_sha256": receipts,
        "selected_counts": dict(Counter(r["topic"] for r in rows)), "articles": rows,
        "note": "Metadata routing is not sentence quality or licensing approval. Exclusions apply before quotas; original extraction, rights and quality gates remain required.",
    })
    staged = output / ".selection.json.part"
    write_json(staged, selection)
    atomic_replace_file(staged, output / "selection.json")
    return output / "selection.json"
