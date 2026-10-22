import hashlib
import http.client
import io
import json

import pytest

from manabi_sentence_db import snapshot
from manabi_sentence_db.snapshot import SnapshotError, create_snapshot, verify_snapshot


def wiki_source():
    return {
        "id": "wikipedia-ja",
        "adapter": "wikimedia",
        "language": "ja",
        "title": "Japanese Wikipedia",
        "acquisition": {
            "wiki_id": "jawiki",
            "api_url": "https://ja.wikipedia.org/w/api.php",
            "sample_titles": ["東京"],
            "export_kind": "content-current",
        },
    }


def sample_bytes(revision=1):
    return json.dumps(
        {
            "query": {
                "pages": [
                    {
                        "pageid": 5,
                        "ns": 0,
                        "title": "東京",
                        "revisions": [
                            {
                                "revid": revision,
                                "timestamp": "2026-10-01T00:00:00Z",
                                "slots": {
                                    "main": {
                                        "content": "東京は日本の首都です。",
                                        "contentmodel": "wikitext",
                                    }
                                },
                            }
                        ],
                    }
                ]
            }
        },
        ensure_ascii=False,
    ).encode()


class Response(io.BytesIO):
    def __init__(self, value, headers=None):
        super().__init__(value)
        self.headers = headers or {"Content-Length": str(len(value))}


@pytest.fixture
def sample_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "_open", lambda *_: Response(sample_bytes()))
    return create_snapshot(wiki_source(), tmp_path / "snapshot")


def test_repeated_snapshot_is_offline_and_checks_content(sample_snapshot, monkeypatch):
    def no_network(*args):
        raise AssertionError("Existing snapshots must not contact the origin")

    monkeypatch.setattr(snapshot, "_open", no_network)
    assert create_snapshot(wiki_source(), sample_snapshot.parent) == sample_snapshot
    (sample_snapshot.parent / "sample.json").write_bytes(b"changed")
    with pytest.raises(SnapshotError, match="content mismatch"):
        create_snapshot(wiki_source(), sample_snapshot.parent)


def test_different_source_config_requires_explicit_refresh(sample_snapshot):
    changed = wiki_source()
    changed["title"] = "Changed source configuration"
    with pytest.raises(SnapshotError, match="different request"):
        create_snapshot(changed, sample_snapshot.parent)


def test_refresh_preserves_original_snapshot(sample_snapshot, monkeypatch):
    original = sample_snapshot.read_bytes()
    monkeypatch.setattr(snapshot, "_open", lambda *_: Response(sample_bytes(revision=2)))
    refreshed = create_snapshot(wiki_source(), sample_snapshot.parent, refresh=True)
    assert refreshed.parent != sample_snapshot.parent
    assert sample_snapshot.read_bytes() == original
    assert (
        verify_snapshot(refreshed)["snapshot_id"] != verify_snapshot(sample_snapshot)["snapshot_id"]
    )


def test_unchanged_refresh_reuses_identity(sample_snapshot, monkeypatch):
    monkeypatch.setattr(snapshot, "_open", lambda *_: Response(sample_bytes()))
    assert create_snapshot(wiki_source(), sample_snapshot.parent, refresh=True) == sample_snapshot


def test_full_export_requires_explicit_date(tmp_path):
    with pytest.raises(SnapshotError, match="explicit --date"):
        create_snapshot(wiki_source(), tmp_path / "new", mode="full")


def test_partial_export_checks_upstream_digest_and_scope(tmp_path, monkeypatch):
    content = b"compressed XML fixture"
    name = "jawiki-2026-10-01-p1p3.xml.bz2"
    listing = f"{hashlib.sha256(content).hexdigest()}  {name}\n".encode()
    monkeypatch.setattr(
        snapshot,
        "_open",
        lambda url, _: Response(listing if url.endswith("SHA256SUMS") else content),
    )
    manifest_path = create_snapshot(
        wiki_source(), tmp_path / "partial", mode="full", date="2026-10-01", max_files=1
    )
    manifest = verify_snapshot(manifest_path)
    assert manifest["mode"] == "partial"
    assert manifest["upstream_date"] == "2026-10-01"
    assert [item["role"] for item in manifest["files"]] == ["upstream-checksums", "mediawiki-xml"]


def test_upstream_checksum_failure_does_not_publish(tmp_path, monkeypatch):
    listing = f"{'0' * 64}  jawiki-test.xml.bz2\n".encode()
    monkeypatch.setattr(
        snapshot,
        "_open",
        lambda url, _: Response(listing if url.endswith("SHA256SUMS") else b"wrong"),
    )
    with pytest.raises(SnapshotError, match="SHA-256 mismatch"):
        create_snapshot(wiki_source(), tmp_path / "bad", mode="full", date="2026-10-01")
    assert not (tmp_path / "bad").exists()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", ["../outside.xml.bz2", "/outside.xml.bz2", "..\\outside.xml.bz2"])
def test_upstream_manifest_cannot_escape_snapshot(tmp_path, monkeypatch, name):
    listing = f"{'0' * 64}  {name}\n".encode()
    monkeypatch.setattr(snapshot, "_open", lambda *_: Response(listing))
    with pytest.raises(SnapshotError, match="Unsafe"):
        create_snapshot(wiki_source(), tmp_path / "bad", mode="full", date="2026-10-01")
    assert not (tmp_path / "bad").exists()


def test_api_http_200_maxlag_is_retried(monkeypatch):
    attempts = [
        Response(b'{"error":{"code":"maxlag","info":"busy"}}', {"Retry-After": "7"}),
        Response(sample_bytes()),
    ]
    sleeps = []
    monkeypatch.setattr(snapshot, "_open", lambda *_: attempts.pop(0))
    monkeypatch.setattr(snapshot.time, "sleep", sleeps.append)
    assert snapshot._api_json("https://example.org/api", "test") == sample_bytes()
    assert sleeps == [7]


def test_interrupted_download_restarts_and_checks_full_digest(tmp_path, monkeypatch):
    content = b"complete compressed source"

    class Interrupted(Response):
        def read(self, size=-1):
            if self.tell():
                raise http.client.IncompleteRead(b"", len(content))
            return super().read(4)

    attempts = [Interrupted(content), Response(content)]
    monkeypatch.setattr(snapshot, "_open", lambda *_: attempts.pop(0))
    monkeypatch.setattr(snapshot.time, "sleep", lambda _: None)
    entry = snapshot._download(
        tmp_path,
        "source.bz2",
        "sentences-jpn",
        "https://example.org/source.bz2",
        "test",
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )
    assert (tmp_path / "source.bz2").read_bytes() == content
    assert entry["size"] == len(content)
    assert not attempts
    assert not (tmp_path / "source.bz2.part").exists()


@pytest.mark.parametrize(
    "options, message",
    [
        ({"date": "2026-10-01"}, "--date applies only"),
        ({"mode": "full", "date": "2026-10-01", "titles": ["東京"]}, "--title applies only"),
        ({"translations": ["en"]}, "--translations applies only"),
        ({"max_files": 1}, "only valid for full"),
    ],
)
def test_invalid_options_fail_before_any_network(tmp_path, monkeypatch, options, message):
    monkeypatch.setattr(snapshot, "_open", lambda *_: pytest.fail("Unexpected network request"))
    with pytest.raises(SnapshotError, match=message):
        create_snapshot(wiki_source(), tmp_path / "invalid", **options)
    assert not (tmp_path / "invalid").exists()


@pytest.mark.parametrize("prefix", ['"schema_version":1,', '"invalid":NaN,'])
def test_snapshot_json_rejects_duplicates_and_nonfinite(sample_snapshot, prefix):
    sample_snapshot.write_text("{" + prefix + sample_snapshot.read_text().lstrip()[1:])
    with pytest.raises(SnapshotError, match="Malformed"):
        verify_snapshot(sample_snapshot)


@pytest.mark.parametrize("change", ["scope", "boolean_size", "timestamp", "url"])
def test_snapshot_semantics_checked_even_with_recomputed_identity(sample_snapshot, change):
    manifest = json.loads(sample_snapshot.read_text())
    if change == "scope":
        manifest["mode"] = "full"
    elif change == "boolean_size":
        manifest["files"][0]["size"] = True
    elif change == "timestamp":
        manifest["retrieved_at"] = "not a timestamp"
    else:
        manifest["files"][0]["url"] = 10
    manifest["snapshot_id"] = snapshot.snapshot_identity(manifest)
    sample_snapshot.write_text(json.dumps(manifest))
    with pytest.raises(SnapshotError):
        verify_snapshot(sample_snapshot)


def test_snapshot_manifest_tampering_detected(sample_snapshot):
    manifest = json.loads(sample_snapshot.read_text())
    manifest["source"]["title"] = "Silently replaced attribution"
    sample_snapshot.write_text(json.dumps(manifest))
    with pytest.raises(SnapshotError, match="configuration hash"):
        verify_snapshot(sample_snapshot)


def test_symlink_raw_input_rejected(sample_snapshot, tmp_path):
    raw = sample_snapshot.parent / "sample.json"
    external = tmp_path / "external.json"
    raw.rename(external)
    raw.symlink_to(external)
    with pytest.raises(SnapshotError, match="Missing snapshot"):
        verify_snapshot(sample_snapshot)


def test_tatoeba_optional_translations_and_current_date(tmp_path, monkeypatch):
    source = {
        "id": "tatoeba-ja",
        "adapter": "tatoeba",
        "acquisition": {
            "files": [
                {"role": "sentences-jpn", "url": "https://downloads.tatoeba.org/jpn.bz2"},
                {"role": "tags", "url": "https://downloads.tatoeba.org/tags.bz2"},
                {"role": "sentences-eng", "url": "https://downloads.tatoeba.org/eng.bz2"},
                {"role": "links", "url": "https://downloads.tatoeba.org/links.bz2"},
            ]
        },
    }
    requested = []

    def fetch(url, agent):
        requested.append(url)
        return Response(b"fixture")

    monkeypatch.setattr(snapshot, "_open", fetch)
    with pytest.raises(SnapshotError, match="omit --date"):
        create_snapshot(source, tmp_path / "wrong", mode="full", date="2026-10-01")
    manifest = create_snapshot(source, tmp_path / "ja", mode="full")
    assert {item["role"] for item in verify_snapshot(manifest)["files"]} == {
        "sentences-jpn",
        "tags",
    }
    assert len(requested) == 2
    translated = create_snapshot(source, tmp_path / "en", mode="full", translations=["en"])
    assert len(verify_snapshot(translated)["files"]) == 4
