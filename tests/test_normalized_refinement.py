"""Bounded synthetic QA for compressed normalized Wikipedia refinement."""

import hashlib
import json
import sqlite3
import zipfile
from copy import deepcopy

import pytest
import zstandard
from test_normalized_selection import _fixture, _read, _sentence

from manabi_sentence_db import normalized_refinement as refinement
from manabi_sentence_db.normalized_database import TABLES, build_normalized_database
from manabi_sentence_db.serialization import DataError
from manabi_sentence_db.wikipedia_quality import WIKIPEDIA_QUALITY_VERSION


def _corpus(tables):
    tables["works"][0]["source_id"] = "wikipedia-ja"
    tables["sentences"][0] = _sentence("であることを意味する。")
    bad, good, last = [row["id"] for row in tables["sentences"]]
    tables["occurrences"] = [
        {"id": "left", "work_id": "selected", "sentence_id": good,
         "ordinal": 0, "previous_id": None, "next_id": "bad", "review_state": "unreviewed"},
        {"id": "bad", "work_id": "selected", "sentence_id": bad,
         "ordinal": 1, "previous_id": "left", "next_id": "right"},
        {"id": "right", "work_id": "selected", "sentence_id": last,
         "ordinal": 2, "previous_id": "bad", "next_id": None},
        {"id": "independent", "work_id": "other", "sentence_id": bad, "ordinal": 0},
    ]
    for row, owner in zip(tables["translations"], ("bad", "independent"), strict=True):
        row.update(sentence_id=bad, occurrence_id=owner)
    tables["references"] = [{
        "schema_version": 1, "id": "reference", "kind": "reference", "source_id": "fixture",
        "snapshot_id": "snapshot", "language": "ja", "native_id": "native", "title": "Reference",
        "url": "https://example.org/reference", "attribution": {
            "text": "Author", "url": "https://example.org/reference"}, "tags": [],
        "locator": {"type": "media", "start_seconds": 0},
    }]


def test_neighbor_barriers_shared_ownership_rights_and_database(tmp_path):
    path, original, ancillary = _fixture(tmp_path, change=_corpus)
    result = refinement.refine_normalized_wikipedia(path, tmp_path / "refined.zip")
    tables, manifest = _read(result)
    assert tables["sentences"] == original["sentences"]
    assert tables["works"] == original["works"]
    assert tables["translations"] == original["translations"][1:]
    assert tables["references"] == original["references"]
    expected = deepcopy(original["occurrences"])
    expected[0]["next_id"] = expected[2]["previous_id"] = None
    assert tables["occurrences"] == [expected[i] for i in (0, 2, 3)]
    receipt = manifest["normalized_refinement_provenance"]
    assert receipt["policy_version"] == WIKIPEDIA_QUALITY_VERSION
    assert receipt["input_zip_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert receipt["original_build_id"] == manifest["build_id"] == "original-build"
    assert receipt["rejected_occurrences_by_reason"] == {"wikipedia-dependent-fragment": 1}
    with zipfile.ZipFile(result) as archive:
        for name, data in ancillary.items():
            assert archive.read(name) == data
    database = build_normalized_database(result, tmp_path / "result.sqlite")
    with sqlite3.connect(database) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT count(*) FROM occurrences").fetchone() == (3,)


def test_only_targeted_owners_are_assessed_and_newly_empty_works_drop(tmp_path, monkeypatch):
    def change(tables):
        _corpus(tables)
        tables["occurrences"] = [tables["occurrences"][1], tables["occurrences"][3]]
        tables["occurrences"][0].update(previous_id=None, next_id=None)
    path, original, _ = _fixture(tmp_path, change=change)
    seen = []
    assessor = refinement.wikipedia_quality.assess_wikipedia_sentence
    monkeypatch.setattr(refinement.wikipedia_quality, "assess_wikipedia_sentence",
                        lambda text: (seen.append(text), assessor(text))[1])
    result = refinement.refine_normalized_wikipedia(path, tmp_path / "out.zip")
    tables, _ = _read(result)
    assert seen == [original["sentences"][0]["text"]]
    assert tables["works"] == original["works"][1:]
    assert tables["sentences"] == original["sentences"][:1]


def test_compressed_staging_and_source_unit_preservation(tmp_path, monkeypatch):
    def change(tables):
        _corpus(tables)
        text = tables["sentences"][1]["text"]
        tables["occurrences"][0]["source_unit"] = {
            "id": "unit_" + "a" * 32, "segment_index": 0, "segment_count": 2,
            "translations": [], "text": text,
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "start": 0, "end": len(text),
        }
    path, original, _ = _fixture(tmp_path, change=change)
    write = refinement._write_archive

    def inspect(root, incoming, manifest):
        assert not list(root.glob("*.jsonl"))
        assert "であることを意味する。".encode() not in (root / "identities.sqlite").read_bytes()
        for table in TABLES:
            with zstandard.open(root / (table + ".jsonl.zst"), "rb") as stream:
                assert hashlib.sha256(stream.read()).hexdigest() == manifest["members"][table + ".jsonl"]
        return write(root, incoming, manifest)

    monkeypatch.setattr(refinement, "_write_archive", inspect)
    result = refinement.refine_normalized_wikipedia(path, tmp_path / "out.zip")
    assert _read(result)[0]["occurrences"][0]["source_unit"] == original["occurrences"][0]["source_unit"]


@pytest.mark.parametrize("change", [
    lambda t: t["works"].append(t["works"][0].copy()),
    lambda t: t["sentences"].append(t["sentences"][0].copy()),
    lambda t: t["occurrences"].append(t["occurrences"][1].copy()),
    lambda t: t["translations"].append(t["translations"][0].copy()),
    lambda t: t["references"].append(t["references"][0].copy()),
    lambda t: t["sentences"][0].update(id="malformed"),
    lambda t: t["occurrences"][1].update(work_id="missing"),
    lambda t: t["occurrences"][1].update(sentence_id="missing"),
    lambda t: t["occurrences"][1].update(next_id="missing"),
    lambda t: t["translations"][0].update(occurrence_id="missing"),
    lambda t: t["translations"][0].update(sentence_id=t["sentences"][1]["id"]),
    lambda t: t["translations"][0].update(license={"id": "unknown"}),
])
def test_even_discarded_rows_are_validated(tmp_path, change):
    def mutate(tables):
        _corpus(tables)
        change(tables)
    path, _, _ = _fixture(tmp_path, change=mutate)
    with pytest.raises(DataError):
        refinement.refine_normalized_wikipedia(path, tmp_path / "invalid.zip")
    assert not (tmp_path / "invalid.zip").exists()


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("corruption", ["count", "hash"])
def test_all_members_verified(tmp_path, table, corruption):
    def corrupt(members):
        if corruption == "hash":
            members[table + ".jsonl"] = b" " + members[table + ".jsonl"]
        else:
            manifest = json.loads(members["manifest.json"])
            manifest["counts"][table] += 1
            members["manifest.json"] = json.dumps(manifest).encode()
    path, _, _ = _fixture(tmp_path, change=_corpus, extra=corrupt)
    with pytest.raises(DataError):
        refinement.refine_normalized_wikipedia(path, tmp_path / "invalid.zip")


def test_input_change_and_nonoverwriting_publication(tmp_path, monkeypatch):
    path, _, _ = _fixture(tmp_path, change=_corpus)
    write = refinement._write_archive

    def changed(root, archive, manifest):
        staged = write(root, archive, manifest)
        with path.open("ab") as stream:
            stream.write(b"changed")
        return staged

    monkeypatch.setattr(refinement, "_write_archive", changed)
    with pytest.raises(DataError, match="changed"):
        refinement.refine_normalized_wikipedia(path, tmp_path / "out.zip")
    assert not (tmp_path / "out.zip").exists()
    existing = tmp_path / "existing.zip"
    existing.write_bytes(b"owned")
    with pytest.raises(DataError):
        refinement.refine_normalized_wikipedia(path, existing)
    assert existing.read_bytes() == b"owned"


@pytest.mark.parametrize("extra", [
    lambda m: m.update({"../escape": b"unsafe"}),
    lambda m: m.update({"manifest.json": b'{"schema_version":999}'}),
    lambda m: m.pop("occurrences.jsonl"),
])
def test_unsafe_unsupported_and_incomplete_archives_fail_closed(tmp_path, extra):
    path, _, _ = _fixture(tmp_path, change=_corpus, extra=extra)
    with pytest.raises(DataError):
        refinement.refine_normalized_wikipedia(path, tmp_path / "invalid.zip")
