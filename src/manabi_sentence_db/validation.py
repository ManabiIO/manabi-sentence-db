from __future__ import annotations

import hashlib
import math
import unicodedata
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from .licenses import validate_license, validate_rights
from .serialization import DataError, load_yaml, read_json

SCHEMAS = Path(__file__).parent / "schemas"


@lru_cache
def validator(name: str) -> Draft202012Validator:
    schema = read_json(SCHEMAS / f"{name}.schema.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate(value: dict, name: str) -> None:
    errors = list(validator(name).iter_errors(value))
    if errors:
        error = min(errors, key=lambda e: len(e.absolute_path))
        location = ".".join(map(str, error.absolute_path)) or "root"
        # oneOf failures often contain the useful error one level below.
        detail = "; ".join(e.message for e in error.context[:4]) if error.context else error.message
        raise DataError(f"Invalid {name} at {location}: {detail}")


def load_source(path: Path) -> dict:
    source = load_yaml(path)
    validate(source, "source")
    validate_license(source["license"])
    if source["language"] == "jp":
        raise DataError("Use the language code ja, not jp")
    if path.stem != source["id"]:
        raise DataError(f"Source filename must match its ID: {source['id']}")
    return source


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_source_unit(unit: dict, text: str) -> None:
    root = validator("record")
    schema = root.schema["oneOf"][0]["properties"]["sentences"]["items"]["properties"]["source_unit"]
    errors = list(root.descend(unit, schema))
    if errors:
        raise DataError(f"Invalid source-unit metadata: {errors[0].message}")
    if unit["text_sha256"] != text_sha256(unit["text"]):
        raise DataError("Source-unit hash does not match exact UTF-8 text")
    if unicodedata.normalize("NFC", unit["text"]) != unit["text"]:
        raise DataError("Source-unit text must be NFC")
    if not 0 <= unit["start"] < unit["end"] <= len(unit["text"]):
        raise DataError("Invalid source-unit fragment offsets")
    if unit["text"][unit["start"]:unit["end"]] != text:
        raise DataError("Sentence does not match its source-unit fragment")
    if unit["segment_index"] >= unit["segment_count"]:
        raise DataError("Invalid source-unit segment index")
    identities = set()
    for translation in unit["translations"]:
        validate_rights(translation, source_url_key="source_url")
        if translation["text_sha256"] != text_sha256(translation["text"]):
            raise DataError("Source-unit translation hash mismatch")
        if translation["id"] in identities:
            raise DataError("Duplicate source-unit translation identity")
        identities.add(translation["id"])


def validate_record(record: dict) -> None:
    validate(record, "record")
    if record["kind"] == "reference":
        locator = record["locator"]
        if locator["type"] == "media" and any(
            not math.isfinite(locator[key])
            for key in ("start_seconds", "end_seconds")
            if key in locator
        ):
            raise DataError("Media times must be finite numbers")
        if (
            locator["type"] == "media"
            and "end_seconds" in locator
            and locator["end_seconds"] <= locator["start_seconds"]
        ):
            raise DataError("A media end must be after its absolute start time")
        return
    validate_license(record["license"])
    seen = set()
    for sentence in record["sentences"]:
        if sentence["id"] in seen:
            raise DataError("Duplicate sentence identity within a document")
        seen.add(sentence["id"])
        if sentence["text_sha256"] != text_sha256(sentence["text"]):
            raise DataError("Sentence hash does not match exact UTF-8 text")
        unit = sentence.get("source_unit")
        if unit is not None:
            validate_source_unit(unit, sentence["text"])
            if sentence["translations"]:
                raise DataError("Split source-unit translations are not sentence-aligned")
        translations = set()
        for translation in sentence["translations"] + (unit or {}).get("translations", []):
            validate_license(translation["license"])
            if translation["id"] in translations:
                raise DataError("Duplicate translation identity")
            translations.add(translation["id"])
            if translation["text_sha256"] != text_sha256(translation["text"]):
                raise DataError("Translation hash does not match exact UTF-8 text")

