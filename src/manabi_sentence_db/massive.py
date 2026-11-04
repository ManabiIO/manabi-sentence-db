"""Pinned, human-localized Japanese requests with independent publisher reviews."""

import hashlib
import io
import re
import tarfile
from collections import Counter
from pathlib import PurePosixPath

import zstandard

from .serialization import DataError, canonical_json, parse_json, safe_relative

ROLE = "massive-tar"
TRANSFORMATION = "massive-reviewed-japanese-localization-v1"
MAX_MEMBER_BYTES = 32 * 1024**2
MAX_TOTAL_BYTES = 1024**3
MAX_ROW_BYTES = 64 * 1024
LANGUAGES = {"target", "english", "other", "target & english", "target & other",
             "english & other", "target & english & other"}


def validate_source(source):
    acquisition = source["acquisition"]
    counts = acquisition.get("partition_counts")
    notice = acquisition.get("publisher_notice", {})
    if (source["language"] != "ja" or source["license"]["id"] != "CC-BY-4.0"
            or acquisition.get("version") != "1.1" or not isinstance(counts, dict)
            or set(counts) != {"train", "dev", "test"}
            or any(type(n) is not int or not 0 <= n <= 20000 for n in counts.values())
            or not 1 <= sum(counts.values()) <= 20000
            or not isinstance(notice, dict)
            or not isinstance(notice.get("url"), str)
            or type(notice.get("size")) is not int or not 1 <= notice["size"] <= 128 * 1024
            or not isinstance(notice.get("sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", notice["sha256"])
            or type(acquisition.get("size")) is not int
            or not 1 <= acquisition["size"] <= 64 * 1024**2
            or not isinstance(acquisition.get("sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", acquisition["sha256"])
            or not isinstance(acquisition.get("archive_notice_sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", acquisition["archive_notice_sha256"])):
        raise DataError("Invalid pinned MASSIVE Japanese source/evidence inventory")


def _archive(manifest, snapshot_dir, stats):
    """Scan once, retaining only compressed Japanese; require rights before yield.

    The data LICENSE may follow the locale files in the TAR. Do not yield text
    until the entire bounded inventory and licensing evidence have been checked.
    No TAR member is extracted to disk, and no other locale is retained.
    """
    source = manifest["source"]
    pin = source["acquisition"]["publisher_notice"]
    notice = [e for e in manifest["files"] if e["role"] == "massive-publisher-notice"]
    entries = [e for e in manifest["files"] if e["role"] == ROLE]
    if len(entries) != 1 or len(notice) != 1:
        raise DataError("MASSIVE requires exactly one archive and publisher notice")
    if any(entries[0].get(key) != source["acquisition"][key] for key in ("size", "sha256")):
        raise DataError("MASSIVE archive entry differs from the pinned source")
    notice_path = safe_relative(snapshot_dir, notice[0]["path"])
    if notice_path.stat().st_size != pin["size"]:
        raise DataError("MASSIVE publisher notice size differs from review")
    evidence = notice_path.read_bytes()
    if len(evidence) != pin["size"] or hashlib.sha256(evidence).hexdigest() != pin["sha256"]:
        raise DataError("MASSIVE publisher license notice differs from the reviewed evidence")
    compressed = io.BytesIO()
    seen, required = set(), set()
    total = 0
    with tarfile.open(safe_relative(snapshot_dir, entries[0]["path"]), mode="r|gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if (member.name != str(path) and not (member.isdir() and member.name == str(path) + "/")
                    or path.is_absolute() or ".." in path.parts
                    or not path.parts or path.parts[0] != "1.1" or str(path) in seen
                    or not (member.isfile() or member.isdir()) or member.size < 0
                    or member.size > MAX_MEMBER_BYTES or len(seen) >= 100):
                raise DataError("Unsafe, duplicate or oversized MASSIVE archive member")
            seen.add(str(path))
            total += member.size
            if total > MAX_TOTAL_BYTES:
                raise DataError("MASSIVE archive exceeds its uncompressed bound")
            if member.name not in {"1.1/LICENSE", "1.1/NOTICE.md", "1.1/data/ja-JP.jsonl"}:
                continue
            if not member.isfile():
                raise DataError("MASSIVE selected evidence/text member is not a regular file")
            required.add(member.name)
            with archive.extractfile(member) as stream:
                if member.name.endswith(".jsonl"):
                    with zstandard.ZstdCompressor(level=3).stream_writer(compressed, closefd=False) as out:
                        while chunk := stream.read(1024 * 1024):
                            out.write(chunk)
                    stats["massive_japanese_member_bytes"] = member.size
                else:
                    if member.size > 128 * 1024:
                        raise DataError("Oversized MASSIVE license evidence")
                    data = stream.read()
                    if member.name.endswith("NOTICE.md"):
                        if hashlib.sha256(data).hexdigest() != source["acquisition"]["archive_notice_sha256"]:
                            raise DataError("MASSIVE inherited SLURP notice differs from review")
                    elif (b"Attribution 4.0 International" not in data
                          or b"Creative Commons Attribution 4.0 International Public License" not in data):
                        raise DataError("Unexpected MASSIVE data license")
    if required != {"1.1/LICENSE", "1.1/NOTICE.md", "1.1/data/ja-JP.jsonl"}:
        raise DataError("Missing MASSIVE text or license evidence")
    stats["massive_archive_members"] = len(seen)
    stats["massive_archive_uncompressed_bytes"] = total
    compressed.seek(0)
    return compressed


def _worker(value):
    if (type(value) not in {str, int} or not str(value) or len(str(value)) > 64
            or (type(value) is int and value < 0)):
        raise DataError("Invalid MASSIVE worker identity")
    return str(value)


def _review_reason(row):
    author = _worker(row.get("worker_id"))
    reviews = row.get("judgments")
    if not isinstance(reviews, list) or len(reviews) > 20:
        raise DataError("Invalid MASSIVE review collection")
    independent, seen = [], set()
    for review in reviews:
        if not isinstance(review, dict):
            raise DataError("Invalid MASSIVE review")
        reviewer = _worker(review.get("worker_id"))
        if reviewer in seen:
            raise DataError("Duplicate MASSIVE reviewer identity")
        seen.add(reviewer)
        for field, allowed in [("intent_score", {0, 1, 2}), ("slots_score", {0, 1, 2}),
                               ("grammar_score", {0, 1, 2, 3, 4}), ("spelling_score", {0, 1, 2})]:
            if type(review.get(field)) is not int or review[field] not in allowed:
                raise DataError("Invalid MASSIVE review score")
        if not isinstance(review.get("language_identification"), str) or review["language_identification"] not in LANGUAGES:
            raise DataError("Invalid MASSIVE review language")
        if reviewer != author:
            independent.append(review)
    if len(independent) < 2:
        return "massive-insufficient-independent-review"
    if any(r["grammar_score"] < 3 or r["spelling_score"] != 2
           or r["intent_score"] == 0 or r["slots_score"] == 0
           or r["language_identification"] not in {"target", "target & english"}
           for r in independent):
        return "massive-adverse-independent-review"
    return None


def iter_documents(manifest, snapshot_dir, *, stats=None):
    stats = stats if stats is not None else Counter()
    source = manifest["source"]
    validate_source(source)
    try:
        compressed = _archive(manifest, snapshot_dir, stats)
        identities, counts = set(), Counter()
        with compressed, zstandard.ZstdDecompressor().stream_reader(compressed) as reader:
            with io.BufferedReader(reader) as stream:
                while line := stream.readline(MAX_ROW_BYTES + 1):
                    if len(line) > MAX_ROW_BYTES:
                        raise DataError("Oversized MASSIVE Japanese row")
                    row = parse_json(line)
                    if not isinstance(row, dict):
                        raise DataError("Invalid MASSIVE Japanese row")
                    identity, text = row.get("id"), row.get("utt")
                    partition, scenario, intent = (row.get(k) for k in ("partition", "scenario", "intent"))
                    if (type(identity) not in {str, int} or not re.fullmatch(r"[0-9]{1,8}", str(identity))
                            or row.get("locale") != "ja-JP" or not isinstance(partition, str)
                            or partition not in {"train", "dev", "test"}
                            or not isinstance(text, str) or not text.strip()
                            or any(not isinstance(v, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", v)
                                   for v in (scenario, intent))):
                        raise DataError("Invalid MASSIVE Japanese identity/locale/text metadata")
                    identity = str(identity)
                    if identity in identities:
                        raise DataError("Duplicate MASSIVE utterance identity")
                    identities.add(identity)
                    counts[partition] += 1
                    if counts[partition] > source["acquisition"]["partition_counts"][partition]:
                        raise DataError("MASSIVE partition exceeds pinned inventory")
                    stats["massive_rows_seen"] += 1
                    reason = _review_reason(row)
                    if reason:
                        stats["rejected:" + reason] += 1
                        continue
                    url = source["acquisition"]["url"]
                    yield {"native_id": "ja-JP/" + identity, "language": "ja",
                        "title": f"MASSIVE · ja-JP · utterance {identity}", "url": url,
                        "revision": {"id": "MASSIVE-1.1", "url": url},
                        "license": source["license"], "attribution": source["attribution"],
                        "authorship": "human", "language_origin": "human_translation",
                        "content_type": "assistant-request",
                        "tags": ["translation:from-english", "translation:human-localization",
                                 "upstream:independent-grammar-review", "dataset-split:" + partition,
                                 "scenario:" + scenario, "intent:" + intent],
                        "source_text_hash": hashlib.sha256(canonical_json(row)).hexdigest(),
                        "sentences": [{"native_id": identity, "text": text,
                                       "tags": [], "content_flags": [], "translations": []}]}
        if dict(counts) != {k: v for k, v in source["acquisition"]["partition_counts"].items() if v}:
            raise DataError("MASSIVE Japanese partition inventory differs from the pinned release")
    except (tarfile.TarError, OSError, EOFError, UnicodeError) as exc:
        raise DataError("Malformed MASSIVE compressed source") from exc
