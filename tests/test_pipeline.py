from __future__ import annotations

import copy
import io
import sqlite3
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

import pytest
import yaml
import zstandard

from manabi_sentence_db.build import build_corpus, canonical_document, iter_records, verify_build
from manabi_sentence_db.cli import main
from manabi_sentence_db.database import build_database
from manabi_sentence_db.demo import create_demo_snapshot
from manabi_sentence_db.package import package_build
from manabi_sentence_db.serialization import DataError, StrictLoader, read_json, sha256_file
from manabi_sentence_db.snapshot import SnapshotError, verify_snapshot
from manabi_sentence_db.validation import validate_record


def make_build(tmp_path: Path, **kwargs) -> Path:
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    output = tmp_path / "corpus"
    build_corpus([snapshot], output, **kwargs)
    return output


def test_pipeline_is_offline_and_publishes_queryable_sqlite(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Offline stages must never request network access")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", no_network)
    output = make_build(tmp_path, shard_documents=1)
    catalog = verify_build(output)
    assert catalog["scope"] == "sample"
    assert len(catalog["shards"]) == 2
    database = build_database(output, tmp_path / "sentences.sqlite3")
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT COUNT(*) FROM sentences").fetchone() == (4,)
        assert connection.execute("SELECT DISTINCT review_state FROM sentences").fetchall() == [
            ("unreviewed",)
        ]
        assert connection.execute(
            "SELECT COUNT(*) FROM documents WHERE attribution_url LIKE '%history%'"
        ).fetchone() == (2,)
    release = package_build(output, tmp_path / "release", part_bytes=1024)
    manifest = read_json(release)
    assert len(manifest["databases"]) == 1
    packed = manifest["databases"][0]
    assert len(packed["parts"]) > 1
    compressed = b"".join((release.parent / part).read_bytes() for part in packed["parts"])
    restored = tmp_path / "restored.sqlite3"
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(compressed)) as reader:
        restored.write_bytes(reader.read())
    assert sha256_file(restored) == packed["uncompressed_sha256"]
    with sqlite3.connect(restored) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sentences").fetchone() == (4,)
    for asset in manifest["assets"]:
        assert sha256_file(release.parent / asset["path"]) == asset["sha256"]
        if asset["kind"] == "yaml-zip":
            with zipfile.ZipFile(release.parent / asset["path"]) as archive:
                for name in asset["members"]:
                    assert archive.read(name) == (output / name).read_bytes()


def test_rebuild_reuses_snapshot_and_has_identical_yaml(tmp_path):
    output = make_build(tmp_path, shard_documents=1)
    second = tmp_path / "second"
    build_corpus([tmp_path / "snapshot/manifest.json"], second, shard_documents=1)
    left, right = read_json(output / "catalog.json"), read_json(second / "catalog.json")
    assert left["build_id"] == right["build_id"]
    assert left["shards"] == right["shards"]
    assert left["document_index"] == right["document_index"]


def test_snapshot_corruption_fails_without_creating_build(tmp_path):
    manifest = create_demo_snapshot(tmp_path / "snapshot")
    (manifest.parent / "synthetic.xml").write_text("truncated", encoding="utf-8")
    with pytest.raises(SnapshotError, match="content mismatch"):
        build_corpus([manifest], tmp_path / "corpus")
    assert not (tmp_path / "corpus").exists()


def test_existing_artifacts_are_not_replaced(tmp_path):
    output = make_build(tmp_path)
    original = (output / "catalog.json").read_bytes()
    with pytest.raises(DataError, match="already exists"):
        build_corpus([tmp_path / "snapshot/manifest.json"], output)
    assert (output / "catalog.json").read_bytes() == original
    database = tmp_path / "existing.sqlite3"
    database.write_bytes(b"preserve this file")
    with pytest.raises(DataError, match="already exists"):
        build_database(output, database)
    assert database.read_bytes() == b"preserve this file"


def raw_document():
    return {
        "native_id": "1",
        "title": "Synthetic",
        "language": "ja",
        "url": "https://example.org/1",
        "license": {"id": "CC0-1.0", "url": "https://creativecommons.org/publicdomain/zero/1.0/"},
        "attribution": {"text": "Synthetic", "url": "https://example.org/"},
        "sentences": [{"text": "今日は公園を散歩します。"}, {"text": "図書館で本を読みます。"}],
    }


def test_sentence_identity_survives_insertion_and_preserves_duplicate_occurrences():
    manifest = {
        "source_id": "demo-ja",
        "snapshot_id": "snapshot",
        "source": {"adapter": "wikimedia"},
    }
    raw = raw_document()
    first = canonical_document(raw, manifest, Counter(), set())
    raw["sentences"].insert(0, {"text": "昨日は映画を見に行きました。"})
    raw["sentences"].append(copy.deepcopy(raw["sentences"][1]))
    second = canonical_document(raw, manifest, Counter(), set())
    assert [s["id"] for s in first["sentences"]] == [s["id"] for s in second["sentences"]][1:3]
    assert second["sentences"][1]["text_sha256"] == second["sentences"][3]["text_sha256"]
    assert second["sentences"][1]["id"] != second["sentences"][3]["id"]


def test_translation_provenance_is_independent_and_machine_tool_required():
    raw = raw_document()
    raw["sentences"][0]["translations"] = [
        {
            "language": "en",
            "text": "Today I will walk in the park.",
            "source_url": "https://example.org/en/1",
            "license": raw["license"],
            "attribution": raw["attribution"],
            "generation": {
                "kind": "machine",
                "tool": "example-translator",
                "model": "provider/model-version",
            },
        }
    ]
    manifest = {"source_id": "demo-ja", "snapshot_id": "snapshot", "source": {"adapter": "tatoeba"}}
    record = canonical_document(raw, manifest, Counter(), set())
    assert (
        record["sentences"][0]["translations"][0]["generation"]["model"] == "provider/model-version"
    )
    del record["sentences"][0]["translations"][0]["generation"]["tool"]
    with pytest.raises(DataError):
        validate_record(record)
    del record["sentences"][0]["translations"][0]["generation"]
    validate_record(record)  # Unknown provenance is omitted, never invented.


@pytest.mark.parametrize(
    "tag,reason",
    [
        ("@change", "upstream-needs-correction"),
        ("@change or unlink", "upstream-needs-correction"),
        ("archaic", "archaic-language"),
        ("old-fashioned", "archaic-language"),
        ("unnatural", "upstream-unnatural"),
    ],
)
def test_tatoeba_editorial_tags_exclude_known_bad_units(tag, reason):
    raw = raw_document()
    raw["sentences"] = [{"text": "今日は公園を散歩します。", "tags": [tag]}]
    stats = Counter()
    manifest = {
        "source_id": "tatoeba-ja",
        "snapshot_id": "snapshot",
        "source": {"adapter": "tatoeba"},
    }
    assert canonical_document(raw, manifest, stats, set()) is None
    assert stats[f"rejected:{reason}"] == 1


def test_reference_schema_forbids_redistributed_sentence_text(tmp_path):
    build = make_build(tmp_path)
    record = next(iter_records(build, verify_build(build)))
    reference = {
        key: value
        for key, value in record.items()
        if key not in {"sentences", "license", "transformations"}
    }
    reference["kind"] = "reference"
    reference["locator"] = {"type": "media", "start_seconds": 10, "end_seconds": 20}
    validate_record(reference)
    reference["text"] = "This reference must not contain a copied sentence."
    with pytest.raises(DataError):
        validate_record(reference)
    del reference["text"]
    reference["locator"]["end_seconds"] = 9
    with pytest.raises(DataError, match="after"):
        validate_record(reference)
    reference["locator"] = {"type": "media", "start_seconds": float("nan")}
    with pytest.raises(DataError, match="finite"):
        validate_record(reference)
    reference["locator"] = {"type": "media", "start_seconds": 0, "end_seconds": float("inf")}
    with pytest.raises(DataError, match="finite"):
        validate_record(reference)


@pytest.mark.parametrize("text", ["a: 1\na: 2\n", "a: &x 1\nb: *x\n", "1: value\n"])
def test_yaml_rejects_ambiguous_keys_and_aliases(text):
    with pytest.raises(DataError):
        yaml.load(text, Loader=StrictLoader)


def test_yaml_language_codes_and_dates_are_strings():
    assert yaml.load("no: 2026-10-21\nflag: true\n", Loader=StrictLoader) == {
        "no": "2026-10-21",
        "flag": True,
    }


def test_cli_config_and_demo(tmp_path):
    assert main(["validate-config"]) == 0
    assert main(["demo", "--output", str(tmp_path / "demo")]) == 0
    assert main(["demo", "--output", str(tmp_path / "demo")]) == 2
    assert verify_snapshot(tmp_path / "demo/snapshot/manifest.json")["mode"] == "sample"


def test_no_nc_or_nd_license_is_admitted():
    from manabi_sentence_db.licenses import validate_license

    for identifier in ["CC-BY-NC-4.0", "CC-BY-ND-4.0", "CC-BY-NC-SA-4.0", "unknown"]:
        with pytest.raises(DataError, match="Unreviewed"):
            validate_license({"id": identifier, "url": "https://example.org/license"})
