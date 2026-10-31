"""Synthetic caption archives only; never acquire or scan upstream captions."""
import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest
import yaml

from manabi_sentence_db import yj_captions as yj
from manabi_sentence_db.build import build_corpus, iter_records, verify_build
from manabi_sentence_db.normalized import export_normalized
from manabi_sentence_db.serialization import (
    DataError,
    canonical_json,
    digest_json,
    sha256_file,
    write_json,
)
from manabi_sentence_db.snapshot import snapshot_identity


def fixture(tmp_path, monkeypatch, rows=None, extra=False, mode=None, raw=None):
    source = yaml.safe_load(Path("sources/yj-captions-ja.yaml").read_text())
    rows = rows if rows is not None else [
        {"id": 1, "image_id": 9, "caption": "今日は公園を散歩しました。"},
        {"id": 2, "image_id": 9, "caption": "川の水がとてもきれいですね。"},
        {"id": 3, "image_id": 9, "caption": "青い空と白い雲"}]
    path = tmp_path / "captions.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo(yj.MEMBER)
        if mode is not None:
            info.create_system = 3
            info.external_attr = mode << 16
        archive.writestr(info, raw if raw is not None else json.dumps({
            "annotations": rows, "images": [{"url": "private-image-url", "license": "private-image-rights"}],
            "licenses": ["private-license"], "translations": ["private-English"]}, ensure_ascii=False))
        if extra:
            archive.writestr("unexpected.json", "{}")
    checksum = sha256_file(path)
    source["acquisition"].update(sha256=checksum, size=path.stat().st_size)
    monkeypatch.setattr(yj, "SHA256", checksum)
    monkeypatch.setattr(yj, "MAX_ARCHIVE_BYTES", path.stat().st_size)
    manifest = {"schema_version": 1, "source": source, "source_id": source["id"],
                "source_config_sha256": digest_json(source), "mode": "sample", "upstream_date": None,
                "retrieved_at": "2026-10-31T00:00:00Z", "request": {"synthetic": True},
                "files": [{"path": path.name, "role": yj.ROLE, "sha256": sha256_file(path),
                           "size": path.stat().st_size, "url": source["acquisition"]["url"]}]}
    manifest["snapshot_id"] = snapshot_identity(manifest)
    return manifest


def test_independent_human_original_caption_provenance(tmp_path, monkeypatch):
    manifest = fixture(tmp_path, monkeypatch)
    from collections import Counter

    stats = Counter()
    docs = list(yj.iter_documents(manifest, tmp_path, stats=stats))
    assert stats["publisher_captions_seen"] == 3
    assert stats["rejected:yj-incomplete-caption"] == 1
    assert [d["native_id"] for d in docs] == ["1", "2"]
    assert docs[0]["source_text_hash"] == hashlib.sha256(canonical_json(
        {"id": 1, "image_id": 9, "caption": "今日は公園を散歩しました。"})).hexdigest()
    for doc in docs:
        assert doc["authorship"] == "human" and doc["language_origin"] == "original_japanese"
        assert doc["content_type"] == "caption" and len(doc["sentences"]) == 1
        assert doc["sentences"][0]["translations"] == []
        assert "context:image-not-included" in doc["tags"]
        assert yj.REVISION in doc["revision"]["url"]
    assert "private-" not in json.dumps(docs)


@pytest.mark.parametrize("row", [None, {}, {"id": True, "image_id": 1, "caption": "猫です。"},
    {"id": 1, "image_id": -1, "caption": "猫です。"},
    {"id": 1, "image_id": 1, "caption": None},
    {"id": 1, "image_id": 1, "caption": " "},
    {"id": 2**64, "image_id": 1, "caption": "猫です。"}])
def test_invalid_rows(tmp_path, monkeypatch, row):
    with pytest.raises(DataError):
        list(yj.iter_documents(fixture(tmp_path, monkeypatch, [row]), tmp_path))


def test_duplicate_incomplete_rows_still_fail(tmp_path, monkeypatch):
    row = {"id": 1, "image_id": 1, "caption": "青い空"}
    with pytest.raises(DataError, match="Duplicate"):
        list(yj.iter_documents(fixture(tmp_path, monkeypatch, [row, row]), tmp_path))


@pytest.mark.parametrize("kwargs", [{"extra": True}, {"mode": stat.S_IFLNK | 0o777},
    {"mode": stat.S_IFDIR | 0o755}, {"raw": '{"annotations":['},
    {"raw": '{"annotations":[],"annotations":[]}'}, {"raw": '{}'}])
def test_invalid_inventory_or_json(tmp_path, monkeypatch, kwargs):
    with pytest.raises(DataError):
        list(yj.iter_documents(fixture(tmp_path, monkeypatch, **kwargs), tmp_path))


def test_member_bound(tmp_path, monkeypatch):
    manifest = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(yj, "MAX_MEMBER_BYTES", 1)
    with pytest.raises(DataError, match="oversized"):
        list(yj.iter_documents(manifest, tmp_path))


def test_compressed_build_and_normalized_export(tmp_path, monkeypatch):
    manifest = fixture(tmp_path, monkeypatch)
    path = tmp_path / "manifest.json"
    write_json(path, manifest)
    build_corpus([path], tmp_path / "build", record_format="jsonl", shard_compression="zstd")
    records = list(iter_records(tmp_path / "build", verify_build(tmp_path / "build")))
    assert len(records) == 2 and "private-" not in json.dumps(records)
    result = export_normalized(tmp_path / "build", tmp_path / "normalized.zip")
    with zipfile.ZipFile(result) as archive:
        works = [json.loads(line) for line in archive.read("works.jsonl").splitlines()]
        occurrences = [json.loads(line) for line in archive.read("occurrences.jsonl").splitlines()]
    assert len(works) == 2 and len(occurrences) == 2


@pytest.mark.parametrize("field,value", [("revision", "unreviewed"), ("sha256", "0" * 64),
    ("size", True), ("url", "https://example.com/unreviewed.zip")])
def test_review_pins_required(tmp_path, monkeypatch, field, value):
    manifest = fixture(tmp_path, monkeypatch)
    manifest["source"]["acquisition"][field] = value
    with pytest.raises(DataError, match="reviewed"):
        list(yj.iter_documents(manifest, tmp_path))


def test_snapshot_pins_without_network(tmp_path, monkeypatch):
    from manabi_sentence_db import snapshot
    from manabi_sentence_db.validation import load_source

    source = load_source(Path("sources/yj-captions-ja.yaml"))
    calls = []

    def download(staging, filename, role, url, agent, **kwargs):
        calls.append((filename, role, url, kwargs))
        raw = b"synthetic transport only"
        (staging / filename).write_bytes(raw)
        return {"path": filename, "role": role, "url": url, "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest()}

    monkeypatch.setattr(snapshot, "_download", download)
    path = snapshot.create_snapshot(source, tmp_path / "snapshot", mode="full")
    assert snapshot.verify_snapshot(path)["mode"] == "full"
    assert calls == [("yjcaptions26k.zip", yj.ROLE, source["acquisition"]["url"],
                      {"expected_sha256": yj.SHA256, "expected_size": yj.MAX_ARCHIVE_BYTES})]
    with pytest.raises(snapshot.SnapshotError, match="pinned full archive"):
        snapshot.create_snapshot(source, tmp_path / "sample", mode="sample")
    assert len(calls) == 1


def test_archive_bytes_must_match_reviewed_release(tmp_path, monkeypatch):
    manifest = fixture(tmp_path, monkeypatch)
    path = tmp_path / manifest["files"][0]["path"]
    raw = bytearray(path.read_bytes())
    raw[0] ^= 1
    path.write_bytes(raw)
    with pytest.raises(DataError, match="archive checksum"):
        list(yj.iter_documents(manifest, tmp_path))
