"""Bounded, pinned ASDC main human dialogue text only."""

import hashlib
import json
import re
import stat
import zipfile

from .segments import CONTEXT_BREAK
from .serialization import DataError, parse_json, safe_relative

ROLE = "asdc-zip"
REVISION = "f37d6575c73602adcb8ae3687520726793baa672"
ROOT = "asdc-" + REVISION
EVIDENCE = {
    "README.md": "9a60f1c822e5a1c88c45fb81bf4983e71af9b7998b46a4514cd9e61695755244",
    "LICENSE.txt": "9ba9550ad48438d0836ddab3da480b3b69ffa0aac7b7878b5a0039e7ab429411",
    "docs/dialog/collection.md": "9fa48321d51afb5c2e6209832216e30b818c953245a1d0df976896c6c50c82e3",
    "docs/dialog/format.md": "daf61eff83c2bb035872c234d8114c1e87e2c20e8bfbf8c833bfd1c2972643ba",
}

_BOOKING_SLOT = re.compile(
    r"^・(?:日付|時期|日程|宿泊日数|宿泊数|泊数|人数|場所|宿泊地|行先|予算|ご予算)は"
)
_SUMMARY_PREAMBLE = (
    "ご希望をお聞かせくださり、ありがとうございました。それでは以下の条件で"
    "お調べしますので、よろしくお願いいたします。"
)


def _is_booking_summary(text):
    """Recognize the pinned main corpus's operator booking checklists only."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and lines[0] == _SUMMARY_PREAMBLE:
        lines = lines[1:]
    return (len(lines) >= 6 and all(line.startswith("・") for line in lines)
            and sum(bool(_BOOKING_SLOT.match(line)) for line in lines) >= 2)


def iter_documents(manifest, snapshot_dir):
    source = manifest["source"]
    acquisition = source["acquisition"]
    if (acquisition.get("revision") != REVISION
            or type(acquisition.get("dialogue_count")) is not int
            or acquisition.get("dialogue_count") != 210):
        raise DataError("ASDC requires the reviewed revision and 210 main dialogues")
    if source["homepage"] != "https://github.com/megagonlabs/asdc":
        raise DataError("ASDC publisher URL differs from review")
    if source["license"] != {
        "id": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/",
    }:
        raise DataError("ASDC corpus requires CC BY 4.0")
    if acquisition.get("evidence_sha256") != EVIDENCE:
        raise DataError("ASDC publisher evidence pins differ from review")
    entries = [item for item in manifest["files"] if item["role"] == ROLE]
    if len(entries) != 1:
        raise DataError("Expected exactly one ASDC archive")
    try:
        with zipfile.ZipFile(safe_relative(snapshot_dir, entries[0]["path"])) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if len(infos) > 20000 or len(names) != len(set(names)):
                raise DataError("Oversized or duplicate ASDC ZIP inventory")
            for info in infos:
                parts = info.filename.rstrip("/").split("/")
                if (not parts or parts[0] != ROOT or any(p in {"", ".", ".."} for p in parts)
                        or "\\" in info.filename or stat.S_ISLNK(info.external_attr >> 16)):
                    raise DataError("Invalid ASDC publisher root/member")
            prefix = ROOT + "/data/main/dialog/json/"
            expected = {prefix + f"{n:03}.json" for n in range(1, 211)}
            actual = {i.filename for i in infos if i.filename.startswith(prefix) and not i.is_dir()}
            if actual != expected:
                raise DataError("ASDC main dialogue inventory differs from review")
            # Check every selected member's size and all rights evidence before decoding any turn.
            if (any(archive.getinfo(name).file_size > 2 * 1024**2 for name in expected)
                    or sum(archive.getinfo(name).file_size for name in expected) > 32 * 1024**2):
                raise DataError("Oversized ASDC dialogue member")
            for relative, digest in EVIDENCE.items():
                name = ROOT + "/" + relative
                if name not in names or archive.getinfo(name).file_size > 256 * 1024:
                    raise DataError("Missing or oversized ASDC publisher evidence")
                if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                    raise DataError("ASDC publisher evidence differs from review")
            for name in sorted(expected):
                raw = archive.read(name)
                try:
                    dialogue = parse_json(raw)
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise DataError("Invalid ASDC JSON") from exc
                number = name.rsplit("/", 1)[1][:-5]
                identity = "asdc.v4." + number
                if (not isinstance(dialogue, dict) or not isinstance(dialogue.get("meta"), dict)
                        or dialogue["meta"].get("id") != {"id": identity}):
                    raise DataError("ASDC dialogue identity disagreement")
                turns = dialogue.get("utterances")
                if not isinstance(turns, list) or not 1 <= len(turns) <= 1000:
                    raise DataError("Invalid ASDC utterance collection")
                sentences, previous = [], -1
                for turn in turns:
                    if not isinstance(turn, dict) or "text_fixed" in turn:
                        raise DataError("ASDC corrected/invalid utterance requires separate review (text_fixed)")
                    native = turn.get("id")
                    match = (
                        re.fullmatch(re.escape(identity) + r"\.(0|[1-9][0-9]{0,5})", native["id"])
                        if isinstance(native, dict) and isinstance(native.get("id"), str)
                        else None
                    )
                    role = (
                        re.fullmatch(r"(operator|customer)_[1-9][0-9]*", turn["name"])
                        if isinstance(turn.get("name"), str) else None
                    )
                    if (not match or set(native) != {"id"} or not role
                            or not isinstance(turn.get("text"), str)):
                        raise DataError("Invalid ASDC utterance identity, role or text")
                    index = int(match[1])
                    if index <= previous:
                        raise DataError("Duplicate or unordered ASDC turn identity")
                    if index != previous + 1:
                        sentences.append(CONTEXT_BREAK)
                    previous = index
                    if role[1] == "operator" and _is_booking_summary(turn["text"]):
                        # Withhold the whole turn before segmentation/source_unit creation.
                        sentences.append(CONTEXT_BREAK)
                        continue
                    sentences.append({"native_id": native["id"], "text": turn["text"],
                                      "source_range": {"unit": "utterance", "start": index, "end": index + 1},
                                      "tags": ["speaker:" + role[1]], "content_flags": [], "translations": []})
                relative = name[len(ROOT) + 1:]
                url = f"{source['homepage']}/blob/{REVISION}/{relative}"
                yield {"native_id": identity, "language": "ja", "title": f"ASDC · Dialogue {number}",
                       "url": url, "revision": {"id": REVISION, "url": url},
                       "license": source["license"], "attribution": source["attribution"],
                       "tags": ["conversation", "accommodation"], "authorship": "human",
                       "language_origin": "original_japanese", "content_type": "dialogue",
                       "source_text_hash": hashlib.sha256(raw).hexdigest(), "sentences": sentences}
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise DataError("Invalid ASDC ZIP archive") from exc
