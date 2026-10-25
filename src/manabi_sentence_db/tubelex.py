"""Opt-in TUBELEX Japanese caption snapshots and sentence-to-cue alignment.

Caption text is private input. Public records produced here are the existing
text-free canonical ``reference`` kind, never corpus ``document`` records.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import math
import os
import re
import subprocess
import time
import unicodedata
import uuid
from bisect import bisect_left, bisect_right
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

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
from .text import _PAIRS, assess_sentence, is_complete_sentence, sentence_spans

TUBELEX_REVISION = "7cb5fb36add76b83a266d1967536e1a1d3faa513"
TUBELEX_LIST_SHA256 = "eb0e2442a4872bda280ec96e99b6d0b9f620eaf3f2f8da13511bfeca284002ba"
TUBELEX_LIST_URL = (
    f"https://raw.githubusercontent.com/naist-nlp/tubelex/{TUBELEX_REVISION}/corpus/videos-ja.csv"
)
MAX_INPUT_BYTES = 32 * 1024**2
PROCESSOR = "tubelex-ja-independent-coverage-v7"
BOUNDARY_POLICY = "selective-mixed-punctuation-v1"
# Cue labels/export inventory changed in processor v6, not model input text or
# segmentation. Preserve completed inference; advance this only when those change.
BOUNDARY_INPUT_VERSION = "tubelex-ja-independent-coverage-v5"
CACHE_POLICY = "manual-ja-v3"
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
TIMESTAMP = r"(?:\d{2,}:)?\d{2}:\d{2}\.\d{3}"
TIMING = re.compile(rf"^({TIMESTAMP})[ \t]+-->[ \t]+({TIMESTAMP})(?:[ \t].*)?$")


@dataclass(frozen=True)
class Origin:
    start: int
    end: int
    start_ms: int
    end_ms: int
    cue_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    text: str
    voice: str = ""
    region: str = ""
    origins: tuple[Origin, ...] = field(default=(), compare=False)
    scrolling: bool = field(default=False, compare=False)


@dataclass(frozen=True)
class AlignedSentence:
    text: str
    start_ms: int
    end_ms: int
    boundary: str
    start: int = 0
    end: int = 0


@dataclass(frozen=True)
class CaptionStream:
    text: str
    origins: tuple[Origin, ...]
    voice: str = ""
    region: str = ""


class CaptionUnavailable(DataError):
    """Explicitly removed/private content can be recorded and skipped."""


def _new_output(path: Path) -> Path:
    """Resolve parents but reject an existing destination, including dangling links."""
    if path.is_symlink() or path.exists():
        raise DataError(f"Output already exists: {path}; choose a fresh destination")
    resolved = path.resolve()
    if resolved.exists():
        raise DataError(f"Output already exists: {resolved}")
    return resolved


def _get(url: str, *, user_agent: str) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": user_agent}), timeout=30) as response:
        data = response.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise DataError("TUBELEX input exceeds the 32 MiB per-file budget")
    return data


def select_manual_japanese(info: dict) -> dict | None:
    """Use only uploader/manual Japanese tracks, never the automatic-caption map.

    Japanese being present in a subtitle-language map alone does not rule out
    translation. Reject tlang, ASR, and explicit translation labels as well.
    Human-created translations cannot reliably be distinguished from originals.
    """
    if not isinstance(info, dict) or not isinstance(info.get("subtitles", {}), dict):
        raise DataError("Invalid YouTube subtitle metadata")
    tracks = info.get("subtitles", {}).get("ja", [])
    if not isinstance(tracks, list) or any(not isinstance(track, dict) for track in tracks):
        raise DataError("Invalid YouTube Japanese track metadata")
    for track in tracks:
        url = track.get("url", "")
        if not isinstance(url, str):
            continue
        try:
            parsed = urlparse(url)
            if parsed.port not in {None, 443}:
                continue
        except ValueError:
            continue
        query = parse_qs(parsed.query, keep_blank_values=True)
        label = str(track.get("name", "")).lower()
        if (
            track.get("ext") != "vtt"
            or parsed.scheme != "https"
            or parsed.hostname not in {"www.youtube.com", "youtube.com"}
            or parsed.path != "/api/timedtext"
            or parsed.username
            or parsed.password
            or "tlang" in query
            or "asr" in query.get("kind", [])
            or query.get("lang", [None]) != ["ja"]
            or ("v" in query and query["v"] != [info.get("id")])
            or track.get("is_translated")
            or track.get("is_auto_generated")
            or "auto" in label
            or "translated" in label
        ):
            continue
        return track
    return None


def _read_bounded(path: Path) -> bytes:
    with path.open("rb") as source:
        data = source.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise DataError("TUBELEX input exceeds the 32 MiB per-file budget")
    return data


def _compress_private(path: Path, value: dict) -> None:
    # Exclusive creation; caller must use a fresh snapshot/cache directory.
    encoded = canonical_json(value)
    if len(encoded) > MAX_INPUT_BYTES:
        raise DataError("Encoded private caption exceeds input budget")
    _write_new_bytes(path, zstandard.ZstdCompressor(level=9).compress(encoded))


def _write_new_bytes(path: Path, data: bytes) -> None:
    """A failed/interrupted write must never look like a completed cache entry.

    Acquisition is serial. Cache destinations are resolved and must be new;
    staging artifacts are task-owned and moved to Trash on handled failures.
    """
    if path.is_symlink():
        raise DataError("Refusing a symlink cache destination")
    path = path.resolve()
    if path.exists():
        raise DataError(f"Refusing to overwrite existing cache entry: {path.name}")
    staged = path.with_name(f".{path.name}.{uuid.uuid4().hex}.partial")
    try:
        with staged.open("xb") as destination:
            destination.write(data)
            destination.flush()
            os.fsync(destination.fileno())
        if path.exists():
            raise DataError("Cache entry appeared during acquisition; use one writer per cache")
        os.replace(staged, path)
    finally:
        if staged.exists():
            trash = (Path.home() / ".Trash").resolve()
            trash.mkdir(exist_ok=True)
            staged.rename(trash / f"tubelex-{uuid.uuid4().hex}-{staged.name}")


def _read_compressed(path: Path) -> bytes:
    try:
        compressed = _read_bounded(path)
        size = zstandard.frame_content_size(compressed)
        if not 0 <= size <= MAX_INPUT_BYTES:
            raise DataError("Decoded caption exceeds input budget")
        raw = zstandard.ZstdDecompressor().decompress(
            compressed,
            max_output_size=MAX_INPUT_BYTES,
            allow_extra_data=False,
        )
    except zstandard.ZstdError as exc:
        raise DataError("Invalid compressed TUBELEX input") from exc
    if len(raw) > MAX_INPUT_BYTES:
        raise DataError("Decoded caption exceeds input budget")
    return raw


def read_private_caption(path: Path) -> dict:
    try:
        value = parse_json(_read_compressed(path))
        if (
            value["language"] != "ja"
            or value["caption_kind"] != "manual"
            or value["auto_translated"] is not False
            or not VIDEO_ID.fullmatch(value["video_id"])
            or not isinstance(value["vtt"], str)
            or not isinstance(value["metadata"], dict)
        ):
            raise DataError("Private caption is not a manual, untranslated Japanese track")
        return value
    except (KeyError, TypeError, ValueError, zstandard.ZstdError) as exc:
        raise DataError("Invalid private TUBELEX caption cache") from exc


def _extract_info(video_id: str, executable: str) -> dict:
    """Bound metadata/error pipes while running; never cache installed tool state."""
    command = [
        executable,
        "--ignore-config",
        "--no-cache-dir",
        "--skip-download",
        "--no-playlist",
        "--dump-single-json",
        "--no-warnings",
        "--no-progress",
        "--socket-timeout",
        "30",
        "--retries",
        "0",
        "--extractor-retries",
        "0",
        "--sleep-requests",
        "1",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    ) as process:

        def read_pipe(pipe, budget):
            chunks, size = [], 0
            while chunk := pipe.read(64 * 1024):
                size += len(chunk)
                if size > budget:
                    process.kill()
                    raise DataError("YouTube extractor output exceeds its input budget")
                chunks.append(chunk)
            return b"".join(chunks)

        with ThreadPoolExecutor(max_workers=2) as readers:
            stdout = readers.submit(read_pipe, process.stdout, MAX_INPUT_BYTES)
            stderr = readers.submit(read_pipe, process.stderr, 64 * 1024)
            try:
                process.wait(timeout=120)
            except BaseException:
                process.kill()
                process.wait()
                raise
            out, error = stdout.result(), stderr.result()
        if process.returncode:
            message = error.decode(errors="replace").lower()
            # Only explicit content-state failures are skipped. Bot challenges,
            # rate limits and unknown failures stop the run for later resumption.
            unavailable = (
                "this video is private",
                "private video",
                "has been removed",
                "video has been deleted",
                "account associated with this video has been terminated",
            )
            if any(fragment in message for fragment in unavailable):
                raise CaptionUnavailable("removed-or-private")
            raise DataError(f"YouTube acquisition stopped at {video_id}; check access locally")
        return parse_json(out)


def _cache_status(cache, identity, reason):
    if cache:
        path = safe_relative(cache, f"{CACHE_POLICY}-{identity}.status.json")
        if not path.exists():
            _write_new_bytes(
                path,
                canonical_json(
                    {
                        "video_id": identity,
                        "policy": CACHE_POLICY,
                        "reason": reason,
                        "checked_at": datetime.now(UTC).isoformat(),
                    }
                ),
            )


def snapshot_tubelex(
    output: Path,
    *,
    videos_csv: Path | None = None,
    captions_dir: Path | None = None,
    cache: Path | None = None,
    max_videos: int = 10,
    delay: float = 5,
    yt_dlp: str = "yt-dlp",
    user_agent: str = "ManabiSentenceDB/0.1 (TUBELEX references)",
    offset: int = 0,
) -> Path:
    """Snapshot a bounded video-list selection; only this stage acquires captions.

    Local import reads <id>.info.json and <id>.ja.vtt from a TUBELEX rehydration
    directory. Network mode inspects metadata with yt-dlp, then retrieves just
    one validated manual track. No audio/video, translation or transcription.
    Cache keys bind the pinned list (or supplied list bytes) and video identity.
    """
    if not 1 <= max_videos <= 120_000 or offset < 0 or not math.isfinite(delay) or delay < 5:
        raise DataError("Use 1..120000 videos and at least 5 seconds between videos")
    output = _new_output(output)
    if cache is not None:
        cache = cache.resolve()
        if cache == output or cache.is_relative_to(output) or output.is_relative_to(cache):
            raise DataError("Caption cache and snapshot destinations must be separate")
        cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    list_cache = safe_relative(cache, f"videos-ja-{TUBELEX_REVISION}.csv.zst") if cache else None
    if videos_csv:
        data = _read_bounded(videos_csv)
    elif list_cache and list_cache.exists():
        data = _read_compressed(list_cache)
    else:
        data = _get(TUBELEX_LIST_URL, user_agent=user_agent)
    list_hash = hashlib.sha256(data).hexdigest()
    if videos_csv is None and list_hash != TUBELEX_LIST_SHA256:
        raise DataError("Pinned TUBELEX video list checksum mismatch")
    if videos_csv is None and list_cache and not list_cache.exists():
        _write_new_bytes(list_cache, zstandard.ZstdCompressor(level=9).compress(data))
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    if not {"videoid", "sub", "language"} <= set(reader.fieldnames or []):
        raise DataError("Expected a TUBELEX video CSV (videoid, sub, language)")
    selected = []
    seen = set()
    for row in reader:
        if row["language"] != "ja" or row["sub"] != "True":
            continue
        identity = row["videoid"]
        if not VIDEO_ID.fullmatch(identity):
            raise DataError("Invalid video ID in TUBELEX list")
        if identity not in seen:
            seen.add(identity)
            if len(seen) <= offset:
                continue
            selected.append(row)
        if len(selected) == max_videos:
            break
    if not selected:
        raise DataError("No Japanese manual-caption candidates in video list")
    output.mkdir(parents=True, mode=0o700)
    entries, skipped = [], []
    last_request = None
    for row in selected:
        identity = row["videoid"]
        # A new list/shard must not invalidate captions already acquired for
        # the same video under the same eligibility policy.
        cached = safe_relative(cache, f"{CACHE_POLICY}-{identity}.json.zst") if cache else None
        status_path = (
            safe_relative(cache, f"{CACHE_POLICY}-{identity}.status.json") if cache else None
        )
        if status_path and status_path.exists() and captions_dir is None:
            status = read_json(status_path)
            if (
                not isinstance(status, dict)
                or status.get("video_id") != identity
                or status.get("policy") != CACHE_POLICY
            ):
                raise DataError("Invalid caption acquisition ledger entry")
            if status.get("reason") not in {"removed-or-private", "no-original-manual-ja-track"}:
                raise DataError("Unknown caption acquisition ledger status")
            skipped.append({"video_id": identity, "reason": status["reason"]})
            continue
        if cached and cached.exists():
            caption = read_private_caption(cached)
        else:
            if captions_dir is not None:
                info_path = safe_relative(captions_dir, f"{identity}.info.json")
                vtt_path = safe_relative(captions_dir, f"{identity}.ja.vtt")
                if not info_path.exists() or not vtt_path.exists():
                    skipped.append({"video_id": identity, "reason": "missing-local-caption"})
                    continue
                info = parse_json(_read_bounded(info_path))
            else:
                if last_request is not None:
                    time.sleep(max(0, delay - (time.monotonic() - last_request)))
                last_request = time.monotonic()
                try:
                    info = _extract_info(identity, yt_dlp)
                except CaptionUnavailable:
                    skipped.append({"video_id": identity, "reason": "removed-or-private"})
                    _cache_status(cache, identity, "removed-or-private")
                    continue
                except subprocess.TimeoutExpired as exc:
                    raise DataError("YouTube metadata timed out; acquisition stopped") from exc
            if not isinstance(info, dict) or info.get("id") != identity:
                raise DataError("Caption metadata video ID disagrees with TUBELEX list")
            track = select_manual_japanese(info)
            if track is None:
                skipped.append({"video_id": identity, "reason": "no-original-manual-ja-track"})
                if captions_dir is None:
                    _cache_status(cache, identity, "no-original-manual-ja-track")
                continue
            if captions_dir is not None:
                vtt = _read_bounded(vtt_path).decode("utf-8-sig")
            else:
                time.sleep(1)
                try:
                    vtt = _get(track["url"], user_agent=user_agent).decode("utf-8-sig")
                except HTTPError as exc:
                    raise DataError(
                        f"Caption request failed ({exc.code}); acquisition stopped"
                    ) from exc
            # No descriptions, subtitle URLs, access tokens, cookies or titles
            # enter the snapshot manifest or public citations.
            caption = {
                "video_id": identity,
                "language": "ja",
                "caption_kind": "manual",
                "auto_translated": False,
                "vtt": vtt,
                "acquired_at": datetime.now(UTC).isoformat(),
                "track_provenance": {
                    "language": "ja",
                    "container": "subtitles",
                    "name": track.get("name", ""),
                    "format": "vtt",
                    "metadata_sha256": digest_json(info),
                    "extractor_version": info.get("_version", {}).get("version", "unknown"),
                },
                "metadata": {
                    key: row.get(key, "") for key in ("upload_date", "channel_id", "categories")
                },
            }
            parse_vtt(vtt)  # Validate before caching; no plaintext files written.
            if cached:
                _compress_private(cached, caption)
        if caption["video_id"] != identity:
            raise DataError("Cached caption video ID mismatch")
        path = output / f"{identity}.json.zst"
        _compress_private(path, caption)
        entries.append({"video_id": identity, "path": path.name, "sha256": sha256_file(path)})
    if not entries:
        raise DataError("No usable manual Japanese captions; no snapshot manifest was produced")
    manifest = {
        "schema_version": 1,
        "kind": "tubelex-private-snapshot",
        "language": "ja",
        "upstream": "https://github.com/naist-nlp/tubelex",
        "revision": None if videos_csv else TUBELEX_REVISION,
        "captured_at": datetime.now(UTC).isoformat(),
        "video_list_sha256": list_hash,
        "entries": entries,
        "skipped": skipped,
        "selection_limit": max_videos,
        "selection_offset": offset,
    }
    manifest["snapshot_id"] = "tubelex_" + digest_json(manifest)[:32]
    write_json(output / "manifest.json", manifest)
    return output / "manifest.json"


def verify_tubelex_snapshot(path: Path) -> dict:
    path = path.resolve()
    if path.is_dir():
        path /= "manifest.json"
    try:
        manifest = parse_json(_read_bounded(path))
    except DataError:
        raise
    except ValueError as exc:
        raise DataError("Invalid private TUBELEX snapshot JSON encoding") from exc
    if not isinstance(manifest, dict):
        raise DataError("Private TUBELEX snapshot manifest must be an object")
    identity = manifest.get("snapshot_id")
    body = {key: value for key, value in manifest.items() if key != "snapshot_id"}
    if (
        manifest.get("kind") != "tubelex-private-snapshot"
        or manifest.get("schema_version") != 1
        or manifest.get("language") != "ja"
        or identity != "tubelex_" + digest_json(body)[:32]
    ):
        raise DataError("Invalid private TUBELEX snapshot manifest")
    entries, skipped = manifest.get("entries"), manifest.get("skipped")
    limit, offset = manifest.get("selection_limit"), manifest.get("selection_offset")
    if (
        not isinstance(entries, list)
        or not entries
        or not isinstance(skipped, list)
        or type(limit) is not int
        or not 1 <= limit <= 120_000
        or type(offset) is not int
        or offset < 0
        or len(entries) + len(skipped) > limit
    ):
        raise DataError("Invalid private TUBELEX snapshot inventory")
    if any(
        not isinstance(manifest.get(key), str) or not manifest[key]
        for key in ("upstream", "captured_at", "video_list_sha256")
    ):
        raise DataError("Missing private TUBELEX snapshot provenance")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest["video_list_sha256"]):
        raise DataError("Invalid private TUBELEX video-list checksum")
    if "revision" not in manifest or (
        manifest["revision"] is not None
        and (
            not isinstance(manifest["revision"], str)
            or not re.fullmatch(r"[0-9a-f]{40}", manifest["revision"])
        )
    ):
        raise DataError("Invalid private TUBELEX source revision")
    seen = set()
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"video_id", "path", "sha256"}
            or not isinstance(entry["video_id"], str)
            or not VIDEO_ID.fullmatch(entry["video_id"])
            or not isinstance(entry["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
        ):
            raise DataError("Invalid private TUBELEX caption inventory entry")
        if entry["video_id"] in seen:
            raise DataError("Duplicate TUBELEX video")
        seen.add(entry["video_id"])
        caption_path = safe_relative(path.parent, entry["path"])
        if sha256_file(caption_path) != entry["sha256"]:
            raise DataError("Private caption checksum mismatch")
        if read_private_caption(caption_path)["video_id"] != entry["video_id"]:
            raise DataError("Private caption identity mismatch")
    for entry in skipped:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"video_id", "reason"}
            or not isinstance(entry["video_id"], str)
            or not VIDEO_ID.fullmatch(entry["video_id"])
            or entry["video_id"] in seen
            or not isinstance(entry["reason"], str)
            or entry["reason"]
            not in {"missing-local-caption", "removed-or-private", "no-original-manual-ja-track"}
        ):
            raise DataError("Invalid private TUBELEX skipped-video inventory entry")
        seen.add(entry["video_id"])
    return manifest


def _milliseconds(value: str) -> int:
    fields = value.split(":")
    seconds, fraction = fields[-1].split(".")
    minutes = int(fields[-2])
    if minutes >= 60 or int(seconds) >= 60:
        raise DataError("Invalid WebVTT time")
    hours = int(fields[0]) if len(fields) == 3 else 0
    return ((hours * 60 + minutes) * 60 + int(seconds)) * 1000 + int(fraction)


def _word_separator(left: str, right: str) -> str:
    """Keep wrapped Latin words apart; Japanese wrapping remains contiguous.

    A line/cue break does not prove two Latin fragments form a single word.
    This conservative whitespace policy can separate a word split by its author.
    """

    def word_character(char):
        return char.isdecimal() or "LATIN" in unicodedata.name(char, "")

    return " " if left and right and word_character(left[-1]) and word_character(right[0]) else ""


def _display_text(lines: list[str]) -> str:
    parts, previous = [], ""
    for line in lines:
        parts.extend((_word_separator(previous, line), line))
        previous = line
    return "".join(parts)


def parse_vtt(vtt: str) -> list[Cue]:
    """Preserve cue times; strip formatting/ruby readings, not spoken base text.

    Manual tracks can still use repeated/scrolling cues. Deduplicate only
    overlapping display repetitions; a phrase repeated later remains a repeat.
    """
    vtt = vtt.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    header = vtt.partition("\n")[0]
    if not re.fullmatch(r"WEBVTT(?:[ \t].*)?", header) or "-->" in header:
        raise DataError("Expected WebVTT captions")
    cues: list[Cue] = []
    previous_display: list[str] = []
    ordinal = 0
    for number, block in enumerate(re.split(r"\n[ \t]*\n", vtt)):
        lines = block.splitlines()
        if number == 0:
            if any("-->" in line for line in lines[1:]):
                raise DataError("WebVTT header must be separated from cues by a blank line")
            continue
        if (
            not lines
            or lines[0] == "NOTE"
            or lines[0].startswith(("NOTE ", "NOTE\t"))
            or (ordinal == 0 and lines[0] in {"STYLE", "REGION"})
        ):
            continue
        index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if index is None:
            continue
        timing = TIMING.fullmatch(lines[index])
        if not timing:
            raise DataError("Malformed WebVTT cue timing")
        start, end = map(_milliseconds, timing.groups())
        if end <= start or (cues and start < cues[-1].start_ms):
            raise DataError("WebVTT cues must be ordered, with positive durations")
        ordinal += 1
        # Author-supplied identifiers can contain whole captions or arbitrary
        # strings. Keep those only in the compressed original VTT; ordinals map
        # every alignment origin back to its source cue without copying text.
        cue_id = f"cue-{ordinal}"
        region_match = re.search(r"\bregion:(\S+)", lines[index])
        region = region_match[1] if region_match else ""
        parser = _CaptionMarkup()
        parser.feed(re.sub(rf"<{TIMESTAMP}>", "", "\n".join(lines[index + 1 :])))
        for voice, content in parser.parts:
            display = [unicodedata.normalize("NFC", line).strip() for line in content.splitlines()]
            display = [line for line in display if line]
            text = _display_text(display)
            if not text:
                continue
            scrolling = False
            if (
                cues
                and start < cues[-1].end_ms
                and (voice, region) == (cues[-1].voice, cues[-1].region)
            ):
                previous = cues[-1]
                if text == previous.text:
                    origins = tuple(
                        replace(
                            origin,
                            end_ms=max(origin.end_ms, end),
                            cue_ids=origin.cue_ids + (cue_id,),
                        )
                        for origin in previous.origins
                    )
                    cues[-1] = replace(previous, end_ms=max(end, previous.end_ms), origins=origins)
                    previous_display = display
                    continue
                # Only a complete repeated display line proves scrolling. The
                # repeated line retains BOTH original cue ranges in its origin.
                if len(display) > 1 and previous_display and display[0] == previous_display[-1]:
                    repeated_start = len(previous.text) - len(display[0])
                    origins = tuple(
                        replace(
                            origin,
                            end_ms=max(origin.end_ms, end),
                            cue_ids=origin.cue_ids + (cue_id,),
                        )
                        if origin.end > repeated_start
                        else origin
                        for origin in previous.origins
                    )
                    cues[-1] = replace(previous, end_ms=max(end, previous.end_ms), origins=origins)
                    display = display[1:]
                    text = _display_text(display)
                    scrolling = True
            origins, offset, previous_line = [], 0, ""
            for line in display:
                length = len(_word_separator(previous_line, line)) + len(line)
                origins.append(Origin(offset, offset + length, start, end, (cue_id,)))
                offset += length
                previous_line = line
            cues.append(Cue(start, end, text, voice, region, tuple(origins), scrolling))
            previous_display = display
    if not cues:
        raise DataError("No nonempty WebVTT cues")
    return cues


class _CaptionMarkup(HTMLParser):
    """Retain speaker runs; formatting and ruby readings never become words."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[tuple[str, str]] = []
        self.voice = ""
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.handle_data("\n")
        if tag in {"rt", "rp"}:
            self.skip += 1
        if tag == "v" or tag.startswith("v."):
            match = re.match(r"<v(?:\.[^\s>]+)*\s+([^>]+)>", self.get_starttag_text())
            self.voice = html.unescape(match[1]).strip() if match else ""

    def handle_endtag(self, tag):
        if tag in {"rt", "rp"}:
            self.skip = max(0, self.skip - 1)
        if tag == "v":
            self.voice = ""

    def handle_data(self, data):
        if self.skip:
            return
        if self.parts and self.parts[-1][0] == self.voice:
            self.parts[-1] = (self.voice, self.parts[-1][1] + data)
        else:
            self.parts.append((self.voice, data))


def caption_streams(cues: list[Cue]) -> list[CaptionStream]:
    """Separate videos/voices/regions/ambiguous overlaps and gaps >=5 seconds.

    Short timing gaps do not constrain literal search. Unknown overlapping
    speakers are isolated instead of being concatenated into invented phrases.
    """
    groups: list[list[Cue]] = []
    active: dict[tuple[str, str], int] = {}
    last_key = None
    for cue in cues:
        key = cue.voice, cue.region
        if key != last_key:
            # A returning voice is a new turn, even with only a short gap.
            # Do not splice a phrase across another speaker or caption region.
            active.clear()
        last_key = key
        previous = groups[active[key]][-1] if key in active else None
        ambiguous = previous and cue.start_ms < previous.end_ms and not cue.scrolling
        if previous is None or ambiguous or cue.start_ms - previous.end_ms >= 5000:
            groups.append([])
            active[key] = len(groups) - 1
        groups[active[key]].append(cue)
        if ambiguous:
            active.pop(key)  # The next unlabeled cue must not inherit this speaker.
    streams = []
    for group in groups:
        origins, parts, offset, previous_text = [], [], 0, ""
        for cue in group:
            cue_origins = cue.origins or (Origin(0, len(cue.text), cue.start_ms, cue.end_ms),)
            separator = _word_separator(previous_text, cue.text)
            if separator:
                before, after = origins[-1], cue_origins[0]
                origins.append(
                    Origin(
                        offset,
                        offset + 1,
                        min(before.start_ms, after.start_ms),
                        max(before.end_ms, after.end_ms),
                        tuple(dict.fromkeys((*before.cue_ids, *after.cue_ids))),
                    )
                )
                parts.append(separator)
                offset += 1
            for origin in cue_origins:
                origins.append(
                    replace(origin, start=origin.start + offset, end=origin.end + offset)
                )
            offset += len(cue.text)
            parts.append(cue.text)
            previous_text = cue.text
        streams.append(
            _normalize_stream(
                CaptionStream(
                    "".join(parts),
                    tuple(origins),
                    group[0].voice,
                    group[0].region,
                )
            )
        )
    return streams


def _normalize_stream(stream: CaptionStream) -> CaptionStream:
    """NFC across cue boundaries, retaining the union of contributing times.

    Usually every boundary already preserves NFC and the fast check suffices.
    A base kana in one cue and a combining dakuten in the next must still match
    the composed character typed by the user. Normalizing cues independently
    cannot provide that guarantee.
    """
    if unicodedata.is_normalized("NFC", stream.text):
        return stream
    output, origins, cluster, sources = [], [], [], []
    offset = 0

    def flush():
        nonlocal offset
        if not cluster:
            return
        text = unicodedata.normalize("NFC", "".join(cluster))
        start_ms, end_ms = min(p.start_ms for p in sources), max(p.end_ms for p in sources)
        ids = tuple(dict.fromkeys(identity for p in sources for identity in p.cue_ids))
        output.append(text)
        origin = Origin(offset, offset + len(text), start_ms, end_ms, ids)
        if origins and (origins[-1].start_ms, origins[-1].end_ms, origins[-1].cue_ids) == (
            start_ms,
            end_ms,
            ids,
        ):
            origins[-1] = replace(origins[-1], end=origin.end)
        else:
            origins.append(origin)
        offset += len(text)
        cluster.clear()
        sources.clear()

    for origin in stream.origins:
        for char in stream.text[origin.start : origin.end]:
            if cluster and unicodedata.combining(char) == 0:
                # Hangul L/V/T composition is the important exception to
                # treating each combining-class-zero character as a new run.
                before = unicodedata.normalize("NFC", "".join(cluster))
                if unicodedata.normalize("NFC", before + char) == before + unicodedata.normalize(
                    "NFC", char
                ):
                    flush()
            cluster.append(char)
            if not sources or sources[-1] != origin:
                sources.append(origin)
    flush()
    return CaptionStream("".join(output), tuple(origins), stream.voice, stream.region)


_FINITE_ENDING = re.compile(r"(?:です|ます|でした|ました|ません|でしょう|だった|なんだ|なのだ)$")


def _safe_soft_boundaries(text: str, points: list[int]) -> set[int]:
    """Reject inferred splits inside quotations, brackets or Latin words."""
    wanted, allowed, stack = set(points), set(), []
    for offset, char in enumerate(text, 1):
        if char == '"':
            if stack and stack[-1] == '"':
                stack.pop()
            else:
                stack.append('"')
        elif char in _PAIRS:
            stack.append(_PAIRS[char])
        elif stack and char == stack[-1]:
            stack.pop()
        if offset not in wanted or stack or offset == len(text):
            continue
        if char in set(_PAIRS.values()) | {'"'} and text[offset:].startswith(
            ("と", "って", "など", "を", "は", "が", "に", "の")
        ):
            continue
        if char.isascii() and char.isalnum() and text[offset].isascii() and text[offset].isalnum():
            continue
        allowed.add(offset)
    return allowed


def stream_units(stream: CaptionStream, *, segment=None, pause_ms=800, refine_punctuated=True):
    """Return display-boundary proposals without dropping searchable characters.

    Punctuation/model units are preferred. Short pauses propose soft boundaries
    only inside unpunctuated spans; they never split the searchable stream.
    """
    text = stream.text
    origin_starts = [p.start for p in stream.origins]
    pauses = [
        after.start
        for before, after in zip(stream.origins, stream.origins[1:])
        if after.start_ms - before.end_ms >= pause_ms
    ]
    for left, right in sentence_spans(text, "ja"):
        fragment = text[left:right]
        complete = is_complete_sentence(fragment, "ja")
        # A final full stop does not establish that all earlier sentences were
        # punctuated. Refine selectively, retaining the publisher's hard end.
        internal = origin_starts[bisect_right(origin_starts, left):bisect_left(origin_starts, right)]
        finite = {
            point for point in internal
            if point - left >= 4 and right - point >= 4
            and _FINITE_ENDING.search(text[max(left, point - 32):point].rstrip())
        }
        suspect = bool(finite) or len(fragment) > 120
        if complete and (not refine_punctuated or not suspect):
            yield left, right, "punctuation"
            continue
        if segment:
            parts = list(segment(fragment))
            if any(not isinstance(p, str) or not p for p in parts) or "".join(parts) != fragment:
                raise DataError("Sentence segmenter must preserve every original character")
            points, offset = [], 0
            for part in parts:
                offset += len(part)
                points.append(offset)
            # Preserve the existing unpunctuated adapter contract. The extra
            # conservative guard applies to refinement inside publisher units.
            allowed = _safe_soft_boundaries(fragment, points) if complete else set(points[:-1])
            begin = left
            for point in points[:-1]:
                if point not in allowed or (
                    complete and (point + left - begin < 4 or right - left - point < 4)
                ):
                    continue
                yield begin, left + point, "model"
                begin = left + point
            yield begin, right, "punctuation" if complete else "model"
            continue
        first, last = bisect_right(pauses, left), bisect_left(pauses, right)
        points = pauses[first:last]
        if complete:
            safe = _safe_soft_boundaries(fragment, [p - left for p in points])
            points = [p for p in points if p in finite and p - left in safe]
        begin = left
        for end in [*points, right]:
            yield begin, end, (
                "pause-inferred" if end < right else "punctuation" if complete else "unsegmented"
            )
            begin = end


def aligned_sentences(
    cues: list[Cue],
    *,
    segment=None,
    stats: Counter | None = None,
    boundary_mode="hybrid",
    pause_ms=800,
) -> list[AlignedSentence]:
    """Generate bounded display proposals; this never controls indexed coverage."""
    if boundary_mode not in {"hybrid", "punctuation"} or not 250 <= pause_ms <= 5000:
        raise DataError("Use hybrid/punctuation boundaries and a 250..5000 ms pause threshold")
    stats = stats if stats is not None else Counter()
    result = []
    for stream in caption_streams(cues):
        for left, right, boundary in stream_units(
            stream, segment=segment, pause_ms=pause_ms,
            refine_punctuated=boundary_mode == "hybrid",
        ):
            if boundary_mode == "punctuation" and boundary != "punctuation":
                continue
            origins = [p for p in stream.origins if p.start < right and p.end > left]
            groups, group = [], []
            for origin in origins:
                if group and (
                    origin.end_ms - min(p.start_ms for p in group) > 30000
                    or origin.end - group[0].start > 500
                ):
                    groups.append(group)
                    group = []
                group.append(origin)
            if group:
                groups.append(group)
            for group in groups:
                a, b = max(left, group[0].start), min(right, group[-1].end)
                text = stream.text[a:b]
                kind = "context-window" if len(groups) > 1 else boundary
                accepted, flags, reason = assess_sentence(
                    text, "ja", max_length=max(500, len(text))
                )
                if not accepted and reason not in {"unbalanced-delimiters", "too-short"}:
                    stats[reason] += 1
                    continue
                if "sexual-content" in flags:
                    stats["sexual-content"] += 1
                    continue
                start, end = min(p.start_ms for p in group), max(p.end_ms for p in group)
                stats[f"accepted:{kind}"] += 1
                result.append(AlignedSentence(text, start, end, kind, a, b))
    return result


def reference_record(sentence: AlignedSentence, *, video_id: str, snapshot_id: str) -> dict:
    # This factory is also the hot query path. Validate its small input contract
    # here; full JSON Schema validation remains at export/verification boundaries.
    if (
        not isinstance(video_id, str)
        or not VIDEO_ID.fullmatch(video_id)
        or not isinstance(snapshot_id, str)
        or not snapshot_id
        or type(sentence.start_ms) is not int
        or type(sentence.end_ms) is not int
        or not 0 <= sentence.start_ms < sentence.end_ms < 10**15
        or sentence.boundary
        not in {"", "punctuation", "model", "pause-inferred", "unsegmented", "context-window"}
    ):
        raise DataError("Invalid external citation factory inputs")
    start = sentence.start_ms // 1000
    end = (sentence.end_ms + 999) // 1000
    native = f"{video_id}:{sentence.start_ms}:{sentence.end_ms}"
    # Multiple sentences inside one cue deliberately share a citation. Do not
    # encode character offsets or transcript hashes in publicly released IDs.
    return {
        "schema_version": 1,
        "id": "ref_" + hashlib.sha256(native.encode()).hexdigest()[:32],
        "kind": "reference",
        "source_id": "tubelex-ja",
        "snapshot_id": snapshot_id,
        "language": "ja",
        "native_id": native,
        "title": f"YouTube video {video_id}",
        "url": f"https://www.youtube.com/embed/{video_id}?start={start}&end={end}",
        "attribution": {
            "text": "Video on YouTube; discovered through TUBELEX",
            "url": f"https://www.youtube.com/watch?v={video_id}",
        },
        "tags": ["manual-captions", "timing:cue-envelope", f"boundary:{sentence.boundary}"],
        "locator": {
            "type": "media",
            "start_seconds": sentence.start_ms / 1000,
            "end_seconds": sentence.end_ms / 1000,
        },
    }
