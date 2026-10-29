"""Read the immutable JEC basic-sentence v1.3 Japanese/English/Chinese workbook."""

from __future__ import annotations

import hashlib
import re
import unicodedata
import zipfile
from pathlib import Path

import xlrd

from .serialization import DataError, canonical_json, safe_relative

ARCHIVE_MEMBER = "JEC_basic_sentence_v1-3/JEC_basic_sentence_v1-3.xls"
README_MEMBER = "JEC_basic_sentence_v1-3/README.txt"
MAX_ARCHIVE_MEMBER = 16 * 1024**2
_X_PLACEHOLDER = re.compile(r"(?<![A-Za-z])X(?![A-Za-z])")
_NUMERIC_RANGE = re.compile(r"\d\s*[〜～]\s*\d")


def _template_placeholder(text: str) -> bool:
    remainder = _NUMERIC_RANGE.sub("", text)
    return bool(_X_PLACEHOLDER.search(text) or "〜" in remainder or "～" in remainder)


def iter_documents(manifest: dict, snapshot_dir: Path, *, stats=None):
    """Yield one independent row per work; row adjacency is not discourse context."""
    source = manifest["source"]
    acquisition = source["acquisition"]
    url = acquisition["url"]
    workbook_sha = acquisition["workbook_sha256"]
    readme_sha = acquisition["readme_sha256"]
    expected_rows = acquisition["rows"]
    ja_license = source["license"]
    tr_rights = acquisition["translation_rights"]
    archives_seen = 0
    for entry in manifest["files"]:
        if entry["role"] != "jec-basic-zip":
            continue
        archives_seen += 1
        if archives_seen > 1:
            raise DataError("JEC snapshot must contain exactly one pinned archive")
        path = safe_relative(snapshot_dir, entry["path"])
        if path.stat().st_size != acquisition["size"]:
            raise DataError("JEC archive size differs from pinned source")
        try:
            with zipfile.ZipFile(path) as archive:
                names = [x.filename for x in archive.infolist() if not x.is_dir()]
                if sorted(names) != sorted([ARCHIVE_MEMBER, README_MEMBER]):
                    raise DataError("Unexpected JEC archive member inventory")
                for name in names:
                    info = archive.getinfo(name)
                    if info.file_size > MAX_ARCHIVE_MEMBER:
                        raise DataError("Oversized JEC archive member")
                workbook_bytes = archive.read(ARCHIVE_MEMBER)
                readme_bytes = archive.read(README_MEMBER)
        except (OSError, zipfile.BadZipFile, KeyError) as error:
            raise DataError("Invalid JEC v1.3 archive") from error
        if hashlib.sha256(workbook_bytes).hexdigest() != workbook_sha:
            raise DataError("JEC workbook member checksum mismatch")
        if len(workbook_bytes) != acquisition["workbook_size"]:
            raise DataError("JEC workbook member size mismatch")
        if hashlib.sha256(readme_bytes).hexdigest() != readme_sha:
            raise DataError("JEC README checksum mismatch")
        if len(readme_bytes) != acquisition["readme_size"]:
            raise DataError("JEC README size mismatch")
        try:
            workbook = xlrd.open_workbook(file_contents=workbook_bytes, on_demand=True)
        except Exception as error:
            raise DataError("Invalid JEC Excel workbook") from error
        if workbook.sheet_names() != ["ALL_NEW"]:
            raise DataError("Unexpected JEC worksheet inventory")
        sheet = workbook.sheet_by_index(0)
        if sheet.ncols != 4 or sheet.nrows != expected_rows:
            raise DataError("Unexpected JEC row or column count")
        seen = set()
        try:
            for row_number in range(sheet.nrows):
                cells = [sheet.cell_value(row_number, col) for col in range(4)]
                if any(not isinstance(value, str) for value in cells):
                    raise DataError(f"JEC row {row_number + 1} contains a non-text cell")
                native_id, japanese, english, chinese = cells
                expected_id = f"#{row_number + 1:04d}"
                if native_id != expected_id or native_id in seen:
                    raise DataError(f"Invalid or duplicate JEC row ID at row {row_number + 1}")
                seen.add(native_id)
                if any(not text.strip() for text in (japanese, english, chinese)):
                    raise DataError(f"Empty JEC text at row {row_number + 1}")
                if any(
                    unicodedata.normalize("NFC", text) != text
                    for text in (japanese, english, chinese)
                ):
                    raise DataError(f"Non-NFC JEC text at row {row_number + 1}")
                row = {"id": native_id, "ja": japanese, "en": english, "zh": chinese}
                if stats is not None:
                    stats["rows_in_workbook"] += 1
                if _template_placeholder(japanese):
                    if stats is not None:
                        stats["excluded:unresolved-template-placeholder"] += 1
                    continue
                translations = []
                for language, text in (("en", english), ("zh", chinese)):
                    translations.append(
                        {
                            "id": f"{native_id}-{language}",
                            "language": language,
                            "text": text,
                            "source_url": url,
                            "license": tr_rights["license"],
                            "attribution": tr_rights["attribution"],
                            "alignment": "unknown",
                        }
                    )
                yield {
                    "native_id": native_id,
                    "language": "ja",
                    "title": f"JEC Basic Sentence {native_id}",
                    "url": url,
                    "license": ja_license,
                    "attribution": source["attribution"],
                    "revision": {"id": acquisition["version"], "url": url},
                    "tags": ["basic-sentence", "sentence-pattern"],
                    "authorship": "unknown",
                    "language_origin": "original_japanese",
                    "content_type": "example-sentence",
                    "source_text_hash": hashlib.sha256(canonical_json(row)).hexdigest(),
                    "sentences": [
                        {
                            "native_id": native_id,
                            "text": japanese,
                            "tags": [],
                            "content_flags": [],
                            "translations": translations,
                        }
                    ],
                }
        finally:
            workbook.release_resources()
    if archives_seen != 1:
        raise DataError("JEC snapshot is missing its pinned archive")
