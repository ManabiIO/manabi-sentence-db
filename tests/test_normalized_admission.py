"""Normalized imports must not bypass canonical rights/provenance safeguards."""

import copy
import hashlib
import json
import sqlite3
import warnings
import zipfile

import pytest

from manabi_sentence_db.licenses import LICENSE_URLS, WIKINEWS_NOTICE
from manabi_sentence_db.normalized_database import build_normalized_database
from manabi_sentence_db.serialization import DataError, canonical_json


def fixture_tables():
    # Original synthetic fixture, not an imported sentence or licensing assertion.
    text = "犬は庭で遊んでいます。"
    identity = "s_" + hashlib.sha256(canonical_json(["ja", text])).hexdigest()
    rights = {
        "license": {"id": "CC-BY-SA-3.0", "url": LICENSE_URLS["CC-BY-SA-3.0"]},
        "attribution": {"text": "Fixture author", "url": "https://example.org/author"},
    }
    return {
        "works": [dict(
            copy.deepcopy(rights), id="w", source_id="fixture", language="ja",
            title="Fixture work", url="https://example.org/work",
            transformations=["sentence-segmentation", "NFC"],
        )],
        "sentences": [{
            "id": identity, "language": "ja", "text": text,
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        }],
        "occurrences": [{
            "id": "o", "sentence_id": identity, "work_id": "w", "ordinal": 0,
            "content_flags": [], "review_state": "unreviewed",
        }],
        "translations": [dict(
            copy.deepcopy(rights), id="t", sentence_id=identity, occurrence_id="o",
            language="en", text="The dog is playing in the garden.",
            text_sha256=hashlib.sha256(b"The dog is playing in the garden.").hexdigest(),
            source_url="https://example.org/translation",
        )],
        "references": [],
    }


def write_archive(tmp_path, tables, *, change_manifest=None, change_data=None, duplicate=False):
    data = {
        name + ".jsonl": b"".join(canonical_json(row) + b"\n" for row in rows)
        for name, rows in tables.items()
    }
    if change_data:
        change_data(data)
    manifest = {
        "schema_version": 2, "kind": "normalized-corpus", "build_id": "fixture",
        "scope": "sample", "counts": {name: len(rows) for name, rows in tables.items()},
        "members": {name: hashlib.sha256(value).hexdigest() for name, value in data.items()},
    }
    if change_manifest:
        change_manifest(manifest)
    path = tmp_path / "corpus.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", canonical_json(manifest))
        for name, value in data.items():
            archive.writestr(name, value)
        if duplicate:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr("works.jsonl", data["works.jsonl"])
    return path


def rejected(tmp_path, tables, match, **kwargs):
    archive = write_archive(tmp_path, tables, **kwargs)
    output = tmp_path / "corpus.sqlite"
    with pytest.raises(DataError, match=match):
        build_normalized_database(archive, output)
    assert not output.exists()
    assert not list(tmp_path.glob(".normalized-db-*"))


@pytest.mark.parametrize("table", ["works", "translations"])
@pytest.mark.parametrize("identifier", list(LICENSE_URLS))
def test_reviewed_licenses_keep_exact_rights(tmp_path, table, identifier):
    tables = fixture_tables()
    license = {"id": identifier, "url": LICENSE_URLS[identifier]}
    if identifier == "LicenseRef-Wikinews-JA":
        license["notice"] = WIKINEWS_NOTICE
    else:
        license["notice"] = "Retain this supplied notice."
    tables[table][0]["license"] = license
    output = build_normalized_database(write_archive(tmp_path, tables), tmp_path / "out.sqlite")
    with sqlite3.connect(output) as db:
        row = json.loads(db.execute(f"SELECT metadata_json FROM {table}").fetchone()[0])
        assert row["license"] == license
        assert row["attribution"] == tables[table][0]["attribution"]


@pytest.mark.parametrize("table", ["works", "translations"])
@pytest.mark.parametrize("identifier", ["CC-BY-NC-4.0", "CC-BY-ND-4.0", "AllRightsReserved"])
def test_restricted_license_with_valid_checksums_is_rejected(tmp_path, table, identifier):
    tables = fixture_tables()
    tables[table][0]["license"] = {"id": identifier, "url": "https://example.org/license"}
    rejected(tmp_path, tables, "license")


@pytest.mark.parametrize("table", ["works", "translations"])
@pytest.mark.parametrize("notice", [None, "Historical notice removed"])
def test_wikinews_historical_notice_is_required(tmp_path, table, notice):
    tables = fixture_tables()
    tables[table][0]["license"] = {
        "id": "LicenseRef-Wikinews-JA", "url": LICENSE_URLS["LicenseRef-Wikinews-JA"],
    }
    if notice:
        tables[table][0]["license"]["notice"] = notice
    rejected(tmp_path, tables, "historical license notice")


@pytest.mark.parametrize("table", ["works", "translations"])
@pytest.mark.parametrize("attribution", [None, {}, {"text": "   ", "url": "https://example.org/"}])
def test_attribution_cannot_be_lost(tmp_path, table, attribution):
    tables = fixture_tables()
    tables[table][0]["attribution"] = attribution
    rejected(tmp_path, tables, "attribution")


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://", "https://example.org/a\nb", "https://user:pass@example.org/"])
def test_invalid_citation_urls_are_rejected(tmp_path, url):
    tables = fixture_tables()
    tables["works"][0]["attribution"]["url"] = url
    rejected(tmp_path, tables, "citation URL")


def test_license_url_must_match_id(tmp_path):
    tables = fixture_tables()
    tables["works"][0]["license"]["url"] = LICENSE_URLS["CC-BY-SA-4.0"]
    rejected(tmp_path, tables, "License URL")


@pytest.mark.parametrize("value", [None, [], {"id": []}, {"id": "CC-BY-SA-3.0"}])
def test_malformed_license_is_a_data_error(tmp_path, value):
    tables = fixture_tables()
    tables["works"][0]["license"] = value
    rejected(tmp_path, tables, "[Ll]icense")


def test_translation_cannot_claim_another_occurrences_sentence(tmp_path):
    tables = fixture_tables()
    other = copy.deepcopy(tables["sentences"][0])
    other["text"] = "猫は庭で遊んでいます。"
    other["text_sha256"] = hashlib.sha256(other["text"].encode()).hexdigest()
    other["id"] = "s_" + hashlib.sha256(canonical_json(["ja", other["text"]])).hexdigest()
    tables["sentences"].append(other)
    tables["occurrences"].append(dict(tables["occurrences"][0], id="o2", sentence_id=other["id"], ordinal=1))
    tables["translations"][0]["occurrence_id"] = "o2"
    rejected(tmp_path, tables, "Translation.*occurrence")


@pytest.mark.parametrize("key,value", [("kind", "something-else"), ("schema_version", 1)])
def test_manifest_identity_is_required(tmp_path, key, value):
    rejected(tmp_path, fixture_tables(), "normalized corpus v2", change_manifest=lambda m: m.update({key: value}))


def test_duplicate_members_are_rejected(tmp_path):
    rejected(tmp_path, fixture_tables(), "Duplicate ZIP", duplicate=True)


def test_duplicate_json_keys_are_rejected_even_with_matching_digest(tmp_path):
    def duplicate_key(data):
        data["works.jsonl"] = data["works.jsonl"].replace(b'{"attribution":', b'{"id":"hidden","attribution":', 1)
    rejected(tmp_path, fixture_tables(), "Duplicate JSON key", change_data=duplicate_key)


def test_member_counts_are_checked(tmp_path):
    rejected(tmp_path, fixture_tables(), "count", change_manifest=lambda m: m["counts"].update(works=2))


def test_mismatched_text_digest_is_rejected(tmp_path):
    tables = fixture_tables()
    tables["sentences"][0]["text_sha256"] = "0" * 64
    rejected(tmp_path, tables, "text hash")


def test_failed_import_does_not_replace_existing_database(tmp_path):
    output = tmp_path / "existing.sqlite"
    output.write_bytes(b"keep existing")
    with pytest.raises(DataError, match="fresh"):
        build_normalized_database(write_archive(tmp_path, fixture_tables()), output)
    assert output.read_bytes() == b"keep existing"


def test_sentence_content_identity_cannot_be_forged(tmp_path):
    tables = fixture_tables()
    tables["sentences"][0]["id"] = "s_" + "0" * 64
    rejected(tmp_path, tables, "sentence identity")


def test_translation_text_digest_is_verified(tmp_path):
    tables = fixture_tables()
    tables["translations"][0]["text_sha256"] = "0" * 64
    rejected(tmp_path, tables, "text hash")


def test_member_digest_is_verified(tmp_path):
    rejected(tmp_path, fixture_tables(), "digest mismatch", change_manifest=lambda m: m["members"].update({"works.jsonl": "0" * 64}))


@pytest.mark.parametrize("count", [True, -1, 1.0, "1"])
def test_manifest_counts_are_nonnegative_integers(tmp_path, count):
    rejected(tmp_path, fixture_tables(), "table count", change_manifest=lambda m: m["counts"].update(works=count))


def test_bounded_record_reader_fails_without_publishing(tmp_path, monkeypatch):
    from manabi_sentence_db import normalized_database

    archive = write_archive(tmp_path, fixture_tables())
    # Test the streaming bound without allocating a production-size record.
    monkeypatch.setattr(normalized_database, "MAX_RECORD_BYTES", 50)
    with zipfile.ZipFile(archive) as source:
        with pytest.raises(DataError, match="size bound"):
            list(normalized_database._rows(source, "works", {"members": {}, "counts": {}}))
    assert not (tmp_path / "corpus.sqlite").exists()


def test_oversized_manifest_is_rejected_before_read(tmp_path, monkeypatch):
    from manabi_sentence_db import normalized_database

    monkeypatch.setattr(normalized_database, "MAX_RECORD_BYTES", 50)
    rejected(tmp_path, fixture_tables(), "Oversized normalized manifest")
