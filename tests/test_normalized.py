import hashlib
import json
import zipfile

import pytest
import zstandard

from manabi_sentence_db.build import build_corpus, iter_records, verify_build
from manabi_sentence_db.demo import create_demo_snapshot
from manabi_sentence_db.normalized import export_normalized, export_normalized_buckets


def test_bucket_export_reads_canonical_records_once_and_preserves_complete_works(tmp_path, monkeypatch):
    import manabi_sentence_db.build as builder

    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    build = tmp_path / "build"
    build_corpus([snapshot], build, record_format="jsonl", shard_compression="zstd")
    catalog = verify_build(build)
    ordinary = export_normalized(build, tmp_path / "ordinary.zip", catalog=catalog)
    original = builder.iter_records
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        yield from original(*args, **kwargs)

    monkeypatch.setattr(builder, "iter_records", counted)
    result = export_normalized_buckets(build, tmp_path / "new-parent" / "buckets", works_per_archive=1,
                                       catalog=catalog)
    index = json.loads(result.read_text())
    assert len(calls) == 1
    assert index["complete"] and len(index["archives"]) == 2
    tables = {name: [] for name in ("works", "sentences", "occurrences", "translations")}
    for entry in index["archives"]:
        with zipfile.ZipFile(result.parent / entry["name"]) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["counts"]["works"] == 1
            assert manifest["scope"] == "sample"
            assert manifest["work_selection"]["build_id"] == catalog["build_id"]
            for name in tables:
                tables[name] += [json.loads(line) for line in archive.read(name + ".jsonl").splitlines()]
    with zipfile.ZipFile(ordinary) as archive:
        for name, actual in tables.items():
            expected = [json.loads(line) for line in archive.read(name + ".jsonl").splitlines()]
            if name == "sentences":
                actual = list({row["id"]: row for row in actual}.values())
            assert sorted(actual, key=lambda row:row["id"]) == sorted(expected, key=lambda row:row["id"])


def test_interrupted_bucket_export_has_no_completion_index(tmp_path, monkeypatch):
    import manabi_sentence_db.build as builder
    from manabi_sentence_db.serialization import DataError

    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    build = tmp_path / "build"
    build_corpus([snapshot], build)
    catalog = verify_build(build)
    original = builder.iter_records

    def broken(*args, **kwargs):
        yield next(original(*args, **kwargs))
        raise DataError("interrupted source")

    monkeypatch.setattr(builder, "iter_records", broken)
    with pytest.raises(DataError, match="interrupted"):
        export_normalized_buckets(build, tmp_path / "buckets", works_per_archive=1, catalog=catalog)
    assert not (tmp_path / "buckets" / "normalized-buckets.json").exists()


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, 80_001])
def test_invalid_bucket_limit_fails_before_build_verification(tmp_path, limit):
    from manabi_sentence_db.serialization import DataError

    with pytest.raises(DataError, match="bucket"):
        export_normalized_buckets(tmp_path / "missing", tmp_path / "buckets", works_per_archive=limit)


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


@pytest.mark.parametrize("selected", [False, True])
def test_wikimedia_extraction_gaps_survive_build_and_normalized_export(tmp_path, selected):
    from manabi_sentence_db.serialization import read_json, sha256_file, write_json
    from manabi_sentence_db.snapshot import snapshot_identity
    from manabi_sentence_db.wikimedia import WIKIMEDIA_CONTEXT_VERSION

    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    raw = snapshot.parent / "synthetic.xml"
    raw.write_text(raw.read_text().replace(
        "今日は公園まで歩きました。小さな犬が木の下で休んでいます。",
        "今日は公園まで歩きました。そこで友達と会いました。\n"
        "* 途中の一覧です。\n小さな犬が木の下で休んでいます。",
    ))
    manifest = read_json(snapshot)
    manifest["files"][0].update(sha256=sha256_file(raw), size=raw.stat().st_size)
    manifest["snapshot_id"] = snapshot_identity(manifest)
    write_json(snapshot, manifest)
    build_corpus([snapshot], tmp_path / "build")
    catalog = verify_build(tmp_path / "build")
    record = next(record for record in iter_records(tmp_path / "build", catalog)
                  if record["native_id"] == "1")
    options = ({"work_selection": {"schema_version": 1, "build_id": catalog["build_id"],
                                   "work_ids": [record["id"]]}} if selected else {})
    result = export_normalized(tmp_path / "build", tmp_path / "corpus.zip", **options)
    with zipfile.ZipFile(result) as archive:
        works = [json.loads(line) for line in archive.read("works.jsonl").splitlines()]
        work = next(work for work in works if work["native_id"] == "1")
        occurrences = [json.loads(line) for line in archive.read("occurrences.jsonl").splitlines()]
    retained = [item for item in occurrences if item["work_id"] == work["id"]]
    assert [item["ordinal"] for item in retained] == [0, 1, 3]
    assert [(item["previous_id"], item["next_id"]) for item in retained] == [
        (None, retained[1]["id"]),
        (retained[0]["id"], None),
        (None, None),
    ]
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
