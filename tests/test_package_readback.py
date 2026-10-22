from __future__ import annotations

import io
import zipfile

import pytest
import zstandard

from manabi_sentence_db import package as package_module
from manabi_sentence_db.build import build_corpus
from manabi_sentence_db.demo import create_demo_snapshot
from manabi_sentence_db.package import package_build, verify_package
from manabi_sentence_db.serialization import DataError, read_json, sha256_file, write_json


@pytest.fixture
def corpus(tmp_path):
    snapshot = create_demo_snapshot(tmp_path / "snapshot")
    build = tmp_path / "build"
    build_corpus([snapshot], build)
    return build


def test_package_readback_is_independent_and_accepts_split_stream(corpus, tmp_path, monkeypatch):
    output = tmp_path / "release"
    package_build(corpus, output, part_bytes=1024)
    release = read_json(output / "release.json")
    assert len(release["databases"][0]["parts"]) > 1
    assert release["databases"][0]["compressed_size"] == sum(
        asset["size"] for asset in release["assets"] if asset["kind"] == "sqlite-zstd-part"
    )

    def unexpected(*args, **kwargs):
        raise AssertionError("Read-back must not reparse YAML or build another database")

    monkeypatch.setattr(package_module, "iter_records", unexpected)
    monkeypatch.setattr(package_module, "build_database", unexpected)
    assert verify_package(output) == release
    assert not list(output.glob("*.sqlite3"))
    del release["databases"][0]["compressed_size"]  # Previously generated releases remain checkable.
    write_json(output / "release.json", release)
    assert verify_package(output) == release


@pytest.mark.parametrize("damage", ["prefix", "same-size"])
def test_valid_zip_with_changed_canonical_member_is_not_published(
    corpus, tmp_path, monkeypatch, damage
):
    original = package_module._zip_member

    def changed_member(archive, source, name):
        if name.endswith(".yaml"):
            data = source.read_bytes()
            if damage == "prefix":
                boundary = data.find(b"\n---\n")
                assert boundary > 0
                data = data[:boundary + 1]
            else:
                assert b"title:" in data
                data = data.replace(b"title:", b"titlz:", 1)
            archive.writestr(name, data)
        else:
            original(archive, source, name)

    monkeypatch.setattr(package_module, "_zip_member", changed_member)
    with pytest.raises(DataError, match="ZIP member size mismatch|Package content mismatch"):
        package_build(corpus, tmp_path / "release", include_sqlite=False)
    assert not (tmp_path / "release").exists()
    assert not list(tmp_path.glob(".release-*"))


def test_delayed_closed_asset_damage_prevents_publication(corpus, tmp_path, monkeypatch):
    original = package_module.write_json

    def damage_after_asset_hash(path, value):
        original(path, value)
        if path.name == "release.json":
            name = next(asset["path"] for asset in value["assets"] if asset["kind"] == "yaml-zip")
            archive = path.parent / name
            archive.write_bytes(archive.read_bytes()[:-1])

    monkeypatch.setattr(package_module, "write_json", damage_after_asset_hash)
    with pytest.raises(DataError, match="Package content mismatch"):
        package_build(corpus, tmp_path / "release", include_sqlite=False)
    assert not (tmp_path / "release").exists()
    assert not list(tmp_path.glob(".release-*"))


def test_compressed_footer_shortened_before_asset_hash_is_rejected(
    corpus, tmp_path, monkeypatch
):
    original = package_module._PartsWriter.close

    def shortened_close(self):
        original(self)
        path = self.paths[-1]
        path.write_bytes(path.read_bytes()[:-4])

    monkeypatch.setattr(package_module._PartsWriter, "close", shortened_close)
    with pytest.raises(DataError, match="SQLite bytes changed while compressing"):
        package_build(corpus, tmp_path / "release")
    assert not (tmp_path / "release").exists()
    assert not list(tmp_path.glob(".release-*"))


@pytest.mark.parametrize("damage", ["prefix", "same-size"])
def test_readback_binds_valid_zstd_payload_to_original_sqlite(corpus, tmp_path, damage):
    output = tmp_path / "release"
    package_build(corpus, output)
    release = read_json(output / "release.json")
    database = release["databases"][0]
    assert len(database["parts"]) == 1
    path = output / database["parts"][0]
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(path.read_bytes())) as source:
        original = source.read()
    modified = original[:-1] if damage == "prefix" else b"X" + original[1:]
    path.write_bytes(zstandard.ZstdCompressor(write_checksum=True).compress(modified))
    asset = next(item for item in release["assets"] if item["path"] == path.name)
    asset.update(size=path.stat().st_size, sha256=sha256_file(path))
    database["compressed_size"] = path.stat().st_size
    write_json(output / "release.json", release)
    with pytest.raises(DataError, match="Package content mismatch"):
        verify_package(output)


def test_readback_uses_manifest_part_order(corpus, tmp_path):
    output = tmp_path / "release"
    package_build(corpus, output, part_bytes=1024)
    release = read_json(output / "release.json")
    assert len(release["databases"][0]["parts"]) > 1
    release["databases"][0]["parts"].reverse()
    write_json(output / "release.json", release)
    with pytest.raises(DataError, match="Package read-back validation failed"):
        verify_package(output)


def test_duplicate_zip_member_is_rejected(corpus, tmp_path):
    output = tmp_path / "release"
    package_build(corpus, output, include_sqlite=False)
    release = read_json(output / "release.json")
    asset = next(item for item in release["assets"] if item["kind"] == "yaml-zip")
    path = output / asset["path"]
    with zipfile.ZipFile(path, "a") as archive:
        name = asset["members"][0]
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr(name, archive.read(name))
    asset.update(size=path.stat().st_size, sha256=sha256_file(path))
    write_json(output / "release.json", release)
    with pytest.raises(DataError, match="ZIP member inventory mismatch"):
        verify_package(output)
