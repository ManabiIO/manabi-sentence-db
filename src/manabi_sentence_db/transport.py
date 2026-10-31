"""Bounded transport for raw snapshots, without recompressing upstream archives."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

from .serialization import read_json
from .snapshot import (
    READ_SIZE,
    SnapshotError,
    canonical_json,
    safe_filename,
    sha256_file,
    snapshot_identity,
    verify_snapshot,
)

DEFAULT_PART_BYTES = 1024**3
GITHUB_ASSET_LIMIT = 2 * 1024**3
GITHUB_ASSET_COUNT = 1000


def _identity(bundle: dict) -> str:
    return hashlib.sha256(
        canonical_json({key: value for key, value in bundle.items() if key != "bundle_id"})
    ).hexdigest()


def _load_bundle(path: Path, *, verify_parts: bool) -> dict:
    try:
        bundle = read_json(path)
        if not isinstance(bundle, dict):
            raise SnapshotError("Snapshot bundle must be an object")
        if (
            type(bundle["schema_version"]) is not int
            or bundle["schema_version"] != 1
            or bundle["kind"] != "snapshot-bundle"
        ):
            raise SnapshotError("Unsupported snapshot bundle")
        if bundle["bundle_id"] != _identity(bundle):
            raise SnapshotError("Snapshot bundle identity mismatch")
        snapshot = bundle["snapshot"]
        if not isinstance(snapshot, dict) or snapshot["snapshot_id"] != snapshot_identity(snapshot):
            raise SnapshotError("Embedded snapshot identity mismatch")
        if (
            snapshot["source_config_sha256"]
            != hashlib.sha256(canonical_json(snapshot["source"])).hexdigest()
        ):
            raise SnapshotError("Embedded snapshot source configuration hash mismatch")
        if not isinstance(snapshot["files"], list) or not snapshot["files"]:
            raise SnapshotError("Snapshot bundle has no original files")
        originals = {entry["path"]: entry for entry in snapshot["files"]}
        entries = bundle["files"]
        if (
            not isinstance(entries, list)
            or len(originals) != len(snapshot["files"])
            or len(originals) != len(entries)
            or set(originals) != {entry["path"] for entry in entries}
        ):
            raise SnapshotError("Snapshot bundle file inventory mismatch")
        verified = set()
        for entry in entries:
            name = safe_filename(entry["path"])
            if name == "manifest.json":
                raise SnapshotError("Reserved snapshot filename")
            original = originals[name]
            if type(entry["size"]) is not int or entry["size"] < 0:
                raise SnapshotError("Invalid original snapshot file size")
            if not isinstance(entry["sha256"], str) or not re.fullmatch(
                r"[0-9a-f]{64}", entry["sha256"]
            ):
                raise SnapshotError("Invalid original snapshot SHA-256")
            if not isinstance(entry["parts"], list):
                raise SnapshotError("Snapshot bundle parts must be a list")
            if entry["sha256"] != original["sha256"] or entry["size"] != original["size"]:
                raise SnapshotError(f"Snapshot bundle original identity mismatch: {name}")
            if sum(part["size"] for part in entry["parts"]) != entry["size"]:
                raise SnapshotError(f"Snapshot bundle part size mismatch: {name}")
            for part in entry["parts"]:
                part_name = safe_filename(part["path"])
                if not isinstance(part["sha256"], str) or not re.fullmatch(
                    r"[0-9a-f]{64}", part["sha256"]
                ):
                    raise SnapshotError("Invalid snapshot part SHA-256")
                if part_name != f"sha256-{part['sha256']}.part":
                    raise SnapshotError("Snapshot bundle part name/hash mismatch")
                if type(part["size"]) is not int or not 0 < part["size"] < GITHUB_ASSET_LIMIT:
                    raise SnapshotError("Invalid snapshot part size")
                if verify_parts and part_name not in verified:
                    candidate = path.parent / part_name
                    if candidate.is_symlink() or not candidate.is_file():
                        raise SnapshotError(f"Missing snapshot part: {part_name}")
                    if (
                        candidate.stat().st_size != part["size"]
                        or sha256_file(candidate) != part["sha256"]
                    ):
                        raise SnapshotError(f"Snapshot part content mismatch: {part_name}")
                    verified.add(part_name)
        names = {part["path"] for entry in entries for part in entry["parts"]}
        if len(names) + 1 > GITHUB_ASSET_COUNT:
            raise SnapshotError("Snapshot bundle exceeds GitHub's release asset count")
    except SnapshotError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise SnapshotError(f"Malformed snapshot bundle: {error}") from error
    return bundle


def snapshot_pack(
    manifest_path: Path, output: Path, max_part_bytes: int = DEFAULT_PART_BYTES
) -> Path:
    """Split raw files into independently verified release assets below 2 GiB."""
    if (
        isinstance(max_part_bytes, bool)
        or not isinstance(max_part_bytes, int)
        or not 0 < max_part_bytes < GITHUB_ASSET_LIMIT
    ):
        raise SnapshotError("max_part_bytes must be positive and less than 2 GiB")
    manifest_path, output = Path(manifest_path), Path(output)
    snapshot = verify_snapshot(manifest_path)
    if snapshot["source"].get("adapter") == "globalvoices":
        raise SnapshotError(
            "Global Voices raw pages are local rights evidence, including excluded third-party "
            "material; publish only the processed corpus, not raw snapshot release assets"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        inventory = []
        for entry in snapshot["files"]:
            parts = []
            with (manifest_path.parent / entry["path"]).open("rb") as source:
                while True:
                    temporary = staging / "current.part"
                    digest = hashlib.sha256()
                    size = 0
                    with temporary.open("xb") as target:
                        while size < max_part_bytes:
                            chunk = source.read(min(READ_SIZE, max_part_bytes - size))
                            if not chunk:
                                break
                            target.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                    if not size:
                        temporary.unlink()
                        break
                    name = f"sha256-{digest.hexdigest()}.part"
                    destination = staging / name
                    if destination.exists():
                        temporary.unlink()
                    else:
                        temporary.rename(destination)
                    parts.append({"path": name, "sha256": digest.hexdigest(), "size": size})
            inventory.append(
                {
                    "path": entry["path"],
                    "sha256": entry["sha256"],
                    "size": entry["size"],
                    "parts": parts,
                }
            )
        if len(list(staging.iterdir())) + 1 > GITHUB_ASSET_COUNT:
            raise SnapshotError(
                "Snapshot needs over 1,000 assets; use larger parts or object storage"
            )
        bundle = {
            "schema_version": 1,
            "kind": "snapshot-bundle",
            "snapshot": snapshot,
            "files": inventory,
        }
        bundle["bundle_id"] = _identity(bundle)
        (staging / "bundle.json").write_text(
            json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        if output.exists():
            prior = _load_bundle(output / "bundle.json", verify_parts=True)
            if prior["bundle_id"] != bundle["bundle_id"]:
                raise SnapshotError(f"Refusing to replace a different snapshot bundle: {output}")
            return output / "bundle.json"
        staging.rename(output)
        return output / "bundle.json"
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def snapshot_unpack(bundle_path: Path, output: Path) -> Path:
    """Reconstruct and verify a complete snapshot; never fetch missing pieces."""
    bundle_path, output = Path(bundle_path), Path(output)
    bundle = _load_bundle(bundle_path, verify_parts=False)
    snapshot = bundle["snapshot"]
    if output.exists():
        existing = verify_snapshot(output / "manifest.json")
        if existing["snapshot_id"] != snapshot["snapshot_id"]:
            raise SnapshotError(f"Refusing to replace a different snapshot: {output}")
        return output / "manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        for entry in bundle["files"]:
            digest = hashlib.sha256()
            size = 0
            with (staging / entry["path"]).open("xb") as target:
                for part in entry["parts"]:
                    part_path = bundle_path.parent / part["path"]
                    if part_path.is_symlink() or not part_path.is_file():
                        raise SnapshotError(f"Missing snapshot part: {part['path']}")
                    part_digest = hashlib.sha256()
                    part_size = 0
                    with part_path.open("rb") as source:
                        for chunk in iter(lambda: source.read(READ_SIZE), b""):
                            part_size += len(chunk)
                            if part_size > part["size"]:
                                raise SnapshotError(f"Oversized snapshot part: {part['path']}")
                            part_digest.update(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                            target.write(chunk)
                    if part_size != part["size"] or part_digest.hexdigest() != part["sha256"]:
                        raise SnapshotError(f"Snapshot part content mismatch: {part['path']}")
            if size != entry["size"] or digest.hexdigest() != entry["sha256"]:
                raise SnapshotError(f"Reconstructed snapshot mismatch: {entry['path']}")
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        verify_snapshot(manifest_path)
        staging.rename(output)
        return output / "manifest.json"
    finally:
        if staging.exists():
            shutil.rmtree(staging)
