import json
import zipfile

from manabi_sentence_db.build import build_corpus
from manabi_sentence_db.demo import create_demo_snapshot
from manabi_sentence_db.normalized import export_normalized


def test_normalized_export_preserves_context_and_deduplicates(tmp_path):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    build_corpus([snapshot], tmp_path / "build")
    result = export_normalized(tmp_path / "build", tmp_path / "normalized.zip")
    with zipfile.ZipFile(result) as archive:
        tables = {
            name: [json.loads(line) for line in archive.read(name).splitlines()]
            for name in ("works.jsonl", "sentences.jsonl", "occurrences.jsonl")
        }
        assert len(tables["sentences.jsonl"]) == 4
        assert len(tables["works.jsonl"]) == 2
        assert tables["occurrences.jsonl"][0]["next_id"] is not None
        assert tables["occurrences.jsonl"][0]["previous_id"] is None
        assert tables["works.jsonl"][0]["published_at"] is None
        assert tables["works.jsonl"][0]["revision"]["timestamp"]
        assert archive.testzip() is None
    assert not list(tmp_path.glob("*.sqlite*"))


def test_unique_identity_does_not_depend_on_work():
    from manabi_sentence_db.normalized import sentence_identity

    assert sentence_identity("ja", "今日は雨です。") == sentence_identity("ja", "今日は雨です。")
    assert sentence_identity("ja", "今日は雨です。") != sentence_identity("zh", "今日は雨です。")


def test_jsonl_build_and_package(tmp_path):
    from manabi_sentence_db.package import package_build

    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    build_corpus([snapshot], tmp_path / "build", record_format="jsonl")
    release = package_build(tmp_path / "build", tmp_path / "release")
    assets = json.loads(release.read_text())["assets"]
    assert any(a["kind"] == "jsonl-zip" for a in assets)
    assert any(a["kind"] == "normalized-jsonl-zip" for a in assets)


def test_normalized_relational_database(tmp_path):
    import sqlite3

    from manabi_sentence_db.normalized_database import build_normalized_database

    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    build_corpus([snapshot], tmp_path / "build")
    archive = export_normalized(tmp_path / "build", tmp_path / "corpus.zip")
    path = build_normalized_database(archive, tmp_path / "corpus.sqlite")
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (2,)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute(
            "SELECT count(*) FROM sentences s JOIN occurrences o ON o.sentence_id=s.id JOIN works w ON w.id=o.work_id"
        ).fetchone() == (4,)
