"""A canonical text-free URL still needs to agree with private cue alignment."""
import sqlite3
from contextlib import closing

import pytest
import zstandard
from test_tubelex import build_fixture

from manabi_sentence_db.serialization import (
    DataError,
    canonical_json,
    parse_json,
    read_json,
    sha256_file,
    write_json,
)
from manabi_sentence_db.tubelex import AlignedSentence, reference_record
from manabi_sentence_db.tubelex_index import verify_tubelex_index


def read_export(public):
    return [parse_json(line) for line in zstandard.ZstdDecompressor().decompress(
        (public / "references.jsonl.zst").read_bytes(), max_output_size=1024**2).splitlines()]


def replace_export(private, public, records):
    path = public / "references.jsonl.zst"
    path.write_bytes(zstandard.ZstdCompressor(write_checksum=True).compress(
        b"".join(canonical_json(record) + b"\n" for record in records)))
    for path in (private / "manifest.private.json", public / "manifest.json"):
        manifest = read_json(path)
        manifest["asset"]["sha256"] = sha256_file(public / "references.jsonl.zst")
        write_json(path, manifest)


@pytest.mark.parametrize("damage", ["timing", "video", "boundary", "duplicate"])
def test_deep_verifier_binds_export_to_private_clip_inventory_after_rehash(tmp_path, damage):
    _, private, public, _ = build_fixture(tmp_path)
    records = read_export(public)
    original = records[0]
    video, start, end = original["native_id"].split(":")
    boundary = next(t[9:] for t in original["tags"] if t.startswith("boundary:"))
    if damage == "timing":
        records[0] = reference_record(AlignedSentence("", 100000, 103000, boundary),
            video_id=video, snapshot_id=original["snapshot_id"])
    elif damage == "video":
        records[0] = reference_record(AlignedSentence("", int(start), int(end), boundary),
            video_id="zzzzzzzzzzz", snapshot_id=original["snapshot_id"])
    elif damage == "boundary":
        original["tags"] = [t for t in original["tags"] if not t.startswith("boundary:")] + ["boundary:context-window"]
    else:
        assert len(records) > 1
        records[-1] = records[0]
    replace_export(private, public, records)
    assert verify_tubelex_index(private, public)["deep"] is False
    with pytest.raises(DataError, match="reference inventory"):
        verify_tubelex_index(private, public, deep=True)


def test_reference_binding_ignores_export_and_tag_order_without_changing_input(tmp_path):
    _, private, public, _ = build_fixture(tmp_path)
    records = read_export(public)[::-1]
    for record in records:
        record["tags"].reverse()
    replace_export(private, public, records)
    path = private / "citations.private.sqlite3"
    before = sha256_file(path)
    verify_tubelex_index(private, public, deep=True)
    assert sha256_file(path) == before
    with closing(sqlite3.connect(path)) as db:
        assert not db.execute("SELECT 1 FROM sqlite_schema WHERE name LIKE 'verification_%'").fetchone()



def test_deep_reference_inventory_accepts_an_intentionally_empty_punctuation_export(tmp_path):
    from test_tubelex import _build_vtt
    path, _ = _build_vtt(tmp_path, "WEBVTT\n\n00:00.000 --> 00:03.000\n今日は図書館で本を読みます\n", boundary_mode="punctuation")
    result = verify_tubelex_index(path.parent, tmp_path / "public", deep=True)
    assert result["references"] == 0 and result["reference_verification"] == "private-cue-inventory-v1"


@pytest.mark.parametrize("field,value", [("snapshot_id", "other-snapshot"), ("boundary_mode", "punctuation")])
def test_deep_verifier_binds_stream_metadata_to_advertised_options(tmp_path, field, value):
    _, private, public, manifest_path = build_fixture(tmp_path)
    path = private / "citations.private.sqlite3"
    with sqlite3.connect(path) as db:
        stream_id, raw = db.execute("SELECT id,metadata FROM streams LIMIT 1").fetchone()
        metadata = parse_json(raw)
        metadata[field] = value
        db.execute("UPDATE streams SET metadata=? WHERE id=?", (canonical_json(metadata), stream_id))
    manifest = read_json(manifest_path)
    manifest["index_sha256"] = sha256_file(path)
    write_json(manifest_path, manifest)
    assert verify_tubelex_index(private, public)["deep"] is False
    with pytest.raises(DataError, match="stream metadata"):
        verify_tubelex_index(private, public, deep=True)


def test_build_and_deep_verification_read_stream_metadata_once(tmp_path, monkeypatch):
    from test_tubelex import _build_vtt

    from manabi_sentence_db import tubelex_index as index

    original = index._reference_stream
    reads = []

    def observed(database, stream_id):
        reads.append(stream_id)
        return original(database, stream_id)

    monkeypatch.setattr(index, "_reference_stream", observed)
    vtt = "WEBVTT\n\n" + "\n\n".join(
        f"00:00:{number:02}.000 --> 00:00:{number + 1:02}.000\n"
        "今日は図書館へ行きます。明日は公園へ行きます。"
        for number in range(20)
    )
    path, manifest = _build_vtt(tmp_path, vtt)
    assert len(reads) <= manifest["stats"]["streams"]
    reads.clear()
    result = verify_tubelex_index(path.parent, tmp_path / "public", deep=True)
    assert result["references"] == manifest["references"]
    assert len(reads) == result["streams"]
