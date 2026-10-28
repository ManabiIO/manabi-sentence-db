import bz2
import json
from collections import Counter
from pathlib import Path

import pytest
from defusedxml.common import DTDForbidden

from manabi_sentence_db.build import canonical_document
from manabi_sentence_db.text import assess_sentence
from manabi_sentence_db.wikimedia import extract_prose, iter_documents

FIXTURE = Path(__file__).parent / "fixtures" / "wikimedia.xml"
SOURCE = {
    "id": "wikipedia-ja",
    "title": "Japanese Wikipedia",
    "language": "ja",
    "homepage": "https://ja.wikipedia.org/",
    "license": {"id": "CC-BY-SA-4.0", "url": "https://creativecommons.org/licenses/by-sa/4.0/"},
    "acquisition": {"api_url": "https://ja.wikipedia.org/w/api.php"},
}


def manifest(path, role="mediawiki-xml", source=None):
    return {"source": source or SOURCE, "files": [{"path": path, "role": role}]}


def test_halfwidth_stops_survive_prose_completion_without_joining_sentences():
    sentences, tags = extract_prose("朝は公園を歩いた｡ 夕方は家で休んだ｡\n[[Category:生活]]")
    assert sentences == ["朝は公園を歩いた｡", "夕方は家で休んだ｡"]
    assert tags == ["category:生活"]


def test_xml_provenance_main_namespace_and_bzip_stream(tmp_path):
    target = tmp_path / "pages.xml.bz2"
    target.write_bytes(bz2.compress(FIXTURE.read_bytes()))
    documents = list(iter_documents(manifest(target.name), tmp_path))
    assert len(documents) == 1
    doc = documents[0]
    assert doc["native_id"] == "12"
    assert doc["revision"]["id"] == "30"
    assert doc["revision"]["timestamp"] == "2026-01-02T03:04:05Z"
    assert doc["revision"]["url"] == "https://ja.wikipedia.org/w/index.php?oldid=30"
    assert "action=history" in doc["attribution"]["url"]
    assert doc["tags"] == ["category:架空の場所"]
    assert [item["text"] for item in doc["sentences"]] == [
        "架空の公園には大きな池がある。", "毎年多くの人が訪れる。", "公園は架空の町にある。",
    ]


def test_templates_do_not_splice_missing_words():
    sentences, _ = extract_prose("今日は{{lang|en|Tokyo}}に行く。明日は家にいる。")
    accepted = [text for text in sentences if assess_sentence(text)[0]]
    assert accepted == ["明日は家にいる。"]


@pytest.mark.parametrize("link", [
    "[https://example.invalid]",
    "[https://example.invalid ]",
    "[https://example.invalid <!-- no visible label -->]",
])
def test_unlabelled_external_links_do_not_splice_words(link):
    sentences, _ = extract_prose(
        f"最初の文章です。今日は{link}に行った。最後の文章です。"
    )
    assert [text for text in sentences if assess_sentence(text)[0]] == [
        "最初の文章です。", "最後の文章です。",
    ]
    # A detached link does not corrupt a complete preceding sentence or the
    # next paragraph. No surrounding words are silently concatenated.
    sentences, _ = extract_prose(f"最初の文章です。{link}\n最後の文章です。")
    assert sentences == ["最初の文章です。", "最後の文章です。"]


def test_external_link_labels_survive_source_and_canonical_normalization(tmp_path):
    text = (
        "今日は[https://example.invalid]に行った。"
        "今日は[https://example.invalid カ\u3099イドの店]に行った。"
    )
    payload = {"query": {"pages": [{
        "pageid": 12, "ns": 0, "title": "架空", "revisions": [{
            "revid": 35, "timestamp": "2026-01-02T03:04:05Z",
            "slots": {"main": {"contentmodel": "wikitext", "content": text}},
        }],
    }]}}
    (tmp_path / "sample.json").write_text(json.dumps(payload), encoding="utf-8")
    snapshot = {
        **manifest("sample.json", "mediawiki-api", source={**SOURCE, "adapter": "wikimedia"}),
        "source_id": "wikipedia-ja", "snapshot_id": "synthetic",
    }
    raw = next(iter_documents(snapshot, tmp_path))
    stats = Counter()
    record = canonical_document(raw, snapshot, stats, set())
    assert [item["text"] for item in record["sentences"]] == [
        "今日はガイドの店に行った。",
    ]
    assert record["sentences"][0]["review_state"] == "unreviewed"
    assert stats["rejected:unresolved-markup"] == 1


def test_removed_blocks_tables_quotes_lists_and_captions():
    text = """最初の文章です。
{| class="wikitable"
| 表の中の文章です。
|}
<blockquote>引用された文章です。</blockquote>
[[File:Example.jpg|thumb|写真の説明です。]]
* 箇条書きの説明です。
最後の文章です。
"""
    sentences, _ = extract_prose(text)
    assert [text for text in sentences if assess_sentence(text)[0]] == [
        "最初の文章です。", "最後の文章です。",
    ]


def test_removed_unknown_inline_tags_do_not_create_false_sentence():
    sentences, _ = extract_prose("彼は<unknown>重要な語</unknown>と言った。")
    assert not [text for text in sentences if assess_sentence(text)[0]]
    sentences, _ = extract_prose("彼は<q>引用された言葉</q>と言った。")
    assert not [text for text in sentences if assess_sentence(text)[0]]


def test_corner_quotes_and_hidden_styled_blocks_are_excluded():
    sentences, _ = extract_prose(
        '筆者は「すばらしい景色だ」と書いた。別の文章です。\n'
        '<div style="display:none">隠された文章です。</div>\n'
        '最後の文章です。'
    )
    assert sentences == ["別の文章です。", "最後の文章です。"]


def test_language_parameter_is_forwarded_to_segmentation():
    sentences, _ = extract_prose("This is a sample. Another sentence follows.", "en")
    assert sentences == ["This is a sample.", "Another sentence follows."]


def test_reference_sections_resume_only_at_same_or_higher_heading():
    sentences, _ = extract_prose(
        "本文の文章です。\n== 参考文献 ==\n本の説明です。\n=== 補足 ===\nこれも出典です。"
        "\n== 歴史 ==\n新しい本文の文章です。"
    )
    assert sentences == ["本文の文章です。", "新しい本文の文章です。"]


@pytest.mark.parametrize("notice", ["Copyvio", "削除依頼", "Template:即時削除", "subst:Template:Copyvio"])
def test_restricted_notice_rejects_whole_page(notice):
    assert extract_prose("{{" + notice + "}}\nこの文章は取り込まない。")[0] == []


def test_api_sample_current_slot_and_hidden_revision(tmp_path):
    payload = {"query": {"pages": [
        {"pageid": 12, "ns": 0, "title": "架空", "revisions": [{
            "revid": 35, "timestamp": "2026-01-02T03:04:05Z",
            "slots": {"main": {"contentmodel": "wikitext", "content": "公園には大きな木がある。"}},
        }]},
        {"pageid": 13, "ns": 0, "title": "秘匿", "revisions": [{
            "revid": 36, "texthidden": True,
            "slots": {"main": {"content": "この文章は見せてはいけない。"}},
        }]},
    ]}}
    (tmp_path / "sample.json").write_text(json.dumps(payload), encoding="utf-8")
    documents = list(iter_documents(manifest("sample.json", "mediawiki-api"), tmp_path))
    assert len(documents) == 1
    assert documents[0]["revision"]["id"] == "35"


def test_licensing_notice_is_preserved_without_inference(tmp_path):
    source = {**SOURCE, "license": {**SOURCE["license"], "notice": "Historical contributions retain their grants."}}
    (tmp_path / "pages.xml").write_bytes(FIXTURE.read_bytes())
    doc = next(iter_documents(manifest("pages.xml", source=source), tmp_path))
    assert doc["license"] == source["license"]
    assert doc["license"] is not source["license"]


def test_paths_must_remain_inside_snapshot(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        list(iter_documents(manifest("../outside.xml"), tmp_path))


def test_xml_dtd_and_entities_are_rejected(tmp_path):
    (tmp_path / "bad.xml").write_text(
        '<!DOCTYPE mediawiki [<!ENTITY external SYSTEM "file:///etc/passwd">]>'
        '<mediawiki><page><title>&external;</title></page></mediawiki>', encoding="utf-8",
    )
    with pytest.raises(DTDForbidden):
        list(iter_documents(manifest("bad.xml"), tmp_path))


def test_saved_api_errors_are_not_silently_empty(tmp_path):
    (tmp_path / "error.json").write_text('{"error":{"code":"maxlag"}}', encoding="utf-8")
    with pytest.raises(ValueError, match="contains an error"):
        list(iter_documents(manifest("error.json", "mediawiki-api"), tmp_path))


def test_page_text_limit_precedes_parser_and_keeps_exact_boundary(monkeypatch):
    from manabi_sentence_db import wikimedia

    calls = []
    original_parse = wikimedia.mwparserfromhell.parse

    def recording_parse(text):
        calls.append(len(text))
        return original_parse(text)

    monkeypatch.setattr(wikimedia.mwparserfromhell, "parse", recording_parse)
    # A multibyte character counts once; do not allocate an encoded page copy.
    text = "あ" * wikimedia.MAX_WIKITEXT_CHARACTERS
    with pytest.raises(wikimedia.PageTextLimitExceeded):
        wikimedia.extract_prose(text + "。")
    assert calls == []
    wikimedia.extract_prose(text)
    assert calls == [wikimedia.MAX_WIKITEXT_CHARACTERS]


@pytest.mark.parametrize("role", ["mediawiki-api", "mediawiki-xml"])
def test_oversized_page_is_counted_and_next_page_survives(tmp_path, monkeypatch, role):
    from manabi_sentence_db import wikimedia

    monkeypatch.setattr(wikimedia, "MAX_WIKITEXT_CHARACTERS", 30)
    texts = ["あ" * 31, "公園には大きな木がある。"]
    if role == "mediawiki-api":
        payload = {"query": {"pages": [
            {"pageid": i, "ns": 0, "title": f"記事{i}",
             "revisions": [{"revid": i, "content": text}]}
            for i, text in enumerate(texts, 1)
        ]}}
        path = tmp_path / "pages.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        path = tmp_path / "pages.xml"
        path.write_text("<mediawiki>" + "".join(
            f"<page><title>記事{i}</title><ns>0</ns><id>{i}</id>"
            f"<revision><id>{i}</id><text>{text}</text></revision></page>"
            for i, text in enumerate(texts, 1)
        ) + "</mediawiki>", encoding="utf-8")
    original_parse = wikimedia.mwparserfromhell.parse
    parsed = []

    def guarded_parse(text):
        assert len(text) <= 30
        parsed.append(text)
        return original_parse(text)

    monkeypatch.setattr(wikimedia.mwparserfromhell, "parse", guarded_parse)
    stats = Counter()
    documents = list(iter_documents(manifest(path.name, role), tmp_path, stats=stats))
    assert [doc["native_id"] for doc in documents] == ["2"]
    assert parsed == [texts[1]]
    assert stats == {"wikimedia_pages_seen": 2, "rejected:page-text-limit": 1}
