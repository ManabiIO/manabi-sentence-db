"""Synthetic ALT archive fixtures; no network or corpus text in tests."""

import hashlib
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from manabi_sentence_db.alt_parallel import PREFIX, ROLE, iter_documents
from manabi_sentence_db.build import canonical_document
from manabi_sentence_db.serialization import DataError
from manabi_sentence_db.validation import load_source


def fixture(tmp_path, *, ja=None, en=None):
    ja = ja or [
        ("SNT.1.1", "公園には大きな池がある。"),
        ("SNT.1.2-1", "「引用された文章だ」と言った。"),
        ("SNT.1.3", ""),
        ("SNT.1.4", "毎年、多くの人が訪れる。"),
    ]
    en = en or [(i, "There is a large pond in the park.") for i, _ in ja]
    blobs = {
        "README.txt": b"synthetic parallel-text license evidence",
        "URL.txt": b"URL.1\thttp://en.wikinews.org/wiki/Example\r\n",
        "data_ja.txt": "".join(f"{i}\t{t}\r\n" for i, t in ja).encode(),
        "data_en.txt": "".join(f"{i}\t{t}\r\n" for i, t in en).encode(),
    }
    source = load_source(Path("sources/alt-parallel-ja.yaml"))
    source["acquisition"].update(
        article_count=1,
        pair_count=len(ja),
        members={
            PREFIX + n: {"size": len(b), "sha256": hashlib.sha256(b).hexdigest()}
            for n, b in blobs.items()
        },
    )
    path = tmp_path / "fixture.zip"
    with zipfile.ZipFile(path, "w") as z:
        for n, b in blobs.items():
            z.writestr(PREFIX + n, b)
    return {
        "source": source,
        "source_id": source["id"],
        "snapshot_id": "fixture",
        "files": [{"path": path.name, "role": ROLE}],
    }


def test_direction_attribution_pair_integrity_and_context_gaps(tmp_path):
    m = fixture(tmp_path)
    stats = Counter()
    raw = list(iter_documents(m, tmp_path, stats=stats))[0]
    doc = canonical_document(raw, m, stats, set())
    assert [s["ordinal"] for s in doc["sentences"]] == [0, 3]
    assert [s["native_id"] for s in doc["sentences"]] == ["SNT.1.1", "SNT.1.4"]
    assert doc["language_origin"] == "unknown" and doc["authorship"] == "unknown"
    assert "translation:from-english" in doc["tags"]
    assert "published_at" not in doc
    for s in doc["sentences"]:
        t = s["translations"][0]
        assert t["license"]["id"] == "CC-BY-2.5" and t["alignment"] == "unknown"
        assert "generation" not in t
        assert t["source_url"] == "http://en.wikinews.org/wiki/Example"
    assert stats["rejected:alt-empty-pair"] == 1


def test_duplicate_mismatched_and_malformed_ids_are_barriers(tmp_path):
    ja = [
        ("SNT.1.1", "公園には大きな池がある。"),
        ("SNT.1.1", "別の文章が残っている。"),
        ("SNT.1.3-", "毎年多くの人が訪れる。"),
        ("SNT.1.4", "別の文章が残っている。"),
    ]
    en = [("SNT.1.1", "One."), ("SNT.1.2", "Two."), ("SNT.1.3-", "Three."), ("SNT.1.4", "Four.")]
    m = fixture(tmp_path, ja=ja, en=en)
    stats = Counter()
    raw = list(iter_documents(m, tmp_path, stats=stats))[0]
    assert [s["source_ordinal"] for s in raw["sentences"]] == [3]
    assert stats["rejected:alt-publisher-identity-defect"] == 3


def test_inventory_and_member_hash_fail_closed(tmp_path):
    m = fixture(tmp_path)
    m["source"]["acquisition"]["members"][PREFIX + "README.txt"]["sha256"] = "0" * 64
    with pytest.raises(DataError, match="checksum"):
        list(iter_documents(m, tmp_path, stats=Counter()))
    m = fixture(tmp_path)
    m["source"]["acquisition"]["members"].pop(PREFIX + "README.txt")
    with pytest.raises(DataError, match="inventory"):
        list(iter_documents(m, tmp_path, stats=Counter()))


def test_duplicated_english_identity_excludes_every_ambiguous_pair(tmp_path):
    ja = [(f'SNT.1.{n}', '公園には大きな池がある。') for n in (1, 2, 3)]
    en = [('SNT.1.1', 'One.'), ('SNT.1.1', 'Two.'), ('SNT.1.3', 'Three.')]
    manifest = fixture(tmp_path, ja=ja, en=en)
    stats = Counter()
    raw = list(iter_documents(manifest, tmp_path, stats=stats))[0]
    assert [s['source_ordinal'] for s in raw['sentences']] == [2]
    assert stats['rejected:alt-publisher-identity-defect'] == 2


def test_pair_count_mismatch_fails_closed(tmp_path):
    m = fixture(tmp_path)
    m["source"]["acquisition"]["pair_count"] = 100
    with pytest.raises(DataError, match="row count"):
        list(iter_documents(m, tmp_path, stats=Counter()))


def test_verified_fixture_build_and_normalized_export(tmp_path):
    import json

    from manabi_sentence_db.build import build_corpus, verify_build
    from manabi_sentence_db.normalized import export_normalized
    from manabi_sentence_db.serialization import canonical_json
    from manabi_sentence_db.snapshot import snapshot_identity

    manifest = fixture(tmp_path)
    blob = (tmp_path / "fixture.zip").read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    source = manifest["source"]
    source["acquisition"].update(size=len(blob), sha256=digest)
    manifest.update(
        schema_version=1,
        source_config_sha256=hashlib.sha256(canonical_json(source)).hexdigest(),
        mode="sample",
        request={"synthetic": True},
        upstream_date=None,
        retrieved_at="2026-10-30T00:00:00Z",
    )
    manifest["files"][0].update(size=len(blob), sha256=digest, url=source["acquisition"]["url"])
    manifest["snapshot_id"] = snapshot_identity(manifest)
    snapshot = tmp_path / "manifest.json"
    snapshot.write_text(json.dumps(manifest))
    build = tmp_path / "build"
    build_corpus([snapshot], build, record_format="jsonl")
    assert verify_build(build)["statistics"]["sentences"] == 2
    normalized = export_normalized(build, tmp_path / "normalized.zip")
    with zipfile.ZipFile(normalized) as archive:
        occurrences = [json.loads(line) for line in archive.read("occurrences.jsonl").splitlines()]
        translations = [
            json.loads(line) for line in archive.read("translations.jsonl").splitlines()
        ]
    assert [o["ordinal"] for o in occurrences] == [0, 3]
    assert len(translations) == 2
    assert all(t["license"]["id"] == "CC-BY-2.5" and "generation" not in t for t in translations)
