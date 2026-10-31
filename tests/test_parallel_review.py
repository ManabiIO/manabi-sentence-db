"""Conservative pair diagnostics and compressed bounded review, always offline."""

import hashlib
import json
import urllib.request
from copy import deepcopy

import pytest
import zstandard
from test_alt_parallel import fixture

from manabi_sentence_db.build import build_corpus
from manabi_sentence_db.cli import main
from manabi_sentence_db.parallel_review import audit_parallel_numbers, number_signal
from manabi_sentence_db.serialization import DataError, canonical_json
from manabi_sentence_db.snapshot import snapshot_identity


@pytest.mark.parametrize("ja,en,expected", [
    ("昨日は34844レウ、前日は36133レウだった。", "Yesterday 35,844 lei, previously 36,133 lei.", "different-numerals"),
    ("料金は３５８４４円です。", "The price is 35,844 yen.", "same-numerals"),
    ("温度は-3.00度です。", "The temperature is -3 degrees.", "same-numerals"),
    ("温度は−3度です。", "Temperature is -3 degrees.", "unsupported-sign-or-operator"),
    ("温度は−3度です。", "Temperature is 3 degrees.", "unsupported-sign-or-operator"),
    ("ロンドン−2012年の大会です。", "London — the 2012 Games.", "unsupported-sign-or-operator"),
    ("値は--3です。", "Value is -4.", "unsupported-sign-or-operator"),
    ("値は++3です。", "Value is 4.", "unsupported-sign-or-operator"),
    ("値は+-3です。", "Value is -4.", "unsupported-sign-or-operator"),
    ("値は3+4です。", "Values are 3 and 5.", "unsupported-sign-or-operator"),
    ("値は1.234,56です。", "Values are 1.234 and 57.", "unsupported-decimal"),
    ("値は,123です。", "Value is 124.", "unsupported-decimal"),
    ("値は1 234です。", "Value is 1234.", "different-number-count"),
    ("昨日は1ユーロ34844レウ、前の価格は36133レウだった。", "One euro cost 35,844 lei; previously 36,133 lei.", "different-large-numerals"),
    ("価格は1ユーロ1234レウだった。", "One euro cost 1,234 lei.", "different-number-count"),
    ("数は3と4でした。", "Numbers were 5 and 6 and 7.", "different-number-count"),
    ("投票率は45%と70%でした。", "Turnout was 50% and 70%.", "different-numerals"),
    ("試合は0対3でした。", "The match finished 0–3.", "date-time-range-or-written-sign"),
    ("割合は99%から99.9%でした。", "Ratio was 99%-99.9%.", "date-time-range-or-written-sign"),
    ("到着は9月15日です。", "Arrival is September 15.", "date-time-range-or-written-sign"),
    ("若者は2人でした。", "Two people arrived on February 4.", "date-time-range-or-written-sign"),
    ("料金は10円と20円です。", "Prices are 20 and 10 yen.", "same-numerals"),
    ("料金は10円と10円です。", "Prices are 10 and 20 yen.", "different-numerals"),
    ("価格は1.234567890123456789円です。", "Price is 1.234567890123456788 yen.", "different-numerals"),
    ("写真には4万人が写っている。", "There are 40,000 people.", "magnitude-notation"),
    ("写真には40000人が写っている。", "There are 40 thousand people.", "magnitude-notation"),
    ("時刻は17時30分です。", "Time is 1730 UTC.", "date-time-range-or-written-sign"),
    ("価格は10から20円です。", "Prices are 10-20 yen.", "date-time-range-or-written-sign"),
    ("日付は2011/3/11です。", "Date is 3/11/2011.", "date-time-range-or-written-sign"),
    ("気温はマイナス3度です。", "It is -3 degrees.", "date-time-range-or-written-sign"),
    ("新製品はX300です。", "The new product is X400.", "identifier-or-ordinal"),
    ("新製品は型_300です。", "The new product is 400.", "identifier-or-ordinal"),
    ("値は1,23です。", "Value is 123.", "unsupported-grouping"),
    ("値は.5です。", "Value is 0.5.", "unsupported-decimal"),
    ("値は1.2.3です。", "Value is 123.", "unsupported-decimal"),
    ("犬が来た。", "The dog came.", "missing-digits-on-one-or-both-sides"),
    ("犬は3匹いた。", "Three dogs were there.", "missing-digits-on-one-or-both-sides"),
    ("犬は3匹、猫は2匹いた。", "There were 3 dogs.", "different-number-count"),
])
def test_numeric_diagnostics_do_not_claim_translation_accuracy(ja, en, expected):
    assert number_signal(ja, en) == expected


def make_build(tmp_path):
    ja = [("SNT.1.1", "料金は1234円です。"), ("SNT.1.2", "料金は200円です。")]
    en = [("SNT.1.1", "The price is 1,334 yen."), ("SNT.1.2", "The price is 200 yen.")]
    manifest = fixture(tmp_path, ja=ja, en=en)
    blob = (tmp_path / "fixture.zip").read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    source = manifest["source"]
    source["acquisition"].update(size=len(blob), sha256=digest)
    manifest.update(schema_version=1, source_config_sha256=hashlib.sha256(canonical_json(source)).hexdigest(),
                    mode="sample", request={"synthetic": True}, upstream_date=None,
                    retrieved_at="2026-10-31T00:00:00Z")
    manifest["files"][0].update(size=len(blob), sha256=digest, url=source["acquisition"]["url"])
    manifest["snapshot_id"] = snapshot_identity(manifest)
    snapshot = tmp_path / "manifest.json"
    snapshot.write_text(json.dumps(manifest))
    build = tmp_path / "build"
    build_corpus([snapshot], build, record_format="jsonl", shard_compression="zstd")
    return build


def test_offline_cli_summary_and_compressed_packet_preserve_rights(tmp_path, monkeypatch, capsys):
    build = make_build(tmp_path)
    before = {p.relative_to(build): p.read_bytes() for p in build.rglob("*") if p.is_file()}
    def no_network(*args, **kwargs):
        raise AssertionError("Review is offline")
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", no_network)
    report, packet = tmp_path / "report.json", tmp_path / "review.json.zst"
    assert main(["audit-parallel-numbers", "--build", str(build), "--output", str(report),
                 "--review-output", str(packet)]) == 0
    assert "料金" not in capsys.readouterr().out
    summary = json.loads(report.read_bytes())
    assert summary["pairs"] == 2
    assert summary["signals"] == {"different-numerals": 1, "same-numerals": 1}
    assert not summary["contains_source_text"] and not summary["corpus_changed"]
    assert summary["automatic_rejections"] == 0 and not summary["human_review"]
    assert "料金" not in report.read_text() and "1,334" not in report.read_text()
    value = json.loads(zstandard.ZstdDecompressor().decompress(packet.read_bytes()))
    case = value["cases"][0]
    assert case["scope"] == "sentence" and case["text"] == "料金は1234円です。"
    assert case["license"]["id"] == "CC-BY-4.0"
    assert case["translation"]["license"]["id"] == "CC-BY-2.5"
    assert case["attribution"] and case["translation"]["attribution"]
    assert "generation" not in case["translation"] and not case["reviewed"]
    assert before == {p.relative_to(build): p.read_bytes() for p in build.rglob("*") if p.is_file()}


@pytest.mark.parametrize("max_cases", [0, 1])
def test_deterministic_case_bound_does_not_limit_counting(tmp_path, max_cases):
    build = make_build(tmp_path)
    report, packet = tmp_path / "report.json", tmp_path / "review.json.zst"
    audit_parallel_numbers(build, report, review_output=packet, max_cases=max_cases)
    summary = json.loads(report.read_bytes())
    value = json.loads(zstandard.ZstdDecompressor().decompress(packet.read_bytes()))
    assert len(value["cases"]) == max_cases and summary["pairs"] == 2
    second = tmp_path / "second.json"
    audit_parallel_numbers(build, second)
    assert "review_packet" not in json.loads(second.read_bytes())


@pytest.mark.parametrize("limit", [-1, 1001, True, 1.2])
def test_invalid_limits_fail_before_outputs(tmp_path, limit):
    with pytest.raises(DataError):
        audit_parallel_numbers(tmp_path / "missing", tmp_path / "report.json", max_cases=limit)
    assert not (tmp_path / "report.json").exists()


def test_outputs_refuse_aliases_existing_paths_and_input_tree(tmp_path):
    build = make_build(tmp_path)
    output = tmp_path / "report.json"
    output.write_text("preserve")
    with pytest.raises(DataError):
        audit_parallel_numbers(build, output)
    assert output.read_text() == "preserve"
    link = tmp_path / "alias"
    link.symlink_to(build, target_is_directory=True)
    for target in (link / "output.json", build / "output.json"):
        with pytest.raises(DataError):
            audit_parallel_numbers(build, target)
    with pytest.raises(DataError):
        audit_parallel_numbers(build, tmp_path / "fresh.json", review_output=tmp_path / "packet.json")
    with pytest.raises(DataError):
        audit_parallel_numbers(build, tmp_path / "fresh.json", source_id="missing")
    assert not (tmp_path / "fresh.json").exists()


def test_corrupt_or_changed_input_cannot_publish_a_success_report(tmp_path, monkeypatch):
    from manabi_sentence_db import parallel_review as module
    build = make_build(tmp_path)
    original = module.iter_records
    def changed(*args):
        yield from original(*args)
        shard = next((build / "jsonl").rglob("*.zst"))
        with shard.open("ab") as stream:
            stream.write(b"changed")
    monkeypatch.setattr(module, "iter_records", changed)
    with pytest.raises(DataError):
        audit_parallel_numbers(build, tmp_path / "report.json", review_output=tmp_path / "packet.zst")
    assert not (tmp_path / "report.json").exists() and not (tmp_path / "packet.zst").exists()


def test_split_source_unit_translation_counted_once_with_original_scope(tmp_path, monkeypatch):
    from test_segments import _record

    from manabi_sentence_db import parallel_review as module
    translation = dict(language="en", text="There were 3 dogs. They left.",
                       source_url="https://example.org/translation", license={"id":"CC-BY-4.0","url":"https://creativecommons.org/licenses/by/4.0/"},
                       attribution={"text":"Synthetic translator","url":"https://example.org/translator"})
    record, _ = _record("犬は2匹いた。みんな帰った。", [translation])
    assert len(record["sentences"]) == 2
    build = make_build(tmp_path)
    monkeypatch.setattr(module, "iter_records", lambda *args: iter([deepcopy(record)]))
    output, packet = tmp_path / "report.json", tmp_path / "packet.zst"
    audit_parallel_numbers(build, output, review_output=packet)
    assert json.loads(output.read_bytes())["pairs"] == 1
    case = json.loads(zstandard.ZstdDecompressor().decompress(packet.read_bytes()))["cases"][0]
    assert case["scope"] == "source-unit" and case["text"] == "犬は2匹いた。みんな帰った。"
