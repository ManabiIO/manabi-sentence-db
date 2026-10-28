"""Synthetic, offline checks of normalized ZIP transport and SQLite read-back."""

import hashlib
import json
import os
import sqlite3
import zipfile
from contextlib import contextmanager
from pathlib import Path

from manabi_sentence_db import normalized_database as database
from manabi_sentence_db.normalized import _write_normalized_archive, sentence_identity
from manabi_sentence_db.serialization import canonical_json


def make_archive(tmp_path):
    root, build = tmp_path / "staged", tmp_path / "build"
    root.mkdir(parents=True)
    build.mkdir()
    license = {
        "id": "CC0-1.0",
        "url": "https://creativecommons.org/publicdomain/zero/1.0/",
    }
    sentences = [
        {
            "id": sentence_identity("ja", text),
            "language": "ja",
            "text": text,
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
        for text in ("今日は雨です。", "犬がいます。")
    ]
    tables = {
        "works": [
            {
                "id": "work",
                "source_id": "fixture",
                "language": "ja",
                "title": "Synthetic work",
                "url": "https://example.org/work",
                "license": license,
                "attribution": {
                    "text": "Synthetic test author",
                    "url": "https://example.org/work",
                },
            }
        ],
        "sentences": sentences,
        "occurrences": [
            {
                "id": f"occurrence-{i}",
                "sentence_id": row["id"],
                "work_id": "work",
                "ordinal": i,
            }
            for i, row in enumerate(sentences)
        ],
        "translations": [
            {
                "id": "translation",
                "sentence_id": sentences[0]["id"],
                "occurrence_id": "occurrence-0",
                "language": "en",
                "text": "It is raining today.",
                "text_sha256": hashlib.sha256(b"It is raining today.").hexdigest(),
                "license": license,
                "source_url": "https://example.org/translation",
                "attribution": {
                    "text": "Synthetic test author",
                    "url": "https://example.org/translation",
                },
            }
        ],
        "references": [{
            "schema_version": 1, "id": "reference", "kind": "reference",
            "source_id": "fixture", "snapshot_id": "snapshot", "language": "ja",
            "native_id": "reference", "title": "Synthetic reference",
            "url": "https://example.org/reference", "tags": [],
            "attribution": {
                "text": "Synthetic test author", "url": "https://example.org/reference",
            },
            "locator": {"type": "media", "start_seconds": 1, "end_seconds": 4},
        }],
    }
    catalog = {
        "build_id": "synthetic-build",
        "scope": "sample",
        "snapshots": [
            {"source_id": "fixture", "manifest": "provenance/fixture.json"},
            {"source_id": "other", "manifest": "provenance/other.json"},
        ],
    }
    (build / "licenses.json").write_bytes(canonical_json({"licenses": [license]}))
    (build / "catalog.json").write_bytes(canonical_json(catalog))
    for snapshot in catalog["snapshots"]:
        path = build / snapshot["manifest"]
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(
            canonical_json(
                {"source_id": snapshot["source_id"], "retrieved_at": "2026-01-01T00:00:00Z"}
            )
        )
    for name, rows in tables.items():
        (root / f"{name}.jsonl").write_bytes(
            b"".join(canonical_json(row) + b"\n" for row in rows)
        )
    manifest = {
        "schema_version": 2,
        "kind": "normalized-corpus",
        "build_id": catalog["build_id"],
        "scope": catalog["scope"],
        "counts": {name: len(rows) for name, rows in tables.items()},
        "identity": "sha256(canonical_json([language,NFC_text]))",
        "members": {
            f"{name}.jsonl": hashlib.sha256((root / f"{name}.jsonl").read_bytes()).hexdigest()
            for name in tables
        },
    }
    _write_normalized_archive(root, build, catalog, None, manifest)
    return root / "corpus.zip", (root, build, catalog, tables, manifest)


def test_normalized_archive_round_trip_preserves_identity_and_metadata(tmp_path):
    path, (_, _, _, tables, manifest) = make_archive(tmp_path)
    output = database.build_normalized_database(path, tmp_path / "corpus.sqlite")
    with sqlite3.connect(output) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (2,)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT id,text FROM sentences ORDER BY id").fetchall() == sorted(
            (row["id"], row["text"]) for row in tables["sentences"]
        )
        translation = db.execute("SELECT metadata_json FROM translations").fetchone()[0]
        assert json.loads(translation) == tables["translations"][0]
        reference = db.execute("SELECT metadata_json FROM external_references").fetchone()[0]
        assert json.loads(reference) == tables["references"][0]
        saved_manifest = db.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0]
        assert json.loads(saved_manifest) == manifest


def test_all_zip_members_ignore_clock_mtime_and_permissions(tmp_path, monkeypatch):
    path, (root, build, catalog, _, manifest) = make_archive(tmp_path)
    original = path.read_bytes()
    for file in [*build.rglob("*.json"), *root.glob("*.jsonl")]:
        os.utime(file, (946684800, 946684800))
        file.chmod(0o600)
    monkeypatch.setattr(
        zipfile.time, "localtime", lambda *args: (2035, 4, 5, 6, 7, 8, 0, 1, -1)
    )
    _write_normalized_archive(root, build, catalog, None, manifest)
    assert path.read_bytes() == original
    with zipfile.ZipFile(path) as archive:
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())
        assert all(
            info.create_system == 3 and info.external_attr >> 16 == 0o100644
            for info in archive.infolist()
        )
        for name, expected in manifest["members"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected
        names = ["licenses.json", "catalog.json", *(s["manifest"] for s in catalog["snapshots"])]
        for name in names:
            assert archive.read(name) == (build / name).read_bytes()
        assert archive.testzip() is None


def test_archive_streams_files_and_retains_source_filter(tmp_path, monkeypatch):
    path, (root, build, catalog, _, manifest) = make_archive(tmp_path)
    with monkeypatch.context() as patch:
        def no_whole_file(*args, **kwargs):
            raise AssertionError("ZIP file inputs must be streamed")

        patch.setattr(Path, "read_bytes", no_whole_file)
        _write_normalized_archive(root, build, catalog, "fixture", manifest)
    with zipfile.ZipFile(path) as archive:
        assert "provenance/fixture.json" in archive.namelist()
        assert "provenance/other.json" not in archive.namelist()
        assert archive.read("catalog.json") == (build / "catalog.json").read_bytes()


def test_large_table_is_copied_in_bounded_chunks(tmp_path, monkeypatch):
    path, (root, build, catalog, _, manifest) = make_archive(tmp_path)
    target = root / "references.jsonl"
    data = canonical_json({"id": "large-fixture", "text": "あ" * 400000}) + b"\n"
    target.write_bytes(data)
    manifest["members"][target.name] = hashlib.sha256(data).hexdigest()
    original_open, reads = Path.open, []

    @contextmanager
    def bounded_open(self, *args, **kwargs):
        with original_open(self, *args, **kwargs) as stream:
            if self != target:
                yield stream
                return

            class BoundedReader:
                def read(self, size=-1):
                    assert 0 < size <= 1024 * 1024
                    reads.append(size)
                    return stream.read(size)

            yield BoundedReader()

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", bounded_open)
        _write_normalized_archive(root, build, catalog, None, manifest)
    assert len(reads) >= 3  # More than one chunk, plus EOF.
    with zipfile.ZipFile(path) as archive:
        assert archive.read(target.name) == data
        assert archive.testzip() is None


def test_unicode_provenance_paths_are_preserved(tmp_path):
    path, (root, build, catalog, _, manifest) = make_archive(tmp_path)
    snapshot = catalog["snapshots"][0]
    previous = build / snapshot["manifest"]
    snapshot["manifest"] = "provenance/日本語.json"
    previous.rename(build / snapshot["manifest"])
    (build / "catalog.json").write_bytes(canonical_json(catalog))
    _write_normalized_archive(root, build, catalog, None, manifest)
    with zipfile.ZipFile(path) as archive:
        assert archive.read(snapshot["manifest"]) == (build / snapshot["manifest"]).read_bytes()
        assert archive.getinfo(snapshot["manifest"]).flag_bits & 0x800


def test_changed_record_bytes_change_archive_identity(tmp_path):
    path, (root, build, catalog, tables, manifest) = make_archive(tmp_path)
    original = path.read_bytes()
    tables["works"][0]["title"] = "Changed synthetic work"
    data = canonical_json(tables["works"][0]) + b"\n"
    (root / "works.jsonl").write_bytes(data)
    manifest["members"]["works.jsonl"] = hashlib.sha256(data).hexdigest()
    _write_normalized_archive(root, build, catalog, None, manifest)
    assert path.read_bytes() != original
    with zipfile.ZipFile(path) as archive:
        assert archive.read("works.jsonl") == data
        assert json.loads(archive.read("manifest.json")) == manifest
