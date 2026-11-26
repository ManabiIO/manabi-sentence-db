"""Extract only human-written Japanese questions from JaQuAD."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

from .serialization import DataError, safe_relative

MAX_ARCHIVE_SIZE = 10 * 1024**2
MAX_MEMBER_SIZE = 2 * 1024**2
MAX_TOTAL_UNCOMPRESSED = 30 * 1024**2
TRAIN_QUESTIONS = 31_748
VALIDATION_QUESTIONS = 3_939
LICENSE_SHA256 = "075dad5e5fc96c27014fabc269f4f5732909cffd178a486f546d982b6cf86b74"
QUESTION_TYPES = {
    "Lexical variation (synonymy)": "synonymy",
    "Lexical variation (world knowledge)": "world-knowledge",
    "Logical reasoning": "logical-reasoning",
    "Multiple sentence reasoning": "multiple-sentence-reasoning",
    "Syntactic variation": "syntactic-variation",
}


def _members(revision: str) -> tuple[str, set[str]]:
    root = f"JaQuAD-{revision}/"
    names = {root + ".gitignore", root + "JaQuAD.ipynb", root + "LICENSE",
             root + "README.md"}
    names.update(
        f"{root}data/train/jaquad_train_{index:04d}.json" for index in range(30)
    )
    names.update(
        f"{root}data/dev/jaquad_dev_{index:04d}.json" for index in range(4)
    )
    return root, names


def iter_documents(manifest: dict, snapshot_dir: Path, *, stats=None,
                   after_native_id: str | None = None):
    """Yield one question per work; contexts and answers are never emitted."""
    source = manifest["source"]
    pin = source["acquisition"]
    revision = pin["revision"]
    if (pin["dataset_version"] != "JaQuAD-version-0.1.0"
            or pin["train_questions"] != TRAIN_QUESTIONS
            or pin["validation_questions"] != VALIDATION_QUESTIONS
            or pin["withheld_test_questions"] != 4_009):
        raise DataError("JaQuAD source configuration differs from the reviewed split totals")
    root, expected_members = _members(revision)
    seen_ids = set()
    question_counts: Counter = Counter()
    question_text_counts: Counter = Counter()
    archive_count = 0
    cursor_found = after_native_id is None

    for entry in manifest["files"]:
        if entry["role"] != "jaquad-zip":
            continue
        archive_count += 1
        if archive_count > 1:
            raise DataError("JaQuAD snapshot must contain exactly one pinned archive")
        path = safe_relative(snapshot_dir, entry["path"])
        if (path.stat().st_size != pin["size"] or path.stat().st_size > MAX_ARCHIVE_SIZE
                or entry.get("sha256") != pin["sha256"]
                or entry.get("url") != pin["url"]):
            raise DataError("JaQuAD archive differs from the pinned hash, size, URL, or safety cap")
        try:
            with zipfile.ZipFile(path) as archive:
                infos = [info for info in archive.infolist() if not info.is_dir()]
                names = [info.filename for info in infos]
                if len(names) != len(set(names)) or set(names) != expected_members:
                    raise DataError("Unexpected JaQuAD archive member inventory")
                if sum(info.file_size for info in infos) > MAX_TOTAL_UNCOMPRESSED:
                    raise DataError("JaQuAD archive exceeds its total expansion cap")
                if any(info.file_size > MAX_MEMBER_SIZE for info in infos):
                    raise DataError("Oversized JaQuAD archive member")
                license_bytes = archive.read(root + "LICENSE")
                if (hashlib.sha256(license_bytes).hexdigest() != LICENSE_SHA256
                        or LICENSE_SHA256 != pin["license_sha256"]):
                    raise DataError("JaQuAD pinned LICENSE checksum mismatch")
                readme = archive.read(root + "README.md")
                if b"CC BY-SA 3.0" not in readme:
                    raise DataError("JaQuAD README no longer states its dataset license")
                for split, prefix, expected_count, filename_prefix in (
                    ("train", "tr", pin["train_questions"], "jaquad_train_"),
                    ("validation", "de", pin["validation_questions"], "jaquad_dev_"),
                ):
                    split_count = 0
                    directory = "train" if split == "train" else "dev"
                    file_count = 30 if split == "train" else 4
                    for index in range(file_count):
                        member = (f"{root}data/{directory}/{filename_prefix}"
                                  f"{index:04d}.json")
                        payload = json.loads(archive.read(member))
                        if (not isinstance(payload, dict)
                                or payload.get("version") != pin["dataset_version"]
                                or not isinstance(payload.get("data"), list)):
                            raise DataError("Invalid JaQuAD data file or dataset version")
                        for article in payload["data"]:
                            if not isinstance(article, dict) or not isinstance(
                                article.get("paragraphs"), list
                            ):
                                raise DataError("Malformed JaQuAD article row")
                            for paragraph in article["paragraphs"]:
                                if not isinstance(paragraph, dict) or not isinstance(
                                    paragraph.get("qas"), list
                                ):
                                    raise DataError("Malformed JaQuAD paragraph row")
                                for qa in paragraph["qas"]:
                                    if not isinstance(qa, dict):
                                        raise DataError("Malformed JaQuAD question row")
                                    identity = qa.get("id")
                                    text = qa.get("question")
                                    kind = qa.get("question_type")
                                    if (not isinstance(identity, str)
                                            or not re.fullmatch(
                                                rf"{prefix}-[0-9]{{3}}-[0-9]{{2}}-[0-9]{{3}}",
                                                identity,
                                            )
                                            or identity in seen_ids):
                                        raise DataError("Invalid or duplicate JaQuAD question ID")
                                    if (not isinstance(text, str) or not text.strip()
                                            or len(text) > 500
                                            or unicodedata.normalize("NFC", text) != text):
                                        raise DataError("Invalid JaQuAD question text")
                                    if kind not in QUESTION_TYPES:
                                        raise DataError("Unknown JaQuAD question type")
                                    seen_ids.add(identity)
                                    question_counts[split] += 1
                                    question_text_counts[text] += 1
                                    split_count += 1
                                    if not cursor_found:
                                        if identity == after_native_id:
                                            cursor_found = True
                                        continue
                                    url = (f"{source['homepage']}/blob/{revision}/data/"
                                           f"{directory}/{filename_prefix}{index:04d}.json")
                                    yield {
                                        "native_id": identity,
                                        "language": "ja",
                                        "title": f"JaQuAD question {identity}",
                                        "url": url,
                                        "license": source["license"],
                                        "attribution": source["attribution"],
                                        "revision": {"id": revision, "url": url},
                                        "tags": ["question-answering", f"split:{split}"],
                                        "authorship": "human",
                                        "language_origin": "unknown",
                                        "content_type": "question",
                                        "source_text_hash": hashlib.sha256(
                                            text.encode("utf-8")
                                        ).hexdigest(),
                                        "sentences": [{
                                            "native_id": identity,
                                            "text": text,
                                            "tags": [
                                                "question-type:" + QUESTION_TYPES[kind]
                                            ],
                                            "content_flags": [],
                                            "translations": [],
                                        }],
                                    }
                        if stats is not None:
                            stats["articles_read"] += len(payload["data"])
                    if split_count != expected_count:
                        raise DataError(
                            f"JaQuAD {split} count differs from the published total: "
                            f"{split_count} != {expected_count}"
                        )
            if stats is not None:
                stats["train_questions"] = question_counts["train"]
                stats["validation_questions"] = question_counts["validation"]
                stats["duplicate_question_text_groups"] = sum(
                    count > 1 for count in question_text_counts.values()
                )
                stats["duplicate_question_text_excess"] = sum(
                    count - 1 for count in question_text_counts.values() if count > 1
                )
        except (OSError, zipfile.BadZipFile, KeyError, TypeError, ValueError) as error:
            if isinstance(error, DataError):
                raise
            raise DataError("Invalid JaQuAD pinned archive") from error
    if archive_count != 1:
        raise DataError("JaQuAD snapshot is missing its pinned archive")
    if not cursor_found:
        raise DataError(f"Resumable JaQuAD question cursor is absent from snapshot: {after_native_id}")
