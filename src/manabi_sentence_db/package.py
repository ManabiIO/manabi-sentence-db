"""Bounded ZIP archives and streaming Zstandard SQLite release artifacts."""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path

import zstandard

from .build import iter_records, verify_build
from .database import build_database
from .serialization import DataError, require_new_directory, safe_relative, sha256_file, write_json
from .validation import SCHEMAS

MAX_RELEASE_ASSET = 1024 * 1024 * 1024


def _entry(root: Path, path: Path, **metadata) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        **metadata,
    }


def _zip_member(archive: zipfile.ZipFile, source: Path, name: str):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    with source.open("rb") as incoming, archive.open(info, "w", force_zip64=True) as outgoing:
        shutil.copyfileobj(incoming, outgoing, 1024 * 1024)


class _PartsWriter:
    def __init__(self, root: Path, name: str, max_bytes: int):
        self.root, self.name, self.max_bytes = root, name, max_bytes
        self.paths: list[Path] = []
        self.handle = None
        self.size = 0

    def write(self, data: bytes):
        view = memoryview(data)
        total = len(data)
        while view:
            if self.handle is None:
                path = self.root / f"{self.name}.part{len(self.paths):04d}"
                self.paths.append(path)
                self.handle = path.open("wb")
                self.size = 0
            count = min(len(view), self.max_bytes - self.size)
            self.handle.write(view[:count])
            self.size += count
            view = view[count:]
            if self.size == self.max_bytes:
                self.handle.close()
                self.handle = None
        return total

    def flush(self):
        if self.handle:
            self.handle.flush()

    def close(self):
        if self.handle:
            self.handle.close()
            self.handle = None
        if len(self.paths) == 1:
            old = self.paths[0]
            new = self.root / self.name
            old.rename(new)
            self.paths[0] = new


def package_build(
    build: Path,
    output: Path,
    *,
    archive_bytes=128 * 1024 * 1024,
    part_bytes=MAX_RELEASE_ASSET,
    include_sqlite=True,
) -> Path:
    require_new_directory(output)
    if not (1024 <= archive_bytes <= MAX_RELEASE_ASSET // 2):
        raise DataError("ZIP input budget must be between 1 KiB and 512 MiB")
    if not (1024 <= part_bytes <= MAX_RELEASE_ASSET):
        raise DataError("Asset part size must be between 1 KiB and 1 GiB")
    catalog = verify_build(build)
    for name in ("catalog.json", "licenses.json", "documents.jsonl"):
        if (build / name).stat().st_size >= 2 * 1024**3:
            raise DataError(
                f"Metadata file {name} exceeds GitHub's 2 GiB asset limit. "
                "Build fewer sources per release; changing the YAML shard budget "
                "does not reduce the document index."
            )
    # Validation is required even for YAML-only releases. A checksum establishes
    # byte integrity, not schema validity, identity consistency, or permission.
    for _ in iter_records(build, catalog):
        pass
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    assets = []
    databases = []
    try:
        partitions: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for shard in catalog["shards"]:
            partitions[(shard["source_id"], shard["language"])].append(shard)
        for (source_id, language), shards in sorted(partitions.items()):
            groups: list[list[dict]] = []
            group: list[dict] = []
            size = 0
            for shard in shards:
                if group and size + shard["size"] > archive_bytes:
                    groups.append(group)
                    group, size = [], 0
                group.append(shard)
                size += shard["size"]
            if group:
                groups.append(group)
            for number, group in enumerate(groups):
                archive_path = safe_relative(staging, f"{source_id}.{language}.yaml-{number:04d}.zip")
                with zipfile.ZipFile(
                    archive_path,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=6,
                    allowZip64=True,
                ) as archive:
                    for shard in group:
                        _zip_member(archive, safe_relative(build, shard["path"]), shard["path"])
                    _zip_member(archive, build / "licenses.json", "licenses.json")
                    snapshot = next(s for s in catalog["snapshots"] if s["source_id"] == source_id)
                    _zip_member(
                        archive, safe_relative(build, snapshot["manifest"]), snapshot["manifest"]
                    )
                assets.append(
                    _entry(
                        staging,
                        archive_path,
                        kind="yaml-zip",
                        source_id=source_id,
                        language=language,
                        members=[shard["path"] for shard in group],
                    )
                )
            if include_sqlite:
                db_path = safe_relative(staging, f"{source_id}.{language}.sqlite3")
                build_database(build, db_path, source_id=source_id, catalog=catalog)
                db_hash, db_size = sha256_file(db_path), db_path.stat().st_size
                writer = _PartsWriter(staging, db_path.name + ".zst", part_bytes)
                try:
                    with db_path.open("rb") as incoming:
                        zstandard.ZstdCompressor(level=9, write_checksum=True).copy_stream(
                            incoming, writer
                        )
                finally:
                    writer.close()
                parts = [
                    _entry(
                        staging,
                        path,
                        kind="sqlite-zstd-part",
                        source_id=source_id,
                        language=language,
                    )
                    for path in writer.paths
                ]
                assets.extend(parts)
                databases.append(
                    {
                        "source_id": source_id,
                        "language": language,
                        "uncompressed_path": db_path.name,
                        "uncompressed_size": db_size,
                        "uncompressed_sha256": db_hash,
                        "compression": "zstd",
                        "parts": [part["path"] for part in parts],
                    }
                )
                db_path.unlink()
        for name in ["catalog.json", "licenses.json", "documents.jsonl"]:
            shutil.copyfile(build / name, staging / name)
            assets.append(_entry(staging, staging / name, kind="metadata"))
        with zipfile.ZipFile(
            staging / "provenance-and-schemas.zip", "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for snapshot in catalog["snapshots"]:
                _zip_member(
                    archive, safe_relative(build, snapshot["manifest"]), snapshot["manifest"]
                )
            for schema in sorted(SCHEMAS.glob("*.json")):
                _zip_member(archive, schema, "schemas/" + schema.name)
        assets.append(_entry(staging, staging / "provenance-and-schemas.zip", kind="metadata-zip"))
        if any(asset["size"] >= 2 * 1024**3 for asset in assets) or len(assets) + 2 > 1000:
            raise DataError(
                "Release exceeds GitHub asset limits; build fewer sources per release or change shard budget"
            )
        release = {
            "schema_version": 1,
            "build_id": catalog["build_id"],
            "scope": catalog["scope"],
            "assets": assets,
            "databases": databases,
            "sqlite_restore": "Concatenate each database's parts in listed order, then decompress the single zstd stream. Verify the uncompressed SHA-256.",
            "yaml_restore": "Extract YAML ZIP members into a common directory. The external catalog and document index locate a document's shard without decompressing the entire corpus.",
        }
        write_json(staging / "release.json", release)
        checksum_paths = sorted(path for path in staging.iterdir() if path.is_file())
        (staging / "SHA256SUMS").write_text(
            "".join(f"{sha256_file(path)}  {path.name}\n" for path in checksum_paths),
            encoding="utf-8",
        )
        os.replace(staging, output)
        return output / "release.json"
    finally:
        if staging.exists():
            shutil.rmtree(staging)
