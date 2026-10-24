import io
import json

import pytest

from manabi_sentence_db.json_stream import _Reader, array_items, object_items
from manabi_sentence_db.serialization import DataError


class SmallChunks(io.StringIO):
    def read(self, size=-1):
        assert size > 0
        return super().read(min(size, 3))


class SplitOnce(io.StringIO):
    def __init__(self, value, split):
        super().__init__(value)
        self.split = split

    def read(self, size=-1):
        assert size > 0
        remaining = self.split - self.tell()
        return super().read(min(size, remaining) if remaining > 0 else size)


@pytest.mark.parametrize("number", ["1.25", "-0.25", "6.02e23", "-1e-9", "1E+5", "0.0"])
def test_numeric_tokens_remain_intact_at_every_chunk_boundary(number):
    raw = '{"annotations":[' + number + ']}'
    expected = json.loads(raw)["annotations"]
    for split in range(1, len(raw)):
        assert list(array_items(SplitOnce(raw, split), "annotations")) == expected
    # Metadata and skipped arrays pass through the same scalar reader.
    raw = '{"ignored":[' + number + '],"value":' + number + ',"annotations":[]}'
    for split in range(1, len(raw)):
        assert list(array_items(SplitOnce(raw, split), "annotations")) == []


@pytest.mark.parametrize("number", ["1e", "1e+", "1.", "01", "1e+2.3", "1e 2"])
def test_incomplete_or_invalid_numeric_suffixes_are_rejected(number):
    raw = '{"annotations":[' + number + ']}'
    with pytest.raises(DataError):
        list(array_items(SmallChunks(raw), "annotations"))


def test_pending_number_suffix_obeys_item_bound():
    raw = '{"annotations":[1e' + '+' * 200 + ']}'
    with pytest.raises(DataError, match="size bound"):
        list(_Reader(SmallChunks(raw), max_item_chars=100).items(array_key="annotations"))


def test_object_and_array_stream_across_unicode_and_number_boundaries():
    document = {"最初": {"text": "今日は晴れです。", "number": 123456}, "次": [1, 2, 3]}
    assert dict(object_items(SmallChunks(json.dumps(document, ensure_ascii=False)))) == document
    corpus = {"images": [{"id": n} for n in range(100)], "annotations": [document, document]}
    assert list(array_items(SmallChunks(json.dumps(corpus)), "annotations")) == [document, document]


@pytest.mark.parametrize("raw", [
    '{"a":1,"a":2}', '{"a":{"x":1,"x":2}}', '{"a":NaN}',
    '{"a":[1,]}', '{"a":1,}', '{"a":1}x', '{"a":',
])
def test_malformed_duplicate_and_nonfinite_input_is_rejected(raw):
    with pytest.raises(DataError):
        list(object_items(SmallChunks(raw)))


def test_missing_array_and_oversized_unit_are_rejected():
    with pytest.raises(DataError, match="Missing"):
        list(array_items(io.StringIO('{"images":[]}'), "annotations"))
    with pytest.raises(DataError, match="size bound"):
        list(_Reader(SmallChunks('{"a":"' + "x" * 200 + '"}'), max_item_chars=100).items())
