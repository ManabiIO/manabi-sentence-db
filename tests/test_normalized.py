import hashlib
import json
import zipfile

import zstandard

from manabi_sentence_db.build import build_corpus
from manabi_sentence_db.demo import create_demo_snapshot
from manabi_sentence_db.normalized import export_normalized


def test_normalized_export_preserves_context_and_deduplicates(tmp_path):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    build_corpus([snapshot], tmp_path / "build")
    result = export_normalized(tmp_path / "build", tmp_path / "normalized.zip")
    with zipfile.ZipFile(result) as archive:
        tables = {
            name: [json.loads(line) for line in archive.read(name).splitlines()]
            for name in ("works.jsonl", "sentences.jsonl", "occurrences.jsonl")
        }
        assert len(tables["sentences.jsonl"]) == 4
        assert len(tables["works.jsonl"]) == 2
        assert tables["occurrences.jsonl"][0]["next_id"] is not None
        assert tables["occurrences.jsonl"][0]["previous_id"] is None
        assert tables["works.jsonl"][0]["published_at"] is None
        assert tables["works.jsonl"][0]["revision"]["timestamp"]
        assert archive.testzip() is None
    assert not list(tmp_path.glob("*.sqlite*"))


def test_unique_identity_does_not_depend_on_work():
    from manabi_sentence_db.normalized import sentence_identity

    assert sentence_identity("ja", "今日は雨です。") == sentence_identity("ja", "今日は雨です。")
    assert sentence_identity("ja", "今日は雨です。") != sentence_identity("zh", "今日は雨です。")


def test_wikimedia_extraction_gaps_survive_build_and_normalized_export(tmp_path):
    from manabi_sentence_db.serialization import read_json, sha256_file, write_json
    from manabi_sentence_db.snapshot import snapshot_identity
    from manabi_sentence_db.wikimedia import WIKIMEDIA_CONTEXT_VERSION

    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    raw = snapshot.parent / "synthetic.xml"
    raw.write_text(raw.read_text().replace(
        "今日は公園まで歩きました。小さな犬が木の下で休んでいます。",
        "今日は公園まで歩きました。\n* 途中の一覧です。\n小さな犬が木の下で休んでいます。",
    ))
    manifest = read_json(snapshot)
    manifest["files"][0].update(sha256=sha256_file(raw), size=raw.stat().st_size)
    manifest["snapshot_id"] = snapshot_identity(manifest)
    write_json(snapshot, manifest)
    build_corpus([snapshot], tmp_path / "build")
    result = export_normalized(tmp_path / "build", tmp_path / "corpus.zip")
    with zipfile.ZipFile(result) as archive:
        works = [json.loads(line) for line in archive.read("works.jsonl").splitlines()]
        work = next(work for work in works if work["native_id"] == "1")
        occurrences = [json.loads(line) for line in archive.read("occurrences.jsonl").splitlines()]
    retained = [item for item in occurrences if item["work_id"] == work["id"]]
    assert [item["ordinal"] for item in retained] == [0, 2]
    assert WIKIMEDIA_CONTEXT_VERSION in work["transformations"]
    assert work["license"] == manifest["source"]["license"]
    assert work["revision"]["id"] == "11"


def test_jsonl_build_and_package(tmp_path):
    from manabi_sentence_db.package import package_build

    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    build_corpus([snapshot], tmp_path / "build", record_format="jsonl")
    release = package_build(tmp_path / "build", tmp_path / "release")
    assets = json.loads(release.read_text())["assets"]
    assert any(a["kind"] == "jsonl-zip" for a in assets)
    assert any(a["kind"] == "normalized-jsonl-zip" for a in assets)


def test_normalized_relational_database(tmp_path):
    import sqlite3

    from manabi_sentence_db.normalized_database import build_normalized_database

    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    build_corpus([snapshot], tmp_path / "build")
    archive = export_normalized(tmp_path / "build", tmp_path / "corpus.zip")
    path = build_normalized_database(archive, tmp_path / "corpus.sqlite")
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (2,)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute(
            "SELECT count(*) FROM sentences s JOIN occurrences o ON o.sentence_id=s.id JOIN works w ON w.id=o.work_id"
        ).fetchone() == (4,)


def test_export_keeps_staging_tables_compressed_and_hashes_logical_bytes(tmp_path, monkeypatch):
    from manabi_sentence_db import normalized

    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    build_corpus([snapshot], tmp_path / "build")
    write_archive = normalized._write_normalized_archive
    inspected = []

    def inspect(root, build, catalog, source_id, manifest, **options):
        assert options == {"compressed_tables": True}
        assert not list(root.glob("*.jsonl"))
        for name, digest in manifest["members"].items():
            path = root / (name + ".zst")
            assert path.read_bytes().startswith(b"\x28\xb5\x2f\xfd")
            with zstandard.open(path, "rb") as stream:
                assert hashlib.sha256(stream.read()).hexdigest() == digest
        inspected.append(root)
        return write_archive(root, build, catalog, source_id, manifest, **options)

    monkeypatch.setattr(normalized, "_write_normalized_archive", inspect)
    output = export_normalized(tmp_path / "build", tmp_path / "corpus.zip")
    assert inspected and all(not root.exists() for root in inspected)
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert all(hashlib.sha256(archive.read(name)).hexdigest() == digest
                   for name, digest in manifest["members"].items())
