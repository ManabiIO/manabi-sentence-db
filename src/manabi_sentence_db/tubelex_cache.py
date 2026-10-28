"""Private reusable source-preserving boundary offsets; no caption text on disk."""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

import zstandard

from .serialization import DataError, canonical_json, digest_json, parse_json, safe_relative
from .tubelex import BOUNDARY_INPUT_VERSION, MAX_INPUT_BYTES, _read_compressed, _write_new_bytes


def cached_segmenter(segment, model_identity: dict, directory: Path, stats: Counter):
    """One writer per cache; completed entries can outlive interrupted builds.

    Paths and hit counters never enter the logical build identity. The key binds
    the exact input text, processor, model bytes, threshold and runtime profile.
    """
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    policy = {"cache_schema": 1, "processor": BOUNDARY_INPUT_VERSION, "model": model_identity}

    def split(text):
        if not text:
            return []
        key = digest_json(
            {
                "policy": policy,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
        path = safe_relative(directory, key + ".json.zst")
        if path.exists():
            try:
                record = parse_json(_read_compressed(path))
                if (
                    not isinstance(record, dict)
                    or set(record)
                    != {"schema_version", "key", "text_length", "ends", "ends_sha256"}
                    or type(record["schema_version"]) is not int
                    or record["schema_version"] != 1
                    or record["key"] != key
                    or type(record["text_length"]) is not int
                    or record["text_length"] != len(text)
                ):
                    raise DataError("Boundary cache identity disagrees with its input")
                ends = record["ends"]
                if (
                    not isinstance(ends, list)
                    or not ends
                    or len(ends) > len(text)
                    or record["ends_sha256"] != digest_json(ends)
                ):
                    raise DataError("Invalid boundary cache offset checksum")
                previous = 0
                parts = []
                for end in ends:
                    if type(end) is not int or not previous < end <= len(text):
                        raise DataError("Invalid boundary cache offsets")
                    parts.append(text[previous:end])
                    previous = end
                if previous != len(text):
                    raise DataError("Boundary cache does not cover its input")
            except DataError:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise DataError("Invalid private boundary cache entry") from exc
            stats["boundary-cache-hits"] += 1
            return parts
        parts = list(segment(text))
        if any(not isinstance(part, str) or not part for part in parts) or "".join(parts) != text:
            raise DataError("Cached sentence segmenter must preserve every original character")
        ends, offset = [], 0
        for part in parts:
            offset += len(part)
            ends.append(offset)
        record = {
            "schema_version": 1,
            "key": key,
            "text_length": len(text),
            "ends": ends,
            "ends_sha256": digest_json(ends),
        }
        encoded = canonical_json(record)
        if len(encoded) > MAX_INPUT_BYTES:
            raise DataError(
                "Boundary cache metadata exceeds its input budget; build without this cache"
            )
        _write_new_bytes(
            path,
            zstandard.ZstdCompressor(level=9, write_checksum=True).compress(encoded),
        )
        stats["boundary-cache-misses"] += 1
        return parts

    return split
