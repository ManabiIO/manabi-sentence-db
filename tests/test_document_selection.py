import copy
from collections import Counter

import pytest

from manabi_sentence_db import wikimedia
from manabi_sentence_db.build import build_corpus, canonical_document, iter_records, verify_build
from manabi_sentence_db.demo import create_demo_snapshot
from manabi_sentence_db.document_selection import validate_selection
from manabi_sentence_db.serialization import DataError, digest_json, read_json, write_json


def test_selection_filters_before_extraction_and_preserves_records(tmp_path, monkeypatch):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    manifest = read_json(snapshot)
    selection = {"schema_version": 1, "source_id": manifest["source_id"],
                 "snapshot_id": manifest["snapshot_id"], "page_ids": ["2"]}
    path = tmp_path / "selection.json"
    write_json(path, selection)
    baseline = list(wikimedia.iter_documents(manifest, snapshot.parent))
    original = wikimedia._extract_prose_items
    seen = []

    def extract(text, language):
        seen.append(text)
        return original(text, language)

    monkeypatch.setattr(wikimedia, "_extract_prose_items", extract)
    output = tmp_path / "build"
    build_corpus([snapshot], output, document_selection=path)
    catalog = verify_build(output)
    records = list(iter_records(output, catalog))
    assert len(seen) == 1
    assert len(records) == 1
    assert records[0]["native_id"] == "2"
    assert records[0] == canonical_document(baseline[1], manifest, Counter(), {"sexual-content"})
    assert records[0]["revision"] == baseline[1]["revision"]
    assert records[0]["license"] == baseline[1]["license"]
    assert [s["ordinal"] for s in records[0]["sentences"]] == [0, 1]
    assert [s["text"] for s in records[0]["sentences"]] == [
        s["text"] for s in baseline[1]["sentences"]
    ]
    assert catalog["options"]["document_selection_sha256"] == digest_json(selection)
    assert catalog["scope"] == "sample"


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("snapshot_id", "wrong"), ("source_id", "wrong"),
    ("page_ids", []), ("page_ids", [2]), ("page_ids", ["02"]),
    ("page_ids", ["2", "2"]),
])
def test_selection_rejects_invalid_or_unbound_input(tmp_path, field, value):
    manifest = read_json(create_demo_snapshot(tmp_path / "snapshot"))
    selection = {"schema_version": 1, "source_id": manifest["source_id"],
                 "snapshot_id": manifest["snapshot_id"], "page_ids": ["2"]}
    selection[field] = value
    with pytest.raises(DataError):
        validate_selection(selection, [manifest])


def test_selection_rejects_other_adapters(tmp_path):
    manifest = copy.deepcopy(read_json(create_demo_snapshot(tmp_path / "snapshot")))
    manifest["source"]["adapter"] = "tatoeba"
    with pytest.raises(DataError, match="Wikimedia"):
        validate_selection({"schema_version": 1, "source_id": manifest["source_id"],
                            "snapshot_id": manifest["snapshot_id"], "page_ids": ["2"]},
                           [manifest])


def test_selection_reports_absent_page_instead_of_silently_ignoring_it(tmp_path):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    manifest = read_json(snapshot)
    with pytest.raises(DataError, match="absent.*999999"):
        list(wikimedia.iter_documents(manifest, snapshot.parent, page_ids=frozenset({"2", "999999"})))


def test_record_validation_enforces_selected_page_membership(tmp_path):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    manifest = read_json(snapshot)
    output = tmp_path / "build"
    build_corpus([snapshot], output)
    catalog = verify_build(output)
    catalog["options"]["document_selection"] = {
        "schema_version": 1, "source_id": manifest["source_id"],
        "snapshot_id": manifest["snapshot_id"], "page_ids": ["2"],
    }
    with pytest.raises(DataError, match="outside.*selected"):
        list(iter_records(output, catalog))


def test_selection_rejects_document_cap_before_snapshot_verification(tmp_path, monkeypatch):
    def unexpected_verification(path):
        pytest.fail("Snapshot verification must not run for conflicting options")

    monkeypatch.setattr("manabi_sentence_db.snapshot.verify_snapshot", unexpected_verification)
    with pytest.raises(DataError, match="cannot be combined"):
        build_corpus([tmp_path / "missing-snapshot.json"], tmp_path / "build",
                     document_selection=tmp_path / "missing-selection.json", max_documents=1)


def test_catalog_rejects_selection_with_document_cap(tmp_path):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    manifest = read_json(snapshot)
    selection = {"schema_version": 1, "source_id": manifest["source_id"],
                 "snapshot_id": manifest["snapshot_id"], "page_ids": ["2"]}
    path = tmp_path / "selection.json"
    write_json(path, selection)
    output = tmp_path / "build"
    build_corpus([snapshot], output, document_selection=path)
    catalog_path = output / "catalog.json"
    catalog = read_json(catalog_path)
    catalog["options"]["max_documents_per_source"] = 1
    write_json(catalog_path, catalog)
    with pytest.raises(DataError, match="cannot be combined"):
        verify_build(output)


def test_present_selected_page_without_prose_is_not_missing(tmp_path, monkeypatch):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    manifest = read_json(snapshot)
    monkeypatch.setattr(wikimedia, "_extract_prose_items", lambda text, language: ([], []))
    stats = Counter()
    assert list(wikimedia.iter_documents(
        manifest, snapshot.parent, page_ids=frozenset({"2"}), stats=stats
    )) == []
    assert stats["wikimedia_pages_selected"] == 1
