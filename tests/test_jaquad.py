import copy
import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from manabi_sentence_db import jaquad
from manabi_sentence_db.build import canonical_document
from manabi_sentence_db.serialization import DataError, canonical_json
from manabi_sentence_db.snapshot import snapshot_identity
from manabi_sentence_db.transport import snapshot_pack
from manabi_sentence_db.validation import load_source

REVISION = "23f5d72cc273c49b35e2d9efe0f51757aa1770bd"


def _fixture(tmp_path, monkeypatch, *, duplicate_id=False, wrong_license=False):
    monkeypatch.setattr(jaquad, "TRAIN_QUESTIONS", 2)
    monkeypatch.setattr(jaquad, "VALIDATION_QUESTIONS", 1)
    license_bytes = b"Synthetic fixture license text"
    monkeypatch.setattr(
        jaquad, "LICENSE_SHA256", hashlib.sha256(license_bytes).hexdigest()
    )
    source = copy.deepcopy(load_source(Path("sources/jaquad-ja.yaml")))
    source["acquisition"].update(
        train_questions=2, validation_questions=1, size=1,
        license_sha256=hashlib.sha256(license_bytes).hexdigest(),
    )
    root, members = jaquad._members(REVISION)
    path = tmp_path / "jaquad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(root + ".gitignore", "synthetic")
        archive.writestr(root + "JaQuAD.ipynb", "synthetic")
        archive.writestr(root + "LICENSE", b"wrong license" if wrong_license else license_bytes)
        archive.writestr(root + "README.md", "Dataset licensed CC BY-SA 3.0.")
        for index in range(30):
            questions = []
            if index == 0:
                questions = [
                    {"id": "tr-000-00-000", "question": "今日は何曜日ですか?",
                     "question_type": "Syntactic variation",
                     "answers": [{"text": "ANSWER_DO_NOT_IMPORT", "answer_start": 0}]},
                    {"id": "tr-000-00-001" if not duplicate_id else "tr-000-00-000",
                     "question": "今日は何曜日ですか?", "question_type": "Logical reasoning",
                     "answers": [{"text": "ANSWER_DO_NOT_IMPORT", "answer_start": 0}]},
                ]
            data = ([{"title": "ARTICLE_TITLE_DO_NOT_IMPORT", "paragraphs": [{
                "context": "WIKIPEDIA_CONTEXT_DO_NOT_IMPORT", "qas": questions,
            }]}] if index == 0 else [])
            archive.writestr(
                f"{root}data/train/jaquad_train_{index:04d}.json",
                json.dumps({"version": "JaQuAD-version-0.1.0", "data": data}, ensure_ascii=False),
            )
        for index in range(4):
            questions = ([{"id": "de-000-00-000", "question": "今日は何曜日ですか?",
                           "question_type": "Lexical variation (synonymy)",
                           "answers": [{"text": "ANSWER_DO_NOT_IMPORT", "answer_start": 0}]}]
                         if index == 0 else [])
            data = ([{"title": "ARTICLE_TITLE_DO_NOT_IMPORT", "paragraphs": [{
                "context": "WIKIPEDIA_CONTEXT_DO_NOT_IMPORT", "qas": questions,
            }]}] if index == 0 else [])
            archive.writestr(
                f"{root}data/dev/jaquad_dev_{index:04d}.json",
                json.dumps({"version": "JaQuAD-version-0.1.0", "data": data}, ensure_ascii=False),
            )
    source["acquisition"]["size"] = path.stat().st_size
    source["acquisition"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "source_id": source["id"], "source": source,
        "files": [{"role": "jaquad-zip", "path": path.name,
                   "sha256": source["acquisition"]["sha256"],
                   "url": source["acquisition"]["url"]}],
    }
    return manifest, tmp_path


def test_jaquad_emits_question_only_works_and_tracks_duplicate_wording(tmp_path, monkeypatch):
    manifest, root = _fixture(tmp_path, monkeypatch)
    stats = Counter()
    raw = list(jaquad.iter_documents(manifest, root, stats=stats))

    assert len(raw) == 3
    assert [doc["native_id"] for doc in raw] == [
        "tr-000-00-000", "tr-000-00-001", "de-000-00-000",
    ]
    assert all(len(doc["sentences"]) == 1 for doc in raw)
    assert all(doc["authorship"] == "human" for doc in raw)
    assert all(doc["language_origin"] == "unknown" for doc in raw)
    serialized = json.dumps(raw, ensure_ascii=False)
    for excluded in ("ARTICLE_TITLE_DO_NOT_IMPORT", "WIKIPEDIA_CONTEXT_DO_NOT_IMPORT",
                     "ANSWER_DO_NOT_IMPORT"):
        assert excluded not in serialized
    assert stats["train_questions"] == 2
    assert stats["validation_questions"] == 1
    assert stats["duplicate_question_text_groups"] == 1
    assert stats["duplicate_question_text_excess"] == 2

    canonical = canonical_document(raw[0], {**manifest, "snapshot_id": "fixture"},
                                   Counter(), set())
    assert canonical["sentences"][0]["text"] == "今日は何曜日ですか?"
    assert "question-type:syntactic-variation" in canonical["sentences"][0]["tags"]
    assert "split:train" in canonical["tags"]


def test_jaquad_rejects_duplicate_ids_and_bad_license_evidence(tmp_path, monkeypatch):
    manifest, root = _fixture(tmp_path, monkeypatch, duplicate_id=True)
    with pytest.raises(DataError, match="duplicate JaQuAD question ID"):
        list(jaquad.iter_documents(manifest, root))

    manifest, root = _fixture(tmp_path, monkeypatch, wrong_license=True)
    with pytest.raises(DataError, match="LICENSE checksum"):
        list(jaquad.iter_documents(manifest, root))


def test_jaquad_raw_snapshot_cannot_be_published_as_source_bundle(tmp_path):
    source = load_source(Path("sources/jaquad-ja.yaml"))
    raw = tmp_path / "raw.zip"
    raw.write_bytes(b"contains excluded contexts and answers")
    entry = {"path": raw.name, "role": "jaquad-zip", "url": source["acquisition"]["url"],
             "size": raw.stat().st_size, "sha256": hashlib.sha256(raw.read_bytes()).hexdigest()}
    manifest = {
        "schema_version": 1, "source_id": source["id"], "source": source,
        "source_config_sha256": hashlib.sha256(canonical_json(source)).hexdigest(),
        "retrieved_at": "2026-11-24T00:00:00Z", "mode": "full", "upstream_date": None,
        "request": {"mode": "full", "date": None, "max_files": None, "titles": None,
                    "translations": []},
        "files": [entry],
    }
    manifest["snapshot_id"] = snapshot_identity(manifest)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="excluded Wikipedia contexts"):
        snapshot_pack(manifest_path, tmp_path / "public-bundle")
    assert not (tmp_path / "public-bundle").exists()
