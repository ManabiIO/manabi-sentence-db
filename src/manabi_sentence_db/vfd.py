"""Pinned crowdwritten Japanese spoken pairs, without images or action labels."""

import csv
import hashlib
import io
import re
import stat
import unicodedata
import zipfile
from collections import Counter

from .segments import CONTEXT_BREAK
from .serialization import DataError, canonical_json, safe_relative, sha256_file
from .text import is_complete_sentence

ROLE = "yahoo-vfd-zip"
REVISION = "5cb774f44d8fa64e288cbb9b8e96c7aa5959ad62"
HOMEPAGE = "https://github.com/yahoojapan/VFD-Dataset"
PREFIX = f"VFD-Dataset-{REVISION}/"
SHA256 = "d8f90ac159383813da5a79ead1883548356cc97f33fef0cd11a2cc0e737b17d3"
ARCHIVE_BYTES = 6576449
TEXT_BYTES = 34569789
ROW_COUNT = 314895
# The actual publisher file uses gf_id, despite gfid in its README.
HEADER = ("utterance", "image_path", "gf_id", "verbal_response", "non_verbal_response")
TRANSFORMATION = "vfd-punctuated-spoken-pairs-v1"
QUALITY_VERSION = "vfd-example-quality-v1"
# Exact whole spoken units from the 96-text November 4 assistant review.
# Omit siblings too; source_unit must not re-expose a withheld utterance.
REVIEWED_UNIT_EXCLUSIONS = {
    "a38512515f361aa4d8dd4d22c01b6c789353fbb7bb7bad4f75c6443050aa0877":
        "vfd-reviewed-wording",  # fresh retained sample 30
    "ad943a0d9c33a49b7ab46560d5bf5ac3973050f2131984841e3b6f6a7aa27de1":
        "vfd-reviewed-adult-context",  # fresh retained sample 73
}


def assess_reviewed_unit(text):
    """Withhold exact unchanged reviewed units; never correct their text."""
    normalized = unicodedata.normalize("NFC", text.strip())
    return REVIEWED_UNIT_EXCLUSIONS.get(hashlib.sha256(normalized.encode("utf-8")).hexdigest())


def validate_source(source):
    pin = source["acquisition"]
    if (source["id"] != "yahoo-vfd-ja" or source["language"] != "ja"
            or source["homepage"] != HOMEPAGE
            or source["license"] != {"id": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"}
            or pin.get("revision") != REVISION or pin.get("sha256") != SHA256
            or type(pin.get("size")) is not int or pin["size"] != ARCHIVE_BYTES
            or pin.get("url") != f"https://codeload.github.com/yahoojapan/VFD-Dataset/zip/{REVISION}"):
        raise DataError("VFD requires the reviewed publisher, revision, archive and text license")


def iter_documents(manifest, snapshot_dir, *, stats=None):
    stats = stats if stats is not None else Counter()
    source = manifest["source"]
    validate_source(source)
    entries = manifest["files"]
    if len(entries) != 1 or entries[0]["role"] != ROLE:
        raise DataError("Expected exactly one VFD publisher ZIP")
    path = safe_relative(snapshot_dir, entries[0]["path"])
    if path.stat().st_size != ARCHIVE_BYTES or sha256_file(path) != SHA256:
        raise DataError("VFD archive checksum or size mismatch")
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            expected = {PREFIX + name for name in (
                "README.md", "prepare_data_for_selection_task.py", "vfd.tsv")}
            files = [m for m in members if not m.is_dir()]
            if (len({m.filename for m in members}) != len(members)
                    or {m.filename for m in files} != expected
                    or any(m.is_dir() and m.filename != PREFIX for m in members)
                    or any(m.flag_bits & 1 or stat.S_IFMT(m.external_attr >> 16)
                           not in {0, stat.S_IFREG} for m in files)):
                raise DataError("Invalid VFD regular-file inventory")
            member = archive.getinfo(PREFIX + "vfd.tsv")
            if (member.file_size != TEXT_BYTES
                    or any(m.file_size > 64 * 1024 for m in files if m != member)):
                raise DataError("Invalid VFD member size")
            with archive.open(member) as raw, io.TextIOWrapper(raw, encoding="utf-8", newline="") as stream:
                rows = csv.reader(stream, delimiter="\t", strict=True)
                if next(rows, None) != list(HEADER):
                    raise DataError("Invalid VFD publisher TSV header")
                count = 0
                previous_line = rows.line_num
                for count, values in enumerate(rows, 1):
                    line_start, previous_line = previous_line + 1, rows.line_num
                    if (len(values) != len(HEADER) or any(len(v) > 20000 for v in values)
                            or not values[1].strip() or len(values[1]) > 256
                            or re.fullmatch(r"[0-9]{1,10}", values[2]) is None):
                        raise DataError("Invalid VFD publisher row")
                    if count > ROW_COUNT:
                        raise DataError("VFD publisher row count exceeds reviewed inventory")
                    stats["vfd_rows_seen"] += 1
                    row = dict(zip(HEADER, values, strict=True))
                    items = []
                    for role in ("utterance", "verbal_response"):
                        text = row[role]
                        # This is a deliberately narrow text-only subset, not a
                        # claim that punctuation proves completeness/naturalness.
                        # Withheld turns reserve gaps; never join independent rows.
                        if text.strip().lower() in {"", "x"}:
                            stats["rejected:vfd-dummy-unit"] += 1
                            items.append(CONTEXT_BREAK)
                        elif reason := assess_reviewed_unit(text):
                            stats["rejected:" + reason] += 1
                            items.append(CONTEXT_BREAK)
                        elif not is_complete_sentence(text, "ja"):
                            stats["rejected:vfd-incomplete-unit"] += 1
                            items.append(CONTEXT_BREAK)
                        else:
                            items.append({"native_id": role, "text": text,
                                          "tags": ["role:" + role.replace("_", "-")],
                                          "content_flags": [], "translations": []})
                    url = f"{HOMEPAGE}/blob/{REVISION}/vfd.tsv#L{line_start}"
                    yield {"native_id": f"row-{count}", "language": "ja",
                        "title": f"VFD · Image-grounded dialogue {count}", "url": url,
                        "license": source["license"], "attribution": source["attribution"],
                        "revision": {"id": REVISION, "url": f"{HOMEPAGE}/tree/{REVISION}"},
                        "authorship": "human", "language_origin": "original_japanese",
                        "content_type": "dialogue", "tags": ["crowdwritten", "visual-dialogue",
                                                               "context:image-not-included"],
                        "source_text_hash": hashlib.sha256(canonical_json(row)).hexdigest(),
                        "sentences": items}
                if count != ROW_COUNT:
                    raise DataError("VFD publisher row count differs from reviewed inventory")
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, UnicodeError, csv.Error) as exc:
        raise DataError("Malformed VFD compressed source or TSV") from exc
