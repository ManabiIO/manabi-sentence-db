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
    monkeypatch.setattr(inventory, "snapshot_pages", lambda *a, **kw: pages)
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
    monkeypatch.setattr(inventory, "snapshot_pages", lambda *args, **kwargs: iter(pages))
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
    assert main(["select-wikimedia", "--metadata-cache", str(cache), "--output",
                 str(tmp_path / "selected"), "--per-topic", "0", "--general", "2"]) == 0
    assert len(read_json(tmp_path / "selected" / "selection.json")["page_ids"]) == 2


def test_source_mutation_during_indexing_cannot_publish_completion(tmp_path, monkeypatch):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    original = inventory.snapshot_pages

    def changed(*args, **kwargs):
        yield from original(*args, **kwargs)
        with (snapshot.parent / "synthetic.xml").open("a") as stream:
            stream.write(" ")

    monkeypatch.setattr(inventory, "snapshot_pages", changed)
    with pytest.raises(DataError, match="snapshot changed"):
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
    monkeypatch.setattr(inventory, "snapshot_pages", lambda *a, **kw: iter(pages))
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
