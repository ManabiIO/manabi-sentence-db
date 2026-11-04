"""Pinned authored movie-recommendation dialogue, excluding external prose."""

import hashlib
import io
import re
import stat
import unicodedata
import zipfile
from collections import Counter

from .json_stream import array_values
from .segments import CONTEXT_BREAK, MAX_SOURCE_UNIT_CHARS
from .serialization import DataError, canonical_json, safe_relative

ROLE = "jmrd-zip"
TRANSFORMATION = "jmrd-authored-dialogue-v2"
SPLITS = ("train", "valid", "test")
FACTUAL_TYPES = frozenset({"[知識なし]", "タイトル", "製作年度", "監督名", "キャスト名", "ジャンル"})
# Paper section 3.1: reviews were newly written by crowdworkers for this dataset.
# Plots and director/cast descriptions were extracted from Wikipedia instead.
GROUNDING_TYPES = FACTUAL_TYPES | {"レビュー"}


def _comparable(text):
    return "".join(char for char in unicodedata.normalize("NFKC", text) if char.isalnum())


def _without_facts(text, facts):
    result = _comparable(text)
    for fact in facts:
        # Keep a barrier instead of joining previously separate prose spans.
        result = result.replace(fact, "|")
    return result


def _external_prose(knowledge):
    facts = []
    for kind in FACTUAL_TYPES:
        values = knowledge.get(kind, [])
        for value in (values if isinstance(values, list) else [values]):
            if isinstance(value, str) and len(normalized := _comparable(value)) >= 16:
                facts.append(normalized)
    facts = sorted(set(facts), key=lambda value: (-len(value), value))
    result = []
    for kind, values in knowledge.items():
        if kind in GROUNDING_TYPES:
            continue
        for value in (values if isinstance(values, list) else [values]):
            if isinstance(value, str):
                normalized = _without_facts(value, facts)
                if len(normalized) >= 16:
                    result.append(normalized)
    return result, facts


def _copies_prose(text, prose, facts):
    normalized = _without_facts(text, facts)
    for original in prose:
        width = min(24, len(normalized), len(original))
        if width >= 16 and any("|" not in normalized[i:i + width]
                               and normalized[i:i + width] in original
                               for i in range(len(normalized) - width + 1)):
            return True
    return False


def _turns(dialogue, stats):
    identity, turns, knowledge = dialogue.get("dialog_id"), dialogue.get("dialog"), dialogue.get("knowledge")
    if not isinstance(identity, str) or re.fullmatch(r"[0-9]{5}", identity) is None:
        raise DataError("Invalid JMRD dialogue identity")
    if not isinstance(turns, list) or not 1 <= len(turns) <= 1000 or not isinstance(knowledge, dict):
        raise DataError("Invalid JMRD dialogue/knowledge collection")
    external, facts = _external_prose(knowledge)
    previous = -1
    result = []
    for turn in turns:
        if not isinstance(turn, dict):
            raise DataError("Invalid JMRD turn")
        native_id, speaker, text = turn.get("utterance_id"), turn.get("speaker"), turn.get("text")
        match = re.fullmatch(re.escape(identity) + r"_([0-9]+)", native_id) if isinstance(native_id, str) else None
        if (not match or not isinstance(speaker, str) or speaker not in {"seeker", "recommender"}
                or not isinstance(text, str)):
            raise DataError("Invalid JMRD turn identity, role or text")
        number = int(match[1])
        if number <= previous:
            raise DataError("Duplicate or unordered JMRD turn identity")
        if number != previous + 1:
            result.append(CONTEXT_BREAK)
        previous = number
        stats["jmrd_original_turns"] += 1
        reason = None
        if len(text) > MAX_SOURCE_UNIT_CHARS:
            reason = "source-unit-too-long"
        elif "@" in text or "＠" in text:
            reason = "jmrd-addressed-turn"
        elif speaker == "recommender":
            grounding = turn.get("checked_knowledge", [])
            if not isinstance(grounding, list):
                raise DataError("Invalid JMRD knowledge annotation")
            if not grounding:
                reason = "jmrd-missing-grounding"
            for item in grounding:
                if (not isinstance(item, dict) or not isinstance(item.get("type"), str)
                        or not isinstance(item.get("content"), str)):
                    raise DataError("Invalid JMRD knowledge annotation")
                if item["type"] not in GROUNDING_TYPES:
                    reason = "jmrd-external-knowledge"
                else:
                    values = knowledge.get(item["type"])
                    values = values if isinstance(values, list) else [values]
                    if item["content"] not in values:
                        raise DataError("JMRD retained knowledge annotation disagrees with source")
        if reason is None and _copies_prose(text, external, facts):
            reason = "jmrd-external-prose-copy"
        if reason:
            stats["rejected:" + reason] += 1
            result.append(CONTEXT_BREAK)
            continue
        result.append({"native_id": native_id, "text": text,
            "source_range": {"unit": "utterance", "start": number, "end": number + 1},
            "tags": ["speaker:" + speaker], "content_flags": [], "translations": []})
    return result


def iter_documents(manifest, snapshot_dir, *, stats=None):
    stats = stats if stats is not None else Counter()
    source = manifest["source"]
    acquisition = source["acquisition"]
    revision = acquisition.get("revision")
    if not isinstance(revision, str) or re.fullmatch(r"[a-f0-9]{40}", revision) is None:
        raise DataError("JMRD requires a pinned Git revision")
    expected = acquisition.get("dialogue_counts")
    if (not isinstance(expected, dict) or set(expected) != set(SPLITS)
            or any(type(n) is not int or not 0 <= n <= 10000 for n in expected.values())):
        raise DataError("Invalid JMRD pinned dialogue inventory")
    entries = [entry for entry in manifest["files"] if entry["role"] == ROLE]
    if len(entries) != 1:
        raise DataError("Expected exactly one JMRD archive")
    try:
        archive = zipfile.ZipFile(safe_relative(snapshot_dir, entries[0]["path"]))
    except zipfile.BadZipFile as exc:
        raise DataError("Invalid JMRD archive") from exc
    with archive:
        names = [item.filename for item in archive.infolist() if not item.is_dir()]
        roots = {name.split("/", 1)[0] for name in names}
        if len(roots) != 1 or len(names) != len(set(names)):
            raise DataError("Invalid or duplicate JMRD archive inventory")
        root = next(iter(roots))
        for filename, key in (("LICENSE", "license_sha256"), ("README.md", "readme_sha256")):
            name = f"{root}/{filename}"
            expected_hash = acquisition.get(key)
            if (name not in names or not isinstance(expected_hash, str)
                    or re.fullmatch(r"[a-f0-9]{64}", expected_hash) is None):
                raise DataError("Missing JMRD publisher license evidence")
            info = archive.getinfo(name)
            if (info.file_size > 256 * 1024 or stat.S_ISLNK(info.external_attr >> 16)
                    or hashlib.sha256(archive.read(info)).hexdigest() != expected_hash):
                raise DataError("JMRD publisher license evidence differs from review")
        seen = set()
        for split in SPLITS:
            member = f"{root}/data/{split}.json"
            if member not in names:
                raise DataError("Missing JMRD split inventory")
            info = archive.getinfo(member)
            if stat.S_ISLNK(info.external_attr >> 16) or info.file_size > 128 * 1024**2:
                raise DataError("Oversized or symlink JMRD split")
            count = 0
            url = f"{source['homepage']}/blob/{revision}/data/{split}.json"
            with archive.open(info) as binary, io.TextIOWrapper(binary, encoding="utf-8") as stream:
                for dialogue in array_values(stream):
                    if not isinstance(dialogue, dict):
                        raise DataError("Invalid JMRD dialogue object")
                    sentences = _turns(dialogue, stats)
                    identity = dialogue["dialog_id"]
                    if identity in seen:
                        raise DataError("Duplicate JMRD dialogue across source splits")
                    seen.add(identity)
                    count += 1
                    yield {"native_id": identity, "language": "ja",
                        "title": f"JMRD · Dialogue {identity}", "url": url,
                        "license": source["license"], "attribution": source["attribution"],
                        "revision": {"id": revision, "url": url},
                        "tags": ["conversation", "movie-recommendation", "dataset-split:" + split],
                        "authorship": "human", "language_origin": "original_japanese",
                        "content_type": "dialogue", "sentences": sentences,
                        "source_text_hash": hashlib.sha256(canonical_json(dialogue)).hexdigest()}
            if count != expected[split]:
                raise DataError("JMRD split dialogue inventory differs from the pinned source")
