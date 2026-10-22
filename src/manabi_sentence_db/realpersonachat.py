"""Read only human dialogue turns; never participant profiles or model experiments."""

import hashlib
import json
import re
import zipfile
from pathlib import Path

from .serialization import DataError, safe_relative


def iter_documents(manifest, snapshot_dir):
    source = manifest["source"]
    revision = source["acquisition"]["revision"]
    for entry in manifest["files"]:
        if entry["role"] != "realpersonachat-zip":
            continue
        with zipfile.ZipFile(safe_relative(snapshot_dir, entry["path"])) as archive:
            for name in sorted(archive.namelist()):
                if not re.fullmatch(r"[^/]+/real_persona_chat/dialogues/[0-9]+\.json", name):
                    continue
                if archive.getinfo(name).file_size > 2 * 1024**2:
                    raise DataError("Oversized dialogue")
                raw = archive.read(name)
                dialogue = json.loads(raw)
                identity = Path(name).stem
                url = f"{source['homepage']}/blob/{revision}/real_persona_chat/dialogues/{identity.zfill(5)}.json"
                yield {
                    "native_id": identity,
                    "language": "ja",
                    "title": f"RealPersonaChat · Dialogue {identity}",
                    "url": url,
                    "license": source["license"],
                    "attribution": source["attribution"],
                    "revision": {"id": revision, "url": url},
                    "tags": ["conversation"],
                    "authorship": "human",
                    "language_origin": "original_japanese",
                    "content_type": "dialogue",
                    "source_text_hash": hashlib.sha256(raw).hexdigest(),
                    "sentences": [
                        {
                            "native_id": str(turn["utterance_id"]),
                            "text": turn["text"],
                            "source_range": {
                                "unit": "utterance",
                                "start": turn["utterance_id"],
                                "end": turn["utterance_id"] + 1,
                            },
                            "tags": [],
                            "content_flags": [],
                            "translations": [],
                        }
                        for turn in dialogue["utterances"]
                    ],
                }
