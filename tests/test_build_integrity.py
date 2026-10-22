import json

import pytest
import yaml

from manabi_sentence_db.build import build_corpus, iter_records, verify_build
from manabi_sentence_db.demo import create_demo_snapshot
from manabi_sentence_db.package import package_build
from manabi_sentence_db.serialization import (
    DataError,
    read_json,
    safe_relative,
    sha256_file,
    write_json,
)


@pytest.fixture
def corpus(tmp_path):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    build = tmp_path / "build"
    build_corpus([snapshot], build)
    return build


def edit_catalog(build, change):
    catalog = read_json(build / "catalog.json")
    change(catalog)
    write_json(build / "catalog.json", catalog)


def edit_records(build, change):
    catalog = read_json(build / "catalog.json")
    shard = catalog["shards"][0]
    path = build / shard["path"]
    records = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    change(records)
    path.write_text(
        yaml.safe_dump_all(records, allow_unicode=True, sort_keys=False, explicit_start=True),
        encoding="utf-8",
    )
    shard["size"] = path.stat().st_size
    shard["sha256"] = sha256_file(path)
    write_json(build / "catalog.json", catalog)


def test_original_build_is_verified_and_yaml_only_is_validated(corpus, tmp_path):
    catalog = verify_build(corpus)
    assert len(list(iter_records(corpus, catalog))) == 2
    assert package_build(corpus, tmp_path / "release", include_sqlite=False).is_file()


def test_catalog_cannot_write_outside_package_staging(corpus, tmp_path):
    edit_catalog(corpus, lambda c: c["shards"][0].update(source_id="../escape"))
    with pytest.raises(DataError, match="unknown source"):
        package_build(corpus, tmp_path / "release", include_sqlite=False)
    assert not list(tmp_path.glob("escape*"))
    assert not (tmp_path / "release").exists()


def test_catalog_source_cannot_diverge_from_provenance(corpus):
    edit_catalog(corpus, lambda c: c["sources"][0]["source"].update(title="A different publisher"))
    with pytest.raises(DataError, match="provenance"):
        verify_build(corpus)


def test_sample_cannot_be_relabelled_full(corpus):
    edit_catalog(corpus, lambda c: c.update(scope="full"))
    with pytest.raises(DataError, match="scope"):
        verify_build(corpus)


def test_rehashed_record_cannot_claim_another_snapshot(corpus):
    edit_records(corpus, lambda records: records[0].update(snapshot_id="0" * 64))
    with pytest.raises(DataError, match="snapshot"):
        list(iter_records(corpus, verify_build(corpus)))


def test_yaml_only_release_rejects_a_relicensed_record(corpus, tmp_path):
    edit_records(corpus, lambda records: records[0].update(license={
        "id": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/",
    }))
    with pytest.raises(DataError, match="license disagrees"):
        package_build(corpus, tmp_path / "release", include_sqlite=False)
    assert not (tmp_path / "release").exists()


def test_rehashed_yaml_must_still_match_sentence_text_hash(corpus, tmp_path):
    edit_records(corpus, lambda records: records[0]["sentences"][0].update(text="異なる文章です。"))
    with pytest.raises(DataError, match="hash"):
        package_build(corpus, tmp_path / "release", include_sqlite=False)


def test_index_contents_are_bound_to_records(corpus):
    catalog = read_json(corpus / "catalog.json")
    path = corpus / catalog["document_index"]["path"]
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["title"] = "Wrong title"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    catalog["document_index"]["sha256"] = sha256_file(path)
    write_json(corpus / "catalog.json", catalog)
    with pytest.raises(DataError, match="index disagrees"):
        list(iter_records(corpus, verify_build(corpus)))


def test_duplicate_shard_is_rejected(corpus):
    edit_catalog(corpus, lambda c: c["shards"].append(dict(c["shards"][0])))
    with pytest.raises(DataError, match="Duplicate catalog artifact"):
        verify_build(corpus)


@pytest.mark.parametrize("field,value", [("sources", {}), ("shards", None), ("schema_version", True)])
def test_malformed_catalog_is_a_data_error(corpus, field, value):
    edit_catalog(corpus, lambda c: c.update({field: value}))
    with pytest.raises(DataError):
        verify_build(corpus)


@pytest.mark.parametrize("field", ["document_index", "licenses"])
def test_metadata_paths_match_the_packaging_contract(corpus, field):
    edit_catalog(corpus, lambda c: c[field].update(path="renamed.json"))
    with pytest.raises(DataError, match="canonical metadata path"):
        verify_build(corpus)


@pytest.mark.parametrize("name", ["C:/drive", "a:drive", "a\nb", "a//b", "a/", "a\\b", "a\x7fb"])
def test_artifact_paths_are_portable_and_unambiguous(tmp_path, name):
    with pytest.raises(DataError):
        safe_relative(tmp_path, name)
    assert safe_relative(tmp_path, "yaml/日本語/0000.yaml") == tmp_path / "yaml/日本語/0000.yaml"
