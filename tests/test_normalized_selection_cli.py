"""Command-line selection from released ZIPs needs no canonical build directory."""

import json
import zipfile

from test_normalized_archive import make_archive

from manabi_sentence_db.cli import main
from manabi_sentence_db.serialization import digest_json


def test_cli_selects_complete_work_without_source_build(tmp_path, capsys):
    source, (_, _, catalog, tables, _) = make_archive(tmp_path)
    selection = {"schema_version": 1, "build_id": catalog["build_id"], "work_ids": ["work"]}
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(json.dumps(selection))
    output = tmp_path / "selected.zip"
    assert main([
        "select-normalized-works", "--archive", str(source), "--output", str(output),
        "--work-selection", str(selection_path), "--progress",
    ]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == str(output)
    assert captured.err
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["work_selection"] == selection
        assert manifest["work_selection_sha256"] == digest_json(selection)
        assert manifest["scope"] == "sample"
        for name in ("works", "sentences", "occurrences", "translations"):
            records = [json.loads(line) for line in archive.read(name + ".jsonl").splitlines()]
            assert records == tables[name]
        assert archive.read("references.jsonl") == b""
        for name in ("catalog.json", "licenses.json", "provenance/fixture.json"):
            assert archive.read(name) == original.read(name)


def test_cli_rejects_wrong_build_without_publishing(tmp_path, capsys):
    source, _ = make_archive(tmp_path)
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(json.dumps({
        "schema_version": 1, "build_id": "different-build", "work_ids": ["work"],
    }))
    output = tmp_path / "selected.zip"
    assert main([
        "select-normalized-works", "--archive", str(source), "--output", str(output),
        "--work-selection", str(selection_path),
    ]) == 2
    assert not output.exists()
    assert capsys.readouterr().err
