import zipfile

import pytest
import zstandard

from manabi_sentence_db.build import (
    ShardWriter,
    _shard_records,
    build_corpus,
    iter_records,
    verify_build,
)
from manabi_sentence_db.demo import create_demo_snapshot
from manabi_sentence_db.package import package_build, verify_package
from manabi_sentence_db.serialization import DataError, sha256_file


@pytest.mark.parametrize("record_format", ["yaml", "jsonl"])
def test_compressed_canonical_roundtrip_and_package(tmp_path, record_format):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    builds = []
    for compression in ("none", "zstd"):
        build = tmp_path / compression
        build_corpus([snapshot], build, record_format=record_format, shard_compression=compression)
        builds.append(build)
    plain, compressed = (verify_build(build) for build in builds)
    assert list(iter_records(builds[0], plain)) == list(iter_records(builds[1], compressed))
    for left, right in zip(plain["shards"], compressed["shards"], strict=True):
        data = (builds[1] / right["path"]).read_bytes()
        assert right["path"].endswith("." + record_format + ".zst")
        assert data.startswith(b"\x28\xb5\x2f\xfd")
        assert len(data) == right["size"] < left["size"]
        assert sha256_file(builds[1] / right["path"]) == right["sha256"]
        assert zstandard.ZstdDecompressor().decompress(data, max_output_size=left["size"]) == (builds[0] / left["path"]).read_bytes()
    release = package_build(builds[1], tmp_path / "release")
    manifest = verify_package(release.parent)
    assert manifest["databases"]
    for asset in manifest["assets"]:
        if asset["kind"] == record_format + "-zip":
            with zipfile.ZipFile(release.parent / asset["path"]) as archive:
                for name in asset["members"]:
                    assert archive.read(name) == (builds[1] / name).read_bytes()


@pytest.mark.parametrize("damage", ["truncate", "junk", "frame", "corrupt"])
def test_compressed_shard_rejects_invalid_frame(tmp_path, damage):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    build = tmp_path / "corpus"
    build_corpus([snapshot], build, shard_compression="zstd")
    catalog = verify_build(build)
    entry = catalog["shards"][0]
    path = build / entry["path"]
    data = path.read_bytes()
    if damage == "truncate":
        data = data[:-1]
    elif damage == "junk":
        data += b"junk"
    elif damage == "frame":
        data += zstandard.ZstdCompressor().compress(b"")
    else:
        data = data[:-1] + bytes([data[-1] ^ 1])
    path.write_bytes(data)
    with pytest.raises(DataError, match="zstd"):
        list(_shard_records(build, catalog, entry))


def test_format_compression_mismatch_is_rejected(tmp_path):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    build = tmp_path / "corpus"
    build_corpus([snapshot], build, shard_compression="zstd")
    catalog = verify_build(build)
    catalog["options"]["shard_compression"] = "none"
    with pytest.raises(DataError, match="format/compression"):
        list(iter_records(build, catalog))


def test_compressor_finalization_failure_closes_unpublished_shard(tmp_path):
    writer = ShardWriter(tmp_path, "fixture", "ja", 4096, 10, "jsonl", "zstd")
    writer.append({"text": "今日は雨です。"})
    handle = writer.handle

    class BrokenCompressor:
        def flush(self):
            raise OSError("deliberate compressor failure")

    writer.compressor = BrokenCompressor()
    with pytest.raises(OSError, match="deliberate compressor failure"):
        writer.close()
    assert handle.closed and writer.handle is None
    assert not writer.entries
    assert not list(tmp_path.rglob("*.jsonl.zst"))
    writer.abort()


def test_compressed_shard_rejects_large_window_from_header_before_reading_records(tmp_path):
    # A valid empty frame declaring a 128 MiB window must exceed the 64 MiB cap.
    # This pins the library's actual byte units rather than trusting its docs.
    frame = b"\x28\xb5\x2f\xfd\x00\x88\x01\x00\x00"
    assert zstandard.get_frame_parameters(frame).window_size == 128 * 1024**2
    path = tmp_path / "large.jsonl.zst"
    path.write_bytes(frame)
    catalog = {"options": {"record_format": "jsonl", "shard_compression": "zstd"}}
    with pytest.raises(DataError, match="requires too much memory"):
        list(_shard_records(tmp_path, catalog, {"path": path.name, "documents": 1}))
