"""Pinned TALPCo Japanese examples and original British English translations."""

import hashlib
import re
import unicodedata

from .serialization import DataError, canonical_json, safe_relative

FILES = {"ja": "jpn/data_jpn.txt", "en": "eng/data_eng.txt"}
MAX_FILE_BYTES = 1024 * 1024
TRANSFORMATION = "talpco-bunsetsu-unspacing-v1"


def validate_source(source):
    acquisition = source["acquisition"]
    commit = acquisition.get("version", "")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise DataError("TALPCo requires a pinned publisher commit")
    if (source["id"] != "talpco-ja" or source["language"] != "ja"
            or source["license"] != {"id": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"}):
        raise DataError("Invalid TALPCo source identity or license")
    pins = acquisition.get("files")
    if not isinstance(pins, dict) or set(pins) != set(FILES):
        raise DataError("TALPCo requires exactly Japanese and original English files")
    if type(acquisition.get("pair_count")) is not int or not 1 <= acquisition["pair_count"] <= 10000:
        raise DataError("Invalid TALPCo pair count")
    for language, path in FILES.items():
        pin = pins[language]
        expected = f"https://raw.githubusercontent.com/matbahasa/TALPCo/{commit}/{path}"
        if (not isinstance(pin, dict) or set(pin) != {"url", "size", "sha256"}
                or pin["url"] != expected or type(pin["size"]) is not int
                or not 0 < pin["size"] <= MAX_FILE_BYTES
                or not isinstance(pin["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])):
            raise DataError("Invalid TALPCo file pin")


def _rows(data):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DataError("Invalid TALPCo UTF-8") from error
    rows = {}
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    for line in lines:
        line = line.removesuffix("\r")
        parts = line.split("\t")
        if (len(parts) != 2 or not re.fullmatch(r"[1-9][0-9]*", parts[0])
                or parts[0] in rows or not parts[1].strip()
                or any(unicodedata.category(c) in {"Cc", "Zl", "Zp"} for c in parts[1])):
            raise DataError("Malformed, empty or duplicate TALPCo row")
        rows[parts[0]] = parts[1]
    return rows


def iter_documents(manifest, snapshot_dir, *, stats):
    source = manifest["source"]
    validate_source(source)
    acquisition = source["acquisition"]
    entries = manifest["files"]
    roles = {"talpco-" + language for language in FILES}
    if len(entries) != 2 or {e["role"] for e in entries} != roles:
        raise DataError("TALPCo snapshot file inventory mismatch")
    rows = {}
    for entry in entries:
        language = entry["role"].removeprefix("talpco-")
        pin = acquisition["files"][language]
        path = safe_relative(snapshot_dir, entry["path"])
        if path.stat().st_size != pin["size"]:
            raise DataError("TALPCo file size mismatch")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != pin["sha256"]:
            raise DataError("TALPCo file checksum mismatch")
        rows[language] = _rows(data)
    if (set(rows["ja"]) != set(rows["en"])
            or len(rows["ja"]) != acquisition["pair_count"]):
        raise DataError("TALPCo parallel ID set or row count mismatch")
    commit = acquisition["version"]
    for identity, japanese in rows["ja"].items():
        english = rows["en"][identity]
        stats["publisher_pairs_seen"] += 1
        url = f"https://github.com/matbahasa/TALPCo/blob/{commit}/{FILES['ja']}"
        yield {
            "native_id": identity, "language": "ja", "title": f"TALPCo sentence {identity}",
            "url": url, "license": source["license"], "attribution": source["attribution"],
            "revision": {"id": commit, "url": f"https://github.com/matbahasa/TALPCo/tree/{commit}"},
            "source_text_hash": hashlib.sha256(canonical_json({"id": identity, "ja": japanese, "en": english})).hexdigest(),
            "authorship": "unknown", "language_origin": "original_japanese",
            "content_type": "example-sentence", "tags": ["basic-sentence", "independent-example"],
            "sentences": [{
                # The publisher documents ASCII spaces as bunsetsu annotation,
                # not authorial spacing. Keep raw bytes/hashes in the snapshot
                # and source_text_hash; derive searchable text only here.
                "native_id": identity, "source_ordinal": 0, "text": japanese.replace(" ", ""),
                "tags": [], "content_flags": [],
                "translations": [{
                    "native_id": identity + ":en", "language": "en", "text": english,
                    "source_url": f"https://github.com/matbahasa/TALPCo/blob/{commit}/{FILES['en']}",
                    "license": source["license"], "attribution": source["attribution"],
                    "generation": {"kind": "human"}, "alignment": "human",
                }],
            }],
        }
