"""Pinned human MRMP chat turns; omit participant profiles and evaluations."""

import hashlib
import json
import re
import stat
import zipfile
from contextlib import contextmanager

from .segments import CONTEXT_BREAK
from .serialization import DataError, parse_json, safe_relative

ROLE = "mrmp-zip"
_MEMBER = re.compile(
    r"[^/]+/multi_relational_multi_party_chat_corpus/dialogues/"
    r"(?:(A_first_time)/(A[0-9]{5})|(B_family)/(B[0-9]{5}))\.json"
)


@contextmanager
def _archive(path):
    try:
        with zipfile.ZipFile(path) as archive:
            yield archive
    except zipfile.BadZipFile as exc:
        raise DataError("Invalid MRMP ZIP archive") from exc


def iter_documents(manifest, snapshot_dir):
    source = manifest["source"]
    revision = source["acquisition"].get("revision")
    if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise DataError("MRMP requires an immutable Git revision")
    entries = [item for item in manifest["files"] if item["role"] == ROLE]
    if len(entries) != 1:
        raise DataError("Expected exactly one pinned MRMP archive")
    expected = source["acquisition"].get("dialogue_count")
    if expected is not None and (type(expected) is not int or not 1 <= expected <= 10_000):
        raise DataError("Invalid MRMP dialogue count")
    with _archive(safe_relative(snapshot_dir, entries[0]["path"])) as archive:
        members = [(item, _MEMBER.fullmatch(item.filename)) for item in archive.infolist()]
        members = [(item, match) for item, match in members if match is not None]
        names = [item.filename for item, _ in members]
        identities = [(match[1] or match[3], match[2] or match[4]) for _, match in members]
        if len(names) != len(set(names)) or len(identities) != len(set(identities)):
            raise DataError("Duplicate MRMP dialogue ZIP member")
        if not members or len(members) > 10_000 or (expected is not None and len(members) != expected):
            raise DataError("MRMP dialogue inventory differs from the pinned source")
        roots = {name.split("/", 1)[0] for name in names}
        if len(roots) != 1:
            raise DataError("MRMP archive must contain one publisher root")
        root = next(iter(roots))
        for filename, key in (("LICENSE", "license_sha256"), ("README.md", "readme_sha256")):
            digest = source["acquisition"].get(key)
            name = f"{root}/{filename}"
            if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise DataError("MRMP requires pinned publisher license evidence")
            if archive.namelist().count(name) != 1:
                raise DataError("Missing or duplicate MRMP publisher license evidence")
            info = archive.getinfo(name)
            if (info.file_size > 256 * 1024 or stat.S_ISLNK(info.external_attr >> 16)
                    or hashlib.sha256(archive.read(info)).hexdigest() != digest):
                raise DataError("MRMP publisher license evidence differs from review")
        for item, match in sorted(members, key=lambda pair: pair[0].filename):
            if item.file_size > 2 * 1024**2 or stat.S_ISLNK(item.external_attr >> 16):
                raise DataError("Oversized or symlink MRMP dialogue member")
            group = match[1] or match[3]
            identity = match[2] or match[4]
            raw = archive.read(item)
            try:
                dialogue = parse_json(raw)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise DataError("Invalid MRMP dialogue JSON") from exc
            if not isinstance(dialogue, dict) or dialogue.get("dialogue_id") != identity:
                raise DataError("MRMP dialogue identity disagreement")
            kind = "First time" if group == "A_first_time" else "Family"
            if dialogue.get("dialogue_type") != kind:
                raise DataError("MRMP dialogue type disagreement")
            turns = dialogue.get("utterances")
            if not isinstance(turns, list) or not 1 <= len(turns) <= 1000:
                raise DataError("Invalid MRMP turn collection")
            sentences, previous = [], -1
            for turn in turns:
                if not isinstance(turn, dict):
                    raise DataError("Invalid MRMP utterance")
                number, text = turn.get("utterance_id"), turn.get("text")
                if type(number) is not int or number <= previous or not isinstance(text, str):
                    raise DataError("Invalid, duplicate or unordered MRMP utterance identity/text")
                if number != previous + 1:
                    sentences.append(CONTEXT_BREAK)
                previous = number
                sentences.append({
                    "native_id": str(number), "text": text,
                    "source_range": {"unit": "utterance", "start": number, "end": number + 1},
                    "tags": [], "content_flags": [], "translations": [],
                })
            relative = f"multi_relational_multi_party_chat_corpus/dialogues/{group}/{identity}.json"
            url = f"{source['homepage'].rstrip('/')}/blob/{revision}/{relative}"
            yield {
                "native_id": f"{group}/{identity}", "language": "ja",
                "title": f"MRMP · Dialogue {identity}", "url": url,
                "license": source["license"], "attribution": source["attribution"],
                "revision": {"id": revision, "url": url},
                "tags": ["conversation", "multi-party"], "authorship": "human",
                "language_origin": "original_japanese", "content_type": "dialogue",
                "source_text_hash": hashlib.sha256(raw).hexdigest(), "sentences": sentences,
            }
