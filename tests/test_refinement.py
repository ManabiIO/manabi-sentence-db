"""Canonical refinement never needs raw dumps or changes retained text/rights."""

import json
import sqlite3
import zipfile
from collections import Counter
from pathlib import Path

import pytest
import zstandard

from manabi_sentence_db import build as builder
from manabi_sentence_db import wikipedia_quality
from manabi_sentence_db.build import build_corpus, iter_records, verify_build
from manabi_sentence_db.cli import main
from manabi_sentence_db.database import build_database
from manabi_sentence_db.demo import create_demo_snapshot
from manabi_sentence_db.normalized import export_normalized
from manabi_sentence_db.normalized_database import build_normalized_database
from manabi_sentence_db.package import package_build, verify_package
from manabi_sentence_db.refinement import PARENT_PATH, refine_wikipedia
from manabi_sentence_db.serialization import (
    DataError,
    digest_json,
    read_json,
    sha256_file,
    write_json,
)
from manabi_sentence_db.snapshot import snapshot_identity

TEXTS = ["公園には大きな池がある。", "であることを意味する。", "詳しくは公式資料を参照。",
         "申請者は以下4つを満たす必要がある。", "毎年多くの人が公園を訪れる。"]


def _parent(tmp_path, monkeypatch, *, source_id="wikipedia-ja", record_format="jsonl"):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    manifest = read_json(snapshot)
    manifest["source_id"] = manifest["source"]["id"] = source_id
    manifest["source_config_sha256"] = digest_json(manifest["source"])
    raw = snapshot.parent / "synthetic.xml"
    xml = '<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">'
    for identity, sentences in enumerate((TEXTS, [TEXTS[1]]), 1):
        xml += (f"<page><title>架空の記事{identity}</title><ns>0</ns><id>{identity}</id>"
                f"<revision><id>{identity + 10}</id><timestamp>2026-01-01T00:00:00Z</timestamp>"
                f"<text>{''.join(sentences)}</text></revision></page>")
    raw.write_text(xml + "</mediawiki>")
    manifest["files"][0].update(sha256=sha256_file(raw), size=raw.stat().st_size)
    manifest["snapshot_id"] = snapshot_identity(manifest)
    write_json(snapshot, manifest)
    parent = tmp_path / "parent"
    # Model a previously admitted canonical build; no real source is relaxed.
    with monkeypatch.context() as patch:
        patch.setattr(wikipedia_quality, "assess_wikipedia_sentence", lambda _: (None, []))
        patch.setattr(wikipedia_quality, "WIKIPEDIA_QUALITY_VERSION", "wikipedia-example-quality-v4")
        build_corpus([snapshot], parent, record_format=record_format, shard_compression="zstd")
    snapshot.parent.rename(tmp_path / "retired-synthetic-snapshot")
    return parent


def _records(build):
    return list(iter_records(build, verify_build(build)))


def _tree(build):
    return {str(path.relative_to(build)): sha256_file(path) for path in build.rglob("*") if path.is_file()}


def _resign(build, catalog):
    catalog["build_id"] = "build_" + digest_json({
        "processor": catalog["processor_sha256"], "runtime": catalog["runtime"],
        "options": catalog["options"], "snapshots": [r["snapshot_id"] for r in catalog["snapshots"]],
    })[:32]
    write_json(build / "catalog.json", catalog)


@pytest.mark.parametrize("record_format", ["jsonl", "yaml"])
def test_refinement_uses_no_raw_dump_and_preserves_retained_records_rights_and_context_gaps(
        tmp_path, monkeypatch, record_format):
    parent = _parent(tmp_path, monkeypatch, record_format=record_format)
    before = _tree(parent)
    original = _records(parent)
    output = tmp_path / "refined"
    assert refine_wikipedia(parent, output) == output / "catalog.json"
    assert _tree(parent) == before
    catalog = verify_build(output)
    records = _records(output)
    assert len(records) == 1
    expected = dict(original[0], sentences=[original[0]["sentences"][0], original[0]["sentences"][-1]],
                    transformations=original[0]["transformations"] + [wikipedia_quality.WIKIPEDIA_QUALITY_VERSION])
    assert records == [expected]
    assert catalog["statistics"]["documents"] == 1
    assert catalog["statistics"]["sentences"] == 2
    assert catalog["statistics"]["rejected:wikipedia-dependent-fragment"] == 4
    assert all(row["path"].endswith(".jsonl.zst") for row in catalog["shards"])
    assert catalog["options"]["refinement"]["parent_build_id"] == verify_build(parent)["build_id"]
    assert sha256_file(output / PARENT_PATH) == sha256_file(parent / "catalog.json")
    archive = export_normalized(output, tmp_path / "normalized.zip")
    with zipfile.ZipFile(archive) as zipped:
        occurrences = [json.loads(line) for line in zipped.read("occurrences.jsonl").splitlines()]
        assert zipped.read(PARENT_PATH) == (parent / "catalog.json").read_bytes()
    assert len(occurrences) == 2
    assert all(row["previous_id"] is None and row["next_id"] is None for row in occurrences)
    assert not list(output.rglob("*.sqlite*")), "No plaintext sentence database is staged"


def test_other_sources_are_repacked_without_applying_the_wikipedia_policy(tmp_path, monkeypatch):
    parent = _parent(tmp_path, monkeypatch, source_id="demo-ja")
    output = tmp_path / "refined"
    refine_wikipedia(parent, output)
    assert _records(output) == _records(parent)


def test_refining_again_is_one_way_and_does_not_duplicate_policy_tags(tmp_path, monkeypatch):
    parent = _parent(tmp_path, monkeypatch)
    output, again = tmp_path / "refined", tmp_path / "again"
    refine_wikipedia(parent, output)
    refine_wikipedia(output, again)
    assert _records(output) == _records(again)
    assert verify_build(again)["options"]["refinement"]["parent_build_id"] == verify_build(output)["build_id"]


def test_input_corruption_fails_before_any_candidate_and_aliases_are_refused(tmp_path, monkeypatch):
    parent = _parent(tmp_path, monkeypatch)
    alias = tmp_path / "alias"
    alias.symlink_to(parent, target_is_directory=True)
    with pytest.raises(DataError, match="canonical"):
        refine_wikipedia(alias, tmp_path / "alias-output")
    with pytest.raises(DataError, match="fresh"):
        refine_wikipedia(parent, parent)
    shard = parent / verify_build(parent)["shards"][0]["path"]
    shard.write_bytes(shard.read_bytes() + b"broken")
    with pytest.raises(DataError, match="corrupt"):
        refine_wikipedia(parent, tmp_path / "invalid")
    assert not list(tmp_path.glob(".invalid-*"))


@pytest.mark.parametrize("kind", ["parent-bytes", "policy", "missing-receipt", "source-binding"])
def test_lineage_tampering_is_rejected_even_when_child_build_identity_is_recomputed(
        tmp_path, monkeypatch, kind):
    parent = _parent(tmp_path, monkeypatch)
    output = tmp_path / "refined"
    refine_wikipedia(parent, output)
    catalog = read_json(output / "catalog.json")
    if kind == "parent-bytes":
        with (output / PARENT_PATH).open("ab") as stream:
            stream.write(b"\n")
    elif kind == "policy":
        catalog["options"]["refinement"]["policy"] = "unrelated-v1"
    elif kind == "missing-receipt":
        catalog.pop("refinement_parent")
    else:
        receipt = read_json(output / PARENT_PATH)
        receipt["sources"][0]["source"]["title"] = "Different source"
        write_json(output / PARENT_PATH, receipt)
        digest = sha256_file(output / PARENT_PATH)
        catalog["options"]["refinement"]["parent_catalog_sha256"] = digest
        catalog["refinement_parent"]["sha256"] = digest
    _resign(output, catalog)
    with pytest.raises(DataError, match="refinement|Refinement|corrupt"):
        verify_build(output)


def test_implementation_drift_prevents_publication_and_preserves_failed_compressed_candidate(
        tmp_path, monkeypatch):
    parent = _parent(tmp_path, monkeypatch)
    original = builder._processor_fingerprint
    calls = []
    def drift():
        calls.append(True)
        return original() if len(calls) == 1 else "0" * 64
    monkeypatch.setattr(builder, "_processor_fingerprint", drift)
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    output = tmp_path / "unpublished"
    before = _tree(parent)
    with pytest.raises(DataError, match="changed during"):
        refine_wikipedia(parent, output)
    assert not output.exists() and _tree(parent) == before
    assert list((fake_home / ".Trash").glob(".unpublished-*"))


def test_cli_routes_to_offline_refinement(tmp_path, monkeypatch, capsys):
    parent = _parent(tmp_path, monkeypatch)
    output = tmp_path / "refined"
    assert main(["refine-wikipedia", "--build", str(parent), "--output", str(output), "--progress"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == str(output / "catalog.json")
    assert "raw snapshots are not required" in captured.err
    assert len(_records(output)) == 1


def test_valid_interleaved_sources_keep_their_document_order(tmp_path, monkeypatch):
    manifests = []
    for source_id in ("demo-a", "demo-b"):
        folder = tmp_path / source_id
        folder.mkdir()
        _parent(folder, monkeypatch, source_id=source_id)
        manifests.append(folder / "retired-synthetic-snapshot/manifest.json")
    parent = tmp_path / "mixed"
    build_corpus(manifests, parent, record_format="jsonl", shard_compression="zstd", shard_documents=1)
    catalog = verify_build(parent)
    assert len(catalog["shards"]) == 4
    order = [0, 2, 1, 3]
    catalog["shards"] = [catalog["shards"][i] for i in order]
    index = parent / "documents.jsonl"
    rows = index.read_bytes().splitlines(keepends=True)
    index.write_bytes(b"".join(rows[i] for i in order))
    catalog["document_index"]["sha256"] = sha256_file(index)
    write_json(parent / "catalog.json", catalog)
    original = _records(parent)
    output = tmp_path / "refined"
    refine_wikipedia(parent, output)
    assert _records(output) == original
    assert Counter(row["source_id"] for row in original) == {"demo-a": 2, "demo-b": 2}


def test_empty_refinement_is_not_published(tmp_path, monkeypatch):
    monkeypatch.setitem(globals(), "TEXTS", ["であることを意味する。"] * 2)
    parent = _parent(tmp_path, monkeypatch)
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    output = tmp_path / "empty"
    before = _tree(parent)
    with pytest.raises(DataError, match="No usable documents"):
        refine_wikipedia(parent, output)
    assert not output.exists() and _tree(parent) == before
    assert list((fake_home / ".Trash").glob(".empty-*"))


def test_refined_lineage_survives_sqlite_and_every_release_transport(tmp_path, monkeypatch):
    parent = _parent(tmp_path, monkeypatch)
    refined = tmp_path / "refined"
    refine_wikipedia(parent, refined)
    database = tmp_path / "corpus.sqlite"
    build_database(refined, database)
    with sqlite3.connect(database) as db:
        embedded = json.loads(db.execute("SELECT value FROM metadata WHERE key='refinement_parent_catalog'").fetchone()[0])
        assert embedded == read_json(parent / "catalog.json")
    packaged = tmp_path / "release"
    package_build(refined, packaged, include_sqlite=True)
    verify_package(packaged)
    parent_bytes = (parent / "catalog.json").read_bytes()
    release = read_json(packaged / "release.json")
    for asset in release["assets"]:
        if asset["kind"] in {"jsonl-zip", "metadata-zip", "normalized-jsonl-zip"}:
            with zipfile.ZipFile(packaged / asset["path"]) as zipped:
                assert zipped.read(PARENT_PATH) == parent_bytes
    assert len(release["databases"]) == 1
    database = release["databases"][0]
    # Inspect the actual compressed release database, not the separate legacy
    # canonical SQLite compiler exercised above.
    restored = tmp_path / "restored-release.sqlite"
    compressed = b"".join((packaged / name).read_bytes() for name in database["parts"])
    restored.write_bytes(zstandard.ZstdDecompressor().decompress(compressed, max_output_size=1024**2))
    assert sha256_file(restored) == database["uncompressed_sha256"]
    with sqlite3.connect(restored) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        embedded = dict(db.execute("SELECT key,value FROM metadata"))
        assert json.loads(embedded["catalog"]) == verify_build(refined)
        assert json.loads(embedded["refinement_parent_catalog"]) == read_json(parent / "catalog.json")


@pytest.mark.parametrize("corruption", ["missing-parent", "changed-parent", "missing-catalog", "wrong-build", "missing-receipt", "missing-both"])
def test_normalized_sqlite_refuses_incomplete_or_changed_refinement_before_publication(
        tmp_path, monkeypatch, corruption):
    parent = _parent(tmp_path, monkeypatch)
    refined = tmp_path / "refined"
    refine_wikipedia(parent, refined)
    source = export_normalized(refined, tmp_path / "original.zip")
    invalid = tmp_path / "invalid.zip"
    with zipfile.ZipFile(source) as incoming, zipfile.ZipFile(invalid, "w", compression=zipfile.ZIP_DEFLATED) as out:
        for name in incoming.namelist():
            if (corruption == "missing-parent" and name == PARENT_PATH
                    or corruption == "missing-catalog" and name == "catalog.json"
                    or corruption == "missing-both" and name in {PARENT_PATH, "catalog.json"}):
                continue
            raw = incoming.read(name)
            if corruption == "changed-parent" and name == PARENT_PATH:
                raw += b"\n"
            if name == "catalog.json":
                catalog = json.loads(raw)
                if corruption == "wrong-build":
                    catalog["build_id"] = "different"
                if corruption == "missing-receipt":
                    catalog["options"].pop("refinement")
                raw = json.dumps(catalog).encode()
            out.writestr(name, raw)
    output = tmp_path / "unpublished.sqlite"
    with pytest.raises(DataError, match="provenance|Refinement|refinement|identity"):
        build_normalized_database(invalid, output)
    assert not output.exists()
