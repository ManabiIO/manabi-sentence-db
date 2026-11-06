"""Reusable, body-free Wikimedia metadata for large, disjoint source cohorts.

The snapshot is verified once when indexing. Later selections verify the small
metadata artifact and retain the exact snapshot binding; building still verifies
the original source through the ordinary extraction/rights gates.
"""

import re
import sqlite3
from collections import Counter
from contextlib import closing
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


def _signature(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


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


def snapshot_pages(snapshot, manifest, progress=None):
    entries = [r for r in manifest["files"] if r["role"] in {"mediawiki-xml", "mediawiki-api"}]
    if not entries:
        raise DataError("Snapshot has no Wikimedia content files")
    for entry in entries:
        if progress:
            progress("Metadata indexing " + entry["path"])
        path = _snapshot_path(snapshot.parent, entry["path"])
        yield from (_xml_pages(path) if entry["role"] == "mediawiki-xml" else _api_pages(path))


def index_wikimedia_metadata(snapshot, output, *, progress=None, max_index_bytes=None):
    # Validate before verifying a potentially multi-gigabyte snapshot or creating output.
    if max_index_bytes is not None and (
            type(max_index_bytes) is not int or max_index_bytes < 8192):
        raise DataError("Metadata index budget must be an integer of at least 8192 bytes")
    snapshot = _canonical(snapshot)
    manifest = verify_snapshot(snapshot)
    if (manifest["source"]["adapter"] != "wikimedia"
            or manifest["source"]["language"].split("-", 1)[0] != "ja"):
        raise DataError("Metadata indexing supports Japanese Wikimedia only")
    output = _fresh_output(output)
    producer = (sha256_file(Path(__file__)), _implementation_sha256())
    inputs = [snapshot, *(_snapshot_path(snapshot.parent, entry["path"])
                          for entry in manifest["files"])]
    input_identities = [_signature(path) for path in inputs]
    path = output / "metadata.sqlite"
    counts = Counter()
    compressor = zstandard.ZstdCompressor(level=6)
    with closing(sqlite3.connect(path)) as db:
        if max_index_bytes is not None:
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            pages = max_index_bytes // page_size
            actual = db.execute(f"PRAGMA max_page_count={pages}").fetchone()[0]
            if actual != pages:
                raise DataError("Cannot enforce metadata index storage budget")
        db.executescript("""
            PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
            PRAGMA cache_size=-4096; PRAGMA mmap_size=0;
            CREATE TABLE pages(native_id TEXT PRIMARY KEY, fingerprint BLOB NOT NULL,
                revision_id TEXT NOT NULL, title TEXT NOT NULL,
                source_characters INTEGER NOT NULL, categories BLOB NOT NULL) WITHOUT ROWID;
        """)
        for page in snapshot_pages(snapshot, manifest, progress):
            counts["pages_seen"] += 1
            if progress and counts["pages_seen"] % 50_000 == 0:
                progress(f"Metadata indexed {counts['pages_seen']} pages")
            row = page_metadata(page, counts)
            if row is None:
                continue
            fingerprint = bytes.fromhex(row["fingerprint"])
            previous = db.execute("SELECT fingerprint FROM pages WHERE native_id=?",
                                  (row["native_id"],)).fetchone()
            if previous is not None:
                if previous[0] != fingerprint:
                    raise DataError("Conflicting Wikimedia page identity in metadata index")
                counts["exact_duplicates"] += 1
                continue
            try:
                db.execute("INSERT INTO pages VALUES (?,?,?,?,?,?)", (
                    row["native_id"], fingerprint, row["revision_id"], row["title"],
                    row["source_characters"], compressor.compress(canonical_json(row["categories"])),
                ))
            except sqlite3.OperationalError as exc:
                if max_index_bytes is not None and exc.sqlite_errorcode == sqlite3.SQLITE_FULL:
                    raise DataError("Metadata index storage budget exhausted or disk capacity unavailable") from exc
                raise
            counts["records"] += 1
        db.commit()
        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise DataError("Wikimedia metadata index integrity failure")
    if producer != (sha256_file(Path(__file__)), _implementation_sha256()):
        raise DataError("Metadata implementation changed while indexing")
    if input_identities != [_signature(path) for path in inputs]:
        raise DataError("Wikimedia snapshot changed while indexing metadata")
    if not counts["records"]:
        raise DataError("No valid Wikimedia metadata to index")
    if max_index_bytes is not None and path.stat().st_size > max_index_bytes:
        raise DataError("Metadata index exceeded its storage budget")
    staged = output / ".manifest.json.part"
    write_json(staged, {
        "schema_version": 1, "kind": KIND, "source_id": manifest["source_id"],
        "snapshot_id": manifest["snapshot_id"], "snapshot_scope": manifest["mode"],
        "snapshot_manifest_sha256": sha256_file(snapshot),
        "producer_sha256": list(producer), "records": counts["records"], "counts": dict(counts),
        "bytes": path.stat().st_size, "sha256": sha256_file(path),
        "contains_article_bodies": False,
        "max_index_bytes": max_index_bytes,
    })
    atomic_replace_file(staged, output / "manifest.json")
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
