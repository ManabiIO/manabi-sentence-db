import json

import pytest
from test_snapshot import Response, sample_bytes, wiki_source

from manabi_sentence_db import snapshot, transport
from manabi_sentence_db.snapshot import SnapshotError, create_snapshot, verify_snapshot
from manabi_sentence_db.transport import snapshot_pack, snapshot_unpack


@pytest.fixture
def sample_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "_open", lambda *_: Response(sample_bytes()))
    return create_snapshot(wiki_source(), tmp_path / "snapshot")


def test_split_bundle_round_trip_is_offline(sample_snapshot, tmp_path, monkeypatch):
    bundle_path = snapshot_pack(sample_snapshot, tmp_path / "bundle", max_part_bytes=31)
    bundle = json.loads(bundle_path.read_text())
    assert len(bundle["files"][0]["parts"]) > 1
    assert all(part["size"] <= 31 for item in bundle["files"] for part in item["parts"])
    restored = snapshot_unpack(bundle_path, tmp_path / "restored")
    assert verify_snapshot(restored) == verify_snapshot(sample_snapshot)
    assert snapshot_unpack(bundle_path, restored.parent) == restored
    assert snapshot_pack(sample_snapshot, bundle_path.parent, max_part_bytes=31) == bundle_path


def test_bad_part_never_publishes_partial_snapshot(sample_snapshot, tmp_path):
    bundle_path = snapshot_pack(sample_snapshot, tmp_path / "bundle", max_part_bytes=31)
    bundle = json.loads(bundle_path.read_text())
    part = bundle_path.parent / bundle["files"][0]["parts"][0]["path"]
    part.write_bytes(b"corrupt")
    with pytest.raises(SnapshotError, match="content mismatch"):
        snapshot_unpack(bundle_path, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_missing_part_is_not_downloaded(sample_snapshot, tmp_path):
    bundle_path = snapshot_pack(sample_snapshot, tmp_path / "bundle", max_part_bytes=31)
    bundle = json.loads(bundle_path.read_text())
    (bundle_path.parent / bundle["files"][0]["parts"][0]["path"]).unlink()
    with pytest.raises(SnapshotError, match="Missing snapshot part"):
        snapshot_unpack(bundle_path, tmp_path / "restored")


def test_bundle_manifest_tampering_is_detected(sample_snapshot, tmp_path):
    bundle_path = snapshot_pack(sample_snapshot, tmp_path / "bundle", max_part_bytes=31)
    bundle = json.loads(bundle_path.read_text())
    bundle["files"][0]["path"] = "../escape"
    bundle_path.write_text(json.dumps(bundle))
    with pytest.raises(SnapshotError, match="identity mismatch"):
        snapshot_unpack(bundle_path, tmp_path / "restored")


def test_bundle_rejects_duplicate_json_keys(sample_snapshot, tmp_path):
    path = snapshot_pack(sample_snapshot, tmp_path / "bundle")
    path.write_text('{"schema_version":1,' + path.read_text().lstrip()[1:])
    with pytest.raises(SnapshotError, match="Duplicate JSON key"):
        snapshot_unpack(path, tmp_path / "restored")


@pytest.mark.parametrize("change", ["version", "size", "embedded_source"])
def test_bundle_semantics_checked_with_recomputed_identity(sample_snapshot, tmp_path, change):
    path = snapshot_pack(sample_snapshot, tmp_path / "bundle")
    bundle = json.loads(path.read_text())
    if change == "version":
        bundle["schema_version"] = True
    elif change == "size":
        bundle["files"][0]["size"] = True
    else:
        bundle["snapshot"]["source"]["title"] = "Changed"
    bundle["bundle_id"] = transport._identity(bundle)
    path.write_text(json.dumps(bundle))
    with pytest.raises(SnapshotError):
        snapshot_unpack(path, tmp_path / "restored")


@pytest.mark.parametrize("size", [0, -1, True, 2 * 1024**3])
def test_part_size_respects_release_limit(sample_snapshot, tmp_path, size):
    with pytest.raises(SnapshotError, match="less than 2 GiB"):
        snapshot_pack(sample_snapshot, tmp_path / "bundle", max_part_bytes=size)
