"""Small synthetic interchange checks; no canonical/raw corpus is needed."""

import hashlib
import json
import sqlite3
import stat
import zipfile
from pathlib import Path

import pytest
import zstandard

from manabi_sentence_db import normalized_selection as selection
from manabi_sentence_db.normalized import sentence_identity
from manabi_sentence_db.normalized_database import TABLES, build_normalized_database
from manabi_sentence_db.serialization import DataError, canonical_json, digest_json


def _sentence(text):
    return {"id": sentence_identity("ja", text), "language": "ja", "text": text,
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "future": {"v": 2}}


def _fixture(tmp_path, *, change=None, extra=None):
    rights = {"license": {"id": "CC0-1.0",
                          "url": "https://creativecommons.org/publicdomain/zero/1.0/"},
              "attribution": {"text": "Synthetic author", "url": "https://example.org/work"}}
    sentences = [_sentence(text) for text in ("猫です。", "犬です。", "鳥です。")]
    tables = {
        "works": [{"id": name, "source_id": "fixture", "language": "ja", "title": name,
                   "url": "https://example.org/work", "unknown": [1, 2], **rights}
                  for name in ("selected", "other")],
        "sentences": sentences,
        "occurrences": [
            {"id": "a", "work_id": "selected", "sentence_id": sentences[0]["id"],
             "ordinal": 0, "previous_id": None, "next_id": None, "flags": ["original"],
             "unknown": {"deep": True}},
            {"id": "b", "work_id": "selected", "sentence_id": sentences[1]["id"],
             "ordinal": 3, "previous_id": None, "next_id": None},
            {"id": "other-a", "work_id": "other", "sentence_id": sentences[0]["id"],
             "ordinal": 0},
            {"id": "other-b", "work_id": "other", "sentence_id": sentences[2]["id"],
             "ordinal": 1},
        ],
        "translations": [
            {"id": name, "sentence_id": sentences[0]["id"], "occurrence_id": owner,
             "language": "en", "text": name, "text_sha256": hashlib.sha256(name.encode()).hexdigest(),
             "source_url": "https://example.org/work", "future": True, **rights}
            for name, owner in (("Cat.", "a"), ("A cat.", "other-a"))
        ],
        "references": [{"id": "ignored", "kind": "reference", "unknown": "retained only in input"}],
    }
    if change:
        change(tables)
    catalog = {"build_id": "original-build", "snapshots": [
        {"source_id": "fixture", "manifest": "provenance/日本語.json"}]}
    ancillary = {"licenses.json": b'{ "original": "license bytes" }\n',
                 "catalog.json": canonical_json(catalog),
                 "provenance/日本語.json": b'{ "original": "snapshot bytes" }\n'}
    raw = {name + ".jsonl": b"".join(canonical_json(row) + b"\n" for row in rows)
           for name, rows in tables.items()}
    manifest = {"schema_version": 2, "kind": "normalized-corpus", "build_id": "original-build",
                "scope": "full", "counts": {name: len(rows) for name, rows in tables.items()},
                "members": {name: hashlib.sha256(data).hexdigest() for name, data in raw.items()},
                "future_manifest": {"v": 7}}
    members = {**raw, "manifest.json": canonical_json(manifest), **ancillary}
    if extra:
        extra(members)
    path = tmp_path / "input.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path, tables, ancillary


def _select(path, output, **options):
    return selection.select_normalized_works(path, output, work_selection=options.pop(
        "work_selection", {"schema_version": 1, "build_id": "original-build",
                           "work_ids": ["selected"]}), **options)


def _read(path):
    with zipfile.ZipFile(path) as archive:
        return {table: [json.loads(line) for line in archive.read(table + ".jsonl").splitlines()]
                for table in TABLES}, json.loads(archive.read("manifest.json"))


def test_whole_work_preserves_fields_gaps_shared_identity_and_ancillary(tmp_path):
    path, original, ancillary = _fixture(tmp_path)
    result = _select(path, tmp_path / "selected.zip")
    tables, manifest = _read(result)
    for table, expected in {"works": original["works"][:1], "sentences": original["sentences"][:2],
                            "occurrences": original["occurrences"][:2],
                            "translations": original["translations"][:1], "references": []}.items():
        assert tables[table] == expected
    assert [row["ordinal"] for row in tables["occurrences"]] == [0, 3]
    assert manifest["scope"] == "sample" and manifest["build_id"] == "original-build"
    assert manifest["future_manifest"] == {"v": 7}
    assert manifest["work_selection_sha256"] == digest_json(manifest["work_selection"])
    assert manifest["normalized_selection_provenance"]["input_zip_sha256"] == hashlib.sha256(
        path.read_bytes()).hexdigest()
    with zipfile.ZipFile(result) as archive:
        for name, expected in ancillary.items():
            assert archive.read(name) == expected
        assert archive.testzip() is None
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())
    imported = build_normalized_database(result, tmp_path / "tiny.sqlite")
    with sqlite3.connect(imported) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT count(*) FROM occurrences").fetchone() == (2,)


def test_staging_is_compressed_and_ledger_has_no_text(tmp_path, monkeypatch):
    path, _, _ = _fixture(tmp_path)
    original_write = selection._write_archive

    def inspect(root, incoming, manifest):
        assert not list(root.glob("*.jsonl"))
        assert {p.name for p in root.iterdir()} == {
            "identities.sqlite", *(table + ".jsonl.zst" for table in TABLES)}
        for table in TABLES:
            with zstandard.open(root / (table + ".jsonl.zst"), "rb") as stream:
                assert hashlib.sha256(stream.read()).hexdigest() == manifest["members"][table + ".jsonl"]
        assert "猫です。".encode() not in (root / "identities.sqlite").read_bytes()
        return original_write(root, incoming, manifest)

    monkeypatch.setattr(selection, "_write_archive", inspect)
    one = _select(path, tmp_path / "one.zip")
    two = _select(path, tmp_path / "two.zip")
    assert one.read_bytes() == two.read_bytes()
    assert not list(tmp_path.glob(".normalized-selection-*"))


@pytest.mark.parametrize("change", [
    lambda t: t["works"].append(t["works"][0].copy()),
    lambda t: t["sentences"].append(t["sentences"][0].copy()),
    lambda t: t["occurrences"].append(t["occurrences"][0].copy()),
    lambda t: t["translations"].append(t["translations"][0].copy()),
    lambda t: t["sentences"].pop(0),
    lambda t: t["occurrences"][0].update(next_id="missing"),
    lambda t: t["translations"][0].update(occurrence_id="missing"),
    lambda t: t["translations"][0].pop("occurrence_id"),
    lambda t: t["translations"][0].update(sentence_id=t["sentences"][1]["id"]),
    lambda t: t["sentences"][0].update(language="en"),
])
def test_selected_dependencies_and_ownership_fail_closed(tmp_path, change):
    path, _, _ = _fixture(tmp_path, change=change)
    with pytest.raises(DataError):
        _select(path, tmp_path / "invalid.zip")
    assert not (tmp_path / "invalid.zip").exists()


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("corruption", ["hash", "count"])
def test_every_member_checksum_and_count_is_verified(tmp_path, table, corruption):
    def corrupt(members):
        if corruption == "hash":
            # Valid JSON and identical records/count, but different logical bytes.
            members[table + ".jsonl"] = b" " + members[table + ".jsonl"]
        else:
            manifest = json.loads(members["manifest.json"])
            manifest["counts"][table] += 1
            members["manifest.json"] = canonical_json(manifest)
    path, _, _ = _fixture(tmp_path, extra=corrupt)
    with pytest.raises(DataError):
        _select(path, tmp_path / "invalid.zip")
    assert not (tmp_path / "invalid.zip").exists()


@pytest.mark.parametrize("value", [
    {"schema_version": 1, "build_id": "wrong", "work_ids": ["selected"]},
    {"schema_version": 1, "build_id": "original-build", "work_ids": ["missing"]},
    {"schema_version": 1, "build_id": "original-build", "work_ids": ["selected", "selected"]},
    {"schema_version": True, "build_id": "original-build", "work_ids": ["selected"]},
    {"schema_version": 1, "build_id": "original-build", "work_ids": []},
])
def test_selection_binds_exact_build_and_unique_present_ids(tmp_path, value):
    path, _, _ = _fixture(tmp_path)
    with pytest.raises(DataError):
        _select(path, tmp_path / "invalid.zip", work_selection=value)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a/../b", "a\\b", "a//b"])
def test_unsafe_zip_members_are_rejected(tmp_path, name):
    path, _, _ = _fixture(tmp_path, extra=lambda members: members.update({name: b"unsafe"}))
    with pytest.raises(DataError, match="Unsafe"):
        _select(path, tmp_path / "invalid.zip")


@pytest.mark.parametrize("kind", ["duplicate", "symlink"])
def test_duplicate_members_and_archive_symlinks_are_rejected(tmp_path, kind):
    path, _, _ = _fixture(tmp_path)
    with zipfile.ZipFile(path, "a") as archive:
        if kind == "duplicate":
            with pytest.warns(UserWarning):
                archive.writestr("works.jsonl", b"bad")
        else:
            member = zipfile.ZipInfo("linked")
            member.create_system = 3
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(member, "../target")
    with pytest.raises(DataError):
        _select(path, tmp_path / "invalid.zip")


def test_fresh_canonical_output_and_atomic_publication(tmp_path, monkeypatch):
    path, _, _ = _fixture(tmp_path)
    existing = tmp_path / "existing.zip"
    existing.write_bytes(b"keep")
    with pytest.raises(DataError, match="fresh"):
        _select(path, existing)
    linked = tmp_path / "linked"
    linked.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(DataError, match="canonical"):
        _select(path, linked / "invalid.zip")
    original_link = selection.os.link

    def competing(source, output):
        Path(output).write_bytes(b"competing writer")
        return original_link(source, output)

    monkeypatch.setattr(selection.os, "link", competing)
    with pytest.raises(DataError, match="fresh"):
        _select(path, tmp_path / "race.zip")
    assert (tmp_path / "race.zip").read_bytes() == b"competing writer"


def test_source_unit_preserved_and_translation_rules_enforced(tmp_path):
    def unit(tables):
        before = tables["sentences"][0]["text"]
        text = before + tables["sentences"][1]["text"]
        tables["occurrences"][1]["source_unit"] = {
            "id": "unit_" + "0" * 32, "text": text,
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "start": len(before), "end": len(text), "segment_index": 1, "segment_count": 2,
            "translations": [],
        }
    path, tables, _ = _fixture(tmp_path, change=unit)
    result = _select(path, tmp_path / "selected.zip")
    assert _read(result)[0]["occurrences"][1] == tables["occurrences"][1]

    def invalid(tables):
        unit(tables)
        tables["translations"][0].update(occurrence_id="b",
                                           sentence_id=tables["sentences"][1]["id"])
    subdirectory = tmp_path / "invalid"
    subdirectory.mkdir()
    path, _, _ = _fixture(subdirectory, change=invalid)
    with pytest.raises(DataError, match="source-unit"):
        _select(path, subdirectory / "invalid.zip")


@pytest.mark.parametrize("corrupt", [False, True])
def test_refinement_parent_bytes_and_binding_are_preserved(tmp_path, corrupt):
    parent_bytes = []

    def refinement(members):
        catalog = json.loads(members["catalog.json"])
        parent = {"schema_version": 1, "processor_sha256": "synthetic-processor",
                  "runtime": {"python": "synthetic"}, "options": {"record_format": "jsonl"},
                  "scope": "full", "snapshots": catalog["snapshots"],
                  "sources": [{"source": {"id": "fixture"}}],
                  "licenses": {"sha256": hashlib.sha256(members["licenses.json"]).hexdigest()}}
        parent["build_id"] = "build_" + digest_json({
            "processor": parent["processor_sha256"], "runtime": parent["runtime"],
            "options": parent["options"],
            "snapshots": [row["snapshot_id"] for row in parent["snapshots"]],
        })[:32]
        raw_parent = canonical_json(parent) + b"\n"
        parent_bytes.append(raw_parent)
        digest = hashlib.sha256(raw_parent).hexdigest()
        catalog.update(schema_version=parent["schema_version"], scope=parent["scope"],
                       sources=parent["sources"], licenses=parent["licenses"], options={
                           **parent["options"], "refinement": {"policy": "vfd-example-quality-v1",
                               "parent_build_id": parent["build_id"],
                               "parent_catalog_sha256": digest}},
                       refinement_parent={"path": "lineage/parent.catalog.json", "sha256": digest})
        members["catalog.json"] = canonical_json(catalog)
        members["lineage/parent.catalog.json"] = raw_parent
        manifest = json.loads(members["manifest.json"])
        manifest["refinement_provenance"] = {
            "catalog.json": hashlib.sha256(members["catalog.json"]).hexdigest(),
            "lineage/parent.catalog.json": "0" * 64 if corrupt else digest}
        members["manifest.json"] = canonical_json(manifest)

    # The parent identity binds snapshot IDs, independently of snapshot bytes.
    def with_snapshot_id(members):
        catalog = json.loads(members["catalog.json"])
        catalog["snapshots"][0]["snapshot_id"] = "snapshot-fixture"
        members["catalog.json"] = canonical_json(catalog)
        refinement(members)

    path, _, _ = _fixture(tmp_path, extra=with_snapshot_id)
    if corrupt:
        with pytest.raises(DataError, match="provenance checksum"):
            _select(path, tmp_path / "invalid.zip")
    else:
        result = _select(path, tmp_path / "selected.zip")
        with zipfile.ZipFile(result) as archive:
            assert archive.read("lineage/parent.catalog.json") == parent_bytes[0]


def test_changed_input_cannot_publish(tmp_path, monkeypatch):
    path, _, _ = _fixture(tmp_path)
    original_write = selection._write_archive

    def changing(root, incoming, manifest):
        staged = original_write(root, incoming, manifest)
        with path.open("ab") as stream:
            stream.write(b"changed")
        return staged

    monkeypatch.setattr(selection, "_write_archive", changing)
    with pytest.raises(DataError, match="changed"):
        _select(path, tmp_path / "invalid.zip")
    assert not (tmp_path / "invalid.zip").exists()


def test_failed_file_flush_cannot_publish(tmp_path, monkeypatch):
    path, _, _ = _fixture(tmp_path)

    def failed_flush(_descriptor):
        raise OSError("synthetic staging flush failure")

    monkeypatch.setattr(selection.os, "fsync", failed_flush)
    with pytest.raises(OSError, match="staging flush failure"):
        _select(path, tmp_path / "invalid.zip")
    assert not (tmp_path / "invalid.zip").exists()


def test_selected_manifest_stays_within_release_consumer_bound(tmp_path):
    def oversized(members):
        manifest = json.loads(members["manifest.json"])
        manifest["future_manifest"] = {"large": "x" * selection.MAX_MANIFEST_BYTES}
        members["manifest.json"] = canonical_json(manifest)

    path, _, _ = _fixture(tmp_path, extra=oversized)
    with pytest.raises(DataError, match="Oversized normalized selection manifest"):
        _select(path, tmp_path / "invalid.zip")
    assert not (tmp_path / "invalid.zip").exists()
