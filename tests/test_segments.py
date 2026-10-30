from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

from manabi_sentence_db.build import canonical_document
from manabi_sentence_db.serialization import DataError
from manabi_sentence_db.text import sentence_spans
from manabi_sentence_db.validation import load_source, validate_record


def _record(text, translations=None):
    source = load_source(Path("sources/tatoeba-ja.yaml"))
    manifest = {"source": source, "source_id": source["id"], "snapshot_id": "fixture"}
    raw = {"native_id": "12", "language": "ja", "title": "Synthetic unit",
           "url": "https://example.org/12", "license": source["license"],
           "attribution": source["attribution"],
           "sentences": [{"native_id": "12", "text": text,
                          "translations": translations or []}]}
    stats = Counter()
    return canonical_document(raw, manifest, stats, {"sexual-content"}), stats


def test_exact_fragment_ranges_keep_unicode_and_original_whitespace():
    text = "  写真を撮りました。\n  🚲で帰ります。　 本を読みます。 "
    record, stats = _record(text)
    assert [s["text"] for s in record["sentences"]] == [
        "写真を撮りました。", "🚲で帰ります。", "本を読みます。"
    ]
    assert stats["source_units_split"] == 1
    assert len({s["id"] for s in record["sentences"]}) == 3
    for index, sentence in enumerate(record["sentences"]):
        unit = sentence["source_unit"]
        assert unit["text"] == text
        assert text[unit["start"]:unit["end"]] == sentence["text"]
        assert (unit["segment_index"], unit["segment_count"]) == (index, 3)


def test_unit_translation_is_never_mislabeled_as_a_fragment_translation():
    translation = {
        "language": "en", "text": "I took a photo. I read a book.",
        "source_url": "https://example.org/translation/99",
        "license": {"id": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
        "attribution": {"text": "Synthetic translator", "url": "https://example.org/translator"},
        "native_id": "99",
    }
    record, _ = _record("写真を撮りました。本を読みました。", [translation])
    first, second = record["sentences"]
    assert first["translations"] == second["translations"] == []
    assert first["source_unit"]["translations"] == second["source_unit"]["translations"]
    assert first["source_unit"]["translations"][0]["text"] == translation["text"]
    validate_record(record)
    for originals in ([first["source_unit"]["translations"][0]] * 257,
                      [dict(first["source_unit"]["translations"][0], text="x" * 20_001)]):
        oversized = deepcopy(record)
        oversized["sentences"][0]["source_unit"]["translations"] = originals
        with pytest.raises(DataError):
            validate_record(oversized)


def test_quoted_reporting_clause_is_one_sentence_and_keeps_native_identity():
    record, _ = _record("彼は「今日は雨。明日は晴れ。」と言った。")
    assert len(record["sentences"]) == 1
    assert record["sentences"][0]["native_id"] == "12"
    assert "source_unit" not in record["sentences"][0]


@pytest.mark.parametrize("text", [
    "写真を撮りました。＊＊で働いています。",
    "写真を撮りました。性行為に関する説明です。",
    "写真を撮りました。\n{{不明}}です。",
    "写真を撮りました。\n異常\x00な文です。",
    "写真を撮りました。\n「閉じていません。",
])
def test_whole_unit_exclusion_prevents_context_leaks(text):
    record, stats = _record(text)
    assert record is None
    assert any(k.startswith("rejected:") for k in stats)


@pytest.mark.parametrize("withheld", [
    {"text": "写真を撮りました。＊＊で働いています。"},
    {"text": "写真を撮りました。性行為に関する説明です。"},
    {"text": "写真を撮りました。{{不明}}です。"},
    {"text": "写真を撮りました。「閉じていません。"},
    {"text": "生成された文章です。", "generation": {"kind": "machine", "tool": "fixture"}},
    {"text": "文" * 20_001},
    {"text": "猫が来た。" * 257},
])
def test_withheld_whole_unit_preserves_a_context_gap_between_retained_units(withheld):
    source = load_source(Path("sources/tatoeba-ja.yaml"))
    manifest = {"source": source, "source_id": source["id"], "snapshot_id": "fixture"}
    raw = dict(native_id="context-gap", language="ja", title="Synthetic units",
               url="https://example.org/units", license=source["license"],
               attribution=source["attribution"], sentences=[
                   {"native_id": "before", "text": "今日は晴れです。図書館へ行きます。"},
                   dict(withheld, native_id="withheld"),
                   {"native_id": "after", "text": "明日は家で本を読みます。"},
               ])
    record = canonical_document(raw, manifest, Counter(), {"sexual-content"})
    assert [(s["ordinal"], s["text"]) for s in record["sentences"]] == [
        (0, "今日は晴れです。"), (1, "図書館へ行きます。"), (3, "明日は家で本を読みます。")]
    assert "withheld" not in str(record)
    assert "publisher-context-barriers-v1" in record["transformations"]


def test_fragment_hash_offsets_and_index_are_validated():
    record, _ = _record("写真を撮りました。本を読みました。")
    for field, value in [("start", 1), ("end", 1000), ("segment_index", 2),
                         ("text_sha256", "0" * 64)]:
        broken = deepcopy(record)
        broken["sentences"][0]["source_unit"][field] = value
        with pytest.raises(DataError):
            validate_record(broken)


def test_empty_span_and_trim_preserve_offsets():
    assert sentence_spans(" \n\n") == []
    text = "\t今日は晴れです。 \r\n明日は雨です。"
    assert [text[a:b] for a, b in sentence_spans(text)] == ["今日は晴れです。", "明日は雨です。"]


def test_yaml_shared_fragment_metadata_round_trips_without_aliases(tmp_path):
    import yaml

    from manabi_sentence_db.build import ShardWriter, _canonical_translations
    from manabi_sentence_db.serialization import StrictLoader

    record, _ = _record("写真を撮りました。本を読みました。")
    shared_range = {"unit": "utterance", "start": 0, "end": 1}
    shared_translation = {
        "language": "en", "text": "I took a photo. I read a book.",
        "source_url": "https://example.org/translation",
        "license": record["license"], "attribution": record["attribution"],
    }
    translations = _canonical_translations([shared_translation], "fixture-unit")
    for sentence in record["sentences"]:
        sentence["source_range"] = shared_range
        sentence["source_unit"]["translations"] = translations
    validate_record(record)
    writer = ShardWriter(tmp_path, "fixture", "ja", 1024 * 1024, 500, "yaml")
    path, _ = writer.append(record)
    writer.close()
    with (tmp_path / path).open() as stream:
        assert list(yaml.load_all(stream, Loader=StrictLoader)) == [record]


def test_normalized_round_trip_keeps_source_units_and_rejects_context_license_bypass(tmp_path):
    import json
    import sqlite3

    from test_normalized_admission import write_archive

    from manabi_sentence_db.normalized import sentence_identity
    from manabi_sentence_db.normalized_database import build_normalized_database

    translation = {
        "language": "en", "text": "I took a photo. I read a book.",
        "source_url": "https://example.org/translation/99",
        "license": {"id": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
        "attribution": {"text": "Synthetic translator", "url": "https://example.org/translator"},
        "native_id": "99",
    }
    record, _ = _record("写真を撮りました。本を読みました。", [translation])
    tables = {"works": [{k: v for k, v in record.items() if k != "sentences"}],
              "sentences": [], "occurrences": [], "translations": [], "references": []}
    for item in record["sentences"]:
        identity = sentence_identity("ja", item["text"])
        tables["sentences"].append({"id": identity, "language": "ja", "text": item["text"],
                                    "text_sha256": item["text_sha256"]})
        tables["occurrences"].append({k: v for k, v in dict(item, sentence_id=identity,
                                                          work_id=record["id"]).items()
                                      if k not in {"text", "text_sha256", "translations"}})
    archive = write_archive(tmp_path, tables)
    output = build_normalized_database(archive, tmp_path / "valid.sqlite")
    with sqlite3.connect(output) as db:
        assert db.execute("SELECT COUNT(*) FROM translations").fetchone()[0] == 0
        occurrences = [json.loads(row[0]) for row in db.execute("SELECT metadata_json FROM occurrences")]
        assert all(row["source_unit"]["translations"][0]["text"] == translation["text"]
                   for row in occurrences)
    tables["occurrences"][0]["source_unit"]["translations"][0]["license"] = {
        "id": "CC-BY-NC-4.0", "url": "https://creativecommons.org/licenses/by-nc/4.0/",
    }
    archive = write_archive(tmp_path, tables)
    with pytest.raises(DataError, match="license"):
        build_normalized_database(archive, tmp_path / "invalid.sqlite")
    assert not (tmp_path / "invalid.sqlite").exists()
