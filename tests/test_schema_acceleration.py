"""Native fast acceptance preserves the existing schema and Python diagnostics."""
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

from manabi_sentence_db import validation
from manabi_sentence_db.build import _runtime_versions, canonical_document
from manabi_sentence_db.serialization import DataError


@pytest.fixture
def examples():
    source = validation.load_source(Path("sources/tatoeba-ja.yaml"))
    translation = dict(language="en", text="I walked. I read a book.",
        source_url="https://example.org/translation", license=source["license"],
        attribution=source["attribution"],
        generation={"kind": "machine", "tool": "fixture", "model": "fixture/model"})
    raw = dict(native_id="1", language="ja", title="Synthetic", url="https://example.org/1",
        license=source["license"], attribution=source["attribution"], sentences=[
            {"text": "公園を歩きました。図書館で本を読みました。", "translations": [translation]}])
    manifest = dict(source_id=source["id"], snapshot_id="fixture", source=source)
    split = canonical_document(raw, manifest, Counter(), set())
    raw["sentences"][0]["text"] = "公園を歩きました。"
    paired = canonical_document(raw, manifest, Counter(), set())
    properties = validation.validator("record").schema["oneOf"][1]["properties"]
    media = {key: value for key, value in split.items() if key in properties}
    media.update(kind="reference", locator={"type": "media", "start_seconds": 1, "end_seconds": 2})
    text = dict(media, locator={"type": "text-fragment", "url": "https://example.org/#:~:text=sample"})
    return [("record", row) for row in (split, paired, media, text)] + [("source", source)]


def _walk(value, path=()):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value[:2]):
            yield from _walk(child, (*path, index))


def _changed(original, path, replacement):
    if not path:
        return replacement
    value = deepcopy(original)
    target = value
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = deepcopy(replacement)
    return value


def test_differential_types_nested_translations_units_and_reference_locators(examples):
    if validation.NativeValidator is None:
        pytest.skip("Native validation is absent from this legacy frozen runtime")
    checked = 0
    for name, original in examples:
        oracle = validation.validator(name)
        for path, value in _walk(original):
            replacements = [None, True, False, -1, 0, 0.5, "", [], {}, (), ("x",), set(),
                            ["duplicate", "duplicate"], 2**127, float("nan"), float("inf")]
            if isinstance(value, str) and value.startswith("https://"):
                replacements += ["https://example.org/" + chr(n) + "x" for n in
                    [0, 9, 10, 13, 28, 29, 30, 31, 32, 133, 160, 0x1680, 0x2007, 0x2028, 0x3000]]
            for replacement in replacements:
                changed = _changed(original, path, replacement)
                errors = list(oracle.iter_errors(changed))
                if errors:
                    with pytest.raises(DataError):
                        validation.validate(changed, name)
                else:
                    validation.validate(changed, name)
                checked += 1
    assert checked > 3000


@pytest.mark.parametrize("codepoint", [28, 29, 30, 31, 133])
def test_python_regex_whitespace_is_rejected_with_identical_fallback_diagnostics(
        examples, monkeypatch, codepoint):
    value = deepcopy(examples[0][1])
    value["url"] = "https://example.org/" + chr(codepoint) + "x"
    with pytest.raises(DataError) as accelerated:
        validation.validate(value, "record")
    monkeypatch.setattr(validation, "NativeValidator", None)
    with pytest.raises(DataError) as legacy:
        validation.validate(value, "record")
    assert str(accelerated.value) == str(legacy.value)


def test_missing_native_backend_retains_python_validation_and_records_actual_mode(examples, monkeypatch):
    monkeypatch.setattr(validation, "NativeValidator", None)
    for name, value in examples:
        validation.validate(value, name)
    assert _runtime_versions()["schema_validation"] == "python-jsonschema"
    bad = dict(examples[0][1], tags=())
    with pytest.raises(DataError):
        validation.validate(bad, "record")


def test_native_conversion_failure_falls_back_to_established_validation(examples, monkeypatch):
    class BrokenNative:
        def is_valid(self, value):
            raise ValueError("injected native conversion error")

    monkeypatch.setattr(validation, "NativeValidator", object())
    monkeypatch.setattr(validation, "_native_validator", lambda _: BrokenNative())
    validation.validate(examples[0][1], "record")
    with pytest.raises(DataError):
        validation.validate(dict(examples[0][1], tags=17), "record")
