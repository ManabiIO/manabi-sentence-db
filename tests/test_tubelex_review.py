from __future__ import annotations

import pytest
from test_tubelex_batch import snapshot

from manabi_sentence_db.serialization import DataError, parse_json
from manabi_sentence_db.tubelex import _compress_private, _read_compressed
from manabi_sentence_db.tubelex_review import prepare_tubelex_review, score_tubelex_review


def test_blind_review_uses_independent_labels_and_reports_reviewer_type(tmp_path):
    first, second = "今日は図書館へ行きます。", "明日は公園へ行きます。"
    source = snapshot(tmp_path, "abcdefghijk", first + second)
    packet, labels = tmp_path / "packet.json.zst", tmp_path / "labels.json.zst"
    prepared = prepare_tubelex_review([source], packet)
    decoded = parse_json(_read_compressed(packet))
    assert "prediction" not in decoded["cases"][0]
    assert (first + second).encode() not in packet.read_bytes()
    case = decoded["cases"][0]
    _compress_private(labels, {
        "packet_sha256": prepared["packet_sha256"], "reviewer_type": "assistant-text-only",
        "cases": [{"id": case["id"], "boundaries": [len(first)], "uncertain": []}],
    })
    report = score_tubelex_review(packet, labels)
    assert report["metrics"]["precision"] == report["metrics"]["recall"] == 1
    assert report["reviewer_type"] == "assistant-text-only"
    assert "text" not in report
    assert score_tubelex_review(packet, labels, refine_punctuated=False)["metrics"]["f1"] == 1


@pytest.mark.parametrize("damage", ["checksum", "type", "duplicate", "offset"])
def test_review_rejects_unbound_mislabelled_or_invalid_offsets(tmp_path, damage):
    source = snapshot(tmp_path, "abcdefghijk", "今日は図書館へ行きます。明日は公園へ行きます。")
    packet, labels = tmp_path / "packet.json.zst", tmp_path / "labels.json.zst"
    prepared = prepare_tubelex_review([source], packet)
    case = parse_json(_read_compressed(packet))["cases"][0]
    document = {
        "packet_sha256": prepared["packet_sha256"], "reviewer_type": "human-text-only",
        "cases": [{"id": case["id"], "boundaries": [], "uncertain": []}],
    }
    if damage == "checksum":
        document["packet_sha256"] = "wrong"
    elif damage == "type":
        document["reviewer_type"] = "unknown"
    elif damage == "duplicate":
        document["cases"] *= 2
    else:
        document["cases"][0]["boundaries"] = [0]
    _compress_private(labels, document)
    with pytest.raises(DataError):
        score_tubelex_review(packet, labels)


def test_review_scores_original_stream_context_once_and_allows_explicit_abstention(tmp_path):
    text = "今日は図書館で" + "日本語の本や" * 40 + "資料を読みます"
    source = snapshot(tmp_path, "abcdefghijk", text)
    packet, labels = tmp_path / "packet.json.zst", tmp_path / "labels.json.zst"
    prepared = prepare_tubelex_review([source], packet, per_video=2, window_chars=40)
    cases = parse_json(_read_compressed(packet))["cases"]
    _compress_private(labels, {
        "packet_sha256": prepared["packet_sha256"], "reviewer_type": "human-text-only",
        "cases": [{"id": case["id"], "boundaries": []} for case in cases],
    })
    calls = []

    def model(source):
        calls.append(source)
        return [source]

    score_tubelex_review(packet, labels, segment=model)
    assert calls == [text]
    abstained = tmp_path / "abstained.json.zst"
    _compress_private(abstained, {
        "packet_sha256": prepared["packet_sha256"], "reviewer_type": "human-text-only",
        "cases": [{"id": c["id"], "abstain": True, "reason": "Audio needed"} for c in cases],
    })
    report = score_tubelex_review(packet, abstained)
    assert report["metrics"]["cases"] == 0
    assert report["metrics"]["abstained_cases"] == 2
    assert report["metrics"]["f1"] is None


def test_review_limits_video_sampling_and_is_repeatable(tmp_path):
    sources = [snapshot(tmp_path, video, "今日は図書館へ行きます。明日は公園へ行きます。")
               for video in ["abcdefghijk", "lmnopqrstuv", "0123456789_"]]
    a, b = tmp_path / "a.json.zst", tmp_path / "b.json.zst"
    result = prepare_tubelex_review(sources, a, max_videos=2, seed=17)
    prepare_tubelex_review(sources, b, max_videos=2, seed=17)
    assert result["videos"] == 2 and result["available_videos"] == 3
    assert a.read_bytes() == b.read_bytes()
    packet = parse_json(_read_compressed(a))
    assert len({c["video_id"] for c in packet["cases"]}) == 2


def test_review_checks_total_size_before_creating_an_output(tmp_path, monkeypatch):
    from manabi_sentence_db import tubelex_review

    source = snapshot(tmp_path, "abcdefghijk", "今日は図書館で本を読みます" * 100)
    packet = tmp_path / "packet.json.zst"
    monkeypatch.setattr(tubelex_review, "MAX_INPUT_BYTES", 512)
    with pytest.raises(DataError, match="packet exceeds"):
        prepare_tubelex_review([source], packet)
    assert not packet.exists()


def test_review_only_hydrates_selected_windows(tmp_path, monkeypatch):
    from manabi_sentence_db import tubelex_review

    source = snapshot(tmp_path, "abcdefghijk", "今日は図書館で本を読みます" * 1000)
    original, calls = tubelex_review.asdict, []

    def count(value):
        calls.append(type(value).__name__)
        return original(value)

    monkeypatch.setattr(tubelex_review, "asdict", count)
    prepare_tubelex_review([source], tmp_path / "packet.json.zst", per_video=1, window_chars=40)
    assert calls == ["Origin", "CaptionStream"]


def test_oversized_source_stream_is_rejected_before_copying_its_origins(tmp_path, monkeypatch):
    from manabi_sentence_db import tubelex_review

    source = snapshot(tmp_path, "abcdefghijk", "今日は図書館で本を読みます" * 1000)
    original = tubelex_review.asdict

    def guard(value):
        assert type(value).__name__ != "CaptionStream", "copied oversized full stream"
        return original(value)

    monkeypatch.setattr(tubelex_review, "asdict", guard)
    monkeypatch.setattr(tubelex_review, "MAX_INPUT_BYTES", 4096)
    with pytest.raises(DataError, match="packet exceeds"):
        prepare_tubelex_review([source], tmp_path / "packet.json.zst", per_video=1, window_chars=40)


def test_review_can_exclude_previously_reviewed_videos_and_windows(tmp_path):
    text = "今日は図書館で本を読みます。" * 200
    sources = [snapshot(tmp_path, video, text) for video in ("abcdefghijk", "lmnopqrstuv")]
    previous, fresh = tmp_path / "previous.zst", tmp_path / "fresh.zst"
    prepare_tubelex_review(sources[:1], previous, per_video=1, window_chars=100)
    prepare_tubelex_review(sources, fresh, exclude_packets=[previous])
    assert {c["video_id"] for c in parse_json(_read_compressed(fresh))["cases"]} == {"lmnopqrstuv"}
    windows = tmp_path / "windows.zst"
    prepare_tubelex_review(sources[:1], windows, per_video=4, window_chars=100,
                           exclude_packets=[previous], exclude_scope="windows")
    old = parse_json(_read_compressed(previous))["cases"][0]
    for new in parse_json(_read_compressed(windows))["cases"]:
        assert new["source_start"] >= old["source_start"] + len(old["text"]) or old["source_start"] >= new["source_start"] + len(new["text"])
    with pytest.raises(DataError, match="No caption windows"):
        prepare_tubelex_review(sources[:1], tmp_path / "empty.zst", exclude_packets=[previous])


def test_playback_review_is_text_free_and_requires_separate_listening_labels(tmp_path):
    from test_tubelex import build_fixture

    from manabi_sentence_db.tubelex_review import (
        prepare_tubelex_playback_review,
        score_tubelex_playback_review,
    )

    _, _, exports, _ = build_fixture(tmp_path)
    packet, labels = tmp_path / "playback.zst", tmp_path / "listening.zst"
    result = prepare_tubelex_playback_review([exports], packet)
    document = parse_json(_read_compressed(packet))
    assert document["contains_transcripts"] is False
    case = document["cases"][0]
    ratings = {"packet_sha256": result["packet_sha256"], "reviewer_type": "human-audio-verified",
               "cases": [{"id": case["id"], "listened": True, "start": "clean", "end": "early",
                          "complete_sentence": False, "useful_context": None}]}
    _compress_private(labels, ratings)
    report = score_tubelex_playback_review(packet, labels)
    assert report["counts"]["start:clean"] == 1 and report["counts"]["end:early"] == 1
    assert "f1" not in report and "text" not in case
    ratings["reviewer_type"] = "assistant-text-only"
    denied = tmp_path / "not-audio.zst"
    _compress_private(denied, ratings)
    with pytest.raises(DataError, match="human-audio"):
        score_tubelex_playback_review(packet, denied)


def test_playback_cli_roundtrip_and_listening_confirmation(tmp_path, capsys):
    import json

    from test_tubelex import build_fixture

    from manabi_sentence_db.cli import main
    from manabi_sentence_db.tubelex_review import score_tubelex_playback_review

    _, _, exports, _ = build_fixture(tmp_path)
    packet, labels = tmp_path / "playback.zst", tmp_path / "labels.zst"
    assert main(["prepare-tubelex-playback-review", "--references", str(exports),
                 "--output", str(packet)]) == 0
    receipt = json.loads(capsys.readouterr().out)
    case = parse_json(_read_compressed(packet))["cases"][0]
    # Authored stand-in ratings exercise the format, not actual listening.
    document = {"packet_sha256": receipt["packet_sha256"], "reviewer_type": "human-audio-verified",
                "cases": [{"id": case["id"], "listened": True, "start": "clean", "end": "clean"}]}
    _compress_private(labels, document)
    assert main(["score-tubelex-playback-review", "--packet", str(packet), "--labels", str(labels)]) == 0
    assert json.loads(capsys.readouterr().out)["counts"]["reviewed"] == 1
    document["cases"][0]["listened"] = False
    invalid = tmp_path / "not-listened.zst"
    _compress_private(invalid, document)
    with pytest.raises(DataError, match="listening"):
        score_tubelex_playback_review(packet, invalid)


def test_playback_rejects_nonstring_case_identifiers_cleanly(tmp_path):
    from test_tubelex import build_fixture

    from manabi_sentence_db.tubelex_review import (
        prepare_tubelex_playback_review,
        score_tubelex_playback_review,
    )
    _, _, exports, _ = build_fixture(tmp_path)
    packet, labels = tmp_path / "playback.zst", tmp_path / "bad-labels.zst"
    prepared = prepare_tubelex_playback_review([exports], packet)
    _compress_private(labels, {"packet_sha256": prepared["packet_sha256"],
                              "reviewer_type": "human-audio-verified", "cases": [{"id": []}]})
    with pytest.raises(DataError, match="case"):
        score_tubelex_playback_review(packet, labels)


@pytest.mark.parametrize("damage", ["duplicate", "identity", "source-offset", "text", "core", "origin", "stream"])
def test_scorer_rejects_internally_inconsistent_review_packets_before_inference(tmp_path, damage):
    from manabi_sentence_db.serialization import digest_json, sha256_file

    source = snapshot(tmp_path, "abcdefghijk", "今日は図書館へ行きます。明日は公園へ行きます。")
    original, packet, labels = (tmp_path / name for name in ("original.zst", "changed.zst", "labels.zst"))
    prepare_tubelex_review([source], original)
    document = parse_json(_read_compressed(original))
    case = document["cases"][0]
    if damage == "duplicate":
        document["cases"].append(dict(case))
    elif damage == "identity":
        case["id"] = "wrong"
    else:
        if damage == "source-offset":
            case["source_start"] += 1
        elif damage == "text":
            case["text"] = "別" + case["text"][1:]
        elif damage == "core":
            case["core_end"] = len(case["text"]) + 1
        elif damage == "origin":
            case["origins"][0]["start_ms"] += 1
        else:
            del document["streams"][case["stream_key"]]
        # Even a re-signed case must agree with its full source stream.
        case["id"] = digest_json({k: v for k, v in case.items() if k != "id"})
    _compress_private(packet, document)
    _compress_private(labels, {"packet_sha256": sha256_file(packet), "reviewer_type": "assistant-text-only",
                              "cases": [{"id": case["id"], "boundaries": []}]})
    def forbidden(_):
        pytest.fail("inference on inconsistent review packet")
    with pytest.raises(DataError, match="review|Review"):
        score_tubelex_review(packet, labels, segment=forbidden)


def test_window_exclusions_follow_source_text_when_caption_stream_indices_change(tmp_path):
    from manabi_sentence_db.serialization import digest_json, read_json, sha256_file, write_json

    original_root, updated_root = tmp_path / "old", tmp_path / "updated"
    original_root.mkdir()
    updated_root.mkdir()
    text = "今日は図書館で日本語の本を読みます。" * 80
    old = snapshot(original_root, "abcdefghijk", text)
    previous = tmp_path / "previous.zst"
    prepare_tubelex_review([old], previous, per_video=1, window_chars=100)
    updated = snapshot(updated_root, "abcdefghijk", text)
    manifest = read_json(updated)
    path = updated.parent / manifest["entries"][0]["path"]
    caption = parse_json(_read_compressed(path))
    caption["vtt"] = "WEBVTT\n\n00:00.000 --> 00:02.000\n初めての公園を散歩しました。\n\n00:10.000 --> 00:13.000\n" + text + "\n"
    path.rename(path.with_suffix(".previous"))
    _compress_private(path, caption)
    manifest["entries"][0]["sha256"] = sha256_file(path)
    manifest["snapshot_id"] = "tubelex_" + digest_json({k:v for k,v in manifest.items() if k != "snapshot_id"})[:32]
    write_json(updated, manifest)
    fresh = tmp_path / "fresh.zst"
    prepare_tubelex_review([updated], fresh, per_video=20, window_chars=100,
                           exclude_packets=[previous], exclude_scope="windows")
    old_case = parse_json(_read_compressed(previous))["cases"][0]
    cases = parse_json(_read_compressed(fresh))["cases"]
    assert cases and all(c["stream"] == 1 for c in cases)
    for case in cases:
        assert case["source_start"] >= old_case["source_start"] + len(old_case["text"]) or old_case["source_start"] >= case["source_start"] + len(case["text"])


@pytest.mark.parametrize("damage", ["duplicate", "url", "transcript-role"])
def test_playback_scorer_checks_the_actual_packet_citations(tmp_path, damage):
    from test_tubelex import build_fixture

    from manabi_sentence_db.serialization import sha256_file
    from manabi_sentence_db.tubelex_review import (
        prepare_tubelex_playback_review,
        score_tubelex_playback_review,
    )

    _, _, exports, _ = build_fixture(tmp_path)
    original, packet, labels = (tmp_path / name for name in ("original.zst", "changed.zst", "ratings.zst"))
    prepare_tubelex_playback_review([exports], original)
    document = parse_json(_read_compressed(original))
    case = document["cases"][0]
    if damage == "duplicate":
        document["cases"].append(dict(case))
    elif damage == "url":
        case["url"] += "&start=99999"
    else:
        document["contains_transcripts"] = True
    _compress_private(packet, document)
    _compress_private(labels, {"packet_sha256": sha256_file(packet), "reviewer_type": "human-audio-verified",
        "cases": [{"id": case["id"], "listened": True, "start": "clean", "end": "clean"}]})
    with pytest.raises(DataError):
        score_tubelex_playback_review(packet, labels)
