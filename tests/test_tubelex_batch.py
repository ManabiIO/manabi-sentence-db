from __future__ import annotations

import csv
import json
import shutil
from functools import partial
from pathlib import Path

import pytest

from manabi_sentence_db import tubelex_batch as batch
from manabi_sentence_db.cli import main
from manabi_sentence_db.serialization import DataError, canonical_json, read_json, sha256_file
from manabi_sentence_db.tubelex import snapshot_tubelex
from manabi_sentence_db.tubelex_index import (
    QueryBudgetExceeded,
    QueryWorkLimitExceeded,
    TubelexReader,
)


def snapshot(tmp_path, video, text):
    root = tmp_path / video
    root.mkdir()
    local = root / "local"
    local.mkdir()
    listing = root / "videos.csv"
    with listing.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["videoid", "sub", "language"])
        writer.writerow([video, "True", "ja"])
    (local / f"{video}.info.json").write_bytes(canonical_json({
        "id": video, "subtitles": {"ja": [{
            "ext": "vtt", "url": f"https://www.youtube.com/api/timedtext?lang=ja&v={video}",
        }]},
    }))
    (local / f"{video}.ja.vtt").write_text(f"WEBVTT\n\n00:00.000 --> 00:03.000\n{text}\n")
    return snapshot_tubelex(root / "snapshot", videos_csv=listing, captions_dir=local)


@pytest.fixture
def collection_inputs(tmp_path):
    snapshots = [
        snapshot(tmp_path, "abcdefghijk", "今日は図書館へ行きます。"),
        snapshot(tmp_path, "lmnopqrstuv", "今日は公園へ行きます。"),
        snapshot(tmp_path, "0123456789_", "今日は美術館へ行きます。"),
    ]
    base = tmp_path / "base.zip"
    base.write_bytes(b"authored test corpus identity")
    return snapshots, base, tmp_path / "collection"


def test_resume_reuses_completed_shards_and_final_result_is_idempotent(collection_inputs, monkeypatch):
    snapshots, base, output = collection_inputs
    original = batch.build_tubelex_index
    calls = []

    def interrupt(snapshot, *args, **kwargs):
        calls.append(snapshot)
        if len(calls) == 2:
            raise RuntimeError("authored interrupted shard")
        return original(snapshot, *args, **kwargs)

    monkeypatch.setattr(batch, "build_tubelex_index", interrupt)
    monkeypatch.setattr(batch, "_retire_partial", partial(batch._retire_partial, trash=output.parent / "Trash"))
    with pytest.raises(RuntimeError, match="interrupted"):
        batch.build_tubelex_collection(snapshots, base, output)
    assert not (output / "collection.private.json").exists()
    with pytest.raises(DataError):
        batch.TubelexCollectionReader(output)
    first = next((output / "parts").glob("*/index/citations.private.sqlite3"))
    digest, modified = sha256_file(first), first.stat().st_mtime_ns
    complete = batch.build_tubelex_collection(snapshots, base, output)
    assert calls == [snapshots[0], snapshots[1], snapshots[1], snapshots[2]]
    assert (sha256_file(first), first.stat().st_mtime_ns) == (digest, modified)
    assert not list((output / "parts").glob(".partial-*"))
    assert batch.verify_tubelex_collection(output, base_artifact=base, deep=True)["shards"] == 3
    monkeypatch.setattr(batch, "build_tubelex_index", lambda *a, **k: pytest.fail("rebuilt completed plan"))
    monkeypatch.setattr(batch, "verify_tubelex_index", lambda *a, **k: pytest.fail("reparsed sealed citation export"))
    assert batch.build_tubelex_collection(snapshots, base, output) == complete


def test_combined_search_limits_connections_and_preserves_deterministic_order(collection_inputs):
    snapshots, base, output = collection_inputs
    batch.build_tubelex_collection(snapshots, base, output)
    with batch.TubelexCollectionReader(output, max_open_shards=1) as reader:
        results = reader.search("今日は")
        assert [r["native_id"].split(":")[0] for r in results] == ["abcdefghijk", "lmnopqrstuv", "0123456789_"]
        assert len(reader.readers) == 1
        assert reader.last_search_stats["decoded_chunks"] == 3
        assert len(reader.search("今日は", limit=2)) == 2
        assert reader.search("美術館")[0]["native_id"].startswith("0123456789_:")
    with pytest.raises(DataError, match="closed"):
        reader.search("今日は")


def test_warm_absent_literals_skip_connections_using_bounded_filter_cache(collection_inputs, monkeypatch):
    snapshots, base, output = collection_inputs
    batch.build_tubelex_collection(snapshots, base, output)
    with batch.TubelexCollectionReader(output, max_open_shards=1, max_filter_bytes=1024) as reader:
        assert reader.search("不存在ZZZ404") == []
        assert len(reader.filters) == 3 and reader.filter_bytes <= 1024
        monkeypatch.setattr(batch, "TubelexReader", lambda *a, **k: pytest.fail("opened rejected shard"))
        assert reader.search("不存在ZZZ404") == []
        assert reader.last_search_stats["decoded_chunks"] == 0
        assert reader.last_search_stats["global_literal_rejections"] == 3


@pytest.mark.parametrize("selection", ["first", "diverse"])
def test_combined_work_budget_discards_earlier_shard_results_and_reader_recovers(collection_inputs, selection):
    snapshots, base, output = collection_inputs
    batch.build_tubelex_collection(snapshots, base, output)
    with batch.TubelexCollectionReader(output, max_decoded_chunks=1) as reader:
        with pytest.raises(QueryWorkLimitExceeded):
            reader.search("今日は", selection=selection)
        assert {key: reader.last_search_stats[key] for key in
                ("decoded_chunks", "decoded_characters", "outcome", "results")} == {
                    "decoded_chunks": 1, "decoded_characters": 12, "outcome": "error", "results": 0}
        assert reader.search("美術館", selection=selection)


def test_combined_deadline_is_shared_and_partial_results_are_discarded(collection_inputs, monkeypatch):
    snapshots, base, output = collection_inputs
    batch.build_tubelex_collection(snapshots, base, output)
    original = batch._search_database
    calls = []

    def expire(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            kwargs["budget"].deadline = 0
        return original(*args, **kwargs)

    monkeypatch.setattr(batch, "_search_database", expire)
    with batch.TubelexCollectionReader(output) as reader:
        with pytest.raises(QueryBudgetExceeded):
            reader.search("今日は")
        assert reader.last_search_stats["results"] == 0


def test_collection_cannot_resume_a_changed_plan_or_duplicate_video(collection_inputs):
    snapshots, base, output = collection_inputs
    batch.build_tubelex_collection(snapshots, base, output)
    with pytest.raises(DataError, match="plan changed"):
        batch.build_tubelex_collection(snapshots, base, output, pause_ms=900)
    with pytest.raises(DataError, match="duplicate videos"):
        batch.build_tubelex_collection([snapshots[0], snapshots[0]], base, output.parent / "other")


def test_collection_reader_checks_the_base_once_before_search(collection_inputs):
    snapshots, base, output = collection_inputs
    batch.build_tubelex_collection(snapshots, base, output)
    other = output.parent / "different-base.zip"
    other.write_bytes(b"different release")
    with pytest.raises(DataError, match="different base"):
        batch.TubelexCollectionReader(output, base_artifact=other)
    with batch.TubelexCollectionReader(output, base_artifact=base) as reader:
        assert reader.search("美術館")


def test_batch_nonfinite_options_fail_before_creating_output(collection_inputs):
    snapshots, base, output = collection_inputs
    with pytest.raises(DataError, match="nonfinite"):
        batch.build_tubelex_collection(snapshots, base, output, sat_threshold=float("nan"))
    assert not output.exists()


def test_collection_verification_detects_corrupt_receipts_and_shards(collection_inputs):
    snapshots, base, output = collection_inputs
    batch.build_tubelex_collection(snapshots, base, output)
    manifest = read_json(output / "collection.private.json")
    manifest["shards"][0]["build_id"] = "wrong"
    (output / "collection.private.json").write_bytes(canonical_json(manifest))
    with pytest.raises(DataError, match="receipt|plan"):
        batch.verify_tubelex_collection(output)
    with pytest.raises(DataError, match="identity|plan"):
        batch.TubelexCollectionReader(output)


@pytest.mark.parametrize("budget", [0, -1, True, 1.5, "1", 1000001])
def test_decoded_work_budget_requires_a_bounded_integer_before_open(budget):
    with pytest.raises(DataError, match="chunk budget"):
        TubelexReader(Path("/does/not/exist"), max_decoded_chunks=budget)


def test_cli_build_verify_and_search_collection(collection_inputs, capsys):
    snapshots, base, output = collection_inputs
    args = ["build-tubelex-batch", "--base-artifact", str(base), "--output", str(output)]
    for path in snapshots:
        args.extend(["--snapshot", str(path)])
    assert main(args) == 0
    capsys.readouterr()
    assert main(["verify-tubelex-collection", "--collection", str(output), "--deep"]) == 0
    assert json.loads(capsys.readouterr().out)["shards"] == 3
    assert main(["search-tubelex", "--collection", str(output), "--query", "美術館", "--stats"]) == 0
    captured = capsys.readouterr()
    assert len(json.loads(captured.out)) == 1
    assert json.loads(captured.err)["decoded_chunks"] == 1


def test_resume_normalizes_cli_defaults_and_snapshot_directory_aliases(collection_inputs, monkeypatch):
    snapshots, base, output = collection_inputs
    batch.build_tubelex_collection(snapshots, base, output)
    monkeypatch.setattr(batch, "build_tubelex_index", lambda *a, **k: pytest.fail("rebuilt equivalent plan"))
    arguments = ["build-tubelex-batch", "--base-artifact", str(base), "--output", str(output)]
    for path in snapshots:
        arguments.extend(["--snapshot", str(path.parent)])
    assert main(arguments) == 0


def test_resume_rejects_a_valid_shard_built_with_unplanned_settings(collection_inputs, monkeypatch):
    snapshots, base, output = collection_inputs
    snapshots = snapshots[:1]
    original = batch.build_tubelex_index
    monkeypatch.setattr(batch, "_retire_partial", partial(batch._retire_partial, trash=output.parent / "Trash"))

    def fail(*args, **kwargs):
        raise RuntimeError("stop before first shard")

    monkeypatch.setattr(batch, "build_tubelex_index", fail)
    with pytest.raises(RuntimeError):
        batch.build_tubelex_collection(snapshots, base, output)
    part = output / read_json(output / "plan.json")["shards"][0]["part"]
    part.mkdir()
    original(snapshots[0], base, part / "index", part / "references", pause_ms=900)
    monkeypatch.setattr(batch, "build_tubelex_index", lambda *a, **k: pytest.fail("built after mismatched shard"))
    with pytest.raises(DataError, match="plan|options"):
        batch.build_tubelex_collection(snapshots, base, output)
    assert not (output / "collection.private.json").exists()


def test_transferred_collection_rejects_a_rebound_receipt_with_wrong_options(collection_inputs):
    snapshots, base, output = collection_inputs
    batch.build_tubelex_collection(snapshots[:1], base, output)
    other = output.parent / "wrong-shard"
    other.mkdir()
    batch.build_tubelex_index(snapshots[0], base, other / "index", other / "references", pause_ms=900)
    document = read_json(output / "collection.private.json")
    wrong = read_json(other / "index/manifest.private.json")
    document["shards"][0].update({"build_id": wrong["build_id"], "index_sha256": wrong["index_sha256"]})
    (output / "collection.private.json").write_bytes(canonical_json(document))
    # The individual replacement is valid; the collection advertised 800ms.
    with pytest.raises(DataError, match="plan|options"):
        batch.TubelexCollectionReader(output)


@pytest.mark.parametrize("damage", ["duplicate", "count", "part", "pause", "version"])
def test_collection_metadata_rejects_invalid_plans_before_opening_shards(collection_inputs, damage):
    from manabi_sentence_db.serialization import digest_json

    snapshots, base, output = collection_inputs
    batch.build_tubelex_collection(snapshots, base, output)
    plan = read_json(output / "plan.json")
    document = read_json(output / "collection.private.json")
    if damage == "duplicate":
        plan["shards"][1] = plan["shards"][0]
        document["shards"][1] = document["shards"][0]
    elif damage == "count":
        document["shards"][0]["references"] = True
    elif damage == "part":
        plan["shards"][0]["part"] = document["shards"][0]["part"] = "parts/alias"
    elif damage == "pause":
        plan["profile"]["settings"]["pause_ms"] = 900
    else:
        plan["schema_version"] = document["schema_version"] = 1
    document["plan_sha256"] = digest_json(plan)
    (output / "plan.json").write_bytes(canonical_json(plan))
    (output / "collection.private.json").write_bytes(canonical_json(document))
    with pytest.raises(DataError):
        batch.TubelexCollectionReader(output)


def _fake_character_models(tmp_path, monkeypatch):
    from manabi_sentence_db import tubelex_boundaries

    models = []
    for number in range(2):
        directory = tmp_path / f"model-{number}"
        directory.mkdir()
        (directory / "punct.int8.onnx").write_bytes(f"authored fake weights {number}".encode())
        (directory / "vocab.txt").write_text("[CLS]\n[SEP]\n[UNK]\n")
        models.append(directory)
    monkeypatch.setattr(batch, "version", lambda _: "test")
    monkeypatch.setattr(tubelex_boundaries, "version", lambda _: "test")
    monkeypatch.setattr(tubelex_boundaries, "local_japanese_character_model", lambda path, threshold: (
        lambda text: [text], tubelex_boundaries.describe_japanese_character_model(path, threshold=threshold)[2],
    ))
    return models


@pytest.mark.parametrize("damage", ["weights", "threshold"])
def test_wrong_model_profile_is_rejected_before_a_shard_is_installed(collection_inputs, monkeypatch, damage):
    snapshots, base, output = collection_inputs
    a, b = _fake_character_models(output.parent, monkeypatch)
    original = batch.build_tubelex_index

    def wrong(*args, **options):
        if damage == "weights":
            options["ja_punct_model"] = b
        else:
            options["ja_punct_threshold"] = .8
        return original(*args, **options)

    monkeypatch.setattr(batch, "build_tubelex_index", wrong)
    monkeypatch.setattr(batch, "_retire_partial", partial(batch._retire_partial, trash=output.parent / "Trash"))
    with pytest.raises(DataError, match="plan"):
        batch.build_tubelex_collection(snapshots[:1], base, output, ja_punct_model=a)
    assert not (output / "collection.private.json").exists()
    assert not list((output / "parts").iterdir())


def test_model_profile_ignores_prediction_cache_location(collection_inputs, monkeypatch):
    _, _, output = collection_inputs
    model, _ = _fake_character_models(output.parent, monkeypatch)
    assert batch._profile({"ja_punct_model": model, "boundary_cache": Path("one")}) == batch._profile({
        "ja_punct_model": model, "boundary_cache": Path("two"),
    })


def test_resume_rejects_a_copied_shard_from_another_processing_profile(collection_inputs, monkeypatch):
    snapshots, base, output = collection_inputs
    snapshots = snapshots[:1]
    other = output.parent / "other-collection"
    original = batch._profile

    def different(options):
        profile = original(options)
        profile["runtimes"]["authored-test-runtime"] = "different"
        return profile

    with monkeypatch.context() as context:
        context.setattr(batch, "_profile", different)
        batch.build_tubelex_collection(snapshots, base, other)

    def interrupt(*args, **kwargs):
        raise RuntimeError("stop before first shard")

    with monkeypatch.context() as context:
        context.setattr(batch, "build_tubelex_index", interrupt)
        context.setattr(batch, "_retire_partial", partial(batch._retire_partial, trash=output.parent / "Trash"))
        with pytest.raises(RuntimeError):
            batch.build_tubelex_collection(snapshots, base, output)
    part = read_json(output / "plan.json")["shards"][0]["part"]
    shutil.copytree(other / part, output / part)
    with pytest.raises(DataError, match="plan profile"):
        batch.build_tubelex_collection(snapshots, base, output)
    assert not (output / "collection.private.json").exists()


@pytest.mark.parametrize("damage", ["file", "journal"])
def test_fast_resume_detects_changed_sealed_files_and_pending_sqlite_state(collection_inputs, damage):
    snapshots, base, output = collection_inputs
    batch.build_tubelex_collection(snapshots[:1], base, output)
    part = output / read_json(output / "plan.json")["shards"][0]["part"]
    if damage == "file":
        path = part / "references/references.jsonl.zst"
        with path.open("ab") as stream:
            stream.write(b"authored damage")
    else:
        (part / "index/citations.private.sqlite3-journal").write_bytes(b"authored pending journal")
    with pytest.raises(DataError, match="changed|closed"):
        batch.build_tubelex_collection(snapshots[:1], base, output)


def test_diverse_selection_reaches_later_shards_without_changing_default(collection_inputs):
    snapshots, base, output = collection_inputs
    batch.build_tubelex_collection(snapshots, base, output)
    with batch.TubelexCollectionReader(output) as reader:
        assert reader.search("今日は", limit=1)[0]["native_id"].startswith("abcdefghijk:")
        diverse = reader.search("今日は", limit=2, selection="diverse")
        assert len({record["native_id"].split(":")[0] for record in diverse}) == 2
        assert reader.last_search_stats["shards_examined"] == 3
        reader.document["shards"].reverse()
        assert reader.search("今日は", limit=2, selection="diverse") == diverse
        with pytest.raises(DataError, match="selection"):
            reader.search("今日は", selection="random")


def test_diversity_pool_is_bounded_and_round_robins_videos():
    pool = batch._DiverseReferences("共通", 5)
    for number in range(1000):
        video = f"{number:011}"
        for clip in range(8):
            pool.add({"id": f"r{number}-{clip}", "native_id": f"{video}:{clip}:999"})
        assert len(pool.heap) <= 5 and len(pool.ids) <= 5 and len(pool.counts) <= 5
    assert len({r["native_id"].split(":")[0] for r in pool.results()}) == 5


def test_diverse_selection_does_not_let_one_video_fill_a_shard_budget(collection_inputs):
    from manabi_sentence_db.serialization import digest_json, parse_json, write_json
    from manabi_sentence_db.tubelex import _compress_private, _read_compressed

    snapshots, base, output = collection_inputs
    manifest = read_json(snapshots[0])
    path = snapshots[0].parent / manifest["entries"][0]["path"]
    caption = parse_json(_read_compressed(path))
    caption["vtt"] = "WEBVTT\n\n" + "\n\n".join(
        f"00:{n*4:02}.000 --> 00:{n*4+3:02}.000\n今日は図書館で{n}番の本を読みます。"
        for n in range(12))
    # Replace only task-owned authored fixtures and rebind their manifest.
    retired = path.with_suffix(".original")
    path.rename(retired)
    _compress_private(path, caption)
    manifest["entries"][0]["sha256"] = sha256_file(path)
    manifest["snapshot_id"] = "tubelex_" + digest_json({k:v for k,v in manifest.items() if k != "snapshot_id"})[:32]
    write_json(snapshots[0], manifest)
    batch.build_tubelex_collection(snapshots, base, output)
    with batch.TubelexCollectionReader(output) as reader:
        assert {r["native_id"].split(":")[0] for r in reader.search("今日は", limit=3)} == {"abcdefghijk"}
        result = reader.search("今日は", limit=3, selection="diverse")
        assert len({r["native_id"].split(":")[0] for r in result}) == 3
