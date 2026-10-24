import copy
import hashlib
from collections import Counter
from pathlib import Path

import pytest

from manabi_sentence_db.build import build_corpus, canonical_document, iter_records, verify_build
from manabi_sentence_db.scp_curated import ROLE, URL, extract, iter_documents
from manabi_sentence_db.serialization import DataError
from manabi_sentence_db.snapshot import SnapshotError, create_snapshot, verify_snapshot
from manabi_sentence_db.validation import load_source


@pytest.fixture
def sample():
    source = load_source(Path("sources/scp-jp-aptitude-ja.yaml"))
    data = """<!doctype html><html><body><nav><p>NOT NARRATIVE</p></nav>
<div id="page-title">適性</div><div id="page-content">
<div class="rateBox"><p>RATING</p></div>
<div id="u-credit-view"><div class="credit"><p><strong>タイトル:</strong> 適性<br>
<strong>著者:</strong> <a>terukami</a><br><strong>作成年:</strong> 2023</p></div>
<div class="credit-license"><a href="https://creativecommons.org/licenses/by-sa/3.0/deed.ja"></a></div></div>
<div style="text-align: justify;"><p>　コーヒーを飲みました。電話が鳴りました。</p>
<p>「もしもし。」<br>「お疲れ様です。」</p></div></div>
<div class="page-tags"><a>jp</a><a>tale</a></div>
<div id="page-info">ページリビジョン: 10, 最終更新: <span class="odate time_1778854469">15 May 2026</span></div>
<div class="comments"><p>COMMENT</p></div><script>DO NOT EXECUTE</script></body></html>""".encode()
    paragraphs, digest = extract(data, source, check_hash=False)
    source["acquisition"]["body_sha256"] = digest
    return source, data, paragraphs


def test_exact_narrative_boundaries_rights_and_paragraph_units(sample, tmp_path):
    source, data, paragraphs = sample
    assert paragraphs == [
        "　コーヒーを飲みました。電話が鳴りました。",
        "「もしもし。」\n「お疲れ様です。」",
    ]
    (tmp_path / "aptitude.html").write_bytes(data)
    manifest = {
        "source": source,
        "source_id": source["id"],
        "snapshot_id": "synthetic",
        "files": [{"role": ROLE, "path": "aptitude.html"}],
    }
    raw = list(iter_documents(manifest, tmp_path))[0]
    assert raw["source_text_hash"] == hashlib.sha256("\n\n".join(paragraphs).encode()).hexdigest()
    assert raw["authorship"] == "unknown" and raw["language_origin"] == "original_japanese"
    assert "published_at" not in raw  # The credit supplies a creation year, not a publication date.
    assert raw["license"]["id"] == "CC-BY-SA-3.0" and "terukami" in raw["attribution"]["text"]
    assert raw["sentences"][1]["source_range"]["start"] == len(paragraphs[0]) + 2
    record = canonical_document(raw, manifest, Counter(), set())
    assert len(record["sentences"]) == 4
    assert record["sentences"][0]["source_unit"]["text"] == paragraphs[0]
    assert "publisher-html-narrative-extraction" in record["transformations"]
    assert all(
        word not in str(record) for word in ("NOT NARRATIVE", "RATING", "COMMENT", "EXECUTE")
    )


@pytest.mark.parametrize(
    "before,after,reason",
    [
        ("電話が鳴りました", "雨が降りました", "body changed"),
        ("リビジョン: 10", "リビジョン: 11", "revision changed"),
        ("time_1778854469", "time_1778854470", "timestamp changed"),
        ("terukami</a>", "someone</a>", "attribution changed"),
        ("by-sa/3.0/deed.ja", "by-nc/3.0/deed.ja", "license changed"),
        ("<a>jp</a>", "<a>en</a>", "tags changed"),
        ("text-align: justify;", "text-align: left;", "body boundary"),
        ("<p>　コーヒー", '<p><img src="thirdparty">　コーヒー', "media"),
        ("<p>　コーヒー", "<p><script>text</script>　コーヒー", "media"),
    ],
)
def test_fail_closed_on_content_metadata_and_layout_drift(sample, before, after, reason):
    source, data, _ = sample
    with pytest.raises(DataError, match=reason):
        extract(data.decode().replace(before, after).encode(), source)


def test_source_cannot_be_repurposed_for_other_page_or_license(sample):
    source, data, _ = sample
    for field in ("url", "license"):
        changed = copy.deepcopy(source)
        if field == "url":
            changed["acquisition"]["url"] = "https://scp-jp.wikidot.com/other"
        else:
            changed["license"]["id"] = "CC-BY-4.0"
        with pytest.raises(DataError, match="Only the reviewed"):
            extract(data, changed)


def test_snapshot_preserves_raw_bytes_reuses_offline_and_builds(sample, tmp_path, monkeypatch):
    source, data, _ = sample
    calls = []

    def metadata(url, agent):
        assert url == URL
        calls.append(url)
        return data

    monkeypatch.setattr("manabi_sentence_db.snapshot._metadata", metadata)
    manifest = create_snapshot(source, tmp_path / "snapshot", mode="full")
    assert (manifest.parent / "aptitude.html").read_bytes() == data
    assert create_snapshot(source, manifest.parent, mode="full") == manifest
    assert calls == [URL]
    output = tmp_path / "build"
    build_corpus([manifest], output)
    catalog = verify_build(output)
    assert len(list(iter_records(output, catalog))) == 1
    (manifest.parent / "aptitude.html").write_bytes(data + b"changed")
    with pytest.raises(SnapshotError, match="content mismatch"):
        verify_snapshot(manifest)


def test_failed_pin_is_not_published_as_a_snapshot(sample, tmp_path, monkeypatch):
    source, data, _ = sample
    monkeypatch.setattr(
        "manabi_sentence_db.snapshot._metadata",
        lambda *args: data.replace("電話".encode(), "電車".encode()),
    )
    with pytest.raises(DataError, match="body changed"):
        create_snapshot(source, tmp_path / "snapshot", mode="full")
    assert not (tmp_path / "snapshot").exists()
