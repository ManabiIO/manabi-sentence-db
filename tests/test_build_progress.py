import pytest

from manabi_sentence_db import wikimedia
from manabi_sentence_db.build import build_corpus, iter_records, verify_build
from manabi_sentence_db.cli import main
from manabi_sentence_db.demo import create_demo_snapshot
from manabi_sentence_db.serialization import read_json


def test_progress_does_not_change_artifacts_or_build_identity(tmp_path):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    events = []
    build_corpus([snapshot], tmp_path / "quiet", record_format="jsonl", shard_compression="zstd")
    build_corpus([snapshot], tmp_path / "progress", record_format="jsonl",
                 shard_compression="zstd", progress=events.append)
    quiet, progress = [verify_build(tmp_path / name) for name in ("quiet", "progress")]
    assert quiet["build_id"] == progress["build_id"]
    assert quiet["shards"] == progress["shards"]
    assert list(iter_records(tmp_path / "quiet", quiet)) == list(iter_records(tmp_path / "progress", progress))
    assert events[0] == "Verifying cached snapshot bytes"
    assert events[-1] == "Publishing verified corpus"
    assert any("finished 2 documents; 4 sentences" in event for event in events)


def test_cli_progress_stays_on_stderr_and_stdout_contains_only_result(tmp_path, capsys):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    output = tmp_path / "build"
    assert main(["build", "--snapshot", str(snapshot), "--output", str(output), "--progress"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == str(output / "catalog.json")
    assert "Verifying cached snapshot bytes" in captured.err
    assert "Publishing verified corpus" in captured.err


def test_selection_progress_counts_unselected_pages_before_extraction(tmp_path, monkeypatch):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    manifest = read_json(snapshot)
    page = {"native_id": "999", "revision_id": "1", "title": "Unused", "text": "", "timestamp": ""}
    monkeypatch.setattr(wikimedia, "_xml_pages", lambda _: (page for _ in range(100000)))

    def unexpected(*args):
        raise AssertionError("Unselected pages must not enter prose extraction")

    monkeypatch.setattr(wikimedia, "extract_prose", unexpected)
    events = []
    assert list(wikimedia.iter_documents(manifest, snapshot.parent,
                page_ids=frozenset(), progress=events.append)) == []
    assert events[-1].endswith("scanned 100000 pages")


def test_progress_callback_failure_never_publishes_partial_or_complete_output(tmp_path):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")

    def failing_callback(message):
        if message == "Publishing verified corpus":
            raise OSError("deliberate progress failure")

    with pytest.raises(OSError, match="deliberate progress failure"):
        build_corpus([snapshot], tmp_path / "output", progress=failing_callback)
    assert not (tmp_path / "output").exists()
    assert not list(tmp_path.glob(".output-*"))
