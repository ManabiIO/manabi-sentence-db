import io
import json
import tarfile
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from manabi_sentence_db.build import canonical_document
from manabi_sentence_db.jec_basic import ARCHIVE_MEMBER, README_MEMBER
from manabi_sentence_db.jec_basic import iter_documents as jec_documents
from manabi_sentence_db.jmultiwoz import MEMBER
from manabi_sentence_db.jmultiwoz import iter_documents as dialogues
from manabi_sentence_db.serialization import DataError
from manabi_sentence_db.stair import MEMBERS
from manabi_sentence_db.stair import iter_documents as captions
from manabi_sentence_db.validation import load_source


def _jec_fixture(tmp_path, monkeypatch, rows):
    """A synthetic ZIP/workbook fixture; it is not upstream JEC text."""
    import hashlib

    source = load_source(Path("sources/jec-basic-ja.yaml"))
    workbook_bytes = b"synthetic workbook bytes"
    readme_bytes = b"synthetic README bytes"
    archive_path = tmp_path / "jec.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(ARCHIVE_MEMBER, workbook_bytes)
        archive.writestr(README_MEMBER, readme_bytes)
    source["acquisition"].update(
        size=archive_path.stat().st_size,
        workbook_sha256=hashlib.sha256(workbook_bytes).hexdigest(),
        workbook_size=len(workbook_bytes),
        readme_sha256=hashlib.sha256(readme_bytes).hexdigest(),
        readme_size=len(readme_bytes),
        rows=len(rows),
    )

    class Sheet:
        ncols = 4
        nrows = len(rows)

        def cell_value(self, row, col):
            return rows[row][col]

    class Workbook:
        def sheet_names(self):
            return ["ALL_NEW"]

        def sheet_by_index(self, index):
            assert index == 0
            return Sheet()

        def release_resources(self):
            pass

    monkeypatch.setattr(
        "manabi_sentence_db.jec_basic.xlrd.open_workbook",
        lambda **kwargs: Workbook(),
    )
    manifest = {
        "source": source,
        "source_id": source["id"],
        "snapshot_id": "synthetic-fixture-snapshot",
        "files": [{"role": "jec-basic-zip", "path": archive_path.name}],
    }
    return manifest, tmp_path


def _manifest(source_id, role, path):
    source = load_source(Path("sources") / f"{source_id}.yaml")
    return {"source": source, "source_id": source_id, "snapshot_id": "fixture",
            "files": [{"role": role, "path": path}]}


def _dialogue(identity="dialogue_0001ABCD"):
    return {"dialogue_name": identity, "system_name": "PRIVATE_WORKER",
            "goal_description": {"private": "DO NOT IMPORT"},
            "turns": [{"turn_id": 0, "speaker": "USER", "utterance": "駅に着きました。宿を探します。"},
                      {"turn_id": 1, "speaker": "SYSTEM", "utterance": "近くに宿があります。"}]}


def test_jmultiwoz_reads_only_human_turns_and_preserves_context(tmp_path):
    with zipfile.ZipFile(tmp_path / "source.zip", "w") as archive:
        archive.writestr(MEMBER, json.dumps({"dialogue_0001ABCD": _dialogue()}))
        archive.writestr("output/model.json", json.dumps({"text": "GENERATED"}))
    manifest = _manifest("jmultiwoz-ja", "jmultiwoz-zip", "source.zip")
    raw = list(dialogues(manifest, tmp_path))
    assert len(raw) == 1
    assert "PRIVATE_WORKER" not in json.dumps(raw)
    assert "DO NOT IMPORT" not in json.dumps(raw)
    assert "GENERATED" not in json.dumps(raw)
    assert raw[0]["authorship"] == "human"
    result = canonical_document(raw[0], manifest, Counter(), set())
    assert len(result["sentences"]) == 3
    assert result["sentences"][1]["source_range"] == {"unit": "utterance", "start": 0, "end": 1}
    assert result["sentences"][0]["source_unit"]["text"] == "駅に着きました。宿を探します。"


def test_jmultiwoz_rejects_repeated_turn_or_wrong_identity(tmp_path):
    for case in ("turn", "identity", "malformed"):
        doc = _dialogue()
        if case == "turn":
            doc["turns"][1]["turn_id"] = 0
        elif case == "identity":
            doc["dialogue_name"] = "wrong"
        else:
            doc["turns"][0] = None
        with zipfile.ZipFile(tmp_path / "source.zip", "w") as archive:
            archive.writestr(MEMBER, json.dumps({"dialogue_0001ABCD": doc}))
        with pytest.raises(DataError):
            list(dialogues(_manifest("jmultiwoz-ja", "jmultiwoz-zip", "source.zip"), tmp_path))


def _tar(tmp_path, *, duplicate_id=False, missing=False):
    with tarfile.open(tmp_path / "source.tar.gz", "w:gz") as archive:
        names = sorted(MEMBERS)[:1] if missing else sorted(MEMBERS)
        for index, name in enumerate(names):
            row = {"id": 1 if duplicate_id else index+1, "image_id": 5,
                   "caption": "公園の木の下に椅子があります。"}
            data = json.dumps({"images": [{"url": "IMAGE_DO_NOT_IMPORT"}],
                               "annotations": [row]}).encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        data = b'{"annotations":[{"caption":"TOKENIZED_DUPLICATE"}]}'
        info = tarfile.TarInfo("stair_captions_v1.2_train_tokenized.json")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))


def test_stair_excludes_images_tokenized_duplicates_and_cross_caption_context(tmp_path):
    _tar(tmp_path)
    manifest = _manifest("stair-captions-ja", "stair-tar", "source.tar.gz")
    raw = list(captions(manifest, tmp_path))
    assert len(raw) == 2 and raw[0]["native_id"] != raw[1]["native_id"]
    assert "IMAGE_DO_NOT_IMPORT" not in json.dumps(raw)
    assert "TOKENIZED_DUPLICATE" not in json.dumps(raw)
    assert all(len(d["sentences"]) == 1 for d in raw)
    assert all("context:image-not-included" in d["tags"] for d in raw)
    for doc in raw:
        assert canonical_document(doc, manifest, Counter(), set()) is not None


@pytest.mark.parametrize("options", [{"duplicate_id": True}, {"missing": True}])
def test_stair_fails_on_incomplete_or_ambiguous_corpus(tmp_path, options):
    _tar(tmp_path, **options)
    with pytest.raises(DataError):
        list(captions(_manifest("stair-captions-ja", "stair-tar", "source.tar.gz"), tmp_path))


def test_stair_reads_immutable_legacy_snapshot_role(tmp_path):
    # Existing published snapshots used this role. Do not rewrite their manifest
    # identities or redownload the unchanged pinned archive.
    _tar(tmp_path)
    manifest = _manifest("stair-captions-ja", "stair-captions", "source.tar.gz")
    assert len(list(captions(manifest, tmp_path))) == 2


def test_jec_preserves_aligned_text_and_excludes_only_template_placeholders(tmp_path, monkeypatch):
    rows = [
        ["#0001", "２～３人が来ます", "Two or three people will come.", "两三个人会来。"],
        ["#0002", "彼は「明日来る」と言う", "He says \"I'll come tomorrow.\"", "他说“明天来”。"],
        ["#0003", "２～３人が「～」と言う", "Two or three people say \"~\".", "两三个人说“～”。"],
        ["#0004", "今日は雨です", "It is raining today.", "今天下雨。"],
    ]
    manifest, root = _jec_fixture(tmp_path, monkeypatch, rows)
    stats = Counter()
    raw = list(jec_documents(manifest, root, stats=stats))
    assert [doc["native_id"] for doc in raw] == ["#0001", "#0002", "#0004"]
    assert raw[0]["sentences"][0]["text"] == rows[0][1]
    translations = raw[0]["sentences"][0]["translations"]
    assert [(item["language"], item["text"]) for item in translations] == [
        ("en", rows[0][2]), ("zh", rows[0][3]),
    ]
    assert all(item["alignment"] == "unknown" for item in translations)
    assert translations[0]["license"]["id"] == "CC-BY-3.0"
    assert raw[0]["authorship"] == "unknown"
    assert stats["rows_in_workbook"] == 4
    assert stats["excluded:unresolved-template-placeholder"] == 1
    record = canonical_document(raw[0], manifest, Counter(), set())
    assert record["sentences"][0]["text"] == rows[0][1]
    assert record["sentences"][0]["translations"][0]["text"] == rows[0][2]


def test_jec_rejects_bad_member_checksum_and_row_identity(tmp_path, monkeypatch):

    rows = [["#0001", "今日は雨です", "It is raining today.", "今天下雨。"]]
    manifest, root = _jec_fixture(tmp_path, monkeypatch, rows)
    bad_hash = {**manifest, "source": {**manifest["source"], "acquisition": {
        **manifest["source"]["acquisition"], "workbook_sha256": "0" * 64,
    }}}
    with pytest.raises(DataError, match="workbook member checksum"):
        list(jec_documents(bad_hash, root))
    bad_rows = {**manifest, "source": {**manifest["source"], "acquisition": {
        **manifest["source"]["acquisition"], "rows": 2,
    }}}
    with pytest.raises(DataError, match="row or column count"):
        list(jec_documents(bad_rows, root))

    wrong_id = [["#0002", *rows[0][1:]]]
    class Sheet:
        ncols = 4
        nrows = 1
        def cell_value(self, row, col):
            return wrong_id[row][col]
    class Workbook:
        def sheet_names(self): return ["ALL_NEW"]
        def sheet_by_index(self, index): return Sheet()
        def release_resources(self): pass
    monkeypatch.setattr(
        "manabi_sentence_db.jec_basic.xlrd.open_workbook",
        lambda **kwargs: Workbook(),
    )
    with pytest.raises(DataError, match="row ID"):
        list(jec_documents(manifest, root))


def test_jec_real_xls_runs_through_offline_normalized_build(tmp_path):
    import hashlib

    from manabi_sentence_db.build import build_corpus, verify_build
    from manabi_sentence_db.normalized import export_normalized
    from manabi_sentence_db.serialization import canonical_json
    from manabi_sentence_db.snapshot import snapshot_identity

    # Authored synthetic examples exercise the actual XLS parser without fetching
    # upstream or committing the real workbook. The snapshot remains a sample.
    workbook = (Path(__file__).parent / "fixtures/jec-synthetic.xls").read_bytes()
    readme = b"Synthetic test fixture; CC0. Not a publisher release."
    source = load_source(Path("sources/jec-basic-ja.yaml"))
    root = tmp_path / "snapshot"
    root.mkdir()
    archive_path = root / "jec.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(ARCHIVE_MEMBER, workbook)
        archive.writestr(README_MEMBER, readme)
    raw = archive_path.read_bytes()
    source["acquisition"].update(
        size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), rows=4,
        workbook_size=len(workbook), readme_size=len(readme),
        workbook_sha256=hashlib.sha256(workbook).hexdigest(),
        readme_sha256=hashlib.sha256(readme).hexdigest(),
    )
    manifest = {
        "schema_version": 1, "source_id": source["id"], "source": source,
        "source_config_sha256": hashlib.sha256(canonical_json(source)).hexdigest(),
        "retrieved_at": "2026-10-29T00:00:00Z", "mode": "sample",
        "upstream_date": None, "request": {"synthetic": True},
        "files": [{"role": "jec-basic-zip", "path": archive_path.name,
                   "url": source["acquisition"]["url"], "size": len(raw),
                   "sha256": hashlib.sha256(raw).hexdigest()}],
    }
    manifest["snapshot_id"] = snapshot_identity(manifest)
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    build = tmp_path / "build"
    build_corpus([manifest_path], build, record_format="jsonl")
    catalog = verify_build(build)
    assert catalog["scope"] == "sample"
    assert catalog["statistics"]["sentences"] == 2
    assert catalog["statistics"]["translations"] == 4
    assert catalog["statistics"]["excluded:unresolved-template-placeholder"] == 2
    normalized = export_normalized(build, tmp_path / "normalized.zip")
    with zipfile.ZipFile(normalized) as archive:
        works = [json.loads(line) for line in archive.read("works.jsonl").splitlines()]
        occurrences = [json.loads(line) for line in archive.read("occurrences.jsonl").splitlines()]
        translations = [json.loads(line) for line in archive.read("translations.jsonl").splitlines()]
    assert {w["native_id"] for w in works} == {"#0001", "#0003"}
    assert all(o["previous_id"] is None and o["next_id"] is None for o in occurrences)
    assert {t["language"] for t in translations} == {"en", "zh"}
    assert all("generation" not in t for t in translations)
    assert all(t["license"]["id"] == "CC-BY-3.0" for t in translations)
