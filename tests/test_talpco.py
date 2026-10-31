"""Small authored TALPCo fixtures; no upstream requests or source text."""

import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from manabi_sentence_db.build import build_corpus, canonical_document, verify_build
from manabi_sentence_db.normalized import export_normalized
from manabi_sentence_db.serialization import DataError, canonical_json
from manabi_sentence_db.snapshot import snapshot_identity
from manabi_sentence_db.talpco import iter_documents, validate_source
from manabi_sentence_db.validation import load_source, validate_record


def fixture(tmp_path, *, ja=None, en=None):
    blobs = {
        "ja": ja if ja is not None else "101\t公園には 大きな 池が あります。\r\n205\t今日は 晴れて います。\r\n".encode(),
        "en": en if en is not None else b"205\tIt is sunny today.\r\n101\tThere is a large pond in the park.\r\n",
    }
    source = load_source(Path("sources/talpco-ja.yaml"))
    source["acquisition"]["pair_count"] = 2
    files = []
    for language, data in blobs.items():
        path = tmp_path / f"talpco-{language}.txt"
        path.write_bytes(data)
        pin = source["acquisition"]["files"][language]
        pin.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        files.append(dict(path=path.name, role="talpco-" + language, **pin))
    manifest = dict(
        schema_version=1, source_id=source["id"], source=source,
        source_config_sha256=hashlib.sha256(canonical_json(source)).hexdigest(),
        mode="sample", request={"synthetic": True}, upstream_date=None,
        retrieved_at="2026-10-31T00:00:00Z", files=files,
    )
    manifest["snapshot_id"] = snapshot_identity(manifest)
    return manifest


def test_pairs_join_by_id_preserve_spaces_and_publisher_provenance(tmp_path):
    manifest = fixture(tmp_path)
    stats = Counter()
    documents = list(iter_documents(manifest, tmp_path, stats=stats))
    assert [d["native_id"] for d in documents] == ["101", "205"]
    assert stats["publisher_pairs_seen"] == 2
    records = [canonical_document(d, manifest, stats, set()) for d in documents]
    for record in records:
        validate_record(record)
        assert len(record["sentences"]) == 1
        assert record["language_origin"] == "original_japanese"
        assert record["authorship"] == "unknown"
        assert record["license"]["id"] == "CC-BY-4.0"
        assert "published_at" not in record
        translation = record["sentences"][0]["translations"][0]
        assert translation["generation"] == {"kind": "human"}
        assert translation["alignment"] == "human"
        assert "review" not in translation
        assert translation["license"]["id"] == "CC-BY-4.0"
        assert "Nomoto" in translation["attribution"]["text"]
        assert "/eng/data_eng.txt" in translation["source_url"]
    sentence = records[0]["sentences"][0]
    assert sentence["text"] == "公園には 大きな 池が あります。"
    assert sentence["translations"][0]["text"] == "There is a large pond in the park."


@pytest.mark.parametrize("ja,en", [
    (b"101\tOne.\n101\tTwo.\n", None),
    (None, b"101\tOne.\n101\tTwo.\n"),
    (b"101\tOne.\n", None),
    (None, b"101\tOne.\n206\tTwo.\n"),
    (b"0\tOne.\n205\tTwo.\n", None),
    (b"101 One.\n205\tTwo.\n", None),
    (b"101\tOne.\textra\n205\tTwo.\n", None),
    (b"101\t\n205\tTwo.\n", None),
    (b"101\tOne.\n\n205\tTwo.\n", None),
    (b"101\t\xff\n205\tTwo.\n", None),
    (b"101\tOne.\v205\tTwo.\n", None),
])
def test_defects_fail_before_yielding_any_work(tmp_path, ja, en):
    manifest = fixture(tmp_path, ja=ja, en=en)
    with pytest.raises(DataError):
        next(iter_documents(manifest, tmp_path, stats=Counter()))


def test_inventory_size_hash_and_us_adaptation_fail_closed(tmp_path):
    manifest = fixture(tmp_path)
    manifest["files"].append(dict(manifest["files"][0]))
    with pytest.raises(DataError, match="inventory"):
        list(iter_documents(manifest, tmp_path, stats=Counter()))
    manifest = fixture(tmp_path)
    manifest["source"]["acquisition"]["files"]["en"]["size"] += 1
    with pytest.raises(DataError, match="size"):
        list(iter_documents(manifest, tmp_path, stats=Counter()))
    manifest = fixture(tmp_path)
    manifest["source"]["acquisition"]["files"]["en"]["sha256"] = "0" * 64
    with pytest.raises(DataError, match="checksum"):
        list(iter_documents(manifest, tmp_path, stats=Counter()))
    source = fixture(tmp_path)["source"]
    source["acquisition"]["files"]["en"]["url"] = source["acquisition"]["files"]["en"]["url"].replace("data_eng.txt", "data_eng-US.txt")
    with pytest.raises(DataError, match="file pin"):
        validate_source(source)


def test_complete_pair_is_not_split_and_shared_quality_gate_applies(tmp_path):
    manifest = fixture(tmp_path)
    raw = list(iter_documents(manifest, tmp_path, stats=Counter()))[0]
    raw["sentences"][0]["text"] = "公園には 池が あります。毎朝 鳥が 来ます。"
    record = canonical_document(raw, manifest, Counter(), set())
    assert len(record["sentences"]) == 1
    assert record["sentences"][0]["translations"]
    raw["sentences"][0]["text"] = "髭。"
    assert canonical_document(raw, manifest, Counter(), set()) is None


def test_offline_fixture_build_and_normalized_export_have_no_neighbor_links(tmp_path):
    manifest = fixture(tmp_path)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    build = tmp_path / "build"
    build_corpus([path], build, record_format="jsonl")
    catalog = verify_build(build)
    assert catalog["scope"] == "sample"
    assert catalog["statistics"]["sentences"] == 2
    assert catalog["statistics"]["translations"] == 2
    normalized = export_normalized(build, tmp_path / "normalized.zip")
    with zipfile.ZipFile(normalized) as archive:
        works = [json.loads(line) for line in archive.read("works.jsonl").splitlines()]
        occurrences = [json.loads(line) for line in archive.read("occurrences.jsonl").splitlines()]
        translations = [json.loads(line) for line in archive.read("translations.jsonl").splitlines()]
    assert {w["native_id"] for w in works} == {"101", "205"}
    assert all(o["previous_id"] is None and o["next_id"] is None for o in occurrences)
    assert all(t["generation"] == {"kind": "human"} for t in translations)


def test_snapshot_acquires_only_two_pinned_raw_files(tmp_path, monkeypatch):
    from manabi_sentence_db.snapshot import create_snapshot, verify_snapshot

    manifest = fixture(tmp_path)
    source = manifest["source"]
    blobs = {e["url"]: (tmp_path / e["path"]).read_bytes() for e in manifest["files"]}
    calls = []

    def download(staging, filename, role, url, agent, *, expected_sha256, expected_size):
        calls.append(url)
        data = blobs[url]
        assert hashlib.sha256(data).hexdigest() == expected_sha256
        assert len(data) == expected_size
        (staging / filename).write_bytes(data)
        return dict(path=filename, role=role, url=url, size=len(data), sha256=expected_sha256)

    monkeypatch.setattr("manabi_sentence_db.snapshot._download", download)
    path = create_snapshot(source, tmp_path / "snapshot", mode="full")
    verified = verify_snapshot(path)
    assert set(calls) == set(blobs)
    assert {e["role"] for e in verified["files"]} == {"talpco-ja", "talpco-en"}
    assert len(list(iter_documents(verified, path.parent, stats=Counter()))) == 2
    assert create_snapshot(source, path.parent, mode="full") == path
    assert len(calls) == 2
