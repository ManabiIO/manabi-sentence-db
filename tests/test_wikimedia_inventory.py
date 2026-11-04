import json
import sqlite3
from contextlib import closing

import pytest

from manabi_sentence_db import wikimedia_inventory as inventory
from manabi_sentence_db.cli import main
from manabi_sentence_db.demo import create_demo_snapshot
from manabi_sentence_db.serialization import DataError, read_json
from manabi_sentence_db.wikimedia_selection import sample_pages, select_wikimedia_documents


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
