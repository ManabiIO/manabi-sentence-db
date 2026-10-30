"""Split publisher utterances without pretending their translations are aligned."""

import unicodedata
from collections import Counter

from .serialization import digest_json
from .text import assess_sentence, sentence_spans
from .validation import text_sha256

MAX_SOURCE_UNIT_CHARS = 20_000
MAX_SOURCE_UNIT_SEGMENTS = 256
# Adapter-only control marker. It is never serialized as authored source text.
CONTEXT_BREAK = object()
PUBLISHER_CONTEXT_VERSION = "publisher-context-barriers-v1"


def publisher_items(raw, manifest, stats, excluded_flags):
    """Yield unchanged single units, or exact fragments with original-unit context.

    A None result reserves a missing ordinal for a withheld unit or scene break.
    Bounds and whole-unit exclusions are checked before any fragment can carry
    the original text as context. Report segment_count before per-sentence
    quality filtering so consumers can see missing fragments explicitly.
    """
    if manifest["source"]["adapter"] in {"wikimedia", "kyoto-wikipedia", "alt-parallel"}:
        yield from raw["sentences"]
        return
    repeats = Counter()

    def barrier():
        stats["context_breaks"] += 1
        return None

    for item in raw["sentences"]:
        if item is CONTEXT_BREAK:
            yield barrier()
            continue
        stats["source_units_seen"] += 1
        original = unicodedata.normalize("NFC", item["text"])
        if len(original) > MAX_SOURCE_UNIT_CHARS:
            stats["rejected:source-unit-too-long"] += 1
            yield barrier()
            continue
        context_text = original.translate(str.maketrans({"\n": " ", "\r": " ", "\t": " "}))
        accepted, unit_flags, reason = assess_sentence(
            context_text, raw["language"], max_length=MAX_SOURCE_UNIT_CHARS
        )
        unit_flags = sorted(set(unit_flags) | set(item.get("content_flags", [])))
        if "＊＊" in original:
            stats["rejected:masked-personal-information"] += 1
            yield barrier()
            continue
        if item.get("generation", {}).get("kind") == "machine":
            stats["rejected:machine-generated"] += 1
            yield barrier()
            continue
        if excluded_flags.intersection(unit_flags):
            stats["rejected:content-policy"] += 1
            yield barrier()
            continue
        spans = sentence_spans(original, raw["language"])
        if len(spans) <= 1:
            yield item
            continue
        if len(spans) > MAX_SOURCE_UNIT_SEGMENTS:
            stats["rejected:too-many-segments"] += 1
            yield barrier()
            continue
        # Context may not smuggle unresolved markup, control bytes, or broken
        # delimiters into a sentence that individually passes its quality gate.
        if not accepted:
            stats[f"rejected:{reason}"] += 1
            yield barrier()
            continue
        if any(unicodedata.category(c) == "Cc" and c not in "\n\r\t" for c in original):
            stats["rejected:control-character"] += 1
            yield barrier()
            continue
        digest = text_sha256(original)
        repeats[digest] += 1
        native_id = str(item.get("native_id", f"{digest}:{repeats[digest]}"))
        identity = "unit_" + digest_json(
            [manifest["source_id"], str(raw["native_id"]), native_id]
        )[:32]
        stats["source_units_split"] += 1
        for index, (start, end) in enumerate(spans):
            unit = {
                "id": identity,
                "text": original,
                "text_sha256": digest,
                "start": start,
                "end": end,
                "segment_index": index,
                "segment_count": len(spans),
                "translations": item.get("translations", []),
            }
            yield dict(
                item,
                text=original[start:end],
                native_id=f"{native_id}:segment:{start}:{end}",
                translations=[],
                source_unit=unit,
                content_flags=unit_flags,
            )
