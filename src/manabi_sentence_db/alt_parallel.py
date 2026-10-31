"""NICT ALT parallel text only; English originals paired with Japanese translations."""

import hashlib
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import unquote

from .serialization import DataError, parse_json, safe_relative
from .text import is_complete_sentence

ROLE = "alt-parallel-zip"
PREFIX = "ALT-Parallel-Corpus-20191206/"
MAX_MEMBER_BYTES = 16 * 1024**2
MAX_TOTAL_BYTES = 100 * 1024**2
EN_LICENSE = {"id": "CC-BY-2.5", "url": "https://creativecommons.org/licenses/by/2.5/"}


_REVIEW_DATA = Path(__file__).with_name("alt_reviewed_exclusions.json").read_bytes()
_REVIEW = parse_json(_REVIEW_DATA.decode())
if (not isinstance(_REVIEW, dict) or _REVIEW.get("schema_version") != 1
        or _REVIEW.get("policy") != "alt-reviewed-pair-exclusions-v1"
        or type(_REVIEW.get("schema_version")) is not int
        or _REVIEW.get("release") != "20191206" or _REVIEW.get("reviewer") != "assistant"
        or not isinstance(_REVIEW.get("archive_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", _REVIEW["archive_sha256"])
        or not isinstance(_REVIEW.get("pairs"), list) or not 1 <= len(_REVIEW["pairs"]) <= 1000):
    raise DataError("Invalid reviewed ALT pair inventory")
REVIEW_EXCLUSIONS = {}
for _pair in _REVIEW["pairs"]:
    if (not isinstance(_pair, dict) or set(_pair) != {"native_id", "japanese_sha256", "english_sha256", "reason", "original_url"}
            or not isinstance(_pair["native_id"], str)
            or not re.fullmatch(r"SNT\.[1-9][0-9]*\.[1-9][0-9]*(?:-[0-9]+)?", _pair["native_id"])
            or _pair["native_id"] in REVIEW_EXCLUSIONS
            or any(not isinstance(_pair.get(k), str) or not re.fullmatch(r"[0-9a-f]{64}", _pair[k])
                   for k in ("japanese_sha256", "english_sha256"))
            or _pair.get("reason") not in {"conflicting-speed-value", "conflicting-turnout-value", "conflicting-exchange-rate",
                                          "conflicting-field-dimension", "conflicting-year", "unrelated-source-translation-pair"}
            or not isinstance(_pair["original_url"], str)
            or not re.fullmatch(r"https?://en\.wikinews\.org/wiki/[^\s]+", _pair["original_url"])):
        raise DataError("Invalid reviewed ALT pair entry")
    REVIEW_EXCLUSIONS[_pair["native_id"]] = _pair
REVIEW_TRANSFORMATION = "alt-reviewed-pair-exclusions-v1:" + hashlib.sha256(_REVIEW_DATA).hexdigest()


def reviewed_pair_reason(identity, text, original, url):
    """Withhold only the independently reviewed, exact hash-pinned pair."""
    pair = REVIEW_EXCLUSIONS.get(identity)
    if pair is None:
        return None
    def digest(value):
        return hashlib.sha256(unicodedata.normalize("NFC", value.strip()).encode()).hexdigest()
    if (digest(text) != pair["japanese_sha256"] or digest(original) != pair["english_sha256"]
            or url != pair["original_url"]):
        raise DataError("Reviewed ALT pair changed; review new source text before admission")
    return pair["reason"]


def _rows(data, pattern, *, pairs=False):
    rows = [] if pairs else {}
    for line in data.decode("utf-8").splitlines():
        parts = line.split("\t")
        if pairs and len(parts) == 1:
            parts.append("")
        if (
            len(parts) != 2
            or not re.fullmatch(pattern, parts[0])
            or (not pairs and parts[0] in rows)
        ):
            raise DataError("Invalid or duplicate ALT row identity")
        if pairs:
            rows.append(parts)
        else:
            rows[parts[0]] = parts[1]
    return rows


def iter_documents(manifest, snapshot_dir, *, stats):
    source = manifest["source"]
    acquisition = source["acquisition"]
    entries = [e for e in manifest["files"] if e["role"] == ROLE]
    if len(entries) != 1:
        raise DataError("ALT requires exactly one pinned parallel-text archive")
    with zipfile.ZipFile(safe_relative(snapshot_dir, entries[0]["path"])) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        expected = acquisition["members"]
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise DataError("ALT archive inventory mismatch")
        if sum(i.file_size for i in infos) > MAX_TOTAL_BYTES:
            raise DataError("ALT archive exceeds uncompressed bound")
        selected = {}
        for info in infos:
            pin = expected[info.filename]
            if (
                info.file_size > MAX_MEMBER_BYTES
                or info.file_size != pin["size"]
                or info.flag_bits & 1
                or info.external_attr >> 16 & 0o170000 == 0o120000
            ):
                raise DataError("Invalid or oversized ALT member")
            data = archive.read(info)
            if hashlib.sha256(data).hexdigest() != pin["sha256"]:
                raise DataError("ALT member checksum mismatch")
            if info.filename in {
                PREFIX + n for n in ("README.txt", "URL.txt", "data_ja.txt", "data_en.txt")
            }:
                selected[info.filename.removeprefix(PREFIX)] = data
    if set(selected) != {"README.txt", "URL.txt", "data_ja.txt", "data_en.txt"}:
        raise DataError("Missing ALT parallel-text metadata")
    urls = _rows(selected["URL.txt"], r"URL\.[1-9][0-9]*")
    japanese = _rows(
        selected["data_ja.txt"], r"SNT\.[1-9][0-9]*\.[1-9][0-9]*(?:-[0-9]*)?", pairs=True
    )
    english = _rows(
        selected["data_en.txt"], r"SNT\.[1-9][0-9]*\.[1-9][0-9]*(?:-[0-9]*)?", pairs=True
    )
    if len(japanese) != len(english) or len(japanese) != acquisition["pair_count"]:
        raise DataError("ALT parallel row count mismatch")
    if len(urls) != acquisition["article_count"]:
        raise DataError("ALT article inventory mismatch")
    duplicates = {i for i, count in Counter(i for i, _ in japanese).items() if count > 1}
    english_duplicates = {i for i, count in Counter(i for i, _ in english).items() if count > 1}
    grouped = defaultdict(list)
    for (identity, text), (english_id, original) in zip(japanese, english, strict=True):
        article = identity.split(".")[1]
        if "URL." + article not in urls:
            raise DataError("ALT sentence missing article URL")
        # Preserve barriers for publisher identity defects, never guess a repair.
        defect = (identity != english_id or identity in duplicates
                  or english_id in english_duplicates or identity.endswith("-"))
        grouped[article].append((identity, text, original, defect))
    stats["url-map-articles-without-pairs"] += len(urls) - len(grouped)
    if (acquisition.get("sha256") == _REVIEW["archive_sha256"]
            and not set(REVIEW_EXCLUSIONS).issubset(identity for identity, _ in japanese)):
        raise DataError("Reviewed ALT pair inventory is missing from its pinned release")
    for article, rows in grouped.items():
        url = urls["URL." + article]
        if not re.fullmatch(r"https?://en\.wikinews\.org/wiki/[^\s]+", url):
            raise DataError("Invalid ALT original article URL")
        credit = {
            "text": "English Wikinews contributors; original English text (CC BY 2.5).",
            "url": url + "?action=history",
        }
        sentences = []
        for ordinal, (identity, text, original, defect) in enumerate(rows):
            stats["publisher_pairs_seen"] += 1
            reason = None
            if defect:
                reason = "publisher-identity-defect"
            elif not text.strip() or not original.strip():
                reason = "empty-pair"
            elif (
                any(c in text for c in '「」『』“”"')
                or any(c in original for c in '“”"')
                or re.search(r"(?<!\w)'[^'\r\n]{2,}'(?!\w)", original)
                or re.search(r"‘[^’\r\n]{2,}’", original)
            ):
                reason = "quotation-or-title"
            elif not is_complete_sentence(text):
                reason = "incomplete-prose"
            reviewed = reviewed_pair_reason(identity, text, original, url)
            if reviewed:
                stats["rejected:alt-reviewed-pair"] += 1
                stats["reviewed-pair-exclusion:" + reviewed] += 1
                continue
            if reason:
                stats["rejected:alt-" + reason] += 1
                continue
            sentences.append(
                {
                    "native_id": identity,
                    "source_ordinal": ordinal,
                    "text": text,
                    "source_range": {"unit": "utterance", "start": ordinal, "end": ordinal + 1},
                    "tags": ["translation:from-english", "translation:method-unknown"],
                    "content_flags": [],
                    "translations": [
                        {
                            "native_id": identity + ":en-original",
                            "language": "en",
                            "text": original,
                            "source_url": url,
                            "license": EN_LICENSE,
                            "attribution": credit,
                            "alignment": "unknown",
                        }
                    ],
                }
            )
        yield {
            "native_id": "URL." + article,
            "language": "ja",
            "title": unquote(url.split("/wiki/", 1)[1]).replace("_", " "),
            "url": url,
            "license": source["license"],
            "attribution": {
                "text": source["attribution"]["text"] + " Original article: " + url,
                "url": credit["url"],
            },
            "revision": {"id": "ALT-20191206", "url": acquisition["url"]},
            "source_text_hash": hashlib.sha256(
                "\n".join(f"{i}\t{ja}\t{en}" for i, ja, en, _ in rows).encode()
            ).hexdigest(),
            "authorship": "unknown",
            "language_origin": "unknown",
            "content_type": "news",
            "tags": [
                "translation:from-english",
                "translation:method-unknown",
                "english:original-source",
            ],
            "sentences": sentences,
        }
