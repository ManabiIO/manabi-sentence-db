import sqlite3
from collections import Counter
from itertools import permutations

import pytest

from manabi_sentence_db import wikimedia_selection as selection
from manabi_sentence_db.build import build_corpus, iter_records, verify_build
from manabi_sentence_db.cli import main
from manabi_sentence_db.demo import create_demo_snapshot
from manabi_sentence_db.serialization import DataError, digest_json, read_json
from manabi_sentence_db.snapshot import SnapshotError


def page(identity, category="", *, title=None, text=None):
    return {"native_id": str(identity), "revision_id": str(identity),
            "title": title or f"記事{identity}",
            "text": text or f"本文の文章です。[[Category:{category}]]"}


@pytest.mark.parametrize("title,categories,expected", [
    ("睡眠", ["健康", "睡眠"], "health"),
    ("架空の選手", ["日本の野球選手", "身体運動"], "general"),
    ("架空の歌", ["楽曲", "食文化を題材とした楽曲"], "general"),
    ("架空の企業", ["日本の企業", "健康食品"], "general"),
    ("架空の駅", ["日本の鉄道駅", "鉄道"], "general"),
    ("労働運動", ["労働運動"], "society"),
    ("キリスト教", ["キリスト教"], "general"),
    ("自然数", ["数学"], "science"),
    ("古代史", ["古代の歴史"], "history"),
    ("お菓子の一覧", ["菓子"], "excluded-list"),
    ("曖昧さ回避", [], "excluded-list"),
])
def test_routing_avoids_incidental_subjects_without_excluding_science_history_or_religion(
        title, categories, expected):
    assert selection.classify(title, categories, "0" * 64)[0] == expected


def test_top_k_is_bounded_order_independent_and_seeded():
    pages = [page(i, "健康") for i in range(1, 51)]
    pages += [page(i, "菓子") for i in range(51, 101)]
    pages += [page(i) for i in range(101, 151)]
    forward, counts = selection.sample_pages(iter(pages), snapshot_id="fixture", per_topic=3, general=4)
    reverse, other_counts = selection.sample_pages(reversed(pages), snapshot_id="fixture", per_topic=3, general=4)
    assert forward == reverse and counts == other_counts
    assert Counter(row["topic"] for row in forward) == {"health": 3, "food": 3, "general": 4}
    expected_health = sorted(range(1, 51), key=lambda i: digest_json(
        [selection.POLICY, "fixture", "", str(i)]))[:3]
    assert {row["native_id"] for row in forward if row["topic"] == "health"} == set(map(str, expected_health))
    different, _ = selection.sample_pages(pages, snapshot_id="fixture", per_topic=3, general=4, seed="next")
    assert forward != different
    expanded, _ = selection.sample_pages(pages, snapshot_id="fixture", per_topic=6, general=8)
    assert {row["native_id"] for row in forward} <= {row["native_id"] for row in expanded}
    assert all("text" not in row for row in forward)


def test_duplicates_do_not_consume_quota_or_duplicate_build_ids():
    pages = [page(1), page(1), page(2)]
    rows, counts = selection.sample_pages(pages, snapshot_id="fixture", per_topic=0, general=2)
    assert [row["native_id"] for row in rows] == ["1", "2"]
    assert counts["duplicate-retained-page"] == 1
    with pytest.raises(DataError, match="Conflicting"):
        selection.sample_pages([page(1), page(1, title="違う記事")],
                               snapshot_id="fixture", per_topic=0, general=2)


def test_oversized_pages_and_bad_ids_never_enter_topic_routing(monkeypatch):
    def forbidden(*args):
        pytest.fail("Rejected pages entered category routing")
    monkeypatch.setattr(selection, "classify", forbidden)
    monkeypatch.setattr(selection, "digest_json", forbidden)
    pages = [page(1, text="あ" * (selection.MAX_WIKITEXT_CHARACTERS + 1)), page("bad")]
    rows, counts = selection.sample_pages(pages, snapshot_id="fixture", per_topic=1, general=1)
    assert not rows and counts["page-text-limit"] == counts["invalid-identity"] == 1


@pytest.mark.parametrize("topic,general", [(-1, 2), (True, 2), (1, 1.5), (0, 0), (5000, 1)])
def test_bad_quotas_fail_before_input_verification(tmp_path, monkeypatch, topic, general):
    def forbidden(*args):
        pytest.fail("Invalid quota read a snapshot")
    monkeypatch.setattr(selection, "verify_snapshot", forbidden)
    with pytest.raises(DataError, match="quota"):
        selection.select_wikimedia_documents(tmp_path / "missing", tmp_path / "out",
                                             per_topic=topic, general=general)


def test_cli_selection_build_preserves_snapshot_provenance_and_context(tmp_path, capsys):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    output = tmp_path / "selection"
    assert main(["select-wikimedia", "--snapshot", str(snapshot), "--output", str(output),
                 "--per-topic", "0", "--general", "2", "--progress"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == str(output / "selection.json")
    assert "Metadata scanning" in captured.err
    selected, report = [read_json(output / name) for name in ("selection.json", "selection-report.json")]
    assert selected["page_ids"] == ["1", "2"]
    assert report["selection_sha256"] == digest_json(selected)
    assert report["snapshot_scope"] == "sample"
    build_corpus([snapshot], tmp_path / "build", document_selection=output / "selection.json")
    records = list(iter_records(tmp_path / "build", verify_build(tmp_path / "build")))
    assert len(records) == 2
    assert all(record["snapshot_id"] == selected["snapshot_id"] for record in records)
    assert all(record["license"]["id"] == "CC0-1.0" for record in records)
    assert all("wikimedia-context-gaps-v1" in record["transformations"] for record in records)


def test_corrupt_snapshot_and_output_aliases_are_rejected(tmp_path):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    alias = tmp_path / "manifest-link.json"
    alias.symlink_to(snapshot)
    with pytest.raises(DataError, match="symlink"):
        selection.select_wikimedia_documents(alias, tmp_path / "out")
    parent = tmp_path / "aliased-parent"
    parent.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(DataError, match="symlink"):
        selection.select_wikimedia_documents(snapshot, parent / "out")
    (snapshot.parent / "synthetic.xml").write_text("bad cached bytes")
    with pytest.raises(SnapshotError):
        selection.select_wikimedia_documents(snapshot, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_failed_scan_never_leaves_a_completed_selection(tmp_path):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    output = tmp_path / "out"
    def fail(message):
        raise RuntimeError("interrupted selection")
    with pytest.raises(RuntimeError, match="interrupted"):
        selection.select_wikimedia_documents(snapshot, output, progress=fail)
    assert not (output / "selection.json").exists()
    with pytest.raises(DataError, match="fresh"):
        selection.select_wikimedia_documents(snapshot, output)


def test_interrupted_allowlist_write_never_publishes_a_partial_selection(tmp_path, monkeypatch):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    output = tmp_path / "out"
    original = selection.write_json
    def fail(path, value):
        if path.name == ".selection.json.part":
            path.write_text('{"schema_version":')
            raise OSError("disk interrupted")
        return original(path, value)
    monkeypatch.setattr(selection, "write_json", fail)
    with pytest.raises(OSError, match="interrupted"):
        selection.select_wikimedia_documents(snapshot, output)
    assert not (output / "selection.json").exists()


def test_changed_selector_code_cannot_publish_a_mislabeled_plan(tmp_path, monkeypatch):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    output = tmp_path / "out"
    identities = iter(("a" * 64, "b" * 64))
    monkeypatch.setattr(selection, "_implementation_sha256", lambda: next(identities))
    with pytest.raises(DataError, match="implementation changed"):
        selection.select_wikimedia_documents(snapshot, output)
    assert not (output / "selection.json").exists()
    assert not (output / "selection-report.json").exists()


@pytest.mark.parametrize("change", [
    {"title": "違う記事"},
    {"revision_id": "999"},
    {"text": "別文の文章です。[[Category:]]"},
    {"text": "本文の文章です。[[Category:健康]]"},
    {"title": "長" * 500 + "別"},
])
def test_conflicting_duplicates_fail_in_every_order_after_eviction(change):
    ranked = sorted(range(1, 10), key=lambda i: digest_json(
        [selection.POLICY, "fixture", "", str(i)]))
    original = page(ranked[-1])
    if "title" in change and len(change["title"]) > 500:
        original["title"] = "長" * 500 + "元"
    conflict = original | change
    for pages in permutations([original, page(ranked[0]), conflict]):
        with pytest.raises(DataError, match="Conflicting retained Wikimedia page identity"):
            selection.sample_pages(pages, snapshot_id="fixture", per_topic=1, general=1)


def test_exact_duplicates_after_eviction_preserve_unique_choices():
    pages = [page(i) for i in range(1, 10)]
    expected, _ = selection.sample_pages(pages, snapshot_id="fixture", per_topic=0, general=1)
    actual, _ = selection.sample_pages(pages + pages[::-1], snapshot_id="fixture",
                                      per_topic=0, general=1)
    assert actual == expected


@pytest.mark.parametrize("interrupt", [False, True])
def test_identity_database_has_bounded_cache_and_closes_on_interruption(monkeypatch, interrupt):
    connect = sqlite3.connect
    connections = []

    def tracked(filename):
        assert filename == ""
        connection = connect(filename)
        connections.append(connection)
        return connection

    def pages():
        connection = connections[0]
        assert connection.execute("PRAGMA cache_size").fetchone()[0] == -1024
        assert connection.execute("PRAGMA mmap_size").fetchone() in (None, (0,))
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "off"
        yield page(1)
        stored = connection.execute("SELECT typeof(fingerprint),length(fingerprint) FROM seen").fetchone()
        assert stored == ("blob", 32)
        if interrupt:
            raise RuntimeError("interrupted")

    monkeypatch.setattr(selection.sqlite3, "connect", tracked)
    if interrupt:
        with pytest.raises(RuntimeError, match="interrupted"):
            selection.sample_pages(pages(), snapshot_id="fixture", per_topic=0, general=1)
    else:
        selection.sample_pages(pages(), snapshot_id="fixture", per_topic=0, general=1)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")
