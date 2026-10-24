"""Pinned human Wizard-of-Oz dialogue turns, excluding goals and model outputs."""

import hashlib
import io
import re
import zipfile

from .json_stream import object_items
from .serialization import DataError, canonical_json, safe_relative

MEMBER = "JMultiWOZ_1.0/dialogues.json"


def iter_documents(manifest, snapshot_dir):
    source = manifest["source"]
    revision = source["acquisition"]["revision"]
    url = f"{source['homepage']}/blob/{revision}/dataset/JMultiWOZ_1.0.zip"
    for entry in manifest["files"]:
        if entry["role"] != "jmultiwoz-zip":
            continue
        with zipfile.ZipFile(safe_relative(snapshot_dir, entry["path"])) as archive:
            if archive.namelist().count(MEMBER) != 1:
                raise DataError("Expected one JMultiWOZ human dialogue member")
            if archive.getinfo(MEMBER).file_size > 512 * 1024**2:
                raise DataError("Oversized JMultiWOZ dialogue member")
            with (archive.open(MEMBER) as raw_stream,
                  io.TextIOWrapper(raw_stream, encoding="utf-8") as stream):
                for identity, dialogue in object_items(stream):
                    if not re.fullmatch(r"dialogue_[A-Za-z0-9]+", identity):
                        raise DataError("Invalid JMultiWOZ dialogue identity")
                    if not isinstance(dialogue, dict) or dialogue.get("dialogue_name") != identity:
                        raise DataError("JMultiWOZ dialogue identity disagreement")
                    turns = dialogue.get("turns")
                    if not isinstance(turns, list) or len(turns) > 1000:
                        raise DataError("Invalid JMultiWOZ turn collection")
                    sentences, seen = [], set()
                    for turn in turns:
                        if not isinstance(turn, dict):
                            raise DataError("Invalid JMultiWOZ turn")
                        native_id = turn.get("turn_id")
                        if type(native_id) is not int or native_id < 0 or native_id in seen:
                            raise DataError("Invalid or duplicate JMultiWOZ turn identity")
                        seen.add(native_id)
                        if turn.get("speaker") not in {"USER", "SYSTEM"}:
                            raise DataError("Unknown JMultiWOZ speaker role")
                        if not isinstance(turn.get("utterance"), str):
                            raise DataError("Invalid JMultiWOZ utterance")
                        sentences.append({
                            "native_id": str(native_id),
                            "text": turn["utterance"],
                            "source_range": {"unit": "utterance", "start": native_id,
                                             "end": native_id + 1},
                            "tags": [f"speaker:{turn['speaker'].lower()}", "role-play"],
                            "content_flags": [],
                            "translations": [],
                        })
                    yield {
                        "native_id": identity,
                        "language": "ja",
                        "title": f"JMultiWOZ · {identity}",
                        "url": url,
                        "license": source["license"],
                        "attribution": source["attribution"],
                        "revision": {"id": revision, "url": url},
                        "tags": ["conversation", "role-play", "task-oriented"],
                        "authorship": "human",
                        "language_origin": "original_japanese",
                        "content_type": "dialogue",
                        "source_text_hash": hashlib.sha256(canonical_json(dialogue)).hexdigest(),
                        "sentences": sentences,
                    }
