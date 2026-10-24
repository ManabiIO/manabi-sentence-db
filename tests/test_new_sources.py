import io
import json
import tarfile
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from manabi_sentence_db.build import canonical_document
from manabi_sentence_db.jmultiwoz import MEMBER
from manabi_sentence_db.jmultiwoz import iter_documents as dialogues
from manabi_sentence_db.serialization import DataError
from manabi_sentence_db.stair import MEMBERS
from manabi_sentence_db.stair import iter_documents as captions
from manabi_sentence_db.validation import load_source


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
