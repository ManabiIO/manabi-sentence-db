from collections import Counter

import pytest

from manabi_sentence_db import resumable_build, wikimedia
from manabi_sentence_db.build import build_corpus, iter_records, verify_build
from manabi_sentence_db.demo import create_demo_snapshot
from manabi_sentence_db.serialization import DataError, read_json, write_json
from manabi_sentence_db.wikimedia_selection import select_wikimedia_documents


@pytest.mark.parametrize("shard_documents", [1, 500])
@pytest.mark.parametrize("shard_compression", ["none", "zstd"])
def test_interrupted_selected_wikipedia_build_resumes_without_reextracting_committed_page(
    tmp_path, monkeypatch, shard_documents, shard_compression
):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    selected = tmp_path / "selection"
    select_wikimedia_documents(snapshot, selected, per_topic=0, general=2)
    selection_path = selected / "selection.json"
    clean = tmp_path / "clean"
    resumed = tmp_path / "resumed"
    options = {
        "record_format": "jsonl",
        "shard_compression": shard_compression,
        "shard_documents": shard_documents,
        "document_selection": selection_path,
    }
    build_corpus([snapshot], clean, **options)

    extracted = Counter()
    extract = wikimedia._extract_prose_items

    def track(text, language):
        extracted[text] += 1
        return extract(text, language)

    monkeypatch.setattr(wikimedia, "_extract_prose_items", track)

    def interrupt_after_first_checkpoint(message):
        if message == "Checkpoint committed batch 1 for demo-ja":
            raise RuntimeError("synthetic interruption")

    with pytest.raises(RuntimeError, match="synthetic interruption"):
        build_corpus([snapshot], resumed, resume=True, progress=interrupt_after_first_checkpoint,
                     **options)

    checkpoint = tmp_path / ".resumed.resume"
    assert checkpoint.is_dir()
    assert not resumed.exists()
    batch_dir = checkpoint / "batches" / "00000000"
    batch = read_json(batch_dir / "batch.json")
    expected_records = "records.jsonl.zst" if shard_compression == "zstd" else "records.jsonl"
    assert batch["records_path"] == expected_records
    assert batch["records_compression"] == shard_compression
    assert (batch_dir / expected_records).is_file()
    assert not (batch_dir / (
        "records.jsonl" if shard_compression == "zstd" else "records.jsonl.zst"
    )).exists()
    if shard_compression == "zstd":
        assert (batch_dir / expected_records).read_bytes().startswith(b"\x28\xb5\x2f\xfd")
    with pytest.raises(DataError, match="does not match"):
        build_corpus([snapshot], resumed, resume=True, shard_documents=2, **{
            key: value for key, value in options.items() if key != "shard_documents"
        })

    build_corpus([snapshot], resumed, resume=True, **options)
    assert len(extracted) == 2
    assert sorted(extracted.values()) == ([1, 2] if shard_documents == 1 else [1, 1])
    assert not checkpoint.exists()

    clean_catalog = verify_build(clean)
    resumed_catalog = verify_build(resumed)
    for field in (
        "build_id", "processor_sha256", "runtime", "options", "sources", "snapshots",
        "shards", "statistics", "document_index", "licenses",
    ):
        assert resumed_catalog[field] == clean_catalog[field]
    assert (resumed / "documents.jsonl").read_bytes() == (clean / "documents.jsonl").read_bytes()
    assert list(iter_records(resumed, resumed_catalog)) == list(iter_records(clean, clean_catalog))


@pytest.mark.parametrize("shard_compression", ["none", "zstd"])
def test_resumable_build_rejects_corrupt_cached_records(tmp_path, shard_compression):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    selected = tmp_path / "selection"
    select_wikimedia_documents(snapshot, selected, per_topic=0, general=2)
    output = tmp_path / "build"
    selection_path = selected / "selection.json"
    options = {
        "record_format": "jsonl",
        "shard_compression": shard_compression,
        "shard_documents": 1,
        "document_selection": selection_path,
    }

    def interrupt(message):
        if message == "Checkpoint committed batch 1 for demo-ja":
            raise RuntimeError("synthetic interruption")

    with pytest.raises(RuntimeError, match="synthetic interruption"):
        build_corpus([snapshot], output, resume=True, progress=interrupt, **options)
    records_name = "records.jsonl.zst" if shard_compression == "zstd" else "records.jsonl"
    records = tmp_path / ".build.resume" / "batches" / "00000000" / records_name
    records.write_bytes(records.read_bytes()[:-2] + b"xx")
    with pytest.raises(DataError, match="failed verification"):
        build_corpus([snapshot], output, resume=True, **options)
    assert not output.exists()


def test_resumable_build_preserves_existing_output(tmp_path):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    output = tmp_path / "existing-build"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("existing output", encoding="utf-8")

    with pytest.raises(DataError, match="Output already exists"):
        build_corpus([snapshot], output, resume=True)

    assert sentinel.read_text(encoding="utf-8") == "existing output"
    assert not (tmp_path / ".existing-build.resume").exists()


def test_resumable_build_recovers_a_batch_committed_before_state_refresh(tmp_path, monkeypatch):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    selected = tmp_path / "selection"
    select_wikimedia_documents(snapshot, selected, per_topic=0, general=2)
    output = tmp_path / "build"
    options = {
        "record_format": "jsonl",
        "shard_compression": "zstd",
        "shard_documents": 1,
        "document_selection": selected / "selection.json",
    }
    save_state = resumable_build._Checkpoint.save_state

    def interrupt_state_refresh(checkpoint):
        raise OSError("synthetic state refresh interruption")

    monkeypatch.setattr(resumable_build._Checkpoint, "save_state", interrupt_state_refresh)
    with pytest.raises(OSError, match="state refresh"):
        build_corpus([snapshot], output, resume=True, **options)
    checkpoint = tmp_path / ".build.resume"
    assert resumable_build.read_json(checkpoint / "state.json")["batches"] == []
    monkeypatch.setattr(resumable_build._Checkpoint, "save_state", save_state)
    build_corpus([snapshot], output, resume=True, **options)
    assert len(list(iter_records(output, verify_build(output)))) == 2


@pytest.mark.parametrize("ledger_already_truncated", [False, True])
def test_checkpoint_recovers_interrupted_partial_source_rollback(
    tmp_path, ledger_already_truncated
):
    root = tmp_path / "checkpoint"
    initial = {
        "source_stats": {}, "statistics": {}, "licenses": {},
        "completed_sources": [], "cursors": {},
    }
    checkpoint = resumable_build._Checkpoint(root, "b" * 64, initial)
    checkpoint.commit_batch(
        [{"id": "doc-1", "sentences": [{"id": "sentence-1"}]}],
        source_id="source-ja", language="ja", cursor="native-1",
        stats_delta=Counter(), source_stats=Counter(), licenses_delta={},
    )
    target = {**checkpoint.state, "batches": []}
    checkpoint.state["rollback"] = {"first_batch": 0, "target": target}
    checkpoint.save_state()
    if ledger_already_truncated:
        checkpoint.database.execute("DELETE FROM identities WHERE batch_no>=0")
        checkpoint.database.execute("DELETE FROM batches WHERE batch_no>=0")
        checkpoint.database.commit()
    checkpoint.close()

    recovered = resumable_build._Checkpoint(root, "b" * 64, initial)
    try:
        assert recovered.state["batches"] == []
        assert "rollback" not in recovered.state
        assert recovered.database.execute("SELECT COUNT(*) FROM batches").fetchone() == (0,)
        assert not (root / "batches" / "00000000").exists()
    finally:
        recovered.close()


def test_resumable_build_rejects_a_tampered_state_file(tmp_path):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    selected = tmp_path / "selection"
    select_wikimedia_documents(snapshot, selected, per_topic=0, general=2)
    output = tmp_path / "build"
    options = {
        "record_format": "jsonl",
        "shard_documents": 1,
        "document_selection": selected / "selection.json",
    }

    def interrupt(message):
        if message == "Checkpoint committed batch 1 for demo-ja":
            raise RuntimeError("synthetic interruption")

    with pytest.raises(RuntimeError, match="synthetic interruption"):
        build_corpus([snapshot], output, resume=True, progress=interrupt, **options)
    state_path = tmp_path / ".build.resume" / "state.json"
    state = read_json(state_path)
    state["cursors"]["demo-ja"] = "2"
    write_json(state_path, state)
    with pytest.raises(DataError, match="state failed verification"):
        build_corpus([snapshot], output, resume=True, **options)
    assert not output.exists()


def test_checkpoint_rejects_a_second_concurrent_writer(tmp_path):
    initial = {
        "source_stats": {}, "statistics": {}, "licenses": {},
        "completed_sources": [], "cursors": {},
    }
    checkpoint = resumable_build._Checkpoint(tmp_path / "checkpoint", "a" * 64, initial)
    try:
        with pytest.raises(DataError, match="currently owns"):
            resumable_build._Checkpoint(tmp_path / "checkpoint", "a" * 64, initial)
    finally:
        checkpoint.close()
