"""Private blinded text review packets and explicit, reproducible boundary scoring.

The packet contains copyrighted captions, compressed and private. Labels are
supplied independently of predictions. Text-only/assistant labels are not human
audio-verified sentence truth; reports always retain the declared reviewer type.
"""

from __future__ import annotations

import hashlib
import heapq
import io
import json
import random
from bisect import bisect_right
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .serialization import DataError, digest_json, parse_json, safe_relative, sha256_file
from .tubelex import (
    MAX_INPUT_BYTES,
    AlignedSentence,
    CaptionStream,
    Origin,
    _compress_private,
    _new_output,
    _read_compressed,
    caption_streams,
    parse_vtt,
    read_private_caption,
    reference_record,
    stream_units,
    verify_tubelex_snapshot,
)


def _review_size(value, remaining):
    size = 0
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    for piece in encoder.iterencode(value):
        size += len(piece.encode("utf-8"))
        if size > remaining:
            raise DataError("Private review packet exceeds 32 MiB; reduce max-videos or per-video")
    return size


def prepare_tubelex_review(snapshots, output, *, per_video=4, window_chars=200,
                           max_videos=20, seed=20261024, exclude_packets=(), exclude_scope="videos"):
    if type(per_video) is not int or not 1 <= per_video <= 20:
        raise DataError("Use 1..20 review windows per video")
    if type(window_chars) is not int or not 40 <= window_chars <= 500:
        raise DataError("Use review cores of 40..500 characters")
    if type(max_videos) is not int or not 1 <= max_videos <= 1000:
        raise DataError("Use 1..1000 sampled review videos")
    if exclude_scope not in ("videos", "windows") or len(exclude_packets) > 64:
        raise DataError("Use videos/windows exclusion and at most 64 prior review packets")
    excluded, prior_windows, prior_hashes = set(), {}, []
    for path in exclude_packets:
        path = Path(path).resolve(strict=True)
        prior = parse_json(_read_compressed(path))
        if (not isinstance(prior, dict) or prior.get("kind") != "private-tubelex-blind-review"
                or prior.get("schema_version") != 1 or not isinstance(prior.get("cases"), list)):
            raise DataError("Exclusions require a previous private blind review packet")
        prior_hashes.append(sha256_file(path))
        for case in prior["cases"]:
            if (not isinstance(case, dict) or not isinstance(case.get("video_id"), str)
                    or type(case.get("stream")) is not int or type(case.get("source_start")) is not int
                    or not isinstance(case.get("text"), str)):
                raise DataError("Invalid previous review case")
            excluded.add(case["video_id"])
            prior_windows.setdefault((case["video_id"], case["stream"]), []).append(
                (case["source_start"], case["source_start"] + len(case["text"]))
            )
    output = _new_output(Path(output))
    eligible_videos = 0
    candidates, seen, sampling = [], set(), random.Random(seed)
    # Reservoir sampling bounds retained descriptors even for many batches.
    for snapshot in snapshots:
        snapshot = Path(snapshot).resolve(strict=True)
        root = snapshot if snapshot.is_dir() else snapshot.parent
        if output.is_relative_to(root) or root.is_relative_to(output):
            raise DataError("Review output must be separate from snapshot inputs")
        manifest = verify_tubelex_snapshot(snapshot)
        for entry in manifest["entries"]:
            if entry["video_id"] in seen:
                raise DataError("Review snapshots must have disjoint video IDs")
            seen.add(entry["video_id"])
            if len(seen) > 120_000:
                raise DataError("Review input exceeds 120000 video candidates")
            if exclude_scope == "videos" and entry["video_id"] in excluded:
                continue
            eligible_videos += 1
            candidate = (root, manifest["snapshot_id"], entry)
            if len(candidates) < max_videos:
                candidates.append(candidate)
            else:
                replace = sampling.randrange(eligible_videos)
                if replace < max_videos:
                    candidates[replace] = candidate
    cases, retained_streams = [], {}
    packet = {
        "kind": "private-tubelex-blind-review", "schema_version": 1,
        "seed": seed, "per_video": per_video, "window_chars": window_chars,
        "max_videos": max_videos, "available_videos": len(seen),
        "eligible_videos": eligible_videos, "excluded_packets_sha256": prior_hashes,
        "exclusion_scope": exclude_scope,
        "evaluation_role": "unlabelled; prior holdouts are exploratory after inspection",
        "cases": cases, "streams": retained_streams,
    }
    remaining = MAX_INPUT_BYTES - _review_size(packet, MAX_INPUT_BYTES)
    rng = random.Random(seed)
    for root, snapshot_id, entry in candidates:
        video = entry["video_id"]
        caption = read_private_caption(safe_relative(root, entry["path"]))
        streams = caption_streams(parse_vtt(caption["vtt"]))
        # Sample lightweight offsets first; hydrate context/origins only for
        # selected windows rather than scanning every origin for every window.
        windows = [
            (number, left, min(len(stream.text), left + window_chars))
            for number, stream in enumerate(streams)
            for left in range(0, len(stream.text), window_chars)
            if min(len(stream.text), left + window_chars) - left >= 20
        ]
        if exclude_scope == "windows":
            windows = [(number, left, right) for number, left, right in windows
                       if not any(max(0, left - 100) < b
                                  and min(len(streams[number].text), right + 100) > a
                                  for a, b in prior_windows.get((video, number), ())) ]
        for number, left, right in rng.sample(windows, min(per_video, len(windows))):
            stream = streams[number]
            stream_key = f"{video}:{number}"
            a, b = max(0, left - 100), min(len(stream.text), right + 100)
            first = max(0, bisect_right(stream.origins, a, key=lambda p: p.start) - 1)
            last = bisect_right(stream.origins, b - 1, key=lambda p: p.start)
            origins = [
                {**asdict(p), "start": max(p.start, a) - a, "end": min(p.end, b) - a}
                for p in stream.origins[first:last] if p.end > a
            ]
            case = {
                "video_id": video, "snapshot_id": snapshot_id,
                "stream": number, "source_start": a, "text": stream.text[a:b],
                "stream_key": stream_key, "core_start": left - a, "core_end": right - a,
                "origins": origins, "voice": stream.voice, "region": stream.region,
            }
            case["id"] = digest_json(case)
            remaining -= _review_size(case, remaining) + 1  # reserve a comma
            if stream_key not in retained_streams:
                # A lower bound catches oversized streams before copying every
                # origin into dictionaries. Exact JSON sizing follows below.
                minimum_origin = len('{"cue_ids":[],"end":0,"end_ms":0,"start":0,"start_ms":0}')
                if len(stream.text.encode("utf-8")) + len(stream.origins) * minimum_origin > remaining:
                    raise DataError("Private review packet exceeds 32 MiB; reduce max-videos or per-video")
                original = asdict(stream)
                remaining -= _review_size(original, remaining) + len(json.dumps(stream_key)) + 2
                retained_streams[stream_key] = original
            cases.append(case)
    if not cases:
        raise DataError("No caption windows available for independent review")
    if remaining < 0:
        raise DataError("Private review packet exceeds 32 MiB; reduce max-videos or per-video")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _compress_private(output, packet)
    return {"packet_sha256": sha256_file(output), "cases": len(cases),
            "videos": len({case["video_id"] for case in cases}), "available_videos": len(seen),
            "eligible_videos": eligible_videos, "exclusion_scope": exclude_scope}


def score_tubelex_review(packet_path, labels_path, *, segment=None, pause_ms=800,
                         refine_punctuated=True):
    packet = parse_json(_read_compressed(Path(packet_path)))
    labels = parse_json(_read_compressed(Path(labels_path)))
    if (
        not isinstance(packet, dict) or not isinstance(labels, dict)
        or packet.get("kind") != "private-tubelex-blind-review" or packet.get("schema_version") != 1
        or not isinstance(packet.get("cases"), list) or not isinstance(packet.get("streams"), dict)
        or labels.get("packet_sha256") != sha256_file(Path(packet_path))
        or labels.get("reviewer_type") not in {"human-text-only", "human-audio-verified", "assistant-text-only"}
        or not isinstance(labels.get("cases"), list) or not labels["cases"]
    ):
        raise DataError("Review labels must bind the packet and declare their reviewer type")
    cases = {case["id"]: case for case in packet["cases"]}
    totals, videos, seen, predictions = Counter(), {}, set(), {}
    for label in labels["cases"]:
        if (not isinstance(label, dict) or not isinstance(label.get("id"), str)
                or label["id"] not in cases or label["id"] in seen):
            raise DataError("Unknown or duplicate labelled review case")
        seen.add(label["id"])
        case = cases[label["id"]]
        if label.get("abstain") is True:
            if not isinstance(label.get("reason"), str) or not label["reason"].strip():
                raise DataError("Abstained review cases require a reason")
            totals["abstained_cases"] += 1
            videos.setdefault(case["video_id"], Counter())["abstained_cases"] += 1
            continue
        left, right = case["core_start"], case["core_end"]
        gold, uncertain = label.get("boundaries"), label.get("uncertain", [])
        for points in (gold, uncertain):
            if (
                not isinstance(points, list) or any(type(p) is not int or not left < p < right for p in points)
                or points != sorted(set(points))
            ):
                raise DataError("Review boundaries must be sorted unique offsets inside the core")
        if set(gold) & set(uncertain):
            raise DataError("A boundary cannot be both certain and uncertain")
        key = case["stream_key"]
        if key not in predictions:
            source = packet["streams"][key]
            stream = CaptionStream(
                source["text"], tuple(Origin(**{**p, "cue_ids": tuple(p["cue_ids"])}) for p in source["origins"]),
                source["voice"], source["region"],
            )
            predictions[key] = [end for _, end, _ in stream_units(
                stream, segment=segment, pause_ms=pause_ms, refine_punctuated=refine_punctuated,
            )]
        predicted = {
            end - case["source_start"] for end in predictions[key]
            if left < end - case["source_start"] < right
        } - set(uncertain)
        gold = set(gold)
        counts = Counter({
            "true_positive": len(predicted & gold), "false_positive": len(predicted - gold),
            "false_negative": len(gold - predicted), "uncertain": len(uncertain), "cases": 1,
        })
        totals.update(counts)
        videos.setdefault(case["video_id"], Counter()).update(counts)

    def metrics(counts):
        tp, fp, fn = (counts[k] for k in ("true_positive", "false_positive", "false_negative"))
        return {
            **counts, "cases": counts["cases"], "abstained_cases": counts["abstained_cases"],
            "true_positive": tp, "false_positive": fp, "false_negative": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
        }

    return {
        "reviewer_type": labels["reviewer_type"], "packet_sha256": sha256_file(Path(packet_path)),
        "labelled_cases": len(seen), "unlabelled_cases": len(cases) - len(seen),
        "refine_punctuated": refine_punctuated, "model_supplied": segment is not None,
        "evaluation_role": packet.get("evaluation_role", "Prior exposure unspecified"),
        "exclusion_scope": packet.get("exclusion_scope"),
        "excluded_packets": len(packet.get("excluded_packets_sha256", [])),
        "metrics": metrics(totals), "per_video": {k: metrics(v) for k, v in videos.items()},
        "limitations": "Boundary offsets in text windows; not playback/audio accuracy or a safety rating.",
    }


def prepare_tubelex_playback_review(exports, output, *, max_cases=40, seed=20261025):
    """Sample text-free playback clips separately from blind sentence labels.

    Run artifact verification before preparing a packet. Captions and sentence
    predictions are absent; ratings require an explicitly declared audio review.
    """
    import zstandard

    from .validation import validate_record

    if type(max_cases) is not int or not 1 <= max_cases <= 500 or not 1 <= len(exports) <= 4096:
        raise DataError("Use 1..4096 reference exports and 1..500 playback cases")
    output = _new_output(Path(output))
    heap, retained, builds = [], set(), set()
    for export in exports:
        root = Path(export).resolve(strict=True)
        if root.is_file():
            root = root.parent
        if output.is_relative_to(root) or root.is_relative_to(output):
            raise DataError("Playback review output must be separate from reference inputs")
        manifest = parse_json((root / "manifest.json").read_bytes())
        if (not isinstance(manifest, dict) or manifest.get("kind") != "external-citation-sidecar"
                or manifest.get("contains_transcripts") is not False
                or manifest["build_id"] in builds):
            raise DataError("Use distinct text-free reference builds for playback review")
        builds.add(manifest["build_id"])
        path = safe_relative(root, manifest["asset"]["path"])
        if sha256_file(path) != manifest["asset"]["sha256"]:
            raise DataError("Playback reference export checksum mismatch")
        count = 0
        with path.open("rb") as raw, zstandard.ZstdDecompressor().stream_reader(raw) as stream:
            with io.TextIOWrapper(stream, encoding="utf-8") as lines:
                while line := lines.readline(65537):
                    if len(line) > 65536:
                        raise DataError("Oversized playback reference")
                    record = parse_json(line)
                    validate_record(record)
                    if record["kind"] != "reference" or record["snapshot_id"] != manifest["snapshot_id"]:
                        raise DataError("Playback packets require text-free references")
                    try:
                        video, start, end = record["native_id"].split(":")
                        boundaries = [tag[9:] for tag in record["tags"] if tag.startswith("boundary:")]
                        if len(boundaries) != 1:
                            raise DataError("Invalid playback boundary tag")
                        expected = reference_record(
                            AlignedSentence("", int(start), int(end), boundaries[0]),
                            video_id=video, snapshot_id=record["snapshot_id"],
                        )
                    except (KeyError, ValueError, TypeError) as exc:
                        raise DataError("Invalid playback citation identity") from exc
                    tags = set(record["tags"])
                    if (set(record) != set(expected)
                            or any(record[k] != expected[k] for k in expected if k != "tags")
                            or not set(expected["tags"]) <= tags
                            or tags - set(expected["tags"]) - {"timing:wide-cue-envelope"}):
                        raise DataError("Unexpected metadata in playback reference")
                    count += 1
                    priority = int.from_bytes(hashlib.sha256(f"{seed}:{record['id']}".encode()).digest(), "big")
                    if record["id"] in retained or (len(heap) == max_cases and priority >= -heap[0][0]):
                        continue
                    item = (-priority, record["id"], record)
                    if len(heap) == max_cases:
                        retired = heapq.heapreplace(heap, item)
                        retained.remove(retired[1])
                    else:
                        heapq.heappush(heap, item)
                    retained.add(record["id"])
        if count != manifest["references"]:
            raise DataError("Playback reference inventory mismatch")
    if not heap:
        raise DataError("No playback references available")
    packet = {"kind": "private-tubelex-playback-review", "schema_version": 1,
              "seed": seed, "build_ids": sorted(builds), "contains_transcripts": False,
              "cases": [item[2] for item in sorted(heap, reverse=True)]}
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _compress_private(output, packet)
    return {"packet_sha256": sha256_file(output), "cases": len(heap), "contains_transcripts": False}


def score_tubelex_playback_review(packet_path, labels_path):
    packet = parse_json(_read_compressed(Path(packet_path)))
    labels = parse_json(_read_compressed(Path(labels_path)))
    if (not isinstance(packet, dict) or not isinstance(labels, dict)
            or packet.get("kind") != "private-tubelex-playback-review" or packet.get("schema_version") != 1
            or not isinstance(packet.get("cases"), list) or not packet["cases"]
            or any(not isinstance(case, dict) or not isinstance(case.get("id"), str) for case in packet["cases"])
            or labels.get("packet_sha256") != sha256_file(Path(packet_path))
            or labels.get("reviewer_type") != "human-audio-verified"
            or not isinstance(labels.get("cases"), list) or not labels["cases"]):
        raise DataError("Playback labels must bind the packet and declare human-audio-verified review")
    cases = {case["id"] for case in packet["cases"]}
    seen, counts = set(), Counter()
    for label in labels["cases"]:
        if (not isinstance(label, dict) or not isinstance(label.get("id"), str)
                or label["id"] not in cases or label["id"] in seen):
            raise DataError("Unknown or duplicate playback review case")
        seen.add(label["id"])
        if label.get("abstain") is True:
            if not isinstance(label.get("reason"), str) or not label["reason"].strip():
                raise DataError("Playback abstention requires a reason")
            counts["abstained"] += 1
            continue
        if label.get("listened") is not True:
            raise DataError("Playback ratings require an explicit listening confirmation")
        for field in ("start", "end"):
            if label.get(field) not in ("clean", "early", "late", "unclear"):
                raise DataError("Playback edges must be clean, early, late or unclear")
            counts[field + ":" + label[field]] += 1
        for field in ("complete_sentence", "useful_context"):
            value = label.get(field)
            if value is not None and type(value) is not bool:
                raise DataError("Playback quality ratings must be true, false or null")
            counts[field + ":" + ("unknown" if value is None else str(value).lower())] += 1
        counts["reviewed"] += 1
    return {"reviewer_type": labels["reviewer_type"], "packet_sha256": sha256_file(Path(packet_path)),
            "counts": dict(counts), "unlabelled_cases": len(cases) - len(seen),
            "limitations": "Self-declared listening judgments; separate from text boundary F1 and timing alignment accuracy."}
