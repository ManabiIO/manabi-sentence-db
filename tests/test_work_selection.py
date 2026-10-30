import copy
import json
import zipfile

import pytest

from manabi_sentence_db.build import build_corpus, iter_records, verify_build
from manabi_sentence_db.cli import main
from manabi_sentence_db.demo import create_demo_snapshot
from manabi_sentence_db.normalized import export_normalized, sentence_identity
from manabi_sentence_db.serialization import DataError, digest_json, write_json


def inputs(tmp_path):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    build = tmp_path / "build"
    build_corpus([snapshot], build, shard_compression="zstd")
    catalog = verify_build(build)
    records = list(iter_records(build, catalog))
    selection = {"schema_version": 1, "build_id": catalog["build_id"],
                 "work_ids": [records[1]["id"]]}
    return build, records, selection


def test_complete_work_export_preserves_text_provenance_ordinals_and_context(tmp_path):
    build, records, selection = inputs(tmp_path)
    output = export_normalized(build, tmp_path / "selected.zip", work_selection=selection)
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        works = [json.loads(line) for line in archive.read("works.jsonl").splitlines()]
        sentences = [json.loads(line) for line in archive.read("sentences.jsonl").splitlines()]
        occurrences = [json.loads(line) for line in archive.read("occurrences.jsonl").splitlines()]
        assert manifest["scope"] == "sample"
        assert manifest["work_selection"] == selection
        assert manifest["work_selection_sha256"] == digest_json(selection)
        assert len(works) == 1 and works[0]["id"] == records[1]["id"]
        for key in ("license", "attribution", "revision", "source_id", "snapshot_id"):
            assert works[0][key] == records[1][key]
        assert [row["text"] for row in sentences] == [row["text"] for row in records[1]["sentences"]]
        assert [row["id"] for row in sentences] == [sentence_identity("ja", row["text"]) for row in sentences]
        assert [row["ordinal"] for row in occurrences] == [row["ordinal"] for row in records[1]["sentences"]]
        assert occurrences[0]["previous_id"] is None
        assert occurrences[0]["next_id"] == occurrences[1]["id"]
        assert occurrences[1]["previous_id"] == occurrences[0]["id"]
        assert occurrences[1]["next_id"] is None
        assert archive.read("references.jsonl") == b""
        assert archive.read("catalog.json") == (build / "catalog.json").read_bytes()


@pytest.mark.parametrize("change", ["wrong_build", "empty", "duplicate", "integer", "boolean_schema", "extra"])
def test_invalid_or_unbound_selection_fails_before_publication(tmp_path, change):
    build, _, selection = inputs(tmp_path)
    selection = copy.deepcopy(selection)
    if change == "wrong_build":
        selection["build_id"] = "another-build"
    elif change == "empty":
        selection["work_ids"] = []
    elif change == "duplicate":
        selection["work_ids"] *= 2
    elif change == "integer":
        selection["work_ids"] = [1]
    elif change == "boolean_schema":
        selection["schema_version"] = True
    else:
        selection["unknown"] = True
    with pytest.raises(DataError):
        export_normalized(build, tmp_path / "selected.zip", work_selection=selection)
    assert not (tmp_path / "selected.zip").exists()
    assert not list(tmp_path.glob(".normalized-*"))


def test_absent_work_fails_and_cleans_staging_even_after_an_existing_work(tmp_path):
    build, _, selection = inputs(tmp_path)
    selection["work_ids"].append("missing-work")
    with pytest.raises(DataError, match="absent.*missing-work"):
        export_normalized(build, tmp_path / "selected.zip", work_selection=selection)
    assert not (tmp_path / "selected.zip").exists()
    assert not list(tmp_path.glob(".normalized-*"))


def test_cli_exports_exact_build_bound_selection(tmp_path, capsys):
    build, _, selection = inputs(tmp_path)
    path = tmp_path / "selection.json"
    write_json(path, selection)
    output = tmp_path / "selected.zip"
    assert main(["export-normalized", "--build", str(build), "--output", str(output),
                 "--work-selection", str(path)]) == 0
    assert capsys.readouterr().out.strip() == str(output)
    with zipfile.ZipFile(output) as archive:
        assert json.loads(archive.read("manifest.json"))["counts"]["works"] == 1
