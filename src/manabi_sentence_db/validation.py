from __future__ import annotations

import hashlib
import math
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from .licenses import validate_license
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
        translations = set()
        for translation in sentence["translations"]:
            validate_license(translation["license"])
            if translation["id"] in translations:
                raise DataError("Duplicate translation identity")
            translations.add(translation["id"])
            if translation["text_sha256"] != text_sha256(translation["text"]):
                raise DataError("Translation hash does not match exact UTF-8 text")
