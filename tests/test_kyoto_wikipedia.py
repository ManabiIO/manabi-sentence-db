"""Offline synthetic fixtures for the pinned Kyoto Wikipedia adapter."""

import csv
import hashlib
import io
import tarfile
from collections import Counter

import pytest

from manabi_sentence_db.kyoto_wikipedia import (
    INDEX,
    NOTICE,
    REPAIR_MEMBER,
    ROLE,
    article_document,
    iter_documents,
)
from manabi_sentence_db.serialization import DataError

HOME = "https://alaginrc.nict.go.jp/WikiCorpus/index_E.html"
LICENSE = {"id": "CC-BY-SA-3.0", "url": "https://creativecommons.org/licenses/by-sa/3.0/"}


def _source(*, acquisition=None):
    return {
        "id": "wikipedia-kyoto-ja",
        "title": "NICT Kyoto Wikipedia Corpus",
        "homepage": "https://ja.wikipedia.org/",
        "license": LICENSE,
        "acquisition": {"url": HOME, **(acquisition or {})},
    }


def _row(filename="CLT00001.xml", page_id="12345", category="CLT"):
    return {
        "File name": filename,
        "Wikipedia ID": page_id,
        "Title": "Example article",
        "Category": category,
        "Number of sentences": "3",
        "Translator ID": "translator-1",
    }


def _article(
    sentences,
    *,
    title="Example article",
    copyright_text="Licensed under Creative Commons Attribution-Share-Alike License 3.0.",
):
    rows = "".join(
        f'<sen id="{identity}"><j>{ja}</j>'
        f'<e type="trans" ver="1">PRIMARY EN</e>'
        f'<e type="trans" ver="2">REVISED EN</e>'
        f'<e type="check" ver="1">{en}</e>'
        f'<e type="check" ver="2">UNAPPROVED CHECK</e></sen>'
        for identity, ja, en in sentences
    )
    return (
        '<art orl="ja" trl="en"><inf>jawiki-20080607-pages-articles.xml</inf>'
        f"<tit><j>{title}</j></tit><sec><par>{rows}</par></sec>"
        f"<copyright>{copyright_text}</copyright></art>"
    ).encode()


def _archive(tmp_path, article, *, index_rows=None, readme=b"synthetic license/process note"):
    index_rows = index_rows or [_row()]
    index_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        index_buffer,
        fieldnames=[
            "File name",
            "Wikipedia ID",
            "Title",
            "Category",
            "Number of sentences",
            "Translator ID",
        ],
    )
    writer.writeheader()
    writer.writerows(index_rows)
    index_bytes = index_buffer.getvalue().encode()
    archive_path = tmp_path / "kyoto.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, value in (
            ("CLT/", None),
            ("CLT/CLT00001.xml", article),
            (INDEX, index_bytes),
            ("readme.pdf", readme),
            ("kyoto_lexicon.csv", b"lexicon; never an example"),
        ):
            info = tarfile.TarInfo(name)
            if value is None:
                info.type = tarfile.DIRTYPE
                info.size = 0
                archive.addfile(info)
            else:
                info.size = len(value)
                archive.addfile(info, io.BytesIO(value))
    source = _source(
        acquisition={
            "article_count": len(index_rows),
            "index_sha256": hashlib.sha256(index_bytes).hexdigest(),
            "readme_sha256": hashlib.sha256(readme).hexdigest(),
        }
    )
    manifest = {
        "source": source,
        "source_id": source["id"],
        "files": [{"path": archive_path.name, "role": ROLE}],
    }
    return manifest, archive_path


def test_article_keeps_page_license_and_only_final_checked_translation():
    data = _article([("1", "公園には大きな池がある。", "The park has a large pond.")])
    stats = Counter()
    doc = article_document(data, "CLT/CLT00001.xml", _row(), _source(), stats)
    sentence = doc["sentences"][0]
    translation = sentence["translations"][0]
    assert doc["native_id"] == "CLT/CLT00001.xml"
    assert doc["url"] == "https://ja.wikipedia.org/w/index.php?curid=12345"
    assert "action=history" in doc["attribution"]["url"]
    assert "Creative Commons Attribution-Share-Alike License 3.0" in doc["attribution"]["text"]
    assert NOTICE in doc["attribution"]["text"]
    assert sentence["text"] == "公園には大きな池がある。"
    assert translation["text"] == "The park has a large pond."
    assert translation["generation"] == {"kind": "human", "agent": "NICT"}
    assert translation["alignment"] == "human"
    assert "PRIMARY EN" not in repr(doc) and "REVISED EN" not in repr(doc)
    assert "UNAPPROVED CHECK" not in repr(doc)
    assert stats["publisher_pairs_seen"] == 1


def test_article_filters_quoted_incomplete_and_untranslated_pairs_and_keeps_ordinals():
    data = _article(
        [
            ("1", "公園には大きな池がある。", "The park has a large pond."),
            ("2", "「すばらしい景色だ」と書いた。", "He wrote that it was a wonderful view."),
            ("3", "公園は町の近く", "The park is near the town."),
            ("4", "毎年多くの人が訪れる。", ""),
            ("6", "別の文章が残る。", "Another sentence remains."),
        ]
    )
    stats = Counter()
    doc = article_document(data, "CLT/CLT00001.xml", _row(), _source(), stats)
    assert [s["native_id"] for s in doc["sentences"]] == ["1", "6"]
    assert [s["source_ordinal"] for s in doc["sentences"]] == [0, 5]
    assert doc["sentences"][1]["source_range"] == {"unit": "utterance", "start": 5, "end": 6}
    assert stats["rejected:kyoto-embedded-quotation-or-title"] == 1
    assert stats["rejected:kyoto-incomplete-prose"] == 1
    assert stats["rejected:kyoto-missing-final-translation"] == 1


def test_source_flagged_comment_and_reference_quote_sections_are_not_examples():
    # Comments flag source defects; section headings are publisher structure,
    # not sentence text. None of these source units should become examples.
    data = (
        '<art orl="ja" trl="en"><inf>jawiki-20080607-pages-articles.xml</inf>'
        "<tit><j>Example article</j></tit><sec><par>"
        '<sen id="1"><j>この文には誤りがある。</j><cmt>原文の誤り</cmt>'
        '<e type="check" ver="1">This source sentence contains an error.</e></sen>'
        '<sen id="2"><j>本文の文章がある。</j>'
        '<e type="check" ver="1">There is a sentence in the text.</e></sen>'
        "</par></sec>"
        '<sec><tit><j>参考文献</j></tit><par><sen id="3">'
        "<j>参考文献の文は取り込まない。</j>"
        '<e type="check" ver="1">Do not import this reference sentence.</e>'
        "</sen></par></sec>"
        '<sec><tit><j>引用</j></tit><par><sen id="4">'
        "<j>引用された文章は取り込まない。</j>"
        '<e type="check" ver="1">Do not import this quoted sentence.</e>'
        "</sen></par></sec>"
        "<copyright>Licensed under Creative Commons Attribution-Share-Alike License 3.0.</copyright>"
        "</art>"
    ).encode()
    stats = Counter()
    doc = article_document(data, "CLT/CLT00001.xml", _row(), _source(), stats)
    assert [s["text"] for s in doc["sentences"]] == ["本文の文章がある。"]


def test_archive_iterator_uses_index_identity_and_excludes_nonarticle_members(tmp_path):
    article = _article([("1", "公園には大きな池がある。", "The park has a large pond.")])
    manifest, _ = _archive(tmp_path, article)
    docs = list(iter_documents(manifest, tmp_path, stats=Counter()))
    assert len(docs) == 1
    assert docs[0]["native_id"] == "CLT/CLT00001.xml"
    assert "lexicon" not in repr(docs[0]).lower()
    assert "synthetic license/process note" not in repr(docs[0])


def test_archive_index_inventory_must_match_article_members(tmp_path):
    article = _article([("1", "公園には大きな池がある。", "The park has a large pond.")])
    manifest, _ = _archive(
        tmp_path,
        article,
        index_rows=[_row(page_id="12345"), _row(filename="CLT00002.xml", page_id="12346")],
    )
    with pytest.raises(DataError, match="inventory"):
        list(iter_documents(manifest, tmp_path, stats=Counter()))


def test_archive_index_and_readme_hashes_are_enforced(tmp_path):
    article = _article([("1", "公園には大きな池がある。", "The park has a large pond.")])
    manifest, _ = _archive(tmp_path, article)
    manifest["source"]["acquisition"]["index_sha256"] = "0" * 64
    with pytest.raises(DataError, match="metadata checksum"):
        list(iter_documents(manifest, tmp_path, stats=Counter()))


def test_dtd_is_rejected_and_malformed_xml_fails_closed():
    dtd = b'<!DOCTYPE art [<!ENTITY x SYSTEM "file:///etc/passwd">]><art>&x;</art>'
    with pytest.raises(DataError, match="Invalid Kyoto XML"):
        article_document(dtd, "CLT/CLT00001.xml", _row(), _source(), Counter())
    malformed = b"<art orl='ja' trl='en'><inf>oops"
    with pytest.raises(DataError, match="Invalid Kyoto XML"):
        article_document(malformed, "CLT/CLT00001.xml", _row(), _source(), Counter())


def test_only_exact_pinned_bare_ampersand_repair_is_permitted(monkeypatch):
    import manabi_sentence_db.kyoto_wikipedia as kyoto

    original = _article([("1", "公園には大きな池がある。", "The park has a large pond.")])
    broken = original.replace(b"<copyright>", b"<copyright>AEONseven&i(id:89677) ")
    monkeypatch.setattr(kyoto, "REPAIR_MEMBER", "CLT/CLT00001.xml")
    monkeypatch.setattr(kyoto, "REPAIR_SHA256", hashlib.sha256(broken).hexdigest())
    stats = Counter()
    doc = article_document(broken, "CLT/CLT00001.xml", _row(), _source(), stats)
    assert stats["xml_entity_repairs"] == 1
    assert "AEONseven&i(id:89677)" in doc["attribution"]["text"]
    with pytest.raises(DataError, match="Invalid Kyoto XML"):
        article_document(broken, "CLT/CLT00002.xml", _row(), _source(), Counter())


@pytest.mark.parametrize("source_id", ["CLT/CLT00002.xml", REPAIR_MEMBER])
def test_repair_does_not_apply_to_other_member_or_different_bytes(source_id):
    data = b"<art orl='ja' trl='en'><copyright>AEONseven&i(id:89677)</copyright></art>"
    with pytest.raises(DataError, match="Invalid Kyoto XML"):
        article_document(data, source_id, _row(), _source(), Counter())


def test_canonical_pairs_preserve_translation_alignment_and_source_gaps():
    from manabi_sentence_db.build import canonical_document

    data = _article(
        [
            ("1", "公園には大きな池がある。", "The park has a large pond."),
            ("2", "「すばらしい景色だ」と書いた。", "He wrote about the view."),
            ("6", "毎年、多くの人が訪れる。", "Many people visit every year."),
        ]
    )
    source = {**_source(), "adapter": "kyoto-wikipedia"}
    raw = article_document(data, "CLT/CLT00001.xml", _row(), source, Counter())
    record = canonical_document(
        raw,
        {"source": source, "source_id": source["id"], "snapshot_id": "fixture"},
        Counter(),
        set(),
    )
    assert [s["ordinal"] for s in record["sentences"]] == [0, 5]
    assert "wikipedia-example-quality-v2" in record["transformations"]
    assert "kyoto-final-checked-pairs-v1" in record["transformations"]
    translations = [s["translations"][0] for s in record["sentences"]]
    assert [t["text"] for t in translations] == [
        "The park has a large pond.",
        "Many people visit every year.",
    ]
    assert all(t["generation"] == {"kind": "human", "agent": "NICT"} for t in translations)
    assert all(NOTICE in t["attribution"]["text"] for t in translations)
    assert all(set(t["generation"]) == {"kind", "agent"} for t in translations)


def test_excluded_sections_and_source_noted_defects_do_not_leak_into_examples():
    raw = _article(
        [
            ("1", "公園には大きな池がある。", "The park has a large pond."),
            ("3", "古い文章が引用されている。", "An old passage is quoted."),
        ]
    )
    raw = raw.replace(b'<sen id="3">', '<sen id="3"><cmt>原文に誤字があります。</cmt>'.encode())
    raw = raw.replace(
        b"</art>",
        '<sec><tit><j>参考文献</j></tit><sen id="4"><j>本の紹介が書かれている。</j><e type="check" ver="1">A book is listed.</e></sen></sec></art>'.encode(),
    )
    stats = Counter()
    doc = article_document(raw, "CLT/CLT00001.xml", _row(), _source(), stats)
    assert [s["native_id"] for s in doc["sentences"]] == ["1"]
    assert stats["rejected:kyoto-excluded-section"] == 1
    assert stats["rejected:kyoto-source-noted-defect-or-classical-quotation"] == 1


def test_paired_xml_survives_verified_snapshot_build_and_normalized_export(tmp_path):
    import json
    import zipfile
    from pathlib import Path

    from manabi_sentence_db.build import build_corpus, verify_build
    from manabi_sentence_db.normalized import export_normalized
    from manabi_sentence_db.serialization import canonical_json
    from manabi_sentence_db.snapshot import snapshot_identity
    from manabi_sentence_db.validation import load_source

    data = _article([
        ("1", "公園には大きな池がある。", "The park has a large pond."),
        ("2", "「すばらしい景色だ」と書いた。", "He wrote about the view."),
        ("6", "毎年、多くの人が訪れる。", "Many people visit every year."),
    ])
    original, archive_path = _archive(tmp_path, data)
    source = load_source(Path("sources/wikipedia-kyoto-ja.yaml"))
    source["acquisition"].update(original["source"]["acquisition"])
    blob = archive_path.read_bytes()
    source["acquisition"].update(size=len(blob), sha256=hashlib.sha256(blob).hexdigest())
    manifest = {"schema_version": 1, "source_id": source["id"], "source": source,
                "source_config_sha256": hashlib.sha256(canonical_json(source)).hexdigest(),
                "mode": "sample", "request": {"synthetic": True}, "upstream_date": None,
                "retrieved_at": "2026-10-29T00:00:00Z",
                "files": [{"role": ROLE, "path": archive_path.name, "size": len(blob),
                           "url": source["acquisition"]["url"], "sha256": hashlib.sha256(blob).hexdigest()}]}
    manifest["snapshot_id"] = snapshot_identity(manifest)
    snapshot = tmp_path / "manifest.json"
    snapshot.write_text(json.dumps(manifest))
    build = tmp_path / "build"
    build_corpus([snapshot], build, record_format="jsonl")
    assert verify_build(build)["statistics"]["sentences"] == 2
    normalized = export_normalized(build, tmp_path / "normalized.zip")
    with zipfile.ZipFile(normalized) as archive:
        occurrences = [json.loads(line) for line in archive.read("occurrences.jsonl").splitlines()]
        translations = [json.loads(line) for line in archive.read("translations.jsonl").splitlines()]
    assert [o["ordinal"] for o in occurrences] == [0, 5]
    assert len(translations) == 2
    assert all(t["generation"]["kind"] == "human" and NOTICE in t["attribution"]["text"] for t in translations)
