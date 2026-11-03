"""Synthetic story fixtures; no upstream text, media or network required."""

import copy
import hashlib
from collections import Counter

import pytest
import yaml

from manabi_sentence_db import snapshot as snapshots
from manabi_sentence_db import storybooks as sb
from manabi_sentence_db.build import build_corpus, canonical_document, iter_records, verify_build
from manabi_sentence_db.serialization import DataError
from manabi_sentence_db.validation import load_source


def page(texts, *, identity="0001", license_url="https://creativecommons.org/licenses/by/3.0/",
         navigation="", body_markup=""):
    credits = "".join(f'<h3><span data-tooltip="{role}"><img></span>{value}</h3>' for role, value in [
        ("作者", "Example Author"), ("絵", "Example Illustrator"), ("翻訳", "Example Translator"),
        ("言語", "日本語"), ("レベル", "レベル 2")])
    units = "".join(f'<div id="text{i + 2:02d}"><div class="def"><h3{body_markup}>{text}</h3></div>'
                    f'<div class="l1"><h3>{text}</h3></div></div>' for i, text in enumerate(texts))
    footer = "".join(f'<h5><span class="colophon-heading">{role}:</span> {value}</h5>'
                     for role, value in [("作者", "Example Author"), ("絵", "Example Illustrator"),
                                         ("翻訳", "Example Translator"), ("言語", "日本語"),
                                         ("レベル", "レベル 2")])
    return (f'<html><head><link rel="canonical" href="{sb.HOMEPAGE}{identity}/"></head><body>'
            f'{navigation}<div id="text01"><h1><span class="def">図書館の物語</span></h1>{credits}</div>'
            f'{units}<div id="colophon">{footer}'
            '<h5><span class="colophon-heading">出所:</span>'
            '<a href="https://africanstorybook.org/reader.php?id=42">Original</a></h5>'
            f'<a rel="license" href="{license_url}deed.ja">license</a>'
            '</div>'
            '<img src="https://example.org/never-fetch.jpg"><audio src="never-fetch.mp3"></audio>'
            '</body></html>').encode()


@pytest.fixture
def fixture():
    texts = ["町に図書館があります。毎朝、多くの人が訪れます。", "保留した文です。", "午後には静かになります。"]
    data = page(texts)
    metadata = dict(title="図書館の物語", author="Example Author", illustrator="Example Illustrator",
                    translator="Example Translator", source_url="https://africanstorybook.org/reader.php?id=42",
                    level=2, pages=3)
    commit = "a" * 40
    mit = b"The MIT License (MIT)\nSynthetic wrapper license fixture."
    source = dict(id="storybooks-japan-ja", adapter="storybook-japan", language="ja", title="Storybooks Japan",
                  homepage=sb.HOMEPAGE, license=sb.LICENSES["storybooks-japan-ja"],
                  attribution=dict(text="Storybooks Japan contributors", url=sb.HOMEPAGE),
                  license_evidence=[sb.HOMEPAGE], acquisition=dict(version=commit,
                    site_license=dict(url=sb.RAW + commit + "/LICENSE", size=len(mit), sha256=sb._hash(mit)),
                    files={"0001": dict(url=sb.RAW + commit + "/stories/ja/0001/index.html", size=len(data),
                        sha256=sb._hash(data), metadata=metadata,
                        omitted_pages={"2": dict(sha256=sb._hash(texts[1].encode()), reason="demonstrated-source-typo")})}))
    return source, data, texts, mit


def test_japanese_column_selected_once_with_exact_credits_and_no_media(fixture):
    source, data, _, _ = fixture
    raw = sb.extract(data, source, "0001")
    assert len([s for s in raw["sentences"] if isinstance(s, dict)]) == 2
    assert "Example Author" in raw["attribution"]["text"]
    assert "Example Translator" in raw["attribution"]["text"]
    assert raw["authorship"] == raw["language_origin"] == "unknown"
    assert "translation:source-language-unknown" in raw["tags"]
    assert "publisher-reading-level:2" in raw["tags"]
    assert "published_at" not in raw
    assert "native-review" not in str(raw) and "never-fetch" not in str(raw)
    assert all(s["translations"] == [] for s in raw["sentences"] if isinstance(s, dict))


def test_publisher_unit_splitting_and_exclusion_preserve_offsets_and_context_gaps(fixture):
    source, data, texts, _ = fixture
    stats = Counter()
    raw = sb.extract(data, source, "0001", stats=stats)
    manifest = dict(source=source, source_id=source["id"], snapshot_id="synthetic")
    doc = canonical_document(raw, manifest, stats, set())
    assert [s["ordinal"] for s in doc["sentences"]] == [0, 1, 3]
    assert doc["sentences"][0]["source_unit"]["text"] == texts[0]
    assert doc["sentences"][-1]["source_range"]["start"] == len(texts[0]) + len(texts[1]) + 4
    assert "保留した" not in str(doc)
    assert all(s["review_state"] == "unreviewed" for s in doc["sentences"])
    assert stats["rejected:storybooks-demonstrated-source-typo"] == 1
    assert "publisher-html-narrative-extraction" in doc["transformations"]
    assert sb.TRANSFORMATION in doc["transformations"]


@pytest.mark.parametrize("url", ["https://creativecommons.org/licenses/by-nc/3.0/",
                                "https://creativecommons.org/licenses/by-nd/3.0/",
                                "https://creativecommons.org/licenses/by/4.0/"])
def test_license_version_nc_and_nd_never_fall_back_to_site_or_code_license(url):
    with pytest.raises(DataError, match="license"):
        sb.parts(page(["町に図書館があります。"], license_url=url), "0001", sb.LICENSES["storybooks-japan-ja"])


def test_unrelated_pinned_navigation_duplicate_is_not_story_text():
    data = page(["町に図書館があります。"], navigation='<a class="btn" class="button" href="/">menu</a>')
    _, units = sb.parts(data, "0001", sb.LICENSES["storybooks-japan-ja"])
    assert units == ["町に図書館があります。"]


@pytest.mark.parametrize("change", ["missing", "license-outside", "source-outside", "duplicate",
                                  "author", "translator", "language", "level", "duplicate-credit",
                                  "duplicate-attribute", "unrelated-heading"])
def test_rights_and_matching_work_credits_must_belong_to_the_colophon(change):
    data = page(["町に図書館があります。"])
    colophon = data[data.index(b'<div id="colophon">'):data.index(b'</div><img') + 6]
    if change == "missing":
        data = data.replace(b'id="colophon"', b'id="other"')
    elif change in {"license-outside", "source-outside"}:
        start = colophon.index(b'<a rel="license"' if change == "license-outside" else b'<h5><span class="colophon-heading">' + '出所:'.encode())
        end = colophon.index(b'</a>' if change == "license-outside" else b'</h5>', start)
        end += len(b'</a>' if change == "license-outside" else b'</h5>')
        moved = colophon[start:end]
        data = data.replace(colophon, colophon.replace(moved, b'') + moved)
    elif change == "duplicate":
        data = data.replace(colophon, colophon + colophon)
    elif change in {"author", "translator", "language", "level"}:
        old, new = {"author": ("Example Author", "Different Author"),
                    "translator": ("Example Translator", "Different Translator"),
                    "language": ("日本語", "English"), "level": ("レベル 2", "レベル 3")}[change]
        data = data.replace(colophon, colophon.replace(old.encode(), new.encode()))
    elif change == "duplicate-credit":
        credit = '<h5><span class="colophon-heading">翻訳:</span> Example Translator</h5>'.encode()
        data = data.replace(colophon, colophon.replace(credit, credit + credit))
    elif change == "duplicate-attribute":
        data = data.replace(b'id="colophon"', b'id="colophon" id="other"')
    else:
        data = data.replace(b'class="colophon-heading"', b'class="unrelated-heading"')
    with pytest.raises(DataError, match="colophon"):
        sb.parts(data, "0001", sb.LICENSES["storybooks-japan-ja"])


@pytest.mark.parametrize("before,after", [
    (b'<h3>', b'<h3 class="a" class="b">'),
    ('図書館があります。'.encode(), '図書館<img src="never-fetch">があります。'.encode()),
    (b'id="text02"', b'id="text09"'),
    ('日本語</h3>'.encode(), 'English</h3>'.encode()),
    (b'<span class="def">', b'<span class="other">'),
])
def test_critical_markup_language_and_page_inventory_fail_closed(before, after):
    data = page(["町に図書館があります。"])
    assert before in data
    with pytest.raises(DataError):
        sb.parts(data.replace(before, after, 1), "0001", sb.LICENSES["storybooks-japan-ja"])


@pytest.mark.parametrize("field,value", [("id", "other-ja"), ("language", "en"),
                                       ("homepage", "https://example.org/"),
                                       ("license", {"id": "CC0-1.0", "url": "https://creativecommons.org/publicdomain/zero/1.0/"})])
def test_source_identity_cannot_be_repurposed(fixture, field, value):
    source, _, _, _ = fixture
    changed = copy.deepcopy(source)
    changed[field] = value
    with pytest.raises(DataError):
        sb.validate_source(changed)


def test_entire_bytes_credit_inventory_and_excluded_page_hash_are_bound(fixture):
    source, data, _, _ = fixture
    with pytest.raises(DataError, match="bytes"):
        sb.extract(data.replace(b'</body>', b'changed</body>'), source, "0001")
    changed = copy.deepcopy(source)
    changed["acquisition"]["files"]["0001"]["metadata"]["translator"] = "Wrong name"
    with pytest.raises(DataError, match="credit"):
        sb.extract(data, changed, "0001")
    changed = copy.deepcopy(source)
    changed["acquisition"]["files"]["0001"]["omitted_pages"]["2"]["sha256"] = "0" * 64
    with pytest.raises(DataError, match="excluded"):
        sb.extract(data, changed, "0001")


def test_snapshot_file_inventory_checksum_and_mit_evidence_are_required(fixture, tmp_path):
    source, data, _, mit = fixture
    files = []
    for name, role, raw, pin in [
        ("story.html", "storybook-0001", data, source["acquisition"]["files"]["0001"]),
        ("LICENSE", sb.LICENSE_ROLE, mit, source["acquisition"]["site_license"]),
    ]:
        (tmp_path / name).write_bytes(raw)
        files.append(dict(path=name, role=role, url=pin["url"], size=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    manifest = dict(source=source, files=files)
    assert len(list(sb.iter_documents(manifest, tmp_path))) == 1
    with pytest.raises(DataError, match="inventory"):
        list(sb.iter_documents(dict(manifest, files=files[:1]), tmp_path))
    (tmp_path / "LICENSE").write_bytes(b'bad')
    with pytest.raises(DataError):
        next(sb.iter_documents(manifest, tmp_path))


def test_snapshot_build_and_reuse_stay_offline_after_pinned_acquisition(fixture, tmp_path, monkeypatch):
    source, data, _, mit = fixture
    source_path = tmp_path / (source["id"] + ".yaml")
    source_path.write_text(yaml.safe_dump(source, allow_unicode=True))
    source = load_source(source_path)
    calls = []

    def download(directory, name, role, url, agent, *, expected_sha256, expected_size):
        raw = mit if role == sb.LICENSE_ROLE else data
        assert hashlib.sha256(raw).hexdigest() == expected_sha256 and len(raw) == expected_size
        calls.append(url)
        (directory / name).write_bytes(raw)
        return snapshots._record(directory / name, role, url)

    monkeypatch.setattr(snapshots, "_download", download)
    manifest = snapshots.create_snapshot(source, tmp_path / "snapshot", mode="full")
    assert len(calls) == 2 and not any("never-fetch" in url for url in calls)

    def no_network(*args, **kwargs):
        raise AssertionError("Verified snapshots/builds must not reacquire publisher data")

    monkeypatch.setattr(snapshots, "_download", no_network)
    assert snapshots.create_snapshot(source, tmp_path / "snapshot", mode="full") == manifest
    build = tmp_path / "build"
    build_corpus([tmp_path / "snapshot/manifest.json"], build, record_format="jsonl", shard_compression="zstd")
    catalog = verify_build(build)
    records = list(iter_records(build, catalog))
    assert len(records) == 1 and len(records[0]["sentences"]) == 3
    assert records[0]["license"] == sb.LICENSES["storybooks-japan-ja"]
    assert sb.TRANSFORMATION in records[0]["transformations"]


def test_by4_source_keeps_its_actual_work_license(fixture):
    source, _, texts, _ = fixture
    source = copy.deepcopy(source)
    source["id"] = "storybooks-japan-by4-ja"
    source["license"] = sb.LICENSES[source["id"]]
    data = page(texts, license_url=source["license"]["url"])
    pin = source["acquisition"]["files"]["0001"]
    pin.update(size=len(data), sha256=sb._hash(data))
    assert sb.extract(data, source, "0001")["license"]["id"] == "CC-BY-4.0"


def test_noncommercial_story_cannot_be_snapshotted_under_a_commercial_source(fixture, tmp_path, monkeypatch):
    source, _, texts, mit = fixture
    source = copy.deepcopy(source)
    data = page(texts, license_url="https://creativecommons.org/licenses/by-nc/3.0/")
    source["acquisition"]["files"]["0001"].update(size=len(data), sha256=sb._hash(data))

    def download(directory, name, role, url, agent, **kwargs):
        (directory / name).write_bytes(mit if role == sb.LICENSE_ROLE else data)
        return snapshots._record(directory / name, role, url)

    monkeypatch.setattr(snapshots, "_download", download)
    with pytest.raises(DataError, match="license"):
        snapshots.create_snapshot(source, tmp_path / "refused", mode="full")
    assert not (tmp_path / "refused/manifest.json").exists()


@pytest.mark.parametrize("field,value", [("version", "master"), ("files", {}),
                                       ("site_license", {"url": "https://example.org/", "size": 1, "sha256": "0" * 64})])
def test_floating_empty_and_foreign_acquisitions_are_rejected(fixture, field, value):
    source, _, _, _ = fixture
    source = copy.deepcopy(source)
    source["acquisition"][field] = value
    with pytest.raises(DataError):
        sb.validate_source(source)
