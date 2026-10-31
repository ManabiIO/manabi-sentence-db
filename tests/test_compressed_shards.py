import random
import zipfile

import pytest
import zstandard

from manabi_sentence_db.build import (
    ShardWriter,
    _shard_records,
    _zstd_shard_chunks,
    build_corpus,
    iter_records,
    verify_build,
)
from manabi_sentence_db.demo import create_demo_snapshot
from manabi_sentence_db.package import package_build, verify_package
from manabi_sentence_db.serialization import DataError, sha256_file


@pytest.mark.parametrize("checksum", [False, True])
@pytest.mark.parametrize("content_size", [False, True])
@pytest.mark.parametrize("kind", ["empty", "raw", "rle", "compressed"])
def test_zstd_block_decoding_bounds_output_and_preserves_bytes(
    tmp_path, checksum, content_size, kind
):
    data = {
        "empty": b"", "raw": random.Random(20261031).randbytes(400_000),
        "rle": b"x" * (1024 * 1024),
        "compressed": "今日は公園に行きました。明日は家で本を読みます。".encode() * 6000,
    }[kind]
    frame = zstandard.ZstdCompressor(write_checksum=checksum, write_content_size=content_size).compress(data)
    path = tmp_path / "blocks.zst"
    path.write_bytes(frame)
    with path.open("rb") as source:
        chunks = list(_zstd_shard_chunks(source))
    assert b"".join(chunks) == data
    assert all(len(chunk) <= 128 * 1024 for chunk in chunks)
    if kind in {"raw", "rle", "compressed"}:
        assert len(chunks) >= 3


@pytest.mark.parametrize("damage", [
    "frame-header", "block-header", "raw-payload", "rle-payload", "checksum",
    "checksum-value", "missing-last-block", "reserved-block", "oversized-block",
    "small-window", "skippable", "skippable-prefix", "skippable-suffix",
])
def test_zstd_block_envelope_rejects_malformed_or_trailing_data(tmp_path, damage):
    # Standard frame, omitted content size, 128 KiB window, one raw JSONL block.
    header = b"\x28\xb5\x2f\xfd\x00\x38"
    body = ((3 << 3) | 1).to_bytes(3, "little") + b"{}\n"
    frame = header + body
    skippable = b"\x50\x2a\x4d\x18\x00\x00\x00\x00"
    if damage == "frame-header":
        frame = header[:-1]
    elif damage == "block-header":
        frame = header + body[:2]
    elif damage == "raw-payload":
        frame = frame[:-1]
    elif damage == "rle-payload":
        frame = header + ((16 << 3) | 3).to_bytes(3, "little")
    elif damage in {"checksum", "checksum-value"}:
        frame = zstandard.ZstdCompressor(write_checksum=True).compress(b"{}\n")
        frame = frame[:-1] if damage == "checksum" else frame[:-1] + bytes([frame[-1] ^ 1])
    elif damage == "missing-last-block":
        frame = header + (3 << 3).to_bytes(3, "little") + b"{}\n"
    elif damage == "reserved-block":
        frame = header + b"\x07\x00\x00"
    elif damage == "oversized-block":
        frame = header + ((131073 << 3) | 1).to_bytes(3, "little")
    elif damage == "small-window":
        frame = header[:-1] + b"\x00" + ((1025 << 3) | 1).to_bytes(3, "little")
    elif damage == "skippable":
        frame = skippable
    elif damage == "skippable-prefix":
        frame = skippable + frame
    elif damage == "skippable-suffix":
        frame += skippable
    path = tmp_path / "bad.jsonl.zst"
    path.write_bytes(frame)
    catalog = {"options": {"record_format": "jsonl", "shard_compression": "zstd"}}
    with pytest.raises(DataError, match="zstd"):
        list(_shard_records(tmp_path, catalog, {"path": path.name, "documents": 1}))


def test_zstd_block_reader_keeps_decoded_record_size_guard(tmp_path):
    path = tmp_path / "oversized.jsonl.zst"
    data = b'{"text":"' + b"x" * (32 * 1024**2) + b'"}\n'
    path.write_bytes(zstandard.ZstdCompressor().compress(data))
    catalog = {"options": {"record_format": "jsonl", "shard_compression": "zstd"}}
    # Declared two documents keep the overall shard bound above this single
    # oversized record, so the individual-record guard must still reject it.
    with pytest.raises(DataError, match="Canonical record exceeds 32 MiB"):
        list(_shard_records(tmp_path, catalog, {"path": path.name, "documents": 2}))


def test_zstd_block_reader_accepts_small_window_and_rejects_wrong_content_size(tmp_path):
    path = tmp_path / "small.jsonl.zst"
    body = b"\x19\x00\x00{}\n"  # Last raw block, three payload bytes.
    catalog = {"options": {"record_format": "jsonl", "shard_compression": "zstd"}}
    entry = {"path": path.name, "documents": 1}
    for header in (b"\x28\xb5\x2f\xfd\x00\x00", b"\x28\xb5\x2f\xfd\x20\x03"):
        path.write_bytes(header + body)
        assert list(_shard_records(tmp_path, catalog, entry)) == [{}]
    path.write_bytes(b"\x28\xb5\x2f\xfd\x20\x04" + body)
    with pytest.raises(DataError, match="zstd"):
        list(_shard_records(tmp_path, catalog, entry))


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


@pytest.mark.parametrize("record_format", ["jsonl", "yaml"])
def test_large_multibyte_record_and_following_records_survive_chunk_boundaries(tmp_path, record_format):
    import json

    import yaml

    rng = random.Random(20261029)
    text = "".join(chr(0x4E00 + rng.randrange(1000)) for _ in range(700_000))
    records = [{"text": text}, {"text": "次の文です。"}, {"text": "最後の文です。"}]
    data = (b"".join(json.dumps(row, ensure_ascii=False).encode() + b"\n" for row in records)
            if record_format == "jsonl" else
            yaml.safe_dump_all(records, allow_unicode=True, explicit_start=True).encode())
    path = tmp_path / ("large." + record_format + ".zst")
    path.write_bytes(zstandard.ZstdCompressor().compress(data))
    catalog = {"options": {"record_format": record_format, "shard_compression": "zstd"}}
    assert list(_shard_records(tmp_path, catalog, {"path": path.name, "documents": 3})) == records
