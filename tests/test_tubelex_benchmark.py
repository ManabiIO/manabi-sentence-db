"""Failed/retried work must be visible in rebuild-cost evidence."""
import importlib.util
from functools import partial
from pathlib import Path

import pytest
from test_tubelex_batch import collection_inputs as collection_inputs

from manabi_sentence_db import tubelex_batch as batch
from manabi_sentence_db import tubelex_index as index
from manabi_sentence_db.serialization import DataError, read_json


def module():
    path = Path(__file__).resolve().parents[1] / "benchmarks/tubelex_pipeline.py"
    spec = importlib.util.spec_from_file_location("tubelex_benchmark", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_benchmark_records_interrupted_attempt_and_keeps_successful_identity_checks(collection_inputs, monkeypatch):
    snapshots, base, output = collection_inputs
    monkeypatch.setattr(batch, "_retire_partial", partial(batch._retire_partial, trash=output.parent / "Trash"))
    original = batch.build_tubelex_index
    report = module().benchmark(snapshots, base, output)
    assert batch.build_tubelex_index is original
    assert report["complete"] and report["logical_artifacts_identical"]
    interrupted = [r for r in report["runs"] if r["outcome"] == "interrupted"]
    assert len(report["runs"]) == 5 and len(interrupted) == 1
    assert interrupted[0]["mode"] == "controlled_interruption"
    for run in report["runs"]:
        assert sum(p["exclusive_ns"] for p in run["phases"].values()) == run["phases"]["end_to_end"]["inclusive_ns"]


def test_benchmark_preserves_failure_timings_and_restores_runtime_hooks(collection_inputs, monkeypatch):
    snapshots, base, output = collection_inputs
    original = index.sha256_file
    def fail(*args, **kwargs):
        raise DataError("private authored failure details")
    monkeypatch.setattr(batch, "build_tubelex_collection", fail)
    with pytest.raises(DataError):
        module().benchmark(snapshots, base, output)
    assert index.sha256_file is original
    report = read_json(output / "report.json")
    assert report["complete"] is False and report["logical_artifacts_identical"] is None
    assert report["runs"][0]["outcome"] == "error"
    assert report["runs"][0]["error_type"] == "DataError"
    assert "private authored failure details" not in (output / "report.json").read_text()


def test_benchmark_preserves_mismatching_artifact_evidence(collection_inputs, monkeypatch):
    snapshots, base, output = collection_inputs
    monkeypatch.setattr(batch, "_retire_partial", partial(batch._retire_partial, trash=output.parent / "Trash"))
    bench = module()
    original = bench.read_json
    def changed_receipt(path):
        document = original(path)
        if path.name == "manifest.private.json" and path.is_relative_to(output / "rebuild"):
            document["index_sha256"] = "0" * 64
        return document
    monkeypatch.setattr(bench, "read_json", changed_receipt)
    with pytest.raises(ValueError, match="changed index"):
        bench.benchmark(snapshots, base, output)
    report = read_json(output / "report.json")
    assert report["complete"] is False and report["logical_artifacts_identical"] is False
    assert len(report["runs"]) == 5


def test_benchmark_preserves_attempt_when_receipt_cannot_be_read(collection_inputs, monkeypatch):
    snapshots, base, output = collection_inputs
    bench = module()
    original = index.sha256_file

    def unreadable_receipt(path):
        raise DataError("private receipt details")

    monkeypatch.setattr(bench, "read_json", unreadable_receipt)
    with pytest.raises(DataError):
        bench.benchmark(snapshots, base, output)
    report = read_json(output / "report.json")
    assert report["complete"] is False
    assert len(report["runs"]) == 1
    assert report["runs"][0]["outcome"] == "error"
    assert report["runs"][0]["phases"]["end_to_end"]["calls"] == 1
    assert report["runs"][0]["wall_seconds"] > 0
    assert "private receipt details" not in (output / "report.json").read_text()
    assert index.sha256_file is original


def test_benchmark_distinguishes_unexpected_failure_from_controlled_interruption(collection_inputs, monkeypatch):
    snapshots, base, output = collection_inputs
    bench = module()
    original = batch.build_tubelex_collection

    def unexpected_failure(snapshots, base, destination, **options):
        if destination.name == "interrupted":
            raise DataError("unplanned failure")
        return original(snapshots, base, destination, **options)

    monkeypatch.setattr(batch, "build_tubelex_collection", unexpected_failure)
    with pytest.raises(DataError):
        bench.benchmark(snapshots, base, output)
    report = read_json(output / "report.json")
    assert report["runs"][-1]["mode"] == "controlled_interruption"
    assert report["runs"][-1]["outcome"] == "error"
