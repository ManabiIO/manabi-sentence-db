"""Private exact-substring sidecars for an immutable, redistributable base release.

The public/reference export has no text or postings. The private SQLite file
contains Zstandard verification payloads and a contentless FTS5 trigram index.
It must not be published: contentless is a storage option, not a rights boundary.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import sqlite3
import time
from bisect import bisect_left, bisect_right
from collections import Counter, deque
from contextlib import closing, contextmanager
from heapq import merge
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import zstandard

from .serialization import (
    DataError,
    canonical_json,
    digest_json,
    parse_json,
    read_json,
    safe_relative,
    sha256_file,
    write_json,
)
from .text import TEXT_PROCESSOR_VERSION, assess_sentence
from .tubelex import (
    BOUNDARY_POLICY,
    PROCESSOR,
    AlignedSentence,
    _new_output,
    caption_streams,
    parse_vtt,
    read_private_caption,
    reference_record,
    stream_units,
    verify_tubelex_snapshot,
)
from .validation import validate_record

SCHEMA_VERSION = 7
CHUNK_CHARS = 4096
MAX_QUERY_CHARS = 500
CHUNK_STEP = CHUNK_CHARS - MAX_QUERY_CHARS + 1
MAX_TEXT_BYTES = CHUNK_CHARS * 4
ELIGIBILITY_TILE_CHARS = 256
ELIGIBILITY_CONTEXT_CHARS = 128
DEFAULT_QUERY_TIMEOUT_MS = 1000
DEFAULT_MAX_DECODED_CHUNKS = 2048
CANDIDATE_POLICY = "hard-boundary-separated-grams-v1"
REFERENCE_POLICY = "unit-and-origin-starts-v2"
LITERAL_POLICY = "global-fourgram-bloom-blake2s64-k6-v1"
MAX_LITERAL_FILTER_BYTES = 8 * 1024**2
UNIT_CODES = {
    name: number
    for number, name in enumerate(
        ("punctuation", "model", "pause-inferred", "unsegmented"), start=1
    )
}
UNIT_NAMES = {number: name for name, number in UNIT_CODES.items()}


def _boundary_bitmap(boundaries: list[int], start: int, end: int) -> bytes:
    bits = 0
    for offset in boundaries[bisect_right(boundaries, start) : bisect_left(boundaries, end)]:
        bits |= 1 << (offset - start)
    return bits.to_bytes((bits.bit_length() + 7) // 8, "little")


def _decode_boundary_bitmap(blob: bytes, text_length: int) -> int:
    if not isinstance(blob, bytes) or len(blob) > (CHUNK_CHARS + 7) // 8:
        raise DataError("Invalid private boundary bitmap size")
    bits = int.from_bytes(blob, "little")
    if bits & 1 or bits.bit_length() >= text_length or len(blob) != (bits.bit_length() + 7) // 8:
        raise DataError("Invalid private boundary bitmap padding or encoding")
    return bits


def _candidate_spans(text: str, bitmap: bytes) -> list[str]:
    """Keep every valid literal, while omitting grams crossing a hard boundary."""
    bits = _decode_boundary_bitmap(bitmap, len(text))
    parts, start = [], 0
    while bits:
        first = bits & -bits
        end = first.bit_length() - 1
        parts.append(text[start:end])
        start = end
        bits ^= first
    parts.append(text[start:])
    return parts


class _PostingBinding:
    """Order-independent binding of the complete distinct (term, chunk) set.

    Expected terms come from bounded source windows, independently of FTS data.
    Count plus SHA-256 sum/XOR detects missing, extra and reassigned postings
    without sorting or retaining a corpus-sized vocabulary in memory.
    """
    def __init__(self):
        self.count = self.total = self.xor = 0

    def add(self, term, chunk):
        if not isinstance(term, str) or type(chunk) is not int or chunk <= 0:
            raise DataError("Invalid private substring postings")
        digest = hashlib.sha256(chunk.to_bytes(8, "little") + term.encode("utf-8")).digest()
        value = int.from_bytes(digest, "little")
        self.count += 1
        self.total = (self.total + value) % (1 << 256)
        self.xor ^= value

    @property
    def value(self):
        return self.count, self.total, self.xor


def _expected_postings(text, bitmap, chunk, bindings):
    # The publisher-boundary bitmap is independently checked against units.
    # FTS's ASCII short tokens are reversible UTF-8; the case-sensitive trigram
    # tokenizer emits every three Unicode scalars, including private separators.
    parts = _candidate_spans(text, bitmap)
    for term in {"s" + part[i:i + width].encode("utf-8").hex()
                 for part in parts for width in (1, 2)
                 for i in range(len(part) - width + 1)}:
        bindings["short_substring"].add(term, chunk)
    joined = "\x1f".join(parts)
    for term in {joined[i:i + 3] for i in range(len(joined) - 2)}:
        bindings["substring"].add(term, chunk)


def _literal_keys(parts):
    """A private necessary-condition dictionary, never proof of a full match.

    Colliding 64-bit fingerprints can add candidates, never suppress a match.
    They are an enumerable vocabulary representation, not anonymized text.
    """
    return {
        hashlib.blake2s(part[i:i + 4].encode("utf-8"), digest_size=8).digest()
        for part in parts for i in range(len(part) - 3)
    }


def _literal_filter_size(fingerprints):
    if type(fingerprints) is not int or fingerprints < 0:
        raise DataError("Invalid private literal-filter cardinality")
    # Eight bits per distinct fingerprint; cap memory per immutable shard.
    return min(MAX_LITERAL_FILTER_BYTES, max(8, (fingerprints + 7) // 8 * 8))


def _literal_positions(key, size):
    first = int.from_bytes(key[:4], "little")
    step = int.from_bytes(key[4:], "little") | 1
    return ((first + i * step) % (size * 8) for i in range(6))


def _literal_add(bits, key):
    for point in _literal_positions(key, len(bits)):
        bits[point // 8] |= 1 << (point % 8)


def _literal_maybe_contains(bits, key):
    return all(bits[p // 8] & (1 << (p % 8)) for p in _literal_positions(key, len(bits)))


def _load_literal_filter(database):
    info = database.execute("SELECT fingerprints,length(bits) FROM literal_filter WHERE id=1").fetchone()
    if info is None or info[1] != _literal_filter_size(info[0]):
        raise DataError("Invalid private literal filter")
    row = database.execute("SELECT fingerprints,bits FROM literal_filter WHERE id=1").fetchone()
    if not isinstance(row[1], bytes):
        raise DataError("Invalid private literal filter")
    return row[0], row[1]


class QueryBudgetExceeded(DataError):
    """Search could not finish within its budget; no partial results are returned."""


class QueryWorkLimitExceeded(QueryBudgetExceeded):
    """Candidate verification reached its explicit decoded-chunk budget."""


class _QueryBudget:
    def __init__(self, timeout_ms, max_decoded_chunks=DEFAULT_MAX_DECODED_CHUNKS):
        if type(max_decoded_chunks) is not int or not 1 <= max_decoded_chunks <= 1_000_000:
            raise DataError("Decoded-chunk budget must be an integer from 1 to 1000000")
        self.deadline = time.monotonic() + timeout_ms / 1000
        self.max_decoded_chunks = max_decoded_chunks
        self.stats = {"decoded_chunks": 0, "decoded_characters": 0}
        self.literal_keys = None

    def before_decode(self):
        self.check()
        if self.stats["decoded_chunks"] >= self.max_decoded_chunks:
            raise QueryWorkLimitExceeded(
                "Citation search exceeded its decoded-chunk work budget; use a more "
                "specific literal or increase max_decoded_chunks / --max-decoded-chunks"
            )
        self.stats["decoded_chunks"] += 1

    def expired(self):
        return time.monotonic() >= self.deadline

    def check(self):
        if self.expired():
            raise QueryBudgetExceeded(
                "Citation search exceeded its query budget; use a more specific literal "
                "or increase timeout_ms / --timeout-ms"
            )


def _eligible_window(text: str) -> bool:
    accepted, flags, reason = assess_sentence(text, "ja", max_length=512)
    return (
        accepted or reason in {"unbalanced-delimiters", "too-short"}
    ) and "sexual-content" not in flags


def _eligibility_policy() -> dict:
    return {
        "tile_chars": ELIGIBILITY_TILE_CHARS,
        "context_chars": ELIGIBILITY_CONTEXT_CHARS,
        "processor": TEXT_PROCESSOR_VERSION,
    }


def _eligibility_bits(text: str) -> bytes:
    """Evaluate fixed source windows once; inference never changes eligibility."""
    bits = bytearray((len(text) + ELIGIBILITY_TILE_CHARS * 8 - 1) // (ELIGIBILITY_TILE_CHARS * 8))
    for number, start in enumerate(range(0, len(text), ELIGIBILITY_TILE_CHARS)):
        sample = text[
            max(0, start - ELIGIBILITY_CONTEXT_CHARS) : min(
                len(text), start + ELIGIBILITY_TILE_CHARS + ELIGIBILITY_CONTEXT_CHARS
            )
        ]
        if _eligible_window(sample):
            bits[number // 8] |= 1 << (number % 8)
    return bytes(bits)


def _model_identity(path: Path) -> str:
    """Record model/tokenizer bytes, not a mutable model name or absolute path."""
    identity = hashlib.sha256()
    for file in sorted(path.rglob("*")):
        if file.is_file():
            resolved = file.resolve()
            identity.update(file.relative_to(path).as_posix().encode())
            identity.update(bytes.fromhex(sha256_file(resolved)))
    return identity.hexdigest()


@contextmanager
def _offline_models():
    keys = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        os.environ.update({key: "1" for key in keys})
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _describe_sat(model: Path, tokenizer: Path, *, threshold=0.25):
    model, tokenizer = model.resolve(), tokenizer.resolve()
    if not model.is_dir() or not tokenizer.is_dir():
        raise DataError("SaT requires existing local model and tokenizer directories")
    if not 0 < threshold < 1:
        raise DataError("SaT threshold must be strictly between zero and one")
    model_id, tokenizer_id = _model_identity(model), _model_identity(tokenizer)
    backend = "onnx-cpu" if (model / "model_optimized.onnx").is_file() else "pytorch"
    try:
        identity = {
            "engine": "wtpsplit", "version": version("wtpsplit"),
            "model_sha256": model_id, "tokenizer_sha256": tokenizer_id,
            "backend": backend, "threshold": threshold,
            "onnxruntime": version("onnxruntime") if backend == "onnx-cpu" else None,
            "transformers": version("transformers"), "tokenizers": version("tokenizers"),
        }
        if backend == "pytorch":
            identity["torch"] = version("torch")
    except PackageNotFoundError as exc:
        raise DataError("Install the local SaT build dependencies before selecting its profile") from exc
    return model, tokenizer, identity


def _local_sat(model: Path, tokenizer: Path, *, threshold=0.25):
    """No implicit model/tokenizer download in an offline build."""
    model, tokenizer, identity = _describe_sat(model, tokenizer, threshold=threshold)
    with _offline_models():
        try:
            from wtpsplit import SaT
        except ImportError as exc:
            raise DataError(
                "Install wtpsplit in your own build environment to use local SaT"
            ) from exc
        options = {}
        if identity["backend"] == "onnx-cpu":
            try:
                import onnxruntime
            except ImportError as exc:
                raise DataError("Install wtpsplit[onnx-cpu] to use local ONNX weights") from exc
            session_options = onnxruntime.SessionOptions()
            session_options.intra_op_num_threads = 2
            session_options.inter_op_num_threads = 1
            options = {
                "ort_providers": ["CPUExecutionProvider"],
                "ort_kwargs": {"sess_options": session_options},
            }
        sat = SaT(
            str(model),
            tokenizer_name_or_path=str(tokenizer),
            from_pretrained_kwargs={"local_files_only": True},
            **options,
        )

    def segment(text):
        with _offline_models():
            # wtpsplit infers its default from the *directory name*. Always
            # specify the threshold so renaming identical weights is harmless.
            return list(sat.split(text, threshold=threshold, strip_whitespace=False, batch_size=8))

    return segment, identity


def _validate_boundary_settings(options):
    mode, pause = options["boundary_mode"], options["pause_ms"]
    if mode not in {"hybrid", "punctuation"} or type(pause) is not int or not 250 <= pause <= 5000:
        raise DataError("Use hybrid/punctuation boundaries and an integer 250..5000 ms pause")
    sat, tokenizer, japanese = (options[k] for k in ("sat_model", "sat_tokenizer", "ja_punct_model"))
    if bool(sat) != bool(tokenizer):
        raise DataError("Provide both a local SaT model and local tokenizer")
    if sat and japanese:
        raise DataError("Select one local boundary model: SaT or Japanese character prediction")
    if mode == "punctuation" and (sat or japanese):
        raise DataError("Use hybrid mode with a model; punctuation mode uses explicit boundaries only")
    for key in ("sat_threshold", "ja_punct_threshold"):
        value = options[key]
        if type(value) not in {int, float} or not 0 < value < 1:
            raise DataError("Boundary thresholds must be finite numbers strictly between zero and one")
    if options.get("boundary_cache") is not None and not (sat or japanese):
        raise DataError("A boundary cache requires an optional local boundary model")


def _index_options(boundary_mode, pause_ms, model_info):
    return {
        "boundary_mode": boundary_mode, "pause_ms": pause_ms, "model": model_info,
        "eligibility": _eligibility_policy(), "candidate_policy": CANDIDATE_POLICY,
        "reference_policy": REFERENCE_POLICY, "boundary_policy": BOUNDARY_POLICY,
        "literal_policy": LITERAL_POLICY,
    }


def _index_build_id(snapshot_id, base_hash, options, *, processor=PROCESSOR):
    return "tubelex-index_" + digest_json({
        "snapshot": snapshot_id, "index_schema": SCHEMA_VERSION,
        "base_sha256": base_hash, "processor": processor, "options": options,
    })[:32]


def _open_index(path, *, readonly=False):
    return (
        sqlite3.connect(path.resolve(strict=True).as_uri() + "?mode=ro", uri=True)
        if readonly
        else sqlite3.connect(path)
    )


def _decode_text(blob):
    try:
        size = zstandard.frame_content_size(blob)
        if not 0 <= size <= MAX_TEXT_BYTES:
            raise DataError("Private caption chunk exceeds its decoded size budget")
        raw = zstandard.ZstdDecompressor().decompress(
            blob,
            max_output_size=MAX_TEXT_BYTES,
            allow_extra_data=False,
        )
        if len(raw) != size:
            raise DataError("Private caption chunk decoded size mismatch")
        return raw.decode("utf-8")
    except (zstandard.ZstdError, UnicodeError) as exc:
        raise DataError("Invalid compressed private caption chunk") from exc


def _origins(database, stream_id, left, right):
    first = database.execute(
        "SELECT start FROM origins WHERE stream_id=? AND start<=? ORDER BY start DESC LIMIT 1",
        (stream_id, left),
    ).fetchone()
    if first is None:
        raise DataError("Missing private caption alignment")
    return database.execute(
        "SELECT start,end,start_ms,end_ms FROM origins "
        "WHERE stream_id=? AND start>=? AND start<? ORDER BY start",
        (stream_id, first[0], right),
    ).fetchall()


def _match_reference(database, stream_id, left, right, *, seen_refs=None, boundaries_checked=False):
    """Sentence proposals affect clip selection, not the indexed text coverage."""
    stream = database.execute(
        "SELECT video_id,metadata,eligibility FROM streams WHERE id=?",
        (stream_id,),
    ).fetchone()
    metadata = parse_json(stream[1])
    if not 0 <= left < right <= metadata["text_length"]:
        raise DataError("Invalid private match range")
    for number in range(left // ELIGIBILITY_TILE_CHARS, (right - 1) // ELIGIBILITY_TILE_CHARS + 1):
        if number // 8 >= len(stream[2]):
            raise DataError("Missing private source eligibility bits")
        if not stream[2][number // 8] & (1 << (number % 8)):
            return None
    # Preserve the established within-sentence semantics at explicit terminal
    # punctuation, while allowing matches across uncertain timing boundaries.
    if right - left > 1 and not boundaries_checked:
        chunk = database.execute(
            "SELECT start,end,boundary_bits FROM chunks WHERE stream_id=? AND start<=? "
            "ORDER BY start DESC LIMIT 1",
            (stream_id, left),
        ).fetchone()
        if not chunk or chunk[1] < right:
            raise DataError("Private match range has no containing chunk")
        bits = _decode_boundary_bitmap(chunk[2], chunk[1] - chunk[0])
        if (bits >> (left - chunk[0] + 1)) & ((1 << (right - left - 1)) - 1):
            return None
    unit = database.execute(
        "SELECT start,end,boundary FROM units WHERE stream_id=? AND start<=? "
        "ORDER BY start DESC LIMIT 1",
        (stream_id, left),
    ).fetchone()
    if unit and unit[1] < right:
        unit = None
    unit_kind = UNIT_NAMES.get(unit[2]) if unit else None
    if unit and unit_kind is None:
        raise DataError("Invalid private display-unit boundary code")
    if metadata["boundary_mode"] == "punctuation" and unit_kind != "punctuation":
        return None
    origins = _origins(database, stream_id, left, right)
    boundary = "context-window"
    if unit and unit[1] - unit[0] <= 500:
        proposed = _origins(database, stream_id, unit[0], unit[1])
        if max(p[3] for p in proposed) - min(p[2] for p in proposed) <= 30_000:
            boundary = unit_kind
            origins = proposed
    if boundary == "context-window":
        # Include surrounding caption context where it fits, rather than
        # advertising an arbitrary single caption line as a complete sentence.
        before = database.execute(
            "SELECT start,end,start_ms,end_ms FROM origins WHERE stream_id=? AND start<? "
            "ORDER BY start DESC LIMIT 2",
            (stream_id, origins[0][0]),
        ).fetchall()
        after = database.execute(
            "SELECT start,end,start_ms,end_ms FROM origins WHERE stream_id=? AND start>=? "
            "ORDER BY start LIMIT 2",
            (stream_id, origins[-1][1]),
        ).fetchall()
        for candidate in [*before, *after]:
            proposed = [*origins, candidate]
            a, b = min(p[0] for p in proposed), max(p[1] for p in proposed)
            if b - a <= 500 and max(p[3] for p in proposed) - min(p[2] for p in proposed) <= 30_000:
                origins = proposed
    # A single very long cue cannot be divided into accurate word timestamps.
    # Return its actual envelope, with explicit uncertainty, rather than losing
    # the hit or fabricating a 30-second offset inside the cue.
    start_ms, end_ms = min(p[2] for p in origins), max(p[3] for p in origins)
    record = reference_record(
        AlignedSentence("", start_ms, end_ms, boundary),
        video_id=stream[0],
        snapshot_id=metadata["snapshot_id"],
    )
    if seen_refs is not None and record["id"] in seen_refs:
        return None
    if end_ms - start_ms > 30_000:
        record["tags"].append("timing:wide-cue-envelope")
    return record


def build_tubelex_index(
    snapshot: Path,
    base_artifact: Path,
    private_output: Path,
    references_output: Path,
    *,
    boundary_mode: str = "hybrid",
    pause_ms: int = 800,
    sat_model: Path | None = None,
    sat_tokenizer: Path | None = None,
    sat_threshold: float = 0.25,
    ja_punct_model: Path | None = None,
    ja_punct_threshold: float = 0.5,
    boundary_cache: Path | None = None,
) -> Path:
    snapshot = snapshot.resolve()
    if snapshot.is_dir():
        snapshot /= "manifest.json"
    manifest = verify_tubelex_snapshot(snapshot)
    base_artifact = base_artifact.resolve(strict=True)
    if not base_artifact.is_file():
        raise DataError("Base artifact must be a downloaded release file")
    private_output, references_output = _new_output(private_output), _new_output(references_output)
    if (
        private_output == references_output
        or references_output.is_relative_to(private_output)
        or private_output.is_relative_to(references_output)
    ):
        raise DataError("Private index and reference-export directories must be separate")
    for protected in (snapshot.parent, sat_model, sat_tokenizer, ja_punct_model):
        if protected is None:
            continue
        protected = protected.resolve()
        for destination in (private_output, references_output):
            if destination.is_relative_to(protected) or protected.is_relative_to(destination):
                raise DataError("Citation outputs must be separate from snapshot and model inputs")
    _validate_boundary_settings({
        "boundary_mode": boundary_mode, "pause_ms": pause_ms, "sat_model": sat_model,
        "sat_tokenizer": sat_tokenizer, "sat_threshold": sat_threshold,
        "ja_punct_model": ja_punct_model, "ja_punct_threshold": ja_punct_threshold,
        "boundary_cache": boundary_cache,
    })
    if boundary_cache is not None:
        if not (sat_model or ja_punct_model):
            raise DataError("A boundary cache requires an optional local boundary model")
        boundary_cache = boundary_cache.resolve()
        for protected in (
            snapshot.parent,
            private_output,
            references_output,
            sat_model,
            sat_tokenizer,
            ja_punct_model,
        ):
            if protected is None:
                continue
            protected = protected.resolve()
            if (
                boundary_cache == protected
                or boundary_cache.is_relative_to(protected)
                or protected.is_relative_to(boundary_cache)
            ):
                raise DataError("Boundary cache must be separate from input and output directories")
    segment, model_info = (
        _local_sat(sat_model, sat_tokenizer, threshold=sat_threshold) if sat_model else (None, None)
    )
    if ja_punct_model:
        from .tubelex_boundaries import local_japanese_character_model

        segment, model_info = local_japanese_character_model(
            ja_punct_model, threshold=ja_punct_threshold
        )
    cache_stats = Counter()
    if boundary_cache is not None:
        from .tubelex_cache import cached_segmenter

        segment = cached_segmenter(segment, model_info, boundary_cache, cache_stats)
    base_hash = sha256_file(base_artifact)
    options = _index_options(boundary_mode, pause_ms, model_info)
    build_id = _index_build_id(manifest["snapshot_id"], base_hash, options)
    private_output.mkdir(parents=True, mode=0o700)
    references_output.mkdir(parents=True)
    db_path = private_output / "citations.private.sqlite3"
    compressor = zstandard.ZstdCompressor(level=9, write_checksum=True)
    stats: Counter = Counter()
    # closing() is essential: Connection.__exit__ handles transactions only.
    with closing(_open_index(db_path)) as database, database:
        database.executescript(f"""
            PRAGMA user_version={SCHEMA_VERSION};
            PRAGMA journal_mode=MEMORY;
            PRAGMA temp_store=MEMORY;
            CREATE TABLE metadata(key TEXT PRIMARY KEY, value BLOB NOT NULL) WITHOUT ROWID;
            CREATE TABLE streams(id INTEGER PRIMARY KEY, video_id TEXT NOT NULL,
                metadata BLOB NOT NULL, eligibility BLOB NOT NULL);
            CREATE TABLE chunks(id INTEGER PRIMARY KEY, stream_id INTEGER NOT NULL,
                start INTEGER NOT NULL, end INTEGER NOT NULL, text_zstd BLOB NOT NULL,
                boundary_bits BLOB NOT NULL);
            CREATE INDEX chunks_range ON chunks(stream_id,start);
            CREATE TABLE origins(stream_id INTEGER NOT NULL, start INTEGER NOT NULL,
                end INTEGER NOT NULL, start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
                cue_ids BLOB NOT NULL, PRIMARY KEY(stream_id,start)) WITHOUT ROWID;
            CREATE TABLE units(stream_id INTEGER NOT NULL, start INTEGER NOT NULL,
                end INTEGER NOT NULL, boundary INTEGER NOT NULL,
                PRIMARY KEY(stream_id,start)) WITHOUT ROWID;
            CREATE VIRTUAL TABLE short_substring USING fts5(terms, content='', columnsize=0,
                detail=none, tokenize='ascii');
            CREATE VIRTUAL TABLE substring USING fts5(text, content='', columnsize=0,
                detail=none, tokenize='trigram case_sensitive 1');
            CREATE TABLE literal_grams(gram BLOB PRIMARY KEY) WITHOUT ROWID;
            CREATE TABLE literal_filter(id INTEGER PRIMARY KEY CHECK(id=1),
                fingerprints INTEGER NOT NULL, bits BLOB NOT NULL);
            CREATE TABLE exported_refs(id TEXT PRIMARY KEY) WITHOUT ROWID;
        """)
        known_literals, literal_fifo = set(), deque()
        for key, value in {"build_id": build_id, "base_sha256": base_hash}.items():
            database.execute("INSERT INTO metadata VALUES (?,?)", (key, canonical_json(value)))
        with (references_output / "references.jsonl.zst").open("xb") as raw:
            # A streaming writer and one-shot chunk compression must not share
            # a compressor context: compress() resets its state and loses output.
            with zstandard.ZstdCompressor(level=9, write_checksum=True).stream_writer(
                raw
            ) as public:
                for entry in manifest["entries"]:
                    caption = read_private_caption(safe_relative(snapshot.parent, entry["path"]))
                    for stream in caption_streams(parse_vtt(caption["vtt"])):
                        metadata = {
                            "snapshot_id": manifest["snapshot_id"],
                            "boundary_mode": boundary_mode,
                            "voice": stream.voice,
                            "region": stream.region,
                            "source_metadata": caption["metadata"],
                            "text_length": len(stream.text),
                        }
                        stream_id = database.execute(
                            "INSERT INTO streams(video_id,metadata,eligibility) VALUES (?,?,?)",
                            (
                                entry["video_id"],
                                canonical_json(metadata),
                                _eligibility_bits(stream.text),
                            ),
                        ).lastrowid
                        database.executemany(
                            "INSERT INTO origins VALUES (?,?,?,?,?,?)",
                            (
                                (
                                    stream_id,
                                    p.start,
                                    p.end,
                                    p.start_ms,
                                    p.end_ms,
                                    canonical_json(p.cue_ids),
                                )
                                for p in stream.origins
                            ),
                        )
                        units = list(stream_units(
                            stream, segment=segment, pause_ms=pause_ms,
                            refine_punctuated=boundary_mode == "hybrid",
                        ))
                        database.executemany(
                            "INSERT INTO units VALUES (?,?,?,?)",
                            ((stream_id, a, b, UNIT_CODES[kind]) for a, b, kind in units),
                        )
                        from .text import is_complete_sentence, sentence_spans

                        boundaries = [
                            b
                            for a, b in sentence_spans(stream.text, "ja")
                            if is_complete_sentence(stream.text[a:b], "ja")
                        ]
                        # Overlap guarantees every permitted <=500-character
                        # query is contained in a chunk, independent of units.
                        for offset in range(0, len(stream.text), CHUNK_STEP):
                            text = stream.text[offset : offset + CHUNK_CHARS]
                            bitmap = _boundary_bitmap(boundaries, offset, offset + len(text))
                            rowid = database.execute(
                                "INSERT INTO chunks(stream_id,start,end,text_zstd,boundary_bits) "
                                "VALUES (?,?,?,?,?)",
                                (
                                    stream_id,
                                    offset,
                                    offset + len(text),
                                    compressor.compress(text.encode()),
                                    bitmap,
                                ),
                            ).lastrowid
                            candidate_spans = _candidate_spans(text, bitmap)
                            new_literals = []
                            for key in sorted(_literal_keys(candidate_spans)):
                                if key in known_literals:
                                    continue
                                new_literals.append((key,))
                                known_literals.add(key)
                                literal_fifo.append(key)
                                # A bounded recent vocabulary avoids repeated
                                # inserts without keeping the corpus in RAM.
                                if len(literal_fifo) > 65_536:
                                    known_literals.remove(literal_fifo.popleft())
                            database.executemany(
                                "INSERT OR IGNORE INTO literal_grams VALUES (?)", new_literals,
                            )
                            database.execute(
                                "INSERT INTO substring(rowid,text) VALUES (?,?)",
                                # Controls are forbidden in queries. Positions
                                # are unused: this separator exists only in the
                                # private candidate vocabulary, never the source.
                                (rowid, "\x1f".join(candidate_spans)),
                            )
                            terms = {
                                part[i : i + w].encode()
                                for part in candidate_spans
                                for w in (1, 2)
                                for i in range(len(part) - w + 1)
                            }
                            database.execute(
                                "INSERT INTO short_substring(rowid,terms) VALUES (?,?)",
                                (rowid, " ".join("s" + term.hex() for term in sorted(terms))),
                            )
                            stats["chunks"] += 1
                            stats["boundary-bitmap-bytes"] += len(bitmap)
                        stats["indexed-characters"] += len(stream.text)
                        stats["indexed-units"] += len(units)
                        stats["streams"] += 1
                        # This export is a text-free inventory of suggested
                        # clips. Query-spanning uncertain boundaries may yield
                        # additional envelopes dynamically from private origins.
                        previous_start = None
                        starts = merge(
                            (origin.start for origin in stream.origins),
                            (left for left, _, _ in units),
                        )
                        for left in starts:
                            if left == previous_start:
                                continue
                            previous_start = left
                            record = _match_reference(
                                database,
                                stream_id,
                                left,
                                left + 1,
                            )
                            if (
                                record
                                and database.execute(
                                    "INSERT OR IGNORE INTO exported_refs VALUES (?)",
                                    (record["id"],),
                                ).rowcount
                            ):
                                public.write(canonical_json(record) + b"\n")
                                stats["references"] += 1
        database.execute("INSERT INTO substring(substring) VALUES ('optimize')")
        database.execute("INSERT INTO short_substring(short_substring) VALUES ('optimize')")
        database.execute("INSERT INTO substring(substring,rank) VALUES ('integrity-check',0)")
        database.execute(
            "INSERT INTO short_substring(short_substring,rank) VALUES ('integrity-check',0)"
        )
        database.execute("DROP TABLE exported_refs")
        stats["literal-fourgram-fingerprints"] = database.execute(
            "SELECT count(*) FROM literal_grams"
        ).fetchone()[0]
        bits = bytearray(_literal_filter_size(stats["literal-fourgram-fingerprints"]))
        for (key,) in database.execute("SELECT gram FROM literal_grams"):
            _literal_add(bits, key)
        database.execute(
            "INSERT INTO literal_filter VALUES (1,?,?)",
            (stats["literal-fourgram-fingerprints"], bytes(bits)),
        )
        stats["literal-filter-bytes"] = len(bits)
        stats["literal-filter-set-bits"] = sum(byte.bit_count() for byte in bits)
        database.execute("DROP TABLE literal_grams")
        if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise DataError("Private citation database failed integrity check")
    exported_count = 0
    with (references_output / "references.jsonl.zst").open("rb") as raw:
        with zstandard.ZstdDecompressor().stream_reader(raw) as decoded:
            with io.TextIOWrapper(decoded, encoding="utf-8") as lines:
                for line in lines:
                    record = parse_json(line)
                    validate_record(record)
                    if record["kind"] != "reference":
                        raise DataError("Transcript-bearing record in external reference export")
                    exported_count += 1
    if exported_count != stats["references"]:
        raise DataError("Reference export count does not match private build inventory")
    with closing(_open_index(db_path)) as database:
        # FTS merges and the temporary reference-dedup table leave free pages.
        # Compact the closed logical build before hashing/exporting it. Payloads
        # stay compressed; VACUUM needs temporary disk space, not decoded text.
        database.execute("VACUUM")
        with database:
            database.execute("INSERT INTO metadata VALUES ('complete',?)", (b"true",))
    public_manifest = {
        "schema_version": SCHEMA_VERSION,
        "kind": "external-citation-sidecar",
        "build_id": build_id,
        "source_id": "tubelex-ja",
        "language": "ja",
        "snapshot_id": manifest["snapshot_id"],
        "base_artifact_sha256": base_hash,
        "processor": PROCESSOR,
        "options": options,
        "discovery": {
            "url": manifest["upstream"],
            "revision": manifest["revision"],
            "video_list_sha256": manifest["video_list_sha256"],
        },
        "references": stats["references"],
        "contains_transcripts": False,
        "asset": {
            "path": "references.jsonl.zst",
            "sha256": sha256_file(references_output / "references.jsonl.zst"),
        },
        "rights": "External references only; no transcript redistribution license is asserted.",
    }
    write_json(references_output / "manifest.json", public_manifest)
    stats.update(cache_stats)
    write_json(
        private_output / "manifest.private.json",
        {
            **public_manifest,
            "kind": "private-external-search-index",
            "contains_transcripts": True,
            "publish": False,
            "stats": dict(stats),
            "index_sha256": sha256_file(db_path),
            "index": db_path.name,
        },
    )
    return private_output / "manifest.private.json"


def _canonical_query(query: str, limit: int) -> str:
    import unicodedata

    if not isinstance(query, str) or len(query) > MAX_QUERY_CHARS * 4:
        raise DataError("Use a Unicode literal substring of at most 500 NFC characters")
    if type(limit) is not int or not 1 <= limit <= 250:
        raise DataError("Result limit must be an integer from 1 to 250")
    query = unicodedata.normalize("NFC", query)
    if (
        not query
        or len(query) > MAX_QUERY_CHARS
        or any(unicodedata.category(c) in {"Cc", "Cs"} for c in query)
    ):
        raise DataError("Use a nonempty literal substring of at most 500 characters")
    return query


class TubelexReader:
    """One reusable read-only connection per serving thread or worker.

    Verify the artifacts before activation. Close and recreate the reader when
    activating a new immutable build. No model runtime is loaded by this class.
    """

    def __init__(
        self,
        database_path: Path,
        *,
        base_artifact: Path | None = None,
        timeout_ms: int = DEFAULT_QUERY_TIMEOUT_MS,
        max_decoded_chunks: int = DEFAULT_MAX_DECODED_CHUNKS,
    ):
        if type(timeout_ms) is not int or not 1 <= timeout_ms <= 60_000:
            raise DataError("Query timeout budget must be an integer from 1 to 60000 ms")
        self._database = None
        self._timeout_ms = timeout_ms
        # Validate before opening the database, including bool/string rejection.
        _QueryBudget(timeout_ms, max_decoded_chunks)
        self._max_decoded_chunks = max_decoded_chunks
        self.last_search_stats = None
        database = _open_index(database_path, readonly=True)
        try:
            if database.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise DataError("Unsupported citation index schema; rebuild the private sidecar")
            metadata = dict(database.execute("SELECT key,value FROM metadata"))
            if metadata.get("complete") != b"true":
                raise DataError("Incomplete private citation index")
            try:
                build_id = parse_json(metadata["build_id"])
                base_hash = parse_json(metadata["base_sha256"])
            except (KeyError, TypeError, ValueError) as exc:
                raise DataError("Invalid private citation index identity metadata") from exc
            if (
                not isinstance(build_id, str)
                or not re.fullmatch(r"tubelex-index_[0-9a-f]{32}", build_id)
                or not isinstance(base_hash, str)
                or not re.fullmatch(r"[0-9a-f]{64}", base_hash)
            ):
                raise DataError("Invalid private citation index identity metadata")
            if base_artifact and sha256_file(base_artifact) != base_hash:
                raise DataError("Citation index belongs to a different base artifact")
            _, self._literal_filter = _load_literal_filter(database)
            self.build_id = build_id
        except BaseException:
            database.close()
            raise
        self._database = database

    def search(self, query: str, *, limit=250) -> list[dict]:
        if self._database is None:
            raise DataError("Citation reader is closed")
        query = _canonical_query(query, limit)
        budget = _QueryBudget(self._timeout_ms, self._max_decoded_chunks)
        try:
            results = _search_database(
                self._database, query, limit, self._timeout_ms, budget=budget,
                literal_filter=self._literal_filter,
            )
            self.last_search_stats = {**budget.stats, "outcome": "complete", "results": len(results)}
            return results
        except BaseException:
            self.last_search_stats = {**budget.stats, "outcome": "error", "results": 0}
            raise

    def close(self):
        if self._database is not None:
            self._database.close()
            self._database = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def search_tubelex_index(
    database_path: Path,
    query: str,
    *,
    limit=250,
    base_artifact=None,
    timeout_ms=DEFAULT_QUERY_TIMEOUT_MS,
    max_decoded_chunks=DEFAULT_MAX_DECODED_CHUNKS,
) -> list[dict]:
    """Convenience reader for one lookup; serving code can reuse TubelexReader."""
    query = _canonical_query(query, limit)
    with TubelexReader(
        database_path, base_artifact=base_artifact, timeout_ms=timeout_ms,
        max_decoded_chunks=max_decoded_chunks,
    ) as reader:
        return reader.search(query, limit=limit)


def _search_database(database, query: str, limit: int, timeout_ms: int, *, budget=None,
                     literal_filter=None, collector=None) -> list[dict]:
    budget = budget if budget is not None else _QueryBudget(timeout_ms)
    database.set_progress_handler(budget.expired, 1000)
    try:
        budget.check()
        results = _search_candidates(database, query, limit, budget,
                                     literal_filter=literal_filter, collector=collector)
        budget.check()
        return results
    except sqlite3.OperationalError as exc:
        if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_INTERRUPT and budget.expired():
            raise QueryBudgetExceeded(
                "Citation search exceeded its query budget during SQLite work; "
                "use a more specific literal or increase timeout_ms / --timeout-ms"
            ) from exc
        raise
    finally:
        database.set_progress_handler(None, 0)


def _search_candidates(database, query: str, limit: int, budget: _QueryBudget,
                       *, literal_filter=None, collector=None) -> list[dict]:
    if len(query) >= 4:
        if literal_filter is None:
            _, literal_filter = _load_literal_filter(database)
        if budget.literal_keys is None:
            budget.literal_keys = _literal_keys([query])
        possible = all(_literal_maybe_contains(literal_filter, key) for key in budget.literal_keys)
        budget.check()
        if not possible:
            budget.stats["global_literal_rejections"] = budget.stats.get("global_literal_rejections", 0) + 1
            return []
    if len(query) < 3:
        rows = database.execute(
            "SELECT c.id,c.stream_id,c.start,c.text_zstd,c.boundary_bits FROM short_substring p "
            "JOIN chunks c ON c.id=p.rowid WHERE short_substring MATCH ? ORDER BY p.rowid",
            ("s" + query.encode().hex(),),
        )
    else:
        # detail=none needs three-scalar tokens; verification proves the
        # complete literal. Positions are unnecessary in this candidate index.
        grams = sorted({query[i : i + 3] for i in range(len(query) - 2)})
        match = " AND ".join('"' + g.replace('"', '""') + '"' for g in grams)
        rows = database.execute(
            "SELECT c.id,c.stream_id,c.start,c.text_zstd,c.boundary_bits FROM substring f "
            "JOIN chunks c ON c.id=f.rowid WHERE substring MATCH ? ORDER BY f.rowid",
            (match,),
        )
    try:
        results, seen_refs = [], set()
        interior_mask = (1 << (len(query) - 1)) - 1
        for _, stream_id, offset, compressed, bitmap in rows:
            budget.before_decode()
            text = _decode_text(compressed)
            budget.stats["decoded_characters"] += len(text)
            position = text.find(query)
            boundaries = (
                _decode_boundary_bitmap(bitmap, len(text)) if position >= 0 and interior_mask else 0
            )
            examined = 0
            while position >= 0:
                if examined % 32 == 0:
                    budget.check()
                examined += 1
                left, right = offset + position, offset + position + len(query)
                # Overlap ownership removes duplicate hits with constant
                # bookkeeping, rather than retaining every candidate position.
                crosses = (boundaries >> (position + 1)) & interior_mask
                if position < CHUNK_STEP and not crosses:
                    record = _match_reference(
                        database,
                        stream_id,
                        left,
                        right,
                        seen_refs=seen_refs,
                        boundaries_checked=True,
                    )
                    if record and record["id"] not in seen_refs:
                        seen_refs.add(record["id"])
                        if collector is not None:
                            collector.add(record)
                        else:
                            results.append(record)
                            if len(results) == limit:
                                return results
                position = text.find(query, position + 1)
        return results
    finally:
        rows.close()


def verify_tubelex_index(
    private_build: Path,
    references: Path,
    *,
    base_artifact: Path | None = None,
    deep=False,
) -> dict:
    try:
        return _verify_tubelex_index(
            private_build, references, base_artifact=base_artifact, deep=deep
        )
    except DataError:
        raise
    except (KeyError, TypeError, ValueError, sqlite3.Error, zstandard.ZstdError) as exc:
        raise DataError("Invalid or inconsistent citation build artifacts") from exc


def _verify_tubelex_index(
    private_build: Path,
    references: Path,
    *,
    base_artifact: Path | None = None,
    deep=False,
) -> dict:
    """Verify completed sidecar artifacts once before activation or transfer.

    Checksums bind the private database and text-free export to the same build.
    Deep mode additionally checks bounded decoded chunks, overlap, and private
    alignment partitions. It is not a human assessment of sentence quality.
    """
    import unicodedata

    private_build, references = private_build.resolve(), references.resolve()
    private = read_json(private_build / "manifest.private.json")
    public = read_json(references / "manifest.json")
    if not isinstance(private, dict) or not isinstance(public, dict):
        raise DataError("Citation manifests must be JSON objects")
    if (
        private.get("kind") != "private-external-search-index"
        or private.get("publish") is not False
        or private.get("contains_transcripts") is not True
        or public.get("kind") != "external-citation-sidecar"
        or public.get("contains_transcripts") is not False
    ):
        raise DataError("Invalid private/public citation artifact roles")
    for key in (
        "schema_version",
        "build_id",
        "source_id",
        "language",
        "snapshot_id",
        "base_artifact_sha256",
        "processor",
        "options",
        "references",
        "asset",
        "discovery",
    ):
        if private.get(key) != public.get(key):
            raise DataError(f"Citation manifests disagree on {key}")
    if public["schema_version"] != SCHEMA_VERSION:
        raise DataError("Unsupported citation index schema")
    if public["source_id"] != "tubelex-ja" or public["language"] != "ja":
        raise DataError("Unexpected citation source or language")
    if not isinstance(public.get("options"), dict):
        raise DataError("Invalid private citation index build options")
    if public["options"].get("eligibility") != _eligibility_policy():
        raise DataError("Unsupported private source eligibility policy; rebuild the index")
    if public["options"].get("candidate_policy") != CANDIDATE_POLICY:
        raise DataError("Unsupported private candidate policy; rebuild the index")
    if public["options"].get("reference_policy") != REFERENCE_POLICY:
        raise DataError("Unsupported external reference inventory policy; rebuild the index")
    if public["options"].get("boundary_policy") != BOUNDARY_POLICY:
        raise DataError("Unsupported external display-boundary policy; rebuild the index")
    if public["options"].get("literal_policy") != LITERAL_POLICY:
        raise DataError("Unsupported private literal-dictionary policy; rebuild the index")
    expected_id = _index_build_id(
        public["snapshot_id"], public["base_artifact_sha256"], public["options"],
        processor=public["processor"],
    )
    if expected_id != public["build_id"]:
        raise DataError("Citation build identity is inconsistent")
    database_path = safe_relative(private_build, private["index"])
    if sha256_file(database_path) != private["index_sha256"]:
        raise DataError("Private citation index checksum mismatch")
    for suffix in ("-wal", "-journal"):
        if database_path.with_name(database_path.name + suffix).exists():
            raise DataError("Citation index must be a closed, standalone SQLite artifact")
    if base_artifact and sha256_file(base_artifact) != public["base_artifact_sha256"]:
        raise DataError("Citation index belongs to a different base artifact")
    export = safe_relative(references, public["asset"]["path"])
    if sha256_file(export) != public["asset"]["sha256"]:
        raise DataError("External reference export checksum mismatch")
    count = 0
    with export.open("rb") as raw, zstandard.ZstdDecompressor().stream_reader(raw) as decoded:
        with io.TextIOWrapper(decoded, encoding="utf-8") as lines:
            while line := lines.readline(64 * 1024 + 1):
                if len(line) > 64 * 1024:
                    raise DataError("Oversized external reference record")
                record = parse_json(line)
                validate_record(record)
                if record["kind"] != "reference" or record["snapshot_id"] != public["snapshot_id"]:
                    raise DataError("Unexpected record in text-free reference export")
                locator = record["locator"]
                identity = re.fullmatch(
                    r"([A-Za-z0-9_-]{11}):([0-9]{1,15}):([0-9]{1,15})", record["native_id"]
                )
                if identity is None:
                    raise DataError("Invalid external citation identity")
                video, start, end = identity.groups()
                expected = reference_record(
                    AlignedSentence("", int(start), int(end), ""),
                    video_id=video,
                    snapshot_id=public["snapshot_id"],
                )
                if any(record[key] != expected[key] for key in ("id", "url", "locator")):
                    raise DataError("External citation URL and timing disagree")
                if set(record) != set(expected) or any(
                    record[key] != expected[key] for key in expected if key != "tags"
                ):
                    raise DataError("Unexpected text or metadata in external reference export")
                allowed_boundaries = {
                    "boundary:model",
                    "boundary:punctuation",
                    "boundary:pause-inferred",
                    "boundary:unsegmented",
                    "boundary:context-window",
                }
                tags = set(record["tags"])
                if (
                    not {"manual-captions", "timing:cue-envelope"} <= tags
                    or len(tags & allowed_boundaries) != 1
                    or tags
                    - allowed_boundaries
                    - {"manual-captions", "timing:cue-envelope", "timing:wide-cue-envelope"}
                ):
                    raise DataError("Unexpected text in external reference tags")
                if locator["type"] != "media":
                    raise DataError("Unexpected non-media external citation")
                count += 1
                if count > public["references"]:
                    raise DataError("External reference export exceeds its inventory")
    if count != public["references"]:
        raise DataError("Reference export inventory mismatch")
    with closing(_open_index(database_path, readonly=True)) as database:
        if database.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise DataError("Private index SQLite schema mismatch")
        if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise DataError("Private citation database failed integrity check")
        metadata = dict(database.execute("SELECT key,value FROM metadata"))
        if (
            metadata.get("complete") != b"true"
            or parse_json(metadata["build_id"]) != public["build_id"]
            or parse_json(metadata["base_sha256"]) != public["base_artifact_sha256"]
        ):
            raise DataError("Private database identity disagrees with its manifest")
        chunks = database.execute("SELECT count(*) FROM chunks").fetchone()[0]
        streams = database.execute("SELECT count(*) FROM streams").fetchone()[0]
        units = database.execute("SELECT count(*) FROM units").fetchone()[0]
        fingerprints, literal_filter = _load_literal_filter(database)
        if (
            chunks != private["stats"]["chunks"]
            or streams != private["stats"]["streams"]
            or units != private["stats"]["indexed-units"]
            or fingerprints != private["stats"]["literal-fourgram-fingerprints"]
            or len(literal_filter) != private["stats"]["literal-filter-bytes"]
            or sum(byte.bit_count() for byte in literal_filter) != private["stats"]["literal-filter-set-bits"]
            or database.execute("SELECT count(*) FROM literal_filter").fetchone()[0] != 1
        ):
            raise DataError("Private database inventory mismatch")
        decoded_chars = 0
        if deep:
            expected_filter = bytearray(len(literal_filter))
            expected_postings = {table: _PostingBinding() for table in ("short_substring", "substring")}
            actual_postings = {table: _PostingBinding() for table in expected_postings}
            for table, parent, column in (
                ("chunks", "streams", "stream_id"),
                ("origins", "streams", "stream_id"),
                ("units", "streams", "stream_id"),
            ):
                if database.execute(
                    f"SELECT 1 FROM {table} c WHERE NOT EXISTS "
                    f"(SELECT 1 FROM {parent} p WHERE p.id=c.{column}) LIMIT 1",
                ).fetchone():
                    raise DataError("Orphaned private citation index records")
            database.execute("PRAGMA temp_store=MEMORY")
            for table in ("short_substring", "substring"):
                database.execute(
                    f"CREATE VIRTUAL TABLE temp.{table}_vocab "
                    f"USING fts5vocab(main,{table},'instance')"
                )
                if database.execute(
                    f"SELECT 1 FROM temp.{table}_vocab v WHERE NOT EXISTS "
                    "(SELECT 1 FROM chunks c WHERE c.id=v.doc) LIMIT 1"
                ).fetchone():
                    raise DataError("Orphaned private substring postings")
                for term, chunk in database.execute(f"SELECT term,doc FROM temp.{table}_vocab"):
                    actual_postings[table].add(term, chunk)
            for stream_id, stream_metadata, eligibility in database.execute(
                "SELECT id,metadata,eligibility FROM streams ORDER BY id"
            ):
                stream_info = parse_json(stream_metadata)
                if not isinstance(stream_info, dict):
                    raise DataError("Invalid private caption stream metadata")
                length = stream_info.get("text_length")
                if type(length) is not int or not 0 < length <= chunks * CHUNK_CHARS:
                    raise DataError("Invalid private caption stream length")
                expected_bits = bytearray(
                    (length + ELIGIBILITY_TILE_CHARS * 8 - 1) // (ELIGIBILITY_TILE_CHARS * 8)
                )
                if not isinstance(eligibility, bytes) or len(eligibility) != len(expected_bits):
                    raise DataError("Invalid private source eligibility bitmap")
                next_tile = 0
                punctuation = database.execute(
                    "SELECT end FROM units WHERE stream_id=? AND boundary=? ORDER BY start",
                    (stream_id, UNIT_CODES["punctuation"]),
                )
                next_boundary = next(punctuation, (None,))[0]
                pending = deque()
                previous_text, previous_start, end, expected_start = "", 0, 0, 0
                for chunk_id, start, stop, blob, bitmap in database.execute(
                    "SELECT id,start,end,text_zstd,boundary_bits FROM chunks WHERE stream_id=? ORDER BY start",
                    (stream_id,),
                ):
                    text = _decode_text(blob)
                    boundary_bits = _decode_boundary_bitmap(bitmap, len(text))
                    _expected_postings(text, bitmap, chunk_id, expected_postings)
                    for key in _literal_keys(_candidate_spans(text, bitmap)):
                        _literal_add(expected_filter, key)
                    while next_boundary is not None and next_boundary < stop:
                        if not 0 < next_boundary <= length:
                            raise DataError("Invalid private sentence boundary")
                        pending.append(next_boundary)
                        next_boundary = next(punctuation, (None,))[0]
                    while pending and pending[0] <= start:
                        pending.popleft()
                    expected_boundaries = 0
                    for boundary in pending:
                        expected_boundaries |= 1 << (boundary - start)
                    if boundary_bits != expected_boundaries:
                        raise DataError("Private boundary bitmap disagrees with sentence units")
                    if (
                        start != expected_start
                        or stop - start != len(text)
                        or not text
                        or not unicodedata.is_normalized("NFC", text)
                    ):
                        raise DataError("Invalid private caption chunk partition")
                    overlap = end - start
                    if previous_text and previous_text[start - previous_start :] != text[:overlap]:
                        raise DataError("Overlapping caption chunks disagree")
                    # A two-chunk buffer also verifies eligibility windows
                    # crossing a storage seam, without decoding the whole stream.
                    buffer = previous_text + text[overlap:] if previous_text else text
                    buffer_start = previous_start if previous_text else start
                    while next_tile * ELIGIBILITY_TILE_CHARS < stop:
                        tile_start = next_tile * ELIGIBILITY_TILE_CHARS
                        a = max(0, tile_start - ELIGIBILITY_CONTEXT_CHARS)
                        b = min(
                            length, tile_start + ELIGIBILITY_TILE_CHARS + ELIGIBILITY_CONTEXT_CHARS
                        )
                        if b > stop:
                            break
                        if a < buffer_start or b <= a:
                            raise DataError("Invalid private source eligibility coverage")
                        if _eligible_window(buffer[a - buffer_start : b - buffer_start]):
                            expected_bits[next_tile // 8] |= 1 << (next_tile % 8)
                        next_tile += 1
                    previous_text, previous_start, end = text, start, stop
                    expected_start += CHUNK_STEP
                if not previous_text:
                    raise DataError("Caption stream has no indexed text")
                punctuation.close()
                if end != length:
                    raise DataError("Private caption stream length disagrees with chunks")
                if eligibility != bytes(expected_bits):
                    raise DataError("Private source eligibility bitmap disagrees with text")
                decoded_chars += end
                origin_end = 0
                for a, b, start_ms, end_ms, ids in database.execute(
                    "SELECT start,end,start_ms,end_ms,cue_ids FROM origins WHERE stream_id=? ORDER BY start",
                    (stream_id,),
                ):
                    identities = parse_json(ids)
                    if (
                        a != origin_end
                        or b <= a
                        or b > end
                        or not 0 <= start_ms < end_ms
                        or not isinstance(identities, list)
                        or not identities
                        or any(
                            not isinstance(identity, str)
                            or not re.fullmatch(r"cue-[1-9][0-9]*", identity)
                            for identity in identities
                        )
                    ):
                        raise DataError("Invalid private caption origin partition")
                    origin_end = b
                if origin_end != end:
                    raise DataError("Private origins do not cover indexed caption text")
                unit_end = 0
                for a, b, kind in database.execute(
                    "SELECT start,end,boundary FROM units WHERE stream_id=? ORDER BY start",
                    (stream_id,),
                ):
                    if a < unit_end or not a < b <= end or kind not in UNIT_NAMES:
                        raise DataError("Invalid private display-unit partition")
                    unit_end = b
            if decoded_chars != private["stats"]["indexed-characters"]:
                raise DataError("Private caption coverage count mismatch")
            if bytes(expected_filter) != literal_filter:
                raise DataError("Private literal-filter bits disagree with caption text")
            for table, expected in expected_postings.items():
                if expected.value != actual_postings[table].value:
                    raise DataError(f"Private {table} postings disagree with caption text")
    result = {
        "build_id": public["build_id"],
        "schema_version": SCHEMA_VERSION,
        "references": count,
        "streams": streams,
        "chunks": chunks,
        "deep": bool(deep),
    }
    if deep:
        result["indexed_characters"] = decoded_chars
        result["posting_verification"] = "complete-term-document-v1"
        result["verified_postings"] = {table: binding.count for table, binding in actual_postings.items()}
    return result
