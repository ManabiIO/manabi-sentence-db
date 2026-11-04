import copy
import hashlib
import io
import json
import tarfile
from collections import Counter
from pathlib import Path

import pytest

from manabi_sentence_db.build import build_corpus, canonical_document, iter_records, verify_build
from manabi_sentence_db.massive import ROLE, TRANSFORMATION, iter_documents
from manabi_sentence_db.serialization import DataError, digest_json, sha256_file, write_json
from manabi_sentence_db.snapshot import create_snapshot, snapshot_identity
from manabi_sentence_db.validation import load_source

NOTICE = b"Synthetic publisher notice: MASSIVE dataset CC BY 4.0."
LICENSE = b"Copyright Amazon.com Inc. or its affiliates.\nAttribution 4.0 International\nCreative Commons Attribution 4.0 International Public License"
ARCHIVE_NOTICE = b"Synthetic SLURP attribution and CC BY 4.0 notice."


def row(identity="0"):
    return {"id": identity, "locale": "ja-JP", "partition": "train", "scenario": "weather",
            "intent": "weather_query", "utt": "明日の天気を教えてください", "worker_id": "author",
            "annot_utt": "[date : 明日]の天気を教えてください",
            "slot_method": [{"slot": "date", "method": "localization"}],
            "judgments": [dict(worker_id=worker, intent_score=1, slots_score=1,
                               grammar_score=4, spelling_score=2, language_identification="target")
                          for worker in ["reviewer-1", "reviewer-2", "author"]]}


def fixture(tmp_path, rows=None, *, extra=None, omit=()):
    rows = [row()] if rows is None else rows
    source = copy.deepcopy(load_source(Path("sources/massive-ja.yaml")))
    source["acquisition"].update(partition_counts={"train": len(rows), "dev": 0, "test": 0},
        publisher_notice={"url": "https://example.org/NOTICE", "size": len(NOTICE),
                          "sha256": hashlib.sha256(NOTICE).hexdigest()},
        archive_notice_sha256=hashlib.sha256(ARCHIVE_NOTICE).hexdigest())
    (tmp_path / "publisher-NOTICE.md").write_bytes(NOTICE)
    archive = tmp_path / "massive.tar.gz"
    members = {"1.1/data/ja-JP.jsonl": b"\n".join(
        json.dumps(r, ensure_ascii=False).encode() for r in rows) + b"\n",
        "1.1/data/en-US.jsonl": b'{"utt":"DO NOT EXPORT ENGLISH LOCALIZATION PROMPTS"}\n',
        "1.1/NOTICE.md": ARCHIVE_NOTICE, "1.1/LICENSE": LICENSE}
    with tarfile.open(archive, "w:gz") as tar:
        for name, content in members.items():
            if name in omit:
                continue
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        if extra:
            tar.addfile(*extra)
    source["acquisition"].update(size=archive.stat().st_size, sha256=sha256_file(archive))
    manifest = dict(schema_version=1, source=source, source_id=source["id"],
        source_config_sha256=digest_json(source), mode="sample", upstream_date=None,
        retrieved_at="2026-11-04T00:00:00Z", request={"synthetic": True}, files=[
            dict(path=archive.name, role=ROLE, sha256=sha256_file(archive),
                 size=archive.stat().st_size, url=source["acquisition"]["url"]),
            dict(path="publisher-NOTICE.md", role="massive-publisher-notice", size=len(NOTICE),
                 sha256=hashlib.sha256(NOTICE).hexdigest(), url="https://example.org/NOTICE")])
    manifest["snapshot_id"] = snapshot_identity(manifest)
    return manifest


def test_human_localized_requests_keep_rights_and_ids_without_false_translation_pairs(tmp_path):
    manifest = fixture(tmp_path)
    stats = Counter()
    raw = next(iter_documents(manifest, tmp_path, stats=stats))
    record = canonical_document(raw, manifest, stats, set())
    assert record["authorship"] == "human"
    assert record["language_origin"] == "human_translation"
    assert record["sentences"][0]["text"] == row()["utt"]
    assert record["sentences"][0]["review_state"] == "unreviewed"
    assert record["sentences"][0]["translations"] == []
    assert record["license"]["id"] == "CC-BY-4.0"
    assert TRANSFORMATION in record["transformations"]
    serialized = json.dumps(record)
    assert not any(term in serialized for term in ["worker_id", "reviewer-1", "judgments", "annot_utt", "DO NOT EXPORT"])
    assert "utterance 0" in record["title"]


@pytest.mark.parametrize("change", [
    lambda r: r["judgments"].pop(0),
    lambda r: r["judgments"][0].update(grammar_score=2),
    lambda r: r["judgments"][0].update(spelling_score=1),
    lambda r: r["judgments"][0].update(intent_score=0),
    lambda r: r["judgments"][0].update(language_identification="english"),
    lambda r: r.update(judgments=[]),
])
def test_insufficient_or_adverse_independent_reviews_are_withheld(tmp_path, change):
    value = row()
    change(value)
    manifest = fixture(tmp_path, [value])
    stats = Counter()
    assert list(iter_documents(manifest, tmp_path, stats=stats)) == []
    assert stats["massive_rows_seen"] == 1
    assert sum(n for k, n in stats.items() if k.startswith("rejected:")) == 1


@pytest.mark.parametrize("change", [
    lambda r: r.update(locale="en-US"),
    lambda r: r.update(partition="unknown"),
    lambda r: r["judgments"][0].update(grammar_score=True),
    lambda r: r["judgments"][0].update(worker_id="reviewer-2"),
    lambda r: r["judgments"][0].update(language_identification="not-documented"),
])
def test_malformed_locale_review_and_identity_fields_fail_closed(tmp_path, change):
    value = row()
    change(value)
    manifest = fixture(tmp_path, [value])
    with pytest.raises(DataError):
        list(iter_documents(manifest, tmp_path))


def test_duplicate_ids_even_among_rejected_rows_fail(tmp_path):
    bad = row()
    bad["judgments"] = []
    manifest = fixture(tmp_path, [bad, row()])
    with pytest.raises(DataError, match="Duplicate"):
        list(iter_documents(manifest, tmp_path))


def test_self_review_is_not_counted_but_english_loan_names_and_good_enough_grammar_are_kept(tmp_path):
    value = row()
    value["judgments"][0].update(grammar_score=3, language_identification="target & english")
    value["judgments"][2].update(grammar_score=0, spelling_score=0)
    manifest = fixture(tmp_path, [value])
    assert len(list(iter_documents(manifest, tmp_path))) == 1


@pytest.mark.parametrize("language,kept", [
    ("target|english", True), ("english|target", True),
    ("target & english", True), ("target|other", False),
    ("target|english|other", False), ("other|target|english", False),
])
def test_actual_release_multilanguage_labels_preserve_the_same_review_gate(tmp_path, language, kept):
    value = row()
    value["judgments"][0]["language_identification"] = language
    manifest = fixture(tmp_path, [value])
    stats = Counter()
    records = list(iter_documents(manifest, tmp_path, stats=stats))
    assert bool(records) is kept
    assert stats["rejected:massive-adverse-independent-review"] == int(not kept)


@pytest.mark.parametrize("language", ["target||english", "target|target", "target|unknown", ""])
def test_unknown_empty_or_repeated_language_components_are_not_guessed(tmp_path, language):
    value = row()
    value["judgments"][0]["language_identification"] = language
    with pytest.raises(DataError, match="language"):
        list(iter_documents(fixture(tmp_path, [value]), tmp_path))


def test_changed_publisher_notice_and_partition_count_are_rejected(tmp_path):
    manifest = fixture(tmp_path)
    path = tmp_path / "publisher-NOTICE.md"
    path.write_bytes(b"x" * len(NOTICE))
    with pytest.raises(DataError, match="notice"):
        next(iter_documents(manifest, tmp_path))
    path.write_bytes(NOTICE)
    manifest["source"]["acquisition"]["partition_counts"]["train"] = 2
    with pytest.raises(DataError, match="inventory"):
        list(iter_documents(manifest, tmp_path))


@pytest.mark.parametrize("omit", [("1.1/LICENSE",), ("1.1/NOTICE.md",)])
def test_licensing_evidence_is_required_before_first_record_even_when_license_is_last(tmp_path, omit):
    manifest = fixture(tmp_path, omit=omit)
    with pytest.raises(DataError, match="license|notice|evidence"):
        next(iter_documents(manifest, tmp_path))


@pytest.mark.parametrize("name,kind", [("../escape", tarfile.REGTYPE),
                                       ("1.1/data/ja-JP.jsonl", tarfile.REGTYPE),
                                       ("1.1/link", tarfile.SYMTYPE)])
def test_unsafe_duplicate_or_link_members_fail_before_first_record(tmp_path, name, kind):
    info = tarfile.TarInfo(name)
    info.type = kind
    manifest = fixture(tmp_path, extra=(info, io.BytesIO()))
    with pytest.raises(DataError):
        next(iter_documents(manifest, tmp_path))
    assert not (tmp_path.parent / "escape").exists()


def test_full_compressed_pipeline_keeps_independent_utterances_in_separate_works(tmp_path):
    manifest = fixture(tmp_path, [row("0"), row("1")])
    snapshot = tmp_path / "manifest.json"
    write_json(snapshot, manifest)
    output = tmp_path / "build"
    build_corpus([snapshot], output, record_format="jsonl", shard_compression="zstd")
    catalog = verify_build(output)
    records = list(iter_records(output, catalog))
    assert len(records) == 2 and all(len(r["sentences"]) == 1 for r in records)
    assert catalog["statistics"]["massive_rows_seen"] == 2
    assert catalog["statistics"]["translations"] == 0
    assert all(r["path"].endswith(".zst") for r in catalog["shards"])


def test_snapshot_downloads_exact_archive_and_rights_pins_then_reuses_without_network(tmp_path, monkeypatch):
    from manabi_sentence_db import snapshot as snapshots

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    source = fixture(inputs)["source"]
    requested = []

    def download(destination, name, role, url, agent, *, expected_sha256, expected_size):
        origin = inputs / ("massive.tar.gz" if role == ROLE else "publisher-NOTICE.md")
        assert sha256_file(origin) == expected_sha256 and origin.stat().st_size == expected_size
        requested.append((url, role))
        (destination / name).write_bytes(origin.read_bytes())
        return dict(path=name, role=role, url=url, sha256=expected_sha256, size=expected_size)

    monkeypatch.setattr(snapshots, "_download", download)
    output = tmp_path / "snapshot"
    result = create_snapshot(source, output, mode="full")
    assert [r[1] for r in requested] == [ROLE, "massive-publisher-notice"]

    def no_network(*args, **kwargs):
        raise AssertionError("An unchanged MASSIVE snapshot must not download again")

    monkeypatch.setattr(snapshots, "_download", no_network)
    assert create_snapshot(source, output, mode="full") == result
