"""Bounded JSON collection readers for publisher archives; no eager dataset load."""

import json

from .serialization import DataError


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise DataError("Duplicate publisher JSON key")
        result[key] = value
    return result


class _Reader:
    def __init__(self, stream, max_item_chars=2 * 1024**2):
        self.stream = stream
        self.buffer = ""
        self.eof = False
        self.max_item_chars = max_item_chars
        self.decoder = json.JSONDecoder(object_pairs_hook=_pairs, parse_constant=self._constant)

    @staticmethod
    def _constant(value):
        raise DataError(f"Non-finite publisher JSON value: {value}")

    def more(self):
        chunk = self.stream.read(65536)
        self.eof = not chunk
        self.buffer += chunk

    def peek(self):
        while True:
            self.buffer = self.buffer.lstrip(" \t\r\n")
            if self.buffer or self.eof:
                return self.buffer[:1]
            self.more()

    def take(self, expected):
        if self.peek() != expected:
            raise DataError(f"Expected {expected!r} in publisher JSON")
        self.buffer = self.buffer[1:]

    def value(self):
        self.peek()
        while True:
            try:
                value, end = self.decoder.raw_decode(self.buffer)
            except json.JSONDecodeError as error:
                if self.eof:
                    raise DataError("Invalid or truncated publisher JSON") from error
                if len(self.buffer) > self.max_item_chars:
                    raise DataError("Publisher JSON item exceeds size bound") from error
                self.more()
                continue
            # raw_decode("1e") or raw_decode("1.") returns the valid prefix 1.
            # The remaining exponent/fraction may continue in the next chunk;
            # accept a number only once its complete JSON token is delimited.
            if (type(value) in (int, float) and end < len(self.buffer)
                    and self.buffer[end] not in " \t\r\n,]}"):
                if self.eof or any(c in " \t\r\n,]}" for c in self.buffer[end:]):
                    raise DataError("Invalid publisher JSON number")
                if len(self.buffer) > self.max_item_chars:
                    raise DataError("Publisher JSON item exceeds size bound")
                self.more()
                continue
            # A scalar at the chunk edge might be only a prefix of a number.
            if end == len(self.buffer) and not self.eof:
                self.more()
                continue
            if end > self.max_item_chars:
                raise DataError("Publisher JSON item exceeds size bound")
            self.buffer = self.buffer[end:]
            return value

    def array(self):
        self.take("[")
        if self.peek() != "]":
            while True:
                yield self.value()
                if self.peek() == "]":
                    break
                self.take(",")
        self.take("]")

    def items(self, array_key=None):
        self.take("{")
        seen = set()
        if self.peek() != "}":
            while True:
                key = self.value()
                if not isinstance(key, str) or key in seen:
                    raise DataError("Invalid or duplicate publisher JSON key")
                seen.add(key)
                self.take(":")
                if array_key is None:
                    yield key, self.value()
                elif key == array_key:
                    for item in self.array():
                        yield key, item
                elif self.peek() == "[":
                    for _ in self.array():
                        pass
                else:
                    self.value()
                if self.peek() == "}":
                    break
                self.take(",")
        self.take("}")
        if self.peek():
            raise DataError("Trailing content in publisher JSON")
        if array_key is not None and array_key not in seen:
            raise DataError(f"Missing publisher JSON array: {array_key}")


def object_items(stream):
    """Yield one top-level mapping value at a time, rejecting duplicate keys."""
    yield from _Reader(stream).items()


def array_items(stream, key):
    """Yield a named top-level array, streaming and discarding other arrays."""
    for _, value in _Reader(stream).items(array_key=key):
        yield value
