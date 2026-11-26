"""Opt-in resumable corpus builds using private, shard-sized checkpoints."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import PROCESSOR_VERSION, SCHEMA_VERSION
from .serialization import (
    DataError,
    canonical_json,
    digest_json,
    parse_json,
    read_json,
    safe_relative,
    sha256_file,
    write_json,
)

CHECKPOINT_SCHEMA = 2


def _sync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.part")
    if temporary.exists() or temporary.is_symlink():
        raise DataError("A resumable checkpoint has an unexpected temporary file")
    with temporary.open("xb") as handle:
        handle.write(canonical_json(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _sync_directory(path.parent)


def _write_state(path: Path, value: dict) -> None:
    _atomic_json(path, {**value, "state_sha256": digest_json(value)})


def _read_state(path: Path) -> dict:
    value = read_json(path)
    if not isinstance(value, dict):
        raise DataError("Resumable checkpoint state is corrupt")
    digest = value.pop("state_sha256", None)
    if not isinstance(digest, str) or digest != digest_json(value):
        raise DataError("Resumable checkpoint state failed verification")
    return value


def _counter(value, field: str) -> Counter:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or type(count) is not int or count < 0
        for key, count in value.items()
    ):
        raise DataError(f"Invalid resumable checkpoint {field}")
    return Counter(value)


def _id_rows(records: list[dict]):
    for record in records:
        yield "document", record["id"]
        for sentence in record["sentences"]:
            yield "sentence", sentence["id"]


class _Checkpoint:
    def __init__(self, root: Path, signature: str, initial_state: dict,
                 records_compression: str = "none"):
        if records_compression not in {"none", "zstd"}:
            raise DataError("Unsupported resumable checkpoint compression")
        self.root = root
        self.records_compression = records_compression
        self.batches = root / "batches"
        self.stage = root / "stage"
        self.state_path = root / "state.json"
        self.database_path = root / "identities.sqlite3"
        self.lock_path = root / "checkpoint.lock"
        self.database = None
        self.lock_fd = None
        if root.is_symlink():
            raise DataError("Use a resumable checkpoint outside symlinks")
        if root.exists() and not root.is_dir():
            raise DataError("Resumable checkpoint path is not a directory")
        if not root.exists():
            root.mkdir(mode=0o700, parents=False)
        if self.lock_path.is_symlink():
            raise DataError("Resumable checkpoint contains a symlink")
        descriptor = os.open(
            self.lock_path,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise DataError("Another build currently owns this resumable checkpoint") from exc
        self.lock_fd = descriptor
        try:
            for partial in root.glob(".state.json.*.part"):
                if partial.is_symlink() or not partial.is_file():
                    raise DataError("Resumable checkpoint contains an unsafe state temporary")
                partial.unlink()
            for path in (self.batches, self.stage, self.state_path, self.database_path):
                if path.is_symlink():
                    raise DataError("Resumable checkpoint contains a symlink")
            known_root_items = {
                self.batches, self.stage, self.lock_path, self.state_path,
                self.database_path, Path(f"{self.database_path}-journal"),
                Path(f"{self.database_path}-wal"), Path(f"{self.database_path}-shm"),
            }
            if any(path.is_symlink() for path in known_root_items):
                raise DataError("Resumable checkpoint contains a symlink")
            if any(path not in known_root_items for path in root.iterdir()):
                raise DataError("Resumable checkpoint contains unexpected root data")
            if self.state_path.is_file():
                state = _read_state(self.state_path)
                if (
                    type(state.get("schema_version")) is not int
                    or state.get("schema_version") != CHECKPOINT_SCHEMA
                    or state.get("signature") != signature
                ):
                    raise DataError("Resumable checkpoint does not match this build's inputs and options")
                self.state = state
                if not self.database_path.exists() and self.state.get("batches"):
                    raise DataError("Resumable checkpoint identity database is missing")
            else:
                if self.database_path.exists():
                    raise DataError("Resumable checkpoint is incomplete or corrupt")
                for directory in (self.batches, self.stage):
                    if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
                        raise DataError("Resumable checkpoint is incomplete or corrupt")
                    directory.mkdir(exist_ok=True)
                self.state = {**initial_state, "schema_version": CHECKPOINT_SCHEMA,
                              "signature": signature, "batches": [], "assemblies": {}}
                _write_state(self.state_path, self.state)
            if not self.batches.is_dir() or not self.stage.is_dir():
                raise DataError("Resumable checkpoint staging is corrupt")
            self.database = sqlite3.connect(self.database_path)
            self.database.execute("PRAGMA synchronous=FULL")
            if self.database.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise DataError("Resumable checkpoint identity database is corrupt")
            self.database.executescript(
                "CREATE TABLE IF NOT EXISTS identities(kind TEXT, id TEXT, batch_no INTEGER NOT NULL, "
                "position INTEGER NOT NULL, PRIMARY KEY(kind,id), UNIQUE(batch_no,position)) WITHOUT ROWID;"
                "CREATE TABLE IF NOT EXISTS batches(batch_no INTEGER PRIMARY KEY, digest TEXT);"
            )
            self._recover()
        except BaseException:
            self.close()
            raise

    def _recover(self):
        rollback = self.state.pop("rollback", None)
        if rollback is not None:
            if (not isinstance(rollback, dict)
                    or type(rollback.get("first_batch")) is not int
                    or rollback["first_batch"] < 0
                    or not isinstance(rollback.get("target"), dict)):
                raise DataError("Resumable checkpoint rollback state is corrupt")
            first = rollback["first_batch"]
            target = rollback["target"]
            target_batches = target.get("batches")
            if (not isinstance(target_batches, list)
                    or target_batches != list(range(first))
                    or len(self.state.get("batches", [])) < first):
                raise DataError("Resumable checkpoint rollback target is corrupt")
            self.database.execute("BEGIN IMMEDIATE")
            self.database.execute("DELETE FROM identities WHERE batch_no>=?", (first,))
            self.database.execute("DELETE FROM batches WHERE batch_no>=?", (first,))
            self.database.commit()
            self.state = target
            _write_state(self.state_path, self.state)
        committed = self.database.execute(
            "SELECT batch_no,digest FROM batches ORDER BY batch_no"
        ).fetchall()
        if [row[0] for row in committed] != list(range(len(committed))):
            raise DataError("Resumable checkpoint batch ledger is corrupt")
        identity_batches = [row[0] for row in self.database.execute(
            "SELECT DISTINCT batch_no FROM identities ORDER BY batch_no"
        )]
        if not set(identity_batches).issubset({row[0] for row in committed}):
            raise DataError("Resumable checkpoint identity database has orphaned rows")
        state_batches = self.state.get("batches")
        if (not isinstance(state_batches, list)
                or state_batches != list(range(len(state_batches)))
                or len(state_batches) > len(committed)):
            raise DataError("Resumable checkpoint state is ahead of its identity ledger")
        for number, digest in committed:
            batch_dir = self.batches / f"{number:08d}"
            meta_path = batch_dir / "batch.json"
            if batch_dir.is_symlink() or meta_path.is_symlink():
                raise DataError("Resumable checkpoint batch contains a symlink")
            for artifact in batch_dir.iterdir():
                if artifact.is_symlink() or artifact.name not in {
                    "batch.json", "records.jsonl", "records.jsonl.zst",
                    "index.jsonl", ".index.jsonl.part",
                }:
                    raise DataError("Resumable checkpoint batch contains unexpected data")
            if not meta_path.is_file():
                raise DataError("A committed resumable checkpoint batch is missing")
            meta = read_json(meta_path)
            expected = meta.pop("batch_sha256", None)
            records_path = self._records_path(batch_dir, meta)
            if records_path.is_symlink():
                raise DataError("Resumable checkpoint batch contains a symlink")
            assembly = self.state.get("assemblies", {}).get(str(number))
            alternate_path = batch_dir / (
                "records.jsonl" if records_path.name == "records.jsonl.zst"
                else "records.jsonl.zst"
            )
            if (expected != digest or expected != digest_json(meta)
                    or meta.get("batch_no") != number
                    or (alternate_path.exists() or alternate_path.is_symlink())
                    or (records_path.is_file()
                        and meta.get("records_sha256") != sha256_file(records_path))
                    or (records_path.is_file()
                        and "records_size" in meta
                        and records_path.stat().st_size != meta["records_size"])
                    or (not records_path.is_file() and assembly is None)
                    or meta.get("signature") != self.state["signature"]):
                raise DataError("A committed resumable checkpoint batch failed verification")
            identity_digest = hashlib.sha256()
            identity_count = 0
            for kind, identity in self.database.execute(
                "SELECT kind,id FROM identities WHERE batch_no=? ORDER BY position", (number,)
            ):
                identity_digest.update(canonical_json([kind, identity]) + b"\n")
                identity_count += 1
            if (identity_count != meta.get("identity_count")
                    or identity_digest.hexdigest() != meta.get("identity_sha256")):
                raise DataError("A committed checkpoint identity index failed verification")
            if number >= len(state_batches):
                progress = meta.get("progress_after")
                if not isinstance(progress, dict):
                    raise DataError("A committed checkpoint batch has no recovery state")
                self.state = {**self.state, **progress, "batches": [*state_batches, number]}
                state_batches = self.state["batches"]
        if len(state_batches) != len(committed):
            raise DataError("Resumable checkpoint state and batch ledger disagree")
        for number, digest in committed:
            batch_dir = self.batches / f"{number:08d}"
            meta = read_json(batch_dir / "batch.json")
            state_digest = meta["batch_sha256"]
            if state_digest != digest:
                raise DataError("Resumable checkpoint state and batch ledger disagree")
        committed_names = {f"{number:08d}" for number, _ in committed}
        for path in self.batches.iterdir():
            if path.name.startswith(".tmp-"):
                if path.is_symlink() or not path.is_dir():
                    raise DataError("Resumable checkpoint contains a symlink")
                shutil.rmtree(path)
            elif path.name not in committed_names:
                if path.is_symlink() or not path.is_dir() or not path.name.isdigit():
                    raise DataError("Resumable checkpoint contains an unexpected batch")
                shutil.rmtree(path)
        if len(state_batches) < len(committed):
            raise DataError("Could not recover resumable checkpoint state")
        _write_state(self.state_path, self.state)
        self._remove_uncommitted_stage_files()

    def _remove_uncommitted_stage_files(self):
        try:
            expected = {
                entry["path"]
                for assembly in self.state["assemblies"].values()
                for entry in assembly["shards"]
            }
        except (AttributeError, KeyError, TypeError) as exc:
            raise DataError("Resumable checkpoint assembly ledger is corrupt") from exc
        for path in sorted(self.stage.rglob("*"), reverse=True):
            relative = path.relative_to(self.stage).as_posix()
            if path.is_symlink():
                raise DataError("Resumable build staging contains a symlink")
            if path.is_file() and relative not in expected:
                path.unlink()
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()

    def save_state(self):
        _write_state(self.state_path, self.state)

    def commit_batch(self, records: list[dict], *, source_id: str, language: str,
                     cursor: str | None, stats_delta: Counter, source_stats: Counter,
                     licenses_delta: dict):
        batch_no = len(self.state["batches"])
        temporary = self.batches / f".tmp-{batch_no:08d}-{os.getpid()}"
        destination = self.batches / f"{batch_no:08d}"
        if temporary.exists() or destination.exists() or temporary.is_symlink():
            raise DataError("Resumable checkpoint batch destination already exists")
        temporary.mkdir()
        records_name = "records.jsonl.zst" if self.records_compression == "zstd" else "records.jsonl"
        record_path = temporary / records_name
        stored_digest = hashlib.sha256()
        content_digest = hashlib.sha256()
        identity_digest = hashlib.sha256()
        identity_count = 0
        import zstandard

        compressor = (
            zstandard.ZstdCompressor(level=9, write_checksum=True).compressobj()
            if self.records_compression == "zstd" else None
        )
        with record_path.open("xb") as handle:
            for record in records:
                line = canonical_json(record) + b"\n"
                content_digest.update(line)
                encoded = compressor.compress(line) if compressor is not None else line
                handle.write(encoded)
                stored_digest.update(encoded)
                for kind, identity in _id_rows([record]):
                    identity_digest.update(canonical_json([kind, identity]) + b"\n")
                    identity_count += 1
            if compressor is not None:
                tail = compressor.flush()
                handle.write(tail)
                stored_digest.update(tail)
            handle.flush()
            os.fsync(handle.fileno())
        progress = {
            "source_stats": {**self.state["source_stats"], source_id: dict(source_stats)},
            "statistics": dict(self.state["statistics"]),
            "licenses": {**self.state["licenses"], **licenses_delta},
            "cursors": {**self.state["cursors"], source_id: cursor},
        }
        meta = {
            "batch_no": batch_no,
            "signature": self.state["signature"],
            "source_id": source_id,
            "language": language,
            "records": len(records),
            "records_path": records_name,
            "records_format": "canonical-jsonl",
            "records_compression": self.records_compression,
            "records_sha256": stored_digest.hexdigest(),
            "records_content_sha256": content_digest.hexdigest(),
            "records_size": record_path.stat().st_size,
            "identity_count": identity_count,
            "identity_sha256": identity_digest.hexdigest(),
            "cursor": cursor,
            "stats_delta": dict(stats_delta),
            "licenses_delta": licenses_delta,
            "progress_after": progress,
        }
        meta["batch_sha256"] = digest_json(meta)
        _atomic_json(temporary / "batch.json", meta)
        _sync_directory(temporary)
        os.replace(temporary, destination)
        _sync_directory(self.batches)

        try:
            self.database.execute("BEGIN IMMEDIATE")
            position = 0

            def identity_rows():
                nonlocal position
                for record in records:
                    for kind, identity in _id_rows([record]):
                        yield kind, identity, batch_no, position
                        position += 1

            self.database.executemany(
                "INSERT INTO identities VALUES (?,?,?,?)", identity_rows(),
            )
            self.database.execute("INSERT INTO batches VALUES (?,?)",
                                  (batch_no, meta["batch_sha256"]))
            self.database.commit()
        except sqlite3.IntegrityError as exc:
            self.database.rollback()
            raise DataError("Duplicate upstream identity in resumable checkpoint") from exc
        self.state.update(progress)
        self.state["batches"].append(batch_no)
        self.save_state()
        return batch_no

    @staticmethod
    def _records_path(batch_dir: Path, meta: dict) -> Path:
        """Select the checkpoint payload from its integrity-bound format fields."""
        legacy = "records_path" not in meta and "records_compression" not in meta
        if legacy:
            name, record_format, compression = "records.jsonl", "canonical-jsonl", "none"
        else:
            name = meta.get("records_path")
            record_format = meta.get("records_format")
            compression = meta.get("records_compression")
        expected_name = "records.jsonl.zst" if compression == "zstd" else "records.jsonl"
        if (record_format != "canonical-jsonl" or compression not in {"none", "zstd"}
                or name != expected_name):
            raise DataError("Resumable checkpoint record format is invalid")
        return batch_dir / name

    def records(self, batch_no: int):
        import zstandard

        batch_dir = self.batches / f"{batch_no:08d}"
        meta = read_json(batch_dir / "batch.json")
        path = self._records_path(batch_dir, meta)
        if not path.is_file() or path.is_symlink():
            raise DataError("Unassembled checkpoint batch has no cached records")
        if (sha256_file(path) != meta.get("records_sha256")
                or ("records_size" in meta and path.stat().st_size != meta["records_size"])):
            raise DataError("A committed resumable checkpoint batch failed verification")
        digest = hashlib.sha256()
        decoded_size = 0
        count = 0
        pending = bytearray()
        try:
            if meta.get("records_compression", "none") == "zstd":
                from .build import _zstd_shard_chunks

                with path.open("rb") as source:
                    chunks = _zstd_shard_chunks(source)
                    for chunk in chunks:
                        decoded_size += len(chunk)
                        if decoded_size > meta["records"] * 32 * 1024 * 1024:
                            raise DataError("Resumable checkpoint records exceed their decoded bound")
                        pending.extend(chunk)
                        while (newline := pending.find(b"\n")) >= 0:
                            raw = bytes(pending[:newline])
                            del pending[:newline + 1]
                            if not raw or len(raw) > 32 * 1024 * 1024:
                                raise DataError("Invalid resumable checkpoint record")
                            digest.update(raw + b"\n")
                            record = parse_json(raw)
                            if not isinstance(record, dict):
                                raise DataError("Invalid resumable checkpoint record")
                            count += 1
                            yield record
            else:
                with path.open("rb") as source:
                    for chunk in iter(lambda: source.read(65536), b""):
                        decoded_size += len(chunk)
                        if decoded_size > meta["records"] * 32 * 1024 * 1024:
                            raise DataError("Resumable checkpoint records exceed their decoded bound")
                        pending.extend(chunk)
                        while (newline := pending.find(b"\n")) >= 0:
                            raw = bytes(pending[:newline])
                            del pending[:newline + 1]
                            if not raw or len(raw) > 32 * 1024 * 1024:
                                raise DataError("Invalid resumable checkpoint record")
                            digest.update(raw + b"\n")
                            record = parse_json(raw)
                            if not isinstance(record, dict):
                                raise DataError("Invalid resumable checkpoint record")
                            count += 1
                            yield record
            if (pending or count != meta.get("records")
                    or ("records_content_sha256" in meta
                        and digest.hexdigest() != meta["records_content_sha256"])):
                raise DataError("Resumable checkpoint record contents failed verification")
        except (ValueError, zstandard.ZstdError) as exc:
            raise DataError("Invalid resumable checkpoint records") from exc

    def close(self):
        if self.database is not None:
            self.database.close()
            self.database = None
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None


def _combined_counter(first: Counter, second: Counter) -> Counter:
    combined = Counter(first)
    combined.update(second)
    return combined


def _build_signature(inputs, selection, processor_hash, runtime, options) -> str:
    from .snapshot import snapshot_identity

    return digest_json({
        "schema_version": CHECKPOINT_SCHEMA,
        "processor_version": PROCESSOR_VERSION,
        "processor_sha256": processor_hash,
        "runtime": runtime,
        "options": options,
        "selection": selection,
        "snapshots": [
            {
                "source_id": manifest["source_id"],
                "snapshot_id": snapshot_identity(manifest),
                "source_config_sha256": manifest["source_config_sha256"],
            }
            for _, manifest in inputs
        ],
    })


def _build_resumable_corpus(
    snapshot_paths,
    output,
    *,
    shard_bytes,
    shard_documents,
    excluded_flags,
    max_documents,
    record_format,
    shard_compression,
    document_selection,
    progress,
):
    from . import build as builder
    from .snapshot import verify_snapshot

    output = Path(os.path.abspath(output))
    if output.is_symlink():
        raise DataError("Use a build output outside symlinks")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.parent.resolve(strict=True) != output.parent:
        raise DataError("Use a build output under a non-symlink parent")
    if output.exists():
        raise DataError(f"Output already exists: {output}. Choose a new output directory.")
    if shard_compression not in {"none", "zstd"}:
        raise DataError("Unsupported shard compression")
    if record_format not in {"jsonl", "yaml"}:
        raise DataError("Unsupported record format")
    if not snapshot_paths or shard_bytes < 1024 or shard_documents < 1:
        raise DataError("Provide snapshots and positive shard limits (at least 1024 bytes)")
    if max_documents is not None and max_documents < 1:
        raise DataError("max_documents must be positive")
    if document_selection is not None and max_documents is not None:
        raise DataError("document_selection cannot be combined with max_documents")
    excluded_flags = {"sexual-content"} if excluded_flags is None else excluded_flags
    notify = progress or (lambda _: None)
    inputs = []
    for path in snapshot_paths:
        notify("Verifying cached snapshot bytes")
        inputs.append((path, verify_snapshot(path)))
    selection = None
    page_ids = None
    if document_selection is not None:
        from .document_selection import validate_selection

        selection = read_json(Path(document_selection).resolve(strict=True))
        page_ids = validate_selection(selection, [manifest for _, manifest in inputs])
        selection = {**selection, "page_ids": sorted(page_ids, key=int)}
    inputs.sort(key=lambda pair: pair[1]["source_id"])
    if len({manifest["source_id"] for _, manifest in inputs}) != len(inputs):
        raise DataError("A build must use exactly one snapshot per source")
    for _, manifest in inputs:
        builder.validate(manifest["source"], "source")
    processor_hash = builder._processor_fingerprint()
    runtime = builder._runtime_versions()
    options = {
        "record_format": record_format,
        "shard_bytes": shard_bytes,
        "shard_documents": shard_documents,
        "excluded_flags": sorted(excluded_flags),
        "max_documents_per_source": max_documents,
    }
    if shard_compression != "none":
        options["shard_compression"] = shard_compression
    if selection is not None:
        options["document_selection"] = selection
        options["document_selection_sha256"] = digest_json(selection)
    signature = _build_signature(inputs, selection, processor_hash, runtime, options)
    checkpoint_root = output.parent / f".{output.name}.resume"
    initial = {
        "source_stats": {},
        "statistics": {},
        "licenses": {},
        "completed_sources": [],
        "cursors": {},
    }
    checkpoint = _Checkpoint(
        checkpoint_root, signature, initial, records_compression=shard_compression,
    )
    checkpoint.state.setdefault("source_stats", {})
    checkpoint.state.setdefault("statistics", {})
    checkpoint.state.setdefault("licenses", {})
    checkpoint.state.setdefault("completed_sources", [])
    checkpoint.state.setdefault("cursors", {})
    checkpoint.state.setdefault("assemblies", {})
    if not isinstance(checkpoint.state["assemblies"], dict):
        checkpoint.close()
        raise DataError("Resumable checkpoint assembly ledger is corrupt")
    state = checkpoint.state
    source_ids = {manifest["source_id"] for _, manifest in inputs}
    try:
        _counter(state["statistics"], "statistics")
        if not isinstance(state["source_stats"], dict):
            raise DataError("Invalid resumable checkpoint source statistics")
        for source_id, values in state["source_stats"].items():
            if source_id not in source_ids:
                raise DataError("Resumable checkpoint refers to an unknown source")
            _counter(values, "source statistics")
        if not isinstance(state["completed_sources"], list):
            raise DataError("Invalid resumable checkpoint completed sources")
        if (len(set(state["completed_sources"])) != len(state["completed_sources"])
                or not set(state["completed_sources"]).issubset(source_ids)):
            raise DataError("Resumable checkpoint completed source list is corrupt")
        if (not isinstance(state["cursors"], dict)
                or any(source_id not in source_ids or not isinstance(cursor, str) or not cursor
                       for source_id, cursor in state["cursors"].items())):
            raise DataError("Resumable checkpoint page cursors are corrupt")
        if not isinstance(state["licenses"], dict) or any(
            not isinstance(value, dict) or value.get("id") != license_id
            for license_id, value in state["licenses"].items()
        ):
            raise DataError("Resumable checkpoint license state is corrupt")
        if any(not str(batch_no).isdigit() or str(int(batch_no)) != str(batch_no)
               or int(batch_no) >= len(state["batches"])
               for batch_no in state["assemblies"]):
            raise DataError("Resumable checkpoint assembly ledger is corrupt")
    except (TypeError, KeyError) as exc:
        checkpoint.close()
        raise DataError("Resumable checkpoint state is corrupt") from exc

    # Adapters without stable native-ID cursors replay their partial source.
    for _, manifest in inputs:
        source_id = manifest["source_id"]
        if source_id in state["completed_sources"]:
            continue
        if (manifest["source"]["adapter"] in {"wikimedia", "jaquad"}
                or source_id not in state["cursors"]):
            break
        first = next((number for number in state["batches"]
                      if read_json(checkpoint.batches / f"{number:08d}" / "batch.json")["source_id"]
                      == source_id), None)
        if first is not None:
            rollback_end = len(state["batches"])
            for number in range(first, rollback_end):
                meta_path = checkpoint.batches / f"{number:08d}" / "batch.json"
                if read_json(meta_path)["source_id"] != source_id:
                    checkpoint.close()
                    raise DataError("Resumable checkpoint source order is corrupt")
            target = {**state, "batches": state["batches"][:first]}
            target["source_stats"] = dict(state["source_stats"])
            target["source_stats"].pop(source_id, None)
            target["cursors"] = dict(state["cursors"])
            target["cursors"].pop(source_id, None)
            target["assemblies"] = {
                batch_no: assembly
                for batch_no, assembly in state["assemblies"].items()
                if int(batch_no) < first
            }
            target["completed_sources"] = [
                item for item in state["completed_sources"] if item != source_id
            ]
            retained_stats = Counter()
            for item in target["completed_sources"]:
                retained_stats.update(target["source_stats"].get(item, {}))
            target["statistics"] = dict(retained_stats)
            target["licenses"] = {}
            for number in target["batches"]:
                retained_meta = read_json(
                    checkpoint.batches / f"{number:08d}" / "batch.json"
                )
                target["licenses"].update(retained_meta["licenses_delta"])
            state.clear()
            state.update({**target, "rollback": {"first_batch": first, "target": target}})
            checkpoint.save_state()
            checkpoint.database.execute("BEGIN IMMEDIATE")
            checkpoint.database.execute("DELETE FROM identities WHERE batch_no>=?", (first,))
            checkpoint.database.execute("DELETE FROM batches WHERE batch_no>=?", (first,))
            checkpoint.database.commit()
            state.clear()
            state.update(target)
            checkpoint.save_state()
            for number in range(first, rollback_end):
                shutil.rmtree(checkpoint.batches / f"{number:08d}", ignore_errors=False)
        break

    total_stats = Counter(state["statistics"])
    writers = []
    try:
        for manifest_path, manifest in inputs:
            source = manifest["source"]
            source_id = manifest["source_id"]
            if source["id"] != source_id:
                raise DataError("Snapshot source identity disagrees with its source configuration")
            if source_id in state["completed_sources"]:
                continue
            adapters = {
                "wikimedia": "wikimedia", "tatoeba": "tatoeba",
                "realpersonachat": "realpersonachat", "mrmp": "mrmp", "jmrd": "jmrd",
                "massive": "massive", "vfd": "vfd", "asdc": "asdc",
                "jmultiwoz": "jmultiwoz", "yj-captions": "yj_captions",
                "stair": "stair", "scp-curated": "scp_curated",
                "globalvoices": "globalvoices", "jec-basic": "jec_basic",
                "talpco": "talpco", "storybook-japan": "storybooks",
                "alt-parallel": "alt_parallel", "kyoto-wikipedia": "kyoto_wikipedia",
                "jaquad": "jaquad",
            }
            module_name = adapters.get(source["adapter"])
            if module_name is None:
                raise DataError(f"Unsupported adapter: {source['adapter']}")
            module = __import__(f"manabi_sentence_db.{module_name}", fromlist=["iter_documents"])
            iter_documents = module.iter_documents
            source_stats = Counter(state["source_stats"].get(source_id, {}))
            committed_source_stats = Counter(source_stats)
            pending_stats = Counter()
            records = []
            pending_size = 0
            batch_cursor = None
            pending_licenses = {}
            cursor = state["cursors"].get(source_id)
            resume_cursor = cursor if source["adapter"] in {"wikimedia", "jaquad"} else None
            notify(f"{source_id}: processing cached snapshot")
            stats_for_scan = Counter() if resume_cursor else source_stats
            iterator_kwargs = {}
            if source["adapter"] == "wikimedia":
                if selection is not None and selection["source_id"] == source_id:
                    iterator_kwargs["page_ids"] = page_ids
                if resume_cursor is not None:
                    iterator_kwargs["after_page_id"] = resume_cursor
                iterator_kwargs["progress"] = progress
                iterator_kwargs["stats"] = stats_for_scan
            elif source["adapter"] == "jaquad":
                if resume_cursor is not None:
                    iterator_kwargs["after_native_id"] = resume_cursor
                iterator_kwargs["stats"] = stats_for_scan
            elif source["adapter"] in {
                "jec-basic", "talpco", "kyoto-wikipedia", "alt-parallel", "yj-captions",
                "globalvoices", "storybook-japan", "jmrd", "massive", "vfd", "jaquad",
            }:
                iterator_kwargs["stats"] = source_stats
            documents = iter_documents(manifest, manifest_path.parent, **iterator_kwargs)
            for raw in documents:
                if (max_documents is not None and source_stats["documents_seen"]
                        + pending_stats["documents_seen"] >= max_documents):
                    break
                document_stats = Counter({"documents_seen": 1})
                if raw["language"] != source["language"]:
                    raise DataError("Adapter returned a document with an unexpected language")
                record = builder.canonical_document(raw, manifest, document_stats, excluded_flags)
                encoded = None
                if record is not None:
                    encoded = builder._record_bytes(record, record_format)
                    if len(encoded) > 32 * 1024 * 1024:
                        raise DataError(f"Document exceeds the 32 MiB canonical-record bound: {record['id']}")
                    if records and (
                        len(records) >= shard_documents or pending_size + len(encoded) > shard_bytes
                    ):
                        batch_no = checkpoint.commit_batch(
                            records, source_id=source_id, language=source["language"],
                            cursor=batch_cursor, stats_delta=pending_stats,
                            source_stats=_combined_counter(committed_source_stats, pending_stats),
                            licenses_delta=pending_licenses,
                        )
                        notify(f"Checkpoint committed batch {batch_no + 1} for {source_id}")
                        committed_source_stats.update(pending_stats)
                        source_stats.update(pending_stats)
                        pending_stats.clear()
                        records = []
                        pending_size = 0
                        batch_cursor = None
                        pending_licenses = {}
                    if record is not None:
                        for license_value in [
                            record["license"],
                            *[tr["license"] for sentence in record["sentences"]
                              for tr in builder._all_translations(sentence)],
                        ]:
                            previous = pending_licenses.get(license_value["id"],
                                                            state["licenses"].get(license_value["id"]))
                            if previous is not None and previous != license_value:
                                raise DataError(f"Conflicting notices for license {license_value['id']}")
                            pending_licenses[license_value["id"]] = license_value
                    document_stats["documents"] += 1
                pending_stats.update(document_stats)
                batch_cursor = str(raw["native_id"])
                if record is not None:
                    records.append(record)
                    pending_size += len(encoded)
            if records:
                batch_no = checkpoint.commit_batch(
                    records, source_id=source_id, language=source["language"],
                    cursor=batch_cursor, stats_delta=pending_stats,
                    source_stats=_combined_counter(committed_source_stats, pending_stats),
                    licenses_delta=pending_licenses,
                )
                notify(f"Checkpoint committed batch {batch_no + 1} for {source_id}")
                committed_source_stats.update(pending_stats)
                source_stats.update(pending_stats)
                pending_stats.clear()
                pending_licenses = {}
            elif pending_stats:
                source_stats.update(pending_stats)
                pending_stats.clear()

            if resume_cursor:
                scan_keys = (
                    ("wikimedia_pages_seen", "wikimedia_pages_not_selected",
                     "wikimedia_pages_selected", "rejected:page-text-limit")
                    if source["adapter"] == "wikimedia"
                    else ("articles_read", "train_questions", "validation_questions",
                          "duplicate_question_text_groups", "duplicate_question_text_excess")
                )
                for key in scan_keys:
                    if stats_for_scan[key]:
                        source_stats[key] = stats_for_scan[key]
                    else:
                        source_stats.pop(key, None)
            state["source_stats"][source_id] = dict(source_stats)
            combined_stats = Counter(total_stats)
            combined_stats.update(source_stats)
            state["statistics"] = dict(combined_stats)
            state["licenses"].update(pending_licenses)
            # Checkpoint metadata may have committed a newer cursor after the
            # source's final batch; clear it only after recording completion.
            state["completed_sources"] = [*state["completed_sources"], source_id]
            state["cursors"].pop(source_id, None)
            total_stats.update(source_stats)
            checkpoint.save_state()
            notify(f"{source_id}: finished {source_stats['documents']} documents; "
                   f"{source_stats['sentences']} sentences")

        # Reconcile source totals in case the checkpoint resumed after a source
        # completion but before final catalog construction.
        source_rows = []
        snapshots = []
        for manifest_path, manifest in inputs:
            source_id = manifest["source_id"]
            source_rows.append({
                "source": manifest["source"],
                "statistics": dict(sorted(state["source_stats"].get(source_id, {}).items())),
            })
            provenance = f"provenance/{source_id}.snapshot.json"
            path = safe_relative(checkpoint.stage, provenance)
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(manifest_path, path)
            snapshots.append({
                "source_id": source_id, "snapshot_id": manifest["snapshot_id"],
                "mode": manifest["mode"], "manifest": provenance,
                "manifest_sha256": sha256_file(manifest_path),
            })

        # Assemble each cached group as exactly one normal shard. Cached groups
        # use the same byte/document limits as ShardWriter, preserving order and
        # shard boundaries. The cache copy is retired only after state is durable.
        per_source_shards = Counter()
        entries = []
        index_chunks = []
        for batch_no in range(len(state["batches"])):
            batch_dir = checkpoint.batches / f"{batch_no:08d}"
            meta_path = batch_dir / "batch.json"
            meta = read_json(meta_path)
            assembly = state["assemblies"].get(str(batch_no))
            if assembly is None:
                writer = builder.ShardWriter(
                    checkpoint.stage, meta["source_id"], meta["language"], shard_bytes,
                    shard_documents, record_format, shard_compression,
                    shard_index_start=per_source_shards[meta["source_id"]],
                )
                writers.append(writer)
                index_path = batch_dir / "index.jsonl"
                index_tmp = batch_dir / ".index.jsonl.part"
                for stale in (index_path, index_tmp):
                    if stale.is_symlink():
                        raise DataError("Resumable checkpoint batch contains a symlink")
                if index_tmp.exists():
                    index_tmp.unlink()
                index_digest = hashlib.sha256()
                with index_tmp.open("wb") as index:
                    for position, record in enumerate(checkpoint.records(batch_no)):
                        shard, actual_position = writer.append(record)
                        if actual_position != position:
                            raise DataError("Checkpoint shard positioning is inconsistent")
                        line = (json.dumps({
                            "id": record["id"], "source_id": meta["source_id"],
                            "native_id": record["native_id"], "title": record["title"],
                            "shard": shard, "position": position,
                        }, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
                        index.write(line)
                        index_digest.update(line)
                    writer.close()
                    for entry in writer.entries:
                        shard_path = safe_relative(checkpoint.stage, entry["path"])
                        _sync_file(shard_path)
                        _sync_directory(shard_path.parent)
                    index.flush()
                    os.fsync(index.fileno())
                if len(writer.entries) != 1:
                    raise DataError("Resumable checkpoint group did not produce exactly one shard")
                os.replace(index_tmp, index_path)
                _sync_directory(batch_dir)
                assembly = {
                    "shards": writer.entries,
                    "index_sha256": index_digest.hexdigest(),
                    "index_size": index_path.stat().st_size,
                }
                state["assemblies"][str(batch_no)] = assembly
                checkpoint.save_state()
                records_path = checkpoint._records_path(batch_dir, meta)
                records_path.unlink()
                _sync_directory(batch_dir)
            else:
                index_path = batch_dir / "index.jsonl"
                if not index_path.is_file() or index_path.is_symlink():
                    raise DataError("Assembled checkpoint index chunk is missing")
                if (sha256_file(index_path) != assembly["index_sha256"]
                        or index_path.stat().st_size != assembly["index_size"]):
                    raise DataError("Assembled checkpoint index chunk is corrupt")
                for entry in assembly["shards"]:
                    artifact = safe_relative(checkpoint.stage, entry["path"])
                    if (not artifact.is_file() or artifact.is_symlink()
                            or artifact.stat().st_size != entry["size"]
                            or sha256_file(artifact) != entry["sha256"]):
                        raise DataError("Assembled checkpoint shard is corrupt")
            entries.extend(assembly["shards"])
            index_chunks.append(checkpoint.batches / f"{batch_no:08d}" / "index.jsonl")
            per_source_shards[meta["source_id"]] += len(assembly["shards"])

        index_path = checkpoint.stage / "documents.jsonl"
        index_tmp = checkpoint.stage / ".documents.jsonl.part"
        index_digest = hashlib.sha256()
        with index_tmp.open("wb") as index:
            for chunk in index_chunks:
                with chunk.open("rb") as source_index:
                    shutil.copyfileobj(source_index, index)
                with chunk.open("rb") as source_index:
                    for part in iter(lambda: source_index.read(1024 * 1024), b""):
                        index_digest.update(part)
            index.flush()
            os.fsync(index.fileno())
        if sha256_file(index_tmp) != index_digest.hexdigest():
            raise DataError("Document index bytes changed while writing")
        os.replace(index_tmp, index_path)

        stats = Counter(state["statistics"])
        if not stats["documents"]:
            raise DataError("No usable sentences were extracted; inspect source selection and extraction policy")
        if builder._processor_fingerprint() != processor_hash:
            raise DataError("Processor files changed during the build; rebuild with a stable checkout")
        build_id = "build_" + digest_json({
            "processor": processor_hash, "runtime": runtime, "options": options,
            "snapshots": [manifest["snapshot_id"] for _, manifest in inputs],
        })[:32]
        write_json(checkpoint.stage / "licenses.json", {
            "notice": "Source texts and translations retain their own licenses; this is not a relicensing grant.",
            "licenses": [state["licenses"][key] for key in sorted(state["licenses"])],
        })
        catalog = {
            "schema_version": SCHEMA_VERSION,
            "build_id": build_id,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "scope": "sample" if selection is not None or max_documents
            or any(manifest["mode"] != "full" for _, manifest in inputs) else "full",
            "processor_version": PROCESSOR_VERSION,
            "processor_sha256": processor_hash,
            "git_revision": builder._git_revision(),
            "git_dirty": builder._git_dirty(),
            "runtime": runtime,
            "python_version": builder.platform.python_version(),
            "sqlite_version": sqlite3.sqlite_version,
            "options": options,
            "sources": source_rows,
            "snapshots": snapshots,
            "shards": entries,
            "statistics": dict(sorted(stats.items())),
            "document_index": {"path": "documents.jsonl",
                                "sha256": sha256_file(index_path)},
            "licenses": {"path": "licenses.json",
                         "sha256": sha256_file(checkpoint.stage / "licenses.json")},
        }
        write_json(checkpoint.stage / "catalog.json", catalog)
        notify("Verifying completed corpus artifacts")
        builder.verify_build(checkpoint.stage)
        notify("Publishing verified corpus")
        os.replace(checkpoint.stage, output)
        _sync_directory(output.parent)
        checkpoint.close()
        shutil.rmtree(checkpoint_root)
        return output / "catalog.json"
    except BaseException:
        for writer in writers:
            writer.abort()
        raise
    finally:
        try:
            checkpoint.close()
        except sqlite3.Error:
            pass
