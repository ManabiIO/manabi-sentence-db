import json
import sqlite3
from contextlib import closing

import pytest

from manabi_sentence_db import wikimedia_inventory as inventory
from manabi_sentence_db.cli import main
from manabi_sentence_db.demo import create_demo_snapshot
from manabi_sentence_db.serialization import DataError, read_json
from manabi_sentence_db.wikimedia_selection import sample_pages, select_wikimedia_documents


@pytest.mark.parametrize("budget", [True, False, 0, -1, 8191, 8192.0, "8192"])
def test_invalid_storage_budget_does_not_verify_snapshot_or_create_output(tmp_path, monkeypatch, budget):
    monkeypatch.setattr(inventory, "verify_snapshot", lambda *_: pytest.fail("raw snapshot read"))
    with pytest.raises(DataError, match="budget"):
        inventory.index_wikimedia_metadata(tmp_path / "absent", tmp_path / "output",
                                           max_index_bytes=budget)
    assert not (tmp_path / "output").exists()


def test_storage_cap_stops_growth_without_publishing_completion(tmp_path, monkeypatch):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    pages = ({"native_id": str(i), "revision_id": str(i), "title": "長い題名" * 100,
              "text": "普通の本文です。"} for i in range(1, 501))
    monkeypatch.setattr(inventory, "_file_pages", lambda *a, **kw: pages)
    output = tmp_path / "limited"
    with pytest.raises(DataError, match="storage budget exhausted"):
        inventory.index_wikimedia_metadata(snapshot, output, max_index_bytes=10_000)
    assert (output / "metadata.sqlite").stat().st_size <= 8192
    assert not (output / "manifest.json").exists()
    with pytest.raises(FileNotFoundError):
        inventory.select_wikimedia_metadata(output, tmp_path / "invalid-selection")


def test_cli_budget_preserves_selection_and_is_recorded(tmp_path):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    capped = tmp_path / "capped"
    assert main(["index-wikimedia", "--snapshot", str(snapshot), "--output", str(capped),
                 "--max-index-bytes", "65536"]) == 0
    assert read_json(capped / "manifest.json")["max_index_bytes"] == 65536
    uncapped = inventory.index_wikimedia_metadata(snapshot, tmp_path / "uncapped")
    assert read_json(uncapped / "manifest.json")["max_index_bytes"] is None
    first = inventory.select_wikimedia_metadata(capped, tmp_path / "one", per_topic=0, general=2)
    second = inventory.select_wikimedia_metadata(uncapped, tmp_path / "two", per_topic=0, general=2)
    assert read_json(first) == read_json(second)


def test_indexed_selection_matches_direct_selection_without_rereading_dump(tmp_path, monkeypatch):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    direct = select_wikimedia_documents(snapshot, tmp_path / "direct", per_topic=0, general=2)
    cache = inventory.index_wikimedia_metadata(snapshot, tmp_path / "metadata")
    manifest = read_json(cache / "manifest.json")
    assert manifest["records"] == 2
    assert manifest["snapshot_id"] == read_json(direct)["snapshot_id"]
    assert manifest["contains_article_bodies"] is False
    with closing(sqlite3.connect(cache / "metadata.sqlite")) as db:
        columns = {r[1] for r in db.execute("PRAGMA table_info(pages)")}
        assert columns == {"native_id", "fingerprint", "revision_id", "title", "source_characters", "categories"}

    def forbidden(*args, **kwargs):
        pytest.fail("Cached selection reopened the raw snapshot")

    monkeypatch.setattr(inventory, "verify_snapshot", forbidden)
    selected = inventory.select_wikimedia_metadata(cache, tmp_path / "cached", per_topic=0, general=2)
    assert read_json(selected) == read_json(direct)
    assert main(["select-wikimedia", "--metadata-cache", str(cache), "--output",
                 str(tmp_path / "cli"), "--per-topic", "0", "--general", "1",
                 "--exclude-selection", str(selected)]) == 2


def test_exclusions_fill_quota_and_cannot_cross_snapshot_or_source(tmp_path):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    cache = inventory.index_wikimedia_metadata(snapshot, tmp_path / "metadata")
    first = inventory.select_wikimedia_metadata(cache, tmp_path / "first", per_topic=0, general=1)
    second = inventory.select_wikimedia_metadata(cache, tmp_path / "second", per_topic=0, general=1,
                                                 exclude_selections=[first])
    assert not set(read_json(first)["page_ids"]) & set(read_json(second)["page_ids"])
    report = read_json(second.parent / "selection-report.json")
    assert report["counts"]["previously-selected"] == 1
    assert report["excluded_page_ids"] == 1
    value = read_json(first)
    for field in ("snapshot_id", "source_id"):
        bad = tmp_path / f"bad-{field}.json"
        bad.write_text(json.dumps(value | {field: "different"}))
        with pytest.raises(DataError, match="match"):
            inventory.select_wikimedia_metadata(cache, tmp_path / f"out-{field}",
                per_topic=0, general=1, exclude_selections=[bad])


def test_cache_corruption_interruption_and_aliases_fail_closed(tmp_path, monkeypatch):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    cache = inventory.index_wikimedia_metadata(snapshot, tmp_path / "metadata")
    alias = tmp_path / "alias"
    alias.symlink_to(cache, target_is_directory=True)
    with pytest.raises(DataError, match="symlink"):
        inventory.select_wikimedia_metadata(alias, tmp_path / "alias-out")
    (cache / "metadata.sqlite").write_bytes(b"corrupt")
    with pytest.raises(DataError, match="checksum"):
        inventory.select_wikimedia_metadata(cache, tmp_path / "corrupt-out")
    assert not (tmp_path / "corrupt-out").exists()

    def interrupted(message):
        raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError, match="interrupted"):
        inventory.index_wikimedia_metadata(snapshot, tmp_path / "interrupted", progress=interrupted)
    assert not (tmp_path / "interrupted" / "manifest.json").exists()
    with pytest.raises(DataError, match="fresh"):
        inventory.index_wikimedia_metadata(snapshot, cache)


def test_metadata_routing_retains_seed_dependence_and_conflicting_duplicate_check(tmp_path, monkeypatch):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    pages = [{"native_id": str(i), "revision_id": str(i), "title": f"記事{i}",
              "text": "普通の本文です。[[Category:健康]][[Category:食文化]]"} for i in range(1, 31)]
    monkeypatch.setattr(inventory, "_file_pages", lambda *args, **kwargs: iter(pages))
    cache = inventory.index_wikimedia_metadata(snapshot, tmp_path / "metadata")
    for seed in ("", "new-seed"):
        expected, _ = sample_pages(pages, snapshot_id=read_json(cache / "manifest.json")["snapshot_id"],
                                   per_topic=2, general=0, seed=seed)
        path = inventory.select_wikimedia_metadata(cache, tmp_path / ("result" + seed),
                                                     per_topic=2, general=0, seed=seed)
        assert read_json(path)["page_ids"] == [r["native_id"] for r in expected]
    pages.append(pages[0] | {"text": "変わった文章です。"})
    with pytest.raises(DataError, match="Conflicting"):
        inventory.index_wikimedia_metadata(snapshot, tmp_path / "conflict")
    assert not (tmp_path / "conflict" / "manifest.json").exists()


def test_cli_indexes_then_selects_and_emits_normal_snapshot_bound_allowlist(tmp_path, capsys):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    cache = tmp_path / "new-parent" / "metadata"
    assert main(["index-wikimedia", "--snapshot", str(snapshot), "--output", str(cache)]) == 0
    assert main(["index-wikimedia", "--snapshot", str(snapshot), "--output", str(cache),
                 "--resume"]) == 2
    assert "completed metadata cache" in capsys.readouterr().err
    assert main(["select-wikimedia", "--metadata-cache", str(cache), "--output",
                 str(tmp_path / "selected"), "--per-topic", "0", "--general", "2"]) == 0
    assert len(read_json(tmp_path / "selected" / "selection.json")["page_ids"]) == 2


def test_source_mutation_during_indexing_cannot_publish_completion(tmp_path, monkeypatch):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    original = inventory._file_pages

    def changed(path, role):
        yield from original(path, role)
        with path.open("a") as stream:
            stream.write(" ")

    monkeypatch.setattr(inventory, "_file_pages", changed)
    with pytest.raises(DataError, match="snapshot inputs changed"):
        inventory.index_wikimedia_metadata(snapshot, tmp_path / "metadata")
    assert not (tmp_path / "metadata" / "manifest.json").exists()


def test_metadata_mutation_after_hash_check_cannot_publish_selection(tmp_path, monkeypatch):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    cache = inventory.index_wikimedia_metadata(snapshot, tmp_path / "metadata")
    original = inventory._read_cache

    def changed(*args):
        result = original(*args)
        with (cache / "metadata.sqlite").open("ab") as stream:
            stream.write(b" ")
        return result

    monkeypatch.setattr(inventory, "_read_cache", changed)
    with pytest.raises(DataError, match="metadata changed"):
        inventory.select_wikimedia_metadata(cache, tmp_path / "selected", per_topic=0, general=1)
    assert not (tmp_path / "selected" / "selection.json").exists()


@pytest.mark.parametrize("per_topic,general,seed,excluded", [
    (0, 4, "", ()), (2, 3, "", ("1", "11")),
    (3, 0, "next", ("2", "20")), (1, 2, "next", ()),
])
def test_cached_ordered_selection_matches_direct_without_identity_ledger(
        tmp_path, monkeypatch, per_topic, general, seed, excluded):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    pages = [{"native_id": str(i), "revision_id": str(i), "title": f"記事{i}",
              "text": "普通の本文です。" + (
                  "[[Category:健康]][[Category:食文化]]" if i % 2 else "")}
             for i in range(1, 31)]
    monkeypatch.setattr(inventory, "_file_pages", lambda *a, **kw: iter(pages))
    cache = inventory.index_wikimedia_metadata(snapshot, tmp_path / "metadata")
    manifest = read_json(cache / "manifest.json")
    expected, counts = sample_pages(pages, snapshot_id=manifest["snapshot_id"],
        per_topic=per_topic, general=general, seed=seed, exclude_ids=frozenset(excluded))
    exclusions = []
    if excluded:
        path = tmp_path / "excluded.json"
        path.write_text(json.dumps({"schema_version": 1, "source_id": manifest["source_id"],
            "snapshot_id": manifest["snapshot_id"], "page_ids": list(excluded)}))
        exclusions.append(path)
    connect = sqlite3.connect

    def existing_only(filename, *args, **kwargs):
        assert filename != "", "Cached selection opened a temporary identity ledger"
        return connect(filename, *args, **kwargs)

    monkeypatch.setattr(inventory.sqlite3, "connect", existing_only)
    selected = inventory.select_wikimedia_metadata(cache, tmp_path / "selected",
        per_topic=per_topic, general=general, seed=seed, exclude_selections=exclusions)
    report = read_json(selected.parent / "selection-report.json")
    assert report["articles"] == expected
    assert report["counts"] == counts
    assert read_json(selected)["page_ids"] == [r["native_id"] for r in expected]


@pytest.mark.parametrize("identities", [("1", "1"), ("2", "1")])
def test_invalid_cached_order_cannot_publish_selection(tmp_path, monkeypatch, identities):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    cache = inventory.index_wikimedia_metadata(snapshot, tmp_path / "metadata")
    original = inventory._rows

    def invalid_rows(db):
        rows = {row["native_id"]: row for row in original(db)}
        first = next(iter(rows.values()))
        return iter(first | {"native_id": identity} for identity in identities)

    monkeypatch.setattr(inventory, "_rows", invalid_rows)
    output = tmp_path / "selected"
    with pytest.raises(DataError, match="strictly increase"):
        inventory.select_wikimedia_metadata(cache, output, per_topic=0, general=1)
    assert not (output / "selection.json").exists()
    assert not (output / "selection-report.json").exists()


def test_metadata_id_order_uses_existing_primary_key_without_temporary_sort(tmp_path):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    cache = inventory.index_wikimedia_metadata(snapshot, tmp_path / "metadata")
    with closing(sqlite3.connect(cache / "metadata.sqlite")) as db:
        statements = []
        db.set_trace_callback(statements.append)
        list(inventory._rows(db))
        db.set_trace_callback(None)
        query, = statements
        plan = db.execute("EXPLAIN QUERY PLAN " + query).fetchall()
        assert not any("TEMP B-TREE" in row[3].upper() for row in plan), plan


def _synthetic_pages(count):
    return [{"native_id": str(index), "revision_id": str(index), "title": f"記事{index}",
             "text": "普通の本文です。[[Category:健康]]"}
            for index in range(1, count + 1)]


def test_resume_rolls_back_incomplete_batch_replays_only_current_shard_prefix(tmp_path, monkeypatch):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    pages = _synthetic_pages(5)
    parsed = []

    def file_pages(*_):
        for page in pages:
            parsed.append(page["native_id"])
            yield page

    monkeypatch.setattr(inventory, "_file_pages", file_pages)
    monkeypatch.setattr(inventory, "CHECKPOINT_BATCH_PAGES", 2)
    original = inventory.page_metadata
    failed = False

    def interrupt_inside_batch(page, counts):
        nonlocal failed
        if page["native_id"] == "4" and not failed:
            failed = True
            raise RuntimeError("interrupted while staging batch")
        return original(page, counts)

    monkeypatch.setattr(inventory, "page_metadata", interrupt_inside_batch)
    output = tmp_path / "interrupted-batch"
    with pytest.raises(RuntimeError, match="staging batch"):
        inventory.index_wikimedia_metadata(snapshot, output)
    with sqlite3.connect(output / "metadata.sqlite") as db:
        assert db.execute("SELECT count(*) FROM pages").fetchone() == (2,)
        assert db.execute("SELECT file_index,page_ordinal FROM checkpoint").fetchone() == (0, 2)

    monkeypatch.setattr(inventory, "page_metadata", original)
    inventory.index_wikimedia_metadata(snapshot, output, resume=True)
    assert parsed == ["1", "2", "3", "4", "1", "2", "3", "4", "5"]
    manifest = read_json(output / "manifest.json")
    assert manifest["counts"]["pages_seen"] == manifest["records"] == 5


def test_resume_after_checkpoint_commit_and_skip_completed_shards(tmp_path, monkeypatch):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    entries = [{"path": "shard-a.xml", "role": "mediawiki-xml"},
               {"path": "shard-b.xml", "role": "mediawiki-xml"}]
    monkeypatch.setattr(inventory, "_content_entries", lambda _: entries)
    pages_by_shard = {"shard-a.xml": _synthetic_pages(2),
                      "shard-b.xml": _synthetic_pages(2)}
    for offset, pages in ((0, pages_by_shard["shard-a.xml"]), (2, pages_by_shard["shard-b.xml"])):
        for index, page in enumerate(pages, 1):
            identity = str(index + offset)
            page.update(native_id=identity, revision_id=identity, title=f"記事{identity}")
    parsed = []

    def file_pages(path, _role):
        for page in pages_by_shard[path.name]:
            parsed.append(page["native_id"])
            yield page

    monkeypatch.setattr(inventory, "_file_pages", file_pages)
    monkeypatch.setattr(inventory, "CHECKPOINT_BATCH_PAGES", 2)
    output = tmp_path / "after-commit"

    def crash_after_commit(message):
        if message == "Metadata checkpoint file=1/2 page=2 records=2":
            raise RuntimeError("crash after durable checkpoint")

    with pytest.raises(RuntimeError, match="durable checkpoint"):
        inventory.index_wikimedia_metadata(snapshot, output, progress=crash_after_commit)
    with sqlite3.connect(output / "metadata.sqlite") as db:
        assert db.execute("SELECT count(*) FROM pages").fetchone() == (2,)
        assert db.execute("SELECT file_index,page_ordinal FROM checkpoint").fetchone() == (0, 2)

    def stop_before_second_shard(message):
        if message == "Metadata indexing shard-b.xml":
            raise RuntimeError("stop at next shard")

    with pytest.raises(RuntimeError, match="next shard"):
        inventory.index_wikimedia_metadata(snapshot, output, progress=stop_before_second_shard,
                                           resume=True)
    assert parsed == ["1", "2", "1", "2"]
    with sqlite3.connect(output / "metadata.sqlite") as db:
        assert db.execute("SELECT file_index,page_ordinal FROM checkpoint").fetchone() == (1, 0)

    parsed_before_resume = len(parsed)
    inventory.index_wikimedia_metadata(snapshot, output, resume=True)
    assert parsed[parsed_before_resume:] == ["3", "4"]
    assert parsed == ["1", "2", "1", "2", "3", "4"]
    manifest = read_json(output / "manifest.json")
    assert manifest["counts"]["pages_seen"] == manifest["records"] == 4
    assert manifest["counts"].get("exact_duplicates", 0) == 0
    with pytest.raises(DataError, match="completed metadata cache"):
        inventory.index_wikimedia_metadata(snapshot, output, resume=True)


def test_resume_rejects_manifest_producer_and_checkpoint_format_mismatches(tmp_path, monkeypatch):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    pages = _synthetic_pages(2)
    monkeypatch.setattr(inventory, "_file_pages", lambda *_: iter(pages))
    output = tmp_path / "checkpoint"

    def interrupt(_):
        raise RuntimeError("stop")

    with pytest.raises(RuntimeError):
        inventory.index_wikimedia_metadata(snapshot, output, progress=interrupt)
    manifest = read_json(snapshot)
    manifest["retrieved_at"] = "2026-11-24T07:01:00+00:00"
    snapshot.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DataError, match="identity mismatch"):
        inventory.index_wikimedia_metadata(snapshot, output, resume=True)

    restored = create_demo_snapshot(tmp_path / "restored")
    other = tmp_path / "other-checkpoint"
    with pytest.raises(RuntimeError):
        inventory.index_wikimedia_metadata(restored, other, progress=interrupt)
    monkeypatch.setattr(inventory, "_implementation_sha256", lambda: "0" * 64)
    with pytest.raises(DataError, match="producer identity mismatch"):
        inventory.index_wikimedia_metadata(restored, other, resume=True)

    monkeypatch.undo()
    legacy = tmp_path / "old-incomplete"
    legacy.mkdir()
    (legacy / "metadata.sqlite").write_bytes(b"old incomplete index")
    with pytest.raises(DataError, match="no resumable checkpoint"):
        inventory.index_wikimedia_metadata(restored, legacy, resume=True)


def test_mutated_then_restored_shard_cannot_commit_or_resume_wrong_rows(tmp_path, monkeypatch):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    manifest = read_json(snapshot)
    shard = snapshot.parent / manifest["files"][0]["path"]
    original_bytes = shard.read_bytes()
    original_signature = inventory._input_signature(shard)
    original_pages = _synthetic_pages(2)
    monkeypatch.setattr(inventory, "CHECKPOINT_BATCH_PAGES", 2)

    def changed_then_restored(path, _role):
        path.write_bytes(original_bytes + b" changed during parse")
        yield original_pages[0]
        path.write_bytes(original_bytes)
        yield original_pages[1]

    monkeypatch.setattr(inventory, "_file_pages", changed_then_restored)
    output = tmp_path / "mutated-then-restored"
    with pytest.raises(DataError, match="inputs changed since verified checkpoint"):
        inventory.index_wikimedia_metadata(snapshot, output)
    assert shard.read_bytes() == original_bytes
    assert inventory._input_signature(shard) != original_signature
    inventory.verify_snapshot(snapshot)
    with sqlite3.connect(output / "metadata.sqlite") as db:
        assert db.execute("SELECT count(*) FROM pages").fetchone() == (0,)
        assert db.execute("SELECT file_index,page_ordinal FROM checkpoint").fetchone() == (0, 0)
    with pytest.raises(DataError, match="checkpoint input or producer identity mismatch"):
        inventory.index_wikimedia_metadata(snapshot, output, resume=True)
    assert not (output / "manifest.json").exists()


@pytest.mark.parametrize("name", [
    "metadata.sqlite", "metadata.sqlite-journal", ".manifest.json.part", ".index.lock",
])
@pytest.mark.parametrize("alias_kind", ["symlink", "hardlink"])
def test_resume_rejects_symlink_and_hardlink_output_aliases(tmp_path, name, alias_kind):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    output = tmp_path / (name.replace("/", "-") + "-" + alias_kind)

    def interrupt(_message):
        raise RuntimeError("stop before parse")

    with pytest.raises(RuntimeError):
        inventory.index_wikimedia_metadata(snapshot, output, progress=interrupt)
    target = tmp_path / f"external-{name.replace('/', '-')}-{alias_kind}"
    target.write_bytes(b"external target must remain unchanged")
    alias = output / name
    if name in {"metadata.sqlite", ".index.lock"}:
        alias.rename(tmp_path / f"saved-{name.replace('/', '-')}")
    if alias_kind == "symlink":
        alias.symlink_to(target)
    else:
        alias.hardlink_to(target)
    with pytest.raises(DataError, match="regular metadata database|symlink or hardlink alias"):
        inventory.index_wikimedia_metadata(snapshot, output, resume=True)
    assert target.read_bytes() == b"external target must remain unchanged"
