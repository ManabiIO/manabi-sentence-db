import copy
import hashlib
import json
import stat
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from manabi_sentence_db.build import build_corpus, canonical_document, iter_records, verify_build
from manabi_sentence_db.jmrd import ROLE, TRANSFORMATION, iter_documents
from manabi_sentence_db.normalized import export_normalized
from manabi_sentence_db.serialization import DataError, digest_json, sha256_file, write_json
from manabi_sentence_db.snapshot import SnapshotError, snapshot_identity
from manabi_sentence_db.transport import snapshot_pack
from manabi_sentence_db.validation import load_source

LICENSE = b"Synthetic fixture CC BY-SA 4.0"
README = b"Synthetic human dialogue fixture"


def dialogue():
    return {"dialog_id": "00001", "movie_title": "private-movie-metadata",
            "first_speaker": "seeker", "questionnaire": {"private-evaluation": 5},
            "knowledge": {"[知識なし]": "[知識なし]", "タイトル": "架空の作品",
                          "レビュー": ["この作品は毎回見るたびに楽しい気分になれます。"],
                          "あらすじ": ["この架空の例では、長い外部の解説文を直接コピーしています。"]},
            "dialog": [
                {"utterance_id": "00001_00", "speaker": "seeker", "text": "今日は映画を見たいです。"},
                {"utterance_id": "00001_01", "speaker": "recommender", "text": "一緒に映画を選びましょう。",
                 "checked_knowledge": [{"type": "[知識なし]", "content": "[知識なし]"}]},
                {"utterance_id": "00001_02", "speaker": "recommender", "text": "外部の紹介を言い換えました。",
                 "checked_knowledge": [{"type": "あらすじ", "content": "外部のあらすじ"}]},
                {"utterance_id": "00001_03", "speaker": "seeker", "text": "明日は友達と見に行きます。"},
            ]}


def fixture(tmp_path, value=None, *, raw=None):
    source = copy.deepcopy(load_source(Path("sources/jmrd-ja.yaml")))
    source["acquisition"]["dialogue_counts"] = {"train": 1, "valid": 0, "test": 0}
    source["acquisition"]["license_sha256"] = hashlib.sha256(LICENSE).hexdigest()
    source["acquisition"]["readme_sha256"] = hashlib.sha256(README).hexdigest()
    path = tmp_path / "jmrd.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("repo/LICENSE", LICENSE)
        archive.writestr("repo/README.md", README)
        archive.writestr("repo/data/train.json", raw if raw is not None else json.dumps(
            [dialogue() if value is None else value], ensure_ascii=False))
        for split in ("valid", "test"):
            archive.writestr(f"repo/data/{split}.json", "[]")
        archive.writestr("repo/generated/model.json", '[{"text":"機械の発話です。"}]')
    manifest = {"schema_version": 1, "source": source, "source_id": source["id"],
        "source_config_sha256": digest_json(source), "mode": "sample", "upstream_date": None,
        "retrieved_at": "2026-11-04T00:00:00Z", "request": {"synthetic": True},
        "files": [{"path": path.name, "role": ROLE, "sha256": sha256_file(path),
                   "size": path.stat().st_size, "url": source["acquisition"]["url"]}]}
    manifest["snapshot_id"] = snapshot_identity(manifest)
    return manifest


def test_authored_turns_preserve_credit_text_and_gaps_without_external_metadata(tmp_path):
    manifest = fixture(tmp_path)
    stats = Counter()
    document = next(iter_documents(manifest, tmp_path, stats=stats))
    record = canonical_document(document, manifest, stats, set())
    assert [row["text"] for row in record["sentences"]] == [
        "今日は映画を見たいです。", "一緒に映画を選びましょう。", "明日は友達と見に行きます。"]
    assert [row["ordinal"] for row in record["sentences"]] == [0, 1, 3]
    assert record["authorship"] == "human" and record["language_origin"] == "original_japanese"
    assert record["url"].endswith("/data/train.json")
    assert record["revision"]["id"] == manifest["source"]["acquisition"]["revision"]
    assert record["license"] == manifest["source"]["license"]
    assert record["attribution"] == manifest["source"]["attribution"]
    assert TRANSFORMATION in record["transformations"]
    assert "private-" not in json.dumps(record)
    assert all(row["review_state"] == "unreviewed" for row in record["sentences"])
    assert stats["rejected:jmrd-external-knowledge"] == 1


@pytest.mark.parametrize("speaker", ["seeker", "recommender"])
def test_literal_copy_of_external_prose_is_withheld_even_with_factual_annotation(tmp_path, speaker):
    value = dialogue()
    value["dialog"][0].update(speaker=speaker,
        text="なお、この架空の例では、長い外部の解説文を直接コピーしています。",
        checked_knowledge=[{"type": "タイトル", "content": "架空の作品"}])
    manifest = fixture(tmp_path, value)
    stats = Counter()
    record = canonical_document(next(iter_documents(manifest, tmp_path, stats=stats)), manifest, stats, set())
    assert value["dialog"][0]["text"] not in [r["text"] for r in record["sentences"]]
    assert stats["rejected:jmrd-external-prose-copy"] == 1


def test_missing_grounding_and_addressed_turns_create_context_barriers(tmp_path):
    value = dialogue()
    value["dialog"][1].pop("checked_knowledge")
    value["dialog"][2]["text"] = "@架空さん、こんにちは。"
    manifest = fixture(tmp_path, value)
    record = canonical_document(next(iter_documents(manifest, tmp_path)), manifest, Counter(), set())
    assert [r["ordinal"] for r in record["sentences"]] == [0, 3]


def test_long_factual_movie_title_alone_is_not_an_external_prose_copy(tmp_path):
    value = dialogue()
    title = "架空の長い映画作品の題名だけを話題として紹介するためのタイトル"
    value["knowledge"]["タイトル"] = title
    value["knowledge"]["あらすじ"] = [f"とくに{title}はとても印象に残りました。"]
    value["dialog"][0]["text"] = f"前に{title}を見たことがあります。"
    manifest = fixture(tmp_path, value)
    document = next(iter_documents(manifest, tmp_path))
    assert value["dialog"][0]["text"] in [r["text"] for r in document["sentences"] if isinstance(r, dict)]


def test_first_party_crowdwritten_review_grounding_and_literal_reuse_are_retained(tmp_path):
    value = dialogue()
    review = value["knowledge"]["レビュー"][0]
    value["dialog"][0]["text"] = review
    value["dialog"][1].update(text=review + "おすすめですよ。",
        checked_knowledge=[{"type": "レビュー", "content": review}])
    manifest = fixture(tmp_path, value)
    record = canonical_document(next(iter_documents(manifest, tmp_path)), manifest, Counter(), set())
    assert [r["text"] for r in record["sentences"]][:3] == [review, review, "おすすめですよ。"]
    assert record["license"]["id"] == "CC-BY-SA-4.0"
    assert "knowledge" not in record and "questionnaire" not in record
    assert all(r["review_state"] == "unreviewed" for r in record["sentences"])


def test_first_party_review_label_does_not_restore_copied_wikipedia_plot(tmp_path):
    value = dialogue()
    plot = value["knowledge"]["あらすじ"][0]
    value["knowledge"]["レビュー"] = [plot]
    value["dialog"][1].update(text=plot,
        checked_knowledge=[{"type": "レビュー", "content": plot}])
    manifest = fixture(tmp_path, value)
    stats = Counter()
    document = next(iter_documents(manifest, tmp_path, stats=stats))
    assert plot not in [r["text"] for r in document["sentences"] if isinstance(r, dict)]
    assert stats["rejected:jmrd-external-prose-copy"] == 1


@pytest.mark.parametrize("change", [
    lambda d: d.update(dialog_id="bad"),
    lambda d: d.update(dialog=[]),
    lambda d: d["dialog"][1].update(utterance_id="other_01"),
    lambda d: d["dialog"][1].update(utterance_id="00001_00"),
    lambda d: d["dialog"][1].update(speaker="model"),
    lambda d: d["dialog"][1].update(text=None),
    lambda d: d["dialog"][1].update(checked_knowledge="bad"),
    lambda d: d["dialog"][1].update(checked_knowledge=[{"type": "タイトル", "content": "not-in-source"}]),
])
def test_invalid_turn_identity_types_and_retained_grounding_fail_closed(tmp_path, change):
    value = dialogue()
    change(value)
    manifest = fixture(tmp_path, value)
    with pytest.raises(DataError):
        list(iter_documents(manifest, tmp_path))


@pytest.mark.parametrize("raw", [b'[', b'[{"dialog_id":"1","dialog_id":"2"}]', b'[]trailing'])
def test_malformed_or_trailing_json_fails(tmp_path, raw):
    manifest = fixture(tmp_path, raw=raw)
    with pytest.raises(DataError):
        list(iter_documents(manifest, tmp_path))


def test_exact_license_inventory_is_checked_before_any_dialogue(tmp_path):
    manifest = fixture(tmp_path)
    manifest["source"]["acquisition"]["license_sha256"] = "0" * 64
    with pytest.raises(DataError, match="license evidence"):
        next(iter_documents(manifest, tmp_path))


def test_duplicate_work_ids_across_splits_and_symlinks_are_rejected(tmp_path):
    manifest = fixture(tmp_path)
    with zipfile.ZipFile(tmp_path / "jmrd.zip") as archive:
        members = {item.filename: archive.read(item) for item in archive.infolist()}
    members["repo/data/valid.json"] = json.dumps([dialogue()])
    with zipfile.ZipFile(tmp_path / "jmrd.zip", "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    manifest["source"]["acquisition"]["dialogue_counts"]["valid"] = 1
    with pytest.raises(DataError, match="Duplicate JMRD dialogue"):
        list(iter_documents(manifest, tmp_path))
    manifest = fixture(tmp_path)
    with zipfile.ZipFile(tmp_path / "jmrd.zip") as archive:
        members = {item.filename: archive.read(item) for item in archive.infolist()}
    with zipfile.ZipFile(tmp_path / "jmrd.zip", "w") as archive:
        for name, data in members.items():
            if name != "repo/data/test.json":
                archive.writestr(name, data)
        info = zipfile.ZipInfo("repo/data/test.json")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "elsewhere")
    with pytest.raises(DataError, match="symlink"):
        list(iter_documents(manifest, tmp_path))


def test_compressed_pipeline_export_retains_exact_context_and_blocks_raw_release(tmp_path):
    manifest = fixture(tmp_path)
    path = tmp_path / "manifest.json"
    write_json(path, manifest)
    build_corpus([path], tmp_path / "build", record_format="jsonl", shard_compression="zstd")
    records = list(iter_records(tmp_path / "build", verify_build(tmp_path / "build")))
    assert len(records) == 1 and len(records[0]["sentences"]) == 3
    output = export_normalized(tmp_path / "build", tmp_path / "processed.zip")
    with zipfile.ZipFile(output) as archive:
        occurrences = [json.loads(line) for line in archive.read("occurrences.jsonl").splitlines()]
        assert [(r["previous_id"], r["next_id"]) for r in occurrences] == [
            (None, occurrences[1]["id"]), (occurrences[0]["id"], None), (None, None)]
        assert "private-" not in archive.read("works.jsonl").decode()
    with pytest.raises(SnapshotError, match="raw"):
        snapshot_pack(path, tmp_path / "raw-output")
    assert not (tmp_path / "raw-output").exists()
