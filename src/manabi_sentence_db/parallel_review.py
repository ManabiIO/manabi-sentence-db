"""Conservative numeric disagreement diagnostics for existing parallel text.

A signal proposes review; it never proves a mistranslation, edits a source,
changes generation metadata or excludes corpus content.
"""

import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

import zstandard

from .build import iter_records, verify_build
from .serialization import DataError, canonical_json, sha256_file

VERSION = "parallel-number-review-v2"
MAX_UNIT_CHARS = 32768
MAX_PACKET_BYTES = 8 * 1024**2
# Internal commas stay in the token for grouping validation. A trailing comma
# belongs to ordinary prose punctuation, not to the numeral itself.
_NUMBER = re.compile(r"[+\-]?[0-9](?:[0-9,]*[0-9])?(?:\.[0-9]+)?")
_VALID = re.compile(r"[+\-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?\Z")
_SCALE = re.compile(r"[0-9][\s]*(?:十|百|千|万|億|兆)|\b(?:hundred|thousand|million|billion|trillion)\b", re.I)
_STRUCTURED = re.compile(r"[0-9]%?\s*[-–—/:]\s*[0-9]|[0-9]\s*(?:月|日|時|分|秒)|マイナス|\bminus\b"
    r"|\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\b", re.I)


def _numbers(text):
    if not isinstance(text, str) or len(text) > MAX_UNIT_CHARS:
        return None, "oversized-or-invalid-unit"
    text = unicodedata.normalize("NFKC", text)
    # U+2212 can be a minus or a copied place/date separator in publisher prose.
    # Do not silently drop it or assert a sign interpretation.
    if "−" in text:
        return None, "unsupported-sign-or-operator"
    if _SCALE.search(text):
        return None, "magnitude-notation"
    if _STRUCTURED.search(text):
        return None, "date-time-range-or-written-sign"
    numbers = []
    for match in _NUMBER.finditer(text):
        raw = match[0]
        before, after = text[max(0, match.start() - 1):match.start()], text[match.end():match.end() + 1]
        if any(char.isascii() and (char.isalpha() or char == "_") for char in before + after):
            return None, "identifier-or-ordinal"
        if before in {"+", "-"} or after in {"+", "-"}:
            return None, "unsupported-sign-or-operator"
        if after == "," and text[match.end() + 1:match.end() + 2] == ",":
            return None, "unsupported-grouping"
        if before in {".", ","} or (after in {".", ","} and text[match.end() + 1:match.end() + 2].isdigit()):
            return None, "unsupported-decimal"
        if not _VALID.fullmatch(raw):
            return None, "unsupported-grouping"
        numbers.append(Decimal(raw.replace(",", "")))
    return Counter(numbers), None


def number_signal(original, translation):
    """Return a diagnostic status; unsupported notation is never a conflict."""
    first, reason = _numbers(original)
    if reason:
        return reason
    second, reason = _numbers(translation)
    if reason:
        return reason
    if not first or not second:
        return "missing-digits-on-one-or-both-sides"
    if first.total() != second.total():
        # Small counts are often written as words on just one side (1 euro /
        # one euro). Compare only equal-sized nonempty sets of large numeral
        # anchors; the signal still requires review and cannot prove alignment.
        large_first = Counter({value: count for value, count in first.items() if abs(value) >= 1000})
        large_second = Counter({value: count for value, count in second.items() if abs(value) >= 1000})
        if (large_first and large_second and large_first.total() == large_second.total()
                and large_first != large_second):
            return "different-large-numerals"
        return "different-number-count"
    return "different-numerals" if first != second else "same-numerals"


def _output(path):
    path = Path(path).absolute()
    if path.parent.resolve(strict=True) != path.parent or path.is_symlink() or path.exists():
        raise DataError("Use a fresh review output with an existing canonical parent")
    return path


def audit_parallel_numbers(build, output, *, review_output=None, source_id=None, max_cases=100):
    """Stream a verified build and optionally retain a bounded compressed packet.

    No source text or extracted numerals appear in the summary. Every diagnostic
    is counted, but only a deterministic bounded sample is retained for review.
    Both sentence-aligned and unsplit source-unit translations retain their scope.
    """
    if type(max_cases) is not int or not 0 <= max_cases <= 1000:
        raise DataError("Use max-cases between 0 and 1000")
    build = Path(build).absolute()
    if build.resolve(strict=True) != build or not build.is_dir():
        raise DataError("Use a canonical corpus build directory")
    output = _output(output)
    review_output = _output(review_output) if review_output is not None else None
    if review_output is not None and (review_output == output or review_output.suffix != ".zst"):
        raise DataError("Choose a separate .zst compressed review path")
    for path in (output, review_output):
        if path is not None and path.is_relative_to(build):
            raise DataError("Keep review outputs outside the immutable input build")
    catalog = verify_build(build)
    known = {row["source"]["id"] for row in catalog["sources"]}
    if source_id is not None and source_id not in known:
        raise DataError("Unknown review source")
    before = sha256_file(build / "catalog.json")
    counts = Counter()
    sources = defaultdict(Counter)
    cases, case_bytes = [], 0
    documents = 0
    for record in iter_records(build, catalog, source_id):
        if record["kind"] != "document":
            continue
        documents += 1
        seen_units = set()
        for sentence in record["sentences"]:
            units = [("sentence", sentence)]
            if sentence.get("source_unit"):
                units.append(("source-unit", sentence["source_unit"]))
            for scope, unit in units:
                for translation in unit.get("translations", []):
                    unit_key = scope, unit.get("id", sentence["id"]), translation["id"]
                    if unit_key in seen_units:
                        continue
                    seen_units.add(unit_key)
                    signal = number_signal(unit["text"], translation["text"])
                    counts[signal] += 1
                    sources[record["source_id"]][signal] += 1
                    if signal not in {"different-numerals", "different-large-numerals"} or review_output is None or len(cases) >= max_cases:
                        continue
                    # Keep exact source and independently licensed paired text;
                    # inherited citation metadata cannot imply human generation.
                    case = dict(source_id=record["source_id"], work_id=record["id"],
                                occurrence_id=sentence["id"], unit_id=unit.get("id", sentence["id"]),
                                scope=scope, translation_id=translation["id"],
                                source_language=record["language"], text=unit["text"],
                                source_url=record["url"], title=record["title"],
                                revision=record.get("revision", {}), published_at=record.get("published_at"),
                                snapshot_id=record["snapshot_id"], license=record["license"],
                                attribution=record["attribution"], translation=translation,
                                signal=signal, reviewed=False)
                    size = len(canonical_json(case))
                    if case_bytes + size > MAX_PACKET_BYTES - 65536:
                        continue
                    cases.append(case)
                    case_bytes += size
    if verify_build(build) != catalog or sha256_file(build / "catalog.json") != before:
        raise DataError("Build catalog changed during review")
    result = dict(schema_version=1, policy=VERSION, build_id=catalog["build_id"],
                  catalog_sha256=before, source_id=source_id, documents=documents,
                  pairs=sum(counts.values()), signals=dict(sorted(counts.items())),
                  sources={source: dict(sorted(values.items())) for source, values in sorted(sources.items())},
                  contains_source_text=False, corpus_changed=False, human_review=False,
                  automatic_rejections=0,
                  limitations="Numeric diagnostics only. Skipped formats and unflagged pairs may contain errors; a difference is not proof of mistranslation. No generation or native-review evidence is inferred.")
    if review_output is not None:
        packet = dict(schema_version=1, policy=VERSION, build_id=catalog["build_id"],
                      catalog_sha256=before, cases=cases, contains_source_text=True,
                      sample="first eligible cases in canonical input order, not a random or representative sample",
                      semantic_review_complete=False, automatic_rejections=0)
        data = canonical_json(packet)
        if len(data) > MAX_PACKET_BYTES:
            raise DataError("Compressed review packet exceeds decoded byte budget")
        _write_fresh(review_output, zstandard.ZstdCompressor(level=6, write_checksum=True).compress(data))
        result["review_packet"] = dict(path=str(review_output), sha256=sha256_file(review_output),
                                       cases=len(cases), max_cases=max_cases,
                                       all_signals_reviewed=False)
    _write_fresh(output, (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    return output


def _write_fresh(path, data):
    # Exclusive/no-follow output, with no source text staged uncompressed.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags, 0o600), "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
