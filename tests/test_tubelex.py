from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from contextlib import closing

import pytest
import zstandard

from manabi_sentence_db.cli import main
from manabi_sentence_db.serialization import DataError, canonical_json, read_json
from manabi_sentence_db.tubelex import (
    AlignedSentence,
    Cue,
    aligned_sentences,
    caption_streams,
    parse_vtt,
    reference_record,
    select_manual_japanese,
    snapshot_tubelex,
    verify_tubelex_snapshot,
)
from manabi_sentence_db.tubelex_index import (
    build_tubelex_index,
    search_tubelex_index,
    verify_tubelex_index,
)
from manabi_sentence_db.validation import validate_record

VIDEO = "abcdefghijk"
OTHER = "lmnopqrstuv"
VTT = """WEBVTT

00:00:01.250 --> 00:00:02.500
今日は図書館で

00:00:02.500 --> 00:00:04.750
本を読みました。明日も行きます。

00:00:06.000 --> 00:00:07.000
これは私の

00:00:07.100 --> 00:00:08.000
新しいかばんです

00:00:09.000 --> 00:00:10.000
ありがとうございます
"""


def info(video=VIDEO, **track):
    return {
        "id": video,
        "subtitles": {
            "ja": [
                {
                    "ext": "vtt",
                    "url": "https://www.youtube.com/api/timedtext?lang=ja&v=" + video,
                    **track,
                }
            ]
        },
    }


def inputs(tmp_path):
    local = tmp_path / "rehydrated"
    local.mkdir()
    listing = tmp_path / "videos-ja.csv"
    with listing.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "videoid",
                "sub",
                "auto",
                "language",
                "upload_date",
                "channel_id",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "videoid": VIDEO,
                "sub": "True",
                "auto": "True",
                "language": "ja",
                "upload_date": "20230303",
                "channel_id": "channel",
            }
        )
        writer.writerow({"videoid": OTHER, "sub": "True", "language": "ja"})
    (local / f"{VIDEO}.info.json").write_bytes(canonical_json(info()))
    (local / f"{VIDEO}.ja.vtt").write_text(VTT)
    return listing, local


def build_fixture(tmp_path):
    listing, local = inputs(tmp_path)
    snapshot = snapshot_tubelex(
        tmp_path / "snapshot",
        videos_csv=listing,
        captions_dir=local,
    )
    base = tmp_path / "base.cc.zip"
    base.write_bytes(b"synthetic prebuilt release; must stay unchanged")
    private, references = tmp_path / "private", tmp_path / "references"
    manifest = build_tubelex_index(snapshot, base, private, references)
    return base, private, references, manifest


@pytest.mark.parametrize(
    "track",
    [
        {"url": "https://www.youtube.com/api/timedtext?lang=ja&tlang=ja"},
        {"url": "https://www.youtube.com/api/timedtext?lang=en&tlang=ja"},
        {"url": "https://www.youtube.com/api/timedtext?lang=ja&kind=asr"},
        {"url": "https://www.youtube.com/api/timedtext?lang=ja&v=lmnopqrstuv"},
        {"name": "Japanese (auto-translated)"},
        {"is_translated": True},
        {"is_auto_generated": True},
        {"url": "https://attacker.example/api/timedtext?lang=ja"},
        {"url": "http://www.youtube.com/api/timedtext?lang=ja"},
        {"url": 123},
        {"url": None},
        {"url": "https://[broken"},
        {"url": "https://www.youtube.com:abc/api/timedtext?lang=ja"},
        {"url": "https://www.youtube.com:444/api/timedtext?lang=ja"},
        {"ext": "json3"},
    ],
)
def test_reject_translated_automatic_and_untrusted_tracks(track):
    assert select_manual_japanese(info(**track)) is None


def test_never_use_automatic_caption_map():
    assert select_manual_japanese({"automatic_captions": info()["subtitles"]}) is None
    assert select_manual_japanese(info()) is not None


def test_cues_are_not_sentences_and_times_are_envelopes():
    sentences = aligned_sentences(parse_vtt(VTT))
    assert [s.text for s in sentences] == [
        "今日は図書館で本を読みました。",
        "明日も行きます。",
        "これは私の新しいかばんです",
        "ありがとうございます",
    ]
    assert (sentences[0].start_ms, sentences[0].end_ms) == (1250, 4750)
    # No fabricated interpolation between two sentences inside one cue.
    assert (sentences[1].start_ms, sentences[1].end_ms) == (2500, 4750)
    assert sentences[2].boundary == "pause-inferred"
    assert sentences[3].boundary == "unsegmented"
    assert len(aligned_sentences(parse_vtt(VTT), boundary_mode="punctuation")) == 2


def test_pause_threshold_and_wraps():
    cues = [Cue(0, 1000, "今日は雨です"), Cue(1700, 2300, "傘を持ちます")]
    assert len(aligned_sentences(cues, pause_ms=800)) == 1
    assert len(aligned_sentences(cues, pause_ms=600)) == 2
    # A very long single cue remains available with its real wide envelope.
    assert aligned_sentences([Cue(0, 31000, "今日は晴れです。")])[0].end_ms == 31000


def test_local_model_preserves_text_without_rewriting():
    cues = [Cue(0, 4000, "今日は雨です傘を持ちます")]
    result = aligned_sentences(cues, segment=lambda text: ["今日は雨です", "傘を持ちます"])
    assert len(result) == 2
    assert all(s.boundary == "model" and s.start_ms == 0 and s.end_ms == 4000 for s in result)
    with pytest.raises(DataError, match="preserve"):
        aligned_sentences(cues, segment=lambda text: ["今日は雨です。", "傘を持ちます。"])
    # Give the model enough context to keep a sentence together across a
    # display gap that the default timing-only heuristic would split.
    continuing = [Cue(0, 1000, "明日は"), Cue(1900, 3000, "晴れるでしょう")]
    joined = aligned_sentences(continuing, segment=lambda text: [text])
    assert [s.text for s in joined] == ["明日は晴れるでしょう"]


def test_quoted_sentences_survive_caption_wraps():
    result = aligned_sentences(
        [
            Cue(0, 1000, "彼は「明日"),
            Cue(1000, 2000, "行きます。」と言いました。"),
        ]
    )
    assert [s.text for s in result] == ["彼は「明日行きます。」と言いました。"]


def test_sparse_final_punctuation_does_not_disable_pause_or_model_refinement(tmp_path):
    from manabi_sentence_db.tubelex import stream_units

    parts = ["今日は図書館に行きます", "明日は公園で遊びます", "週末は家で休みます。"]
    cues = [Cue(i * 3000, i * 3000 + 2000, text) for i, text in enumerate(parts)]
    stream = caption_streams(cues)[0]
    units = list(stream_units(stream))
    assert [stream.text[a:b] for a, b, _ in units] == parts
    assert [kind for _, _, kind in units] == ["pause-inferred", "pause-inferred", "punctuation"]
    calls = []

    def model(text):
        calls.append(text)
        return parts

    modeled = list(stream_units(stream, segment=model))
    assert calls == ["".join(parts)]
    assert [kind for _, _, kind in modeled] == ["model", "model", "punctuation"]
    assert len(list(stream_units(stream, refine_punctuated=False))) == 1
    # Inference changes playback units, never literal coverage or hard boundaries.
    vtt = "WEBVTT\n\n" + "\n\n".join(
        f"00:{i*3:02}.000 --> 00:{i*3+2:02}.000\n{text}" for i, text in enumerate(parts)
    )
    db, _ = _build_vtt(tmp_path, vtt)
    result = search_tubelex_index(db, "図書館に行きます明日")
    assert result and result[0]["locator"] == {
        "type": "media", "start_seconds": 0.0, "end_seconds": 8.0,
    }
    verify_tubelex_index(db.parent, tmp_path / "public", deep=True)


def test_mixed_refinement_preserves_continuations_quotes_and_publisher_end():
    from manabi_sentence_db.tubelex import stream_units

    continuing = caption_streams([Cue(0, 1000, "明日は"), Cue(2000, 3000, "晴れるでしょう。")])[0]
    assert len(list(stream_units(continuing))) == 1
    quoted = "彼は「今日は図書館に行きます明日は公園で遊びます」と話しました。"
    cut = quoted.index("明日")
    stream = caption_streams([Cue(0, 1000, quoted[:cut]), Cue(2000, 3000, quoted[cut:])])[0]
    assert len(list(stream_units(stream))) == 1
    units = list(stream_units(stream, segment=lambda text: [text[:cut], text[cut:]]))
    assert units == [(0, len(quoted), "punctuation")]


def test_markup_ruby_and_overlapping_repeats():
    vtt = """WEBVTT

00:00.000 --> 00:02.000
<ruby>今日<rt>きょう</rt></ruby>は晴れです。

00:01.000 --> 00:03.000
今日は晴れです。

00:05.000 --> 00:06.000
今日は晴れです。
"""
    cues = parse_vtt(vtt)
    assert cues == [Cue(0, 3000, "今日は晴れです。"), Cue(5000, 6000, "今日は晴れです。")]


def test_scrolling_repeated_line_does_not_duplicate_text():
    cues = parse_vtt("""WEBVTT

00:00.000 --> 00:02.000
今日は
図書館で

00:01.500 --> 00:03.000
図書館で
本を読みます。
""")
    assert [s.text for s in aligned_sentences(cues)] == ["今日は図書館で本を読みます。"]


@pytest.mark.parametrize(
    "vtt",
    [
        "not vtt",
        "WEBVTT\n\n00:61.000 --> 00:62.000\nああああ。",
        "WEBVTT\n\n00:02.000 --> 00:01.000\nああああ。",
        "WEBVTT\n\n00:01,000 --> 00:02,000\nああああ。",
    ],
)
def test_bad_caption_timing_is_rejected(vtt):
    with pytest.raises(DataError):
        parse_vtt(vtt)


def test_reference_schema_and_player_seconds():
    sentence = AlignedSentence("今日は晴れです。", 1250, 4750, "punctuation")
    record = reference_record(sentence, video_id=VIDEO, snapshot_id="snapshot")
    validate_record(record)
    assert record["url"].endswith("?start=1&end=5")
    assert record["locator"]["end_seconds"] == 4.75
    assert "text" not in record and "sentences" not in record and "license" not in record
    assert sentence.text not in json.dumps(record, ensure_ascii=False)


def test_snapshot_cache_and_no_network_offline(tmp_path, monkeypatch):
    listing, local = inputs(tmp_path)
    monkeypatch.setattr(
        "manabi_sentence_db.tubelex.urlopen", lambda *a, **k: pytest.fail("network")
    )
    cache = tmp_path / "cache"
    first = snapshot_tubelex(
        tmp_path / "first", videos_csv=listing, captions_dir=local, cache=cache
    )
    manifest = verify_tubelex_snapshot(first)
    assert len(manifest["entries"]) == 1
    # auto=True in the video list means ASR is available as well; it does not
    # make the separate manual track automatic.
    assert manifest["skipped"] == [{"video_id": OTHER, "reason": "missing-local-caption"}]
    monkeypatch.setattr(
        "manabi_sentence_db.tubelex.subprocess.run", lambda *a, **k: pytest.fail("extractor")
    )
    second = snapshot_tubelex(
        tmp_path / "second",
        videos_csv=listing,
        cache=cache,
        max_videos=1,
    )
    assert verify_tubelex_snapshot(second)["entries"] == manifest["entries"]
    assert {p.suffix for p in (tmp_path / "first").iterdir()} == {".json", ".zst"}
    caption_path = first.parent / manifest["entries"][0]["path"]
    caption_path.write_bytes(b"broken")
    with pytest.raises(DataError, match="checksum"):
        verify_tubelex_snapshot(first)


def test_build_and_exact_search_do_not_export_transcripts(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "manabi_sentence_db.tubelex.urlopen", lambda *a, **k: pytest.fail("network")
    )
    base, private, public, manifest = build_fixture(tmp_path)
    assert read_json(manifest)["stats"]["indexed-units"] == 4
    db = private / "citations.private.sqlite3"
    for query, count in [
        ("図書館", 1),
        ("館で本", 1),
        ("図", 1),
        ("図書", 1),
        ("かばん", 1),
        ("存在しない", 0),
        ("読みました。明日", 0),
    ]:
        results = search_tubelex_index(db, query, base_artifact=base)
        assert len(results) == count, query
        assert all(r["kind"] == "reference" and "text" not in r for r in results)
    assert base.read_bytes() == b"synthetic prebuilt release; must stay unchanged"
    assert sorted(p.name for p in public.iterdir()) == ["manifest.json", "references.jsonl.zst"]
    with (public / "references.jsonl.zst").open("rb") as source:
        with zstandard.ZstdDecompressor().stream_reader(source) as reader:
            references = reader.read()
    for text in ["今日は", "図書館", "ありがとうございます"]:
        assert text.encode() not in references
    for line in references.splitlines():
        validate_record(json.loads(line))
    assert len(references.splitlines()) == read_json(public / "manifest.json")["references"]
    with closing(sqlite3.connect(db)) as connection:
        assert (
            connection.execute(
                "SELECT text FROM substring WHERE substring MATCH ?", ('"図書館"',)
            ).fetchone()[0]
            is None
        )
        text = connection.execute("SELECT text_zstd FROM chunks LIMIT 1").fetchone()[0]
        assert "読みました。" in zstandard.ZstdDecompressor().decompress(text).decode()
    other_base = tmp_path / "other.zip"
    other_base.write_bytes(b"a different release")
    with pytest.raises(DataError, match="different base"):
        search_tubelex_index(db, "図書館", base_artifact=other_base)


def test_shared_cue_citations_and_literal_fts_syntax(tmp_path):
    listing, local = inputs(tmp_path)
    (local / f"{VIDEO}.ja.vtt").write_text("""WEBVTT

00:00.000 --> 00:04.000
今日は晴れです。明日も晴れです。式はA+Bです。
""")
    snapshot = snapshot_tubelex(tmp_path / "snapshot", videos_csv=listing, captions_dir=local)
    base = tmp_path / "base.zip"
    base.write_bytes(b"cc release")
    private, public = tmp_path / "private", tmp_path / "public"
    build_tubelex_index(snapshot, base, private, public)
    db = private / "citations.private.sqlite3"
    assert len(search_tubelex_index(db, "晴れです")) == 1  # deduplicate same playback window
    assert len(search_tubelex_index(db, "A+B")) == 1
    assert search_tubelex_index(db, '" OR 図書館') == []
    assert search_tubelex_index(db, "晴れです。明日") == []  # sentence boundary


def test_fresh_separate_outputs_and_cli_errors(tmp_path, capsys):
    base, private, public, _ = build_fixture(tmp_path)
    with pytest.raises(DataError, match="already exists"):
        build_tubelex_index(tmp_path / "snapshot", base, private, tmp_path / "fresh")
    with pytest.raises(DataError, match="separate"):
        build_tubelex_index(tmp_path / "snapshot", base, tmp_path / "a", tmp_path / "a" / "b")
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "missing")
    with pytest.raises(DataError, match="already exists"):
        build_tubelex_index(tmp_path / "snapshot", base, link, tmp_path / "fresh")
    assert (
        main(
            [
                "search-tubelex",
                "--index",
                str(private / "citations.private.sqlite3"),
                "--query",
                "図書館",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)[0]["kind"] == "reference"
    assert (
        main(
            ["search-tubelex", "--index", str(private / "citations.private.sqlite3"), "--query", ""]
        )
        == 2
    )


def test_network_acquisition_requests_manual_vtt_only(tmp_path, monkeypatch):
    listing, _ = inputs(tmp_path)
    calls = []

    def extractor(video, executable):
        calls.append(video)
        return info(video)

    monkeypatch.setattr("manabi_sentence_db.tubelex._extract_info", extractor)
    monkeypatch.setattr("manabi_sentence_db.tubelex.time.sleep", lambda seconds: None)
    urls = []

    def get(url, **kwargs):
        urls.append(url)
        return VTT.encode()

    monkeypatch.setattr("manabi_sentence_db.tubelex._get", get)
    snapshot = snapshot_tubelex(tmp_path / "snapshot", videos_csv=listing, max_videos=1)
    assert len(verify_tubelex_snapshot(snapshot)["entries"]) == 1
    assert len(calls) == 1 and len(urls) == 1
    assert "lang=ja" in urls[0] and "tlang" not in urls[0]
    assert "timedtext" not in snapshot.read_text()


def test_all_short_substrings_match_literal_oracle(tmp_path):
    listing, local = inputs(tmp_path)
    texts = ["晴れの日はA+Bですね。", "晴れた日はABですね。", "今日はcaféに行きます。"]
    (local / f"{VIDEO}.ja.vtt").write_text(
        "WEBVTT\n\n"
        + "\n\n".join(
            f"00:{i * 5:02}.000 --> 00:{i * 5 + 3:02}.000\n{text}" for i, text in enumerate(texts)
        )
    )
    snapshot = snapshot_tubelex(tmp_path / "snapshot", videos_csv=listing, captions_dir=local)
    base = tmp_path / "base.zip"
    base.write_bytes(b"cc release")
    private, public = tmp_path / "private", tmp_path / "public"
    build_tubelex_index(snapshot, base, private, public)
    queries = {
        text[i : i + width]
        for text in texts
        for width in range(1, 7)
        for i in range(len(text) - width + 1)
    }
    for query in sorted(queries):
        expected = sum(query in text for text in texts)
        assert (
            len(search_tubelex_index(private / "citations.private.sqlite3", query)) == expected
        ), query


def _build_vtt(tmp_path, vtt, **options):
    listing, local = inputs(tmp_path)
    (local / f"{VIDEO}.ja.vtt").write_text(vtt)
    snapshot = snapshot_tubelex(tmp_path / "snapshot", videos_csv=listing, captions_dir=local)
    base = tmp_path / "base.zip"
    base.write_bytes(b"cc release")
    private = tmp_path / "private"
    manifest = build_tubelex_index(snapshot, base, private, tmp_path / "public", **options)
    return private / "citations.private.sqlite3", read_json(manifest)


def test_zero_gap_unpunctuated_track_remains_searchable(tmp_path):
    texts = [f"今日は図書館で本を読みます{i}明日は晴れるでしょう" for i in range(79)]
    vtt = "WEBVTT\n\n" + "\n\n".join(
        f"00:{i // 12:02}:{(i % 12) * 5:02}.000 --> "
        f"00:{(i + 1) // 12:02}:{((i + 1) % 12) * 5:02}.000\n{text}"
        for i, text in enumerate(texts)
    )
    db, manifest = _build_vtt(tmp_path, vtt)
    assert manifest["stats"]["indexed-characters"] == sum(map(len, texts))
    results = search_tubelex_index(db, "読みます53明日")
    assert results and "boundary:context-window" in results[0]["tags"]
    assert results[0]["locator"]["end_seconds"] - results[0]["locator"]["start_seconds"] <= 30


def test_search_crosses_uncertain_pause_but_not_large_context_gap(tmp_path):
    db, _ = _build_vtt(
        tmp_path,
        """WEBVTT

00:00.000 --> 00:01.000
私たちは

00:01.900 --> 00:03.000
明日出発します

00:10.000 --> 00:12.000
今日は帰ります
""",
    )
    assert search_tubelex_index(db, "私たちは明日出発します")
    assert search_tubelex_index(db, "出発します今日は") == []


def test_overlapping_speakers_are_not_concatenated(tmp_path):
    vtt = """WEBVTT

00:00.000 --> 00:03.000 region:left
<v Alice>私は東京に住んでいます</v>

00:01.000 --> 00:02.000 region:right
<v Bob>明日出発します</v>
"""
    streams = caption_streams(parse_vtt(vtt))
    assert [s.voice for s in streams] == ["Alice", "Bob"]
    db, _ = _build_vtt(tmp_path, vtt)
    assert search_tubelex_index(db, "住んでいます明日") == []
    assert search_tubelex_index(db, "東京に住んでいます")
    ambiguous = caption_streams([Cue(0, 3000, "私は東京に"), Cue(1000, 2000, "住んでいます")])
    assert len(ambiguous) == 2


def test_returning_speaker_cannot_match_across_an_intervening_turn(tmp_path):
    vtt = """WEBVTT

00:00.000 --> 00:01.000
<v Alice>私は明日</v>

00:01.000 --> 00:02.000
<v Bob>それは本当ですか</v>

00:02.000 --> 00:03.000
<v Alice>出発します</v>
"""
    assert [s.text for s in caption_streams(parse_vtt(vtt))] == [
        "私は明日",
        "それは本当ですか",
        "出発します",
    ]
    db, _ = _build_vtt(tmp_path, vtt)
    assert search_tubelex_index(db, "明日出発") == []
    assert search_tubelex_index(db, "出発します")


@pytest.mark.parametrize("separator", ["\n", "<br>", "<br/>"])
def test_latin_word_wraps_keep_a_separator_and_correct_timing(tmp_path, separator):
    vtt = f"WEBVTT\n\n00:01.000 --> 00:04.000\n今日はgood{separator}morningですね。\n"
    assert parse_vtt(vtt)[0].text == "今日はgood morningですね。"
    db, _ = _build_vtt(tmp_path, vtt)
    assert search_tubelex_index(db, "goodmorning") == []
    matches = search_tubelex_index(db, "good morning")
    assert matches[0]["locator"] == {
        "type": "media",
        "start_seconds": 1.0,
        "end_seconds": 4.0,
    }
    verify_tubelex_index(db.parent, tmp_path / "public", deep=True)


def test_latin_words_across_cues_do_not_form_a_new_word(tmp_path):
    vtt = """WEBVTT

00:01.000 --> 00:02.000
今日はgood

00:02.000 --> 00:04.000
morningですね。
"""
    stream = caption_streams(parse_vtt(vtt))[0]
    assert stream.text == "今日はgood morningですね。"
    assert all(a.end == b.start for a, b in zip(stream.origins, stream.origins[1:]))
    db, _ = _build_vtt(tmp_path, vtt)
    assert search_tubelex_index(db, "goodmorning") == []
    assert search_tubelex_index(db, "good morning")
    verify_tubelex_index(db.parent, tmp_path / "public", deep=True)


def test_latin_scrolling_separator_retains_both_cue_envelopes():
    vtt = """WEBVTT

00:00.000 --> 00:02.000
今日はcafé
bonjour

00:01.500 --> 00:03.000
bonjour
明日も行きます。
"""
    stream = caption_streams(parse_vtt(vtt))[0]
    assert stream.text == "今日はcafé bonjour明日も行きます。"
    repeated = next(p for p in stream.origins if p.start <= stream.text.index("bonjour") < p.end)
    assert repeated.start_ms == 0 and repeated.end_ms == 3000
    assert len(repeated.cue_ids) == 2


def test_scrolling_provenance_retains_repeated_display_times():
    streams = caption_streams(
        parse_vtt("""WEBVTT

00:00.000 --> 00:02.000
今日は
図書館で

00:01.500 --> 00:03.000
図書館で
本を読みます。
""")
    )
    assert len(streams) == 1
    repeated = streams[0].origins[1]
    assert repeated.start_ms == 0 and repeated.end_ms == 3000
    assert len(repeated.cue_ids) == 2


def test_max_query_crossing_chunk_boundary_and_wide_cue(tmp_path):
    text = "今日は" + "あ" * 3550 + "".join(chr(0x4E00 + i) for i in range(500)) + "い" * 5000
    db, manifest = _build_vtt(tmp_path, f"WEBVTT\n\n00:00.000 --> 01:10.000\n{text}\n")
    assert manifest["stats"]["indexed-characters"] == len(text)
    query = text[3555:4055]
    results = search_tubelex_index(db, query)
    assert len(results) == 1
    assert "timing:wide-cue-envelope" in results[0]["tags"]
    verify_tubelex_index(db.parent, tmp_path / "public", deep=True)


def test_connections_close_on_success_and_failure(tmp_path, monkeypatch):
    from manabi_sentence_db import tubelex_index

    connections = []
    original = tubelex_index._open_index

    class Tracked(sqlite3.Connection):
        was_closed = False

        def close(self):
            self.was_closed = True
            super().close()

    def track(path, *, readonly=False):
        if readonly:
            connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, factory=Tracked)
        else:
            connection = sqlite3.connect(path, factory=Tracked)
        connections.append(connection)
        return connection

    monkeypatch.setattr(tubelex_index, "_open_index", track)
    db, _ = _build_vtt(tmp_path, VTT)
    assert connections[-1].was_closed
    assert search_tubelex_index(db, "図書館")
    assert connections[-1].was_closed
    with closing(original(db)) as connection:
        connection.execute("PRAGMA user_version=999")
    with pytest.raises(DataError, match="schema"):
        search_tubelex_index(db, "図書館")
    assert connections[-1].was_closed


def test_unavailable_video_ledger_and_cache_survive_list_changes(tmp_path, monkeypatch):
    from manabi_sentence_db.tubelex import CaptionUnavailable

    listing, _ = inputs(tmp_path)
    calls = []

    def extract(video, executable):
        calls.append(video)
        if video == VIDEO:
            raise CaptionUnavailable("removed-or-private")
        return info(video)

    monkeypatch.setattr("manabi_sentence_db.tubelex._extract_info", extract)
    monkeypatch.setattr("manabi_sentence_db.tubelex._get", lambda *a, **kw: VTT.encode())
    monkeypatch.setattr("manabi_sentence_db.tubelex.time.sleep", lambda *a: None)
    cache = tmp_path / "cache"
    first = snapshot_tubelex(tmp_path / "one", videos_csv=listing, cache=cache)
    assert verify_tubelex_snapshot(first)["entries"][0]["video_id"] == OTHER
    assert calls == [VIDEO, OTHER]
    # A different CSV checksum must not force re-downloading either known state.
    listing.write_text(listing.read_text() + "\n")
    monkeypatch.setattr(
        "manabi_sentence_db.tubelex._extract_info", lambda *a: pytest.fail("reacquired")
    )
    second = snapshot_tubelex(tmp_path / "two", videos_csv=listing, cache=cache)
    assert len(verify_tubelex_snapshot(second)["entries"]) == 1


@pytest.mark.parametrize(
    "error,unavailable",
    [
        ("ERROR: This video has been removed by the uploader", True),
        ("ERROR: Private video. Sign in if you have been granted access", True),
        ("ERROR: Sign in to confirm you're not a bot", False),
        ("ERROR: HTTP Error 429: Too Many Requests", False),
        ("ERROR: Video unavailable for an unknown reason", False),
    ],
)
def test_extractor_classifies_errors_without_logging_secrets(monkeypatch, error, unavailable):
    import io

    from manabi_sentence_db.tubelex import CaptionUnavailable, _extract_info

    class Process:
        stdout = io.BytesIO(b"")
        stderr = io.BytesIO(error.encode())
        returncode = 1

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stdout.close()
            self.stderr.close()

        def wait(self, **kwargs):
            return self.returncode

        def kill(self):
            self.returncode = -9

    def popen(command, **kwargs):
        assert "--ignore-config" in command and "--no-cache-dir" in command
        assert "--skip-download" in command and "--no-playlist" in command
        assert kwargs["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
        return Process()

    monkeypatch.setattr("manabi_sentence_db.tubelex.subprocess.Popen", popen)
    with pytest.raises(DataError) as raised:
        _extract_info(VIDEO, "yt-dlp")
    assert isinstance(raised.value, CaptionUnavailable) == unavailable


def test_atomic_cache_failure_preserves_completed_destination(tmp_path, monkeypatch):
    from pathlib import Path

    from manabi_sentence_db.tubelex import _write_new_bytes

    destination = tmp_path / "caption.zst"
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    def fail_replace(*args):
        raise OSError("interrupted before installation")

    with monkeypatch.context() as context:
        context.setattr("manabi_sentence_db.tubelex.os.replace", fail_replace)
        with pytest.raises(OSError):
            _write_new_bytes(destination, b"synthetic compressed input")
    assert not destination.exists()
    assert len(list((tmp_path / ".Trash").iterdir())) == 1
    _write_new_bytes(destination, b"complete")
    with pytest.raises(DataError, match="overwrite"):
        _write_new_bytes(destination, b"replacement")
    assert destination.read_bytes() == b"complete"


def test_offline_model_environment_is_restored(monkeypatch):
    import os

    from manabi_sentence_db.tubelex_index import _offline_models

    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    with pytest.raises(RuntimeError), _offline_models():
        assert os.environ["HF_HUB_OFFLINE"] == "1"
        raise RuntimeError("failed model load")
    assert os.environ["HF_HUB_OFFLINE"] == "0"
    assert "TRANSFORMERS_OFFLINE" not in os.environ


def test_nfc_composition_across_cues_preserves_both_origins(tmp_path):
    vtt = """WEBVTT

00:00.000 --> 00:01.000
今日はか

00:01.000 --> 00:02.000
゙んばります。
"""
    stream = caption_streams(parse_vtt(vtt))[0]
    assert stream.text == "今日はがんばります。"
    composed = next(p for p in stream.origins if p.start <= 3 < p.end)
    assert (composed.start_ms, composed.end_ms) == (0, 2000)
    assert len(composed.cue_ids) == 2
    db, _ = _build_vtt(tmp_path, vtt)
    assert search_tubelex_index(db, "がんばります")
    result = verify_tubelex_index(tmp_path / "private", tmp_path / "public", deep=True)
    assert result["indexed_characters"] == len(stream.text)


def test_hangul_composition_and_reordered_marks_keep_origin_partitions():
    import unicodedata

    for a, b in [("ᄀ", "ᅡ"), ("a\u0315", "\u0300"), ("か", "\u3099")]:
        stream = caption_streams([Cue(0, 1000, a), Cue(1000, 2000, b)])[0]
        assert stream.text == unicodedata.normalize("NFC", a + b)
        assert stream.origins[0].start == 0
        assert stream.origins[-1].end == len(stream.text)
        assert all(
            left.end == right.start for left, right in zip(stream.origins, stream.origins[1:])
        )


def test_completed_artifact_verification_and_cli(tmp_path, capsys):
    base, private, public, manifest = build_fixture(tmp_path)
    result = verify_tubelex_index(private, public, base_artifact=base, deep=True)
    assert result["references"] == read_json(manifest)["references"]
    assert result["indexed_characters"] == read_json(manifest)["stats"]["indexed-characters"]
    assert (
        main(
            [
                "verify-tubelex",
                "--private-build",
                str(private),
                "--references",
                str(public),
                "--deep",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["deep"] is True


@pytest.mark.parametrize("target", ["index", "references", "manifest"])
def test_verifier_rejects_changed_artifacts(tmp_path, target):
    _, private, public, _ = build_fixture(tmp_path)
    if target == "index":
        with closing(sqlite3.connect(private / "citations.private.sqlite3")) as connection:
            connection.execute("PRAGMA user_version=999")
    elif target == "references":
        with (public / "references.jsonl.zst").open("ab") as file:
            file.write(b"corruption")
    else:
        path = public / "manifest.json"
        manifest = read_json(path)
        manifest["build_id"] = "different"
        path.write_bytes(canonical_json(manifest))
    with pytest.raises(DataError, match="checksum|disagree"):
        verify_tubelex_index(private, public, deep=True)


@pytest.mark.parametrize("target", ["origin", "unit", "orphan", "trigram", "eligibility", "length"])
def test_deep_verifier_checks_logical_alignment_after_checksums(tmp_path, target):
    from manabi_sentence_db.serialization import sha256_file

    _, private, public, manifest_path = build_fixture(tmp_path)
    db = private / "citations.private.sqlite3"
    with closing(sqlite3.connect(db)) as connection, connection:
        if target == "origin":
            connection.execute("UPDATE origins SET start=start+1 WHERE start=0")
        elif target == "unit":
            connection.execute("UPDATE units SET end=999999 WHERE start=0")
        elif target == "eligibility":
            connection.execute("UPDATE streams SET eligibility=zeroblob(length(eligibility))")
        elif target == "length":
            row = connection.execute("SELECT id,metadata FROM streams LIMIT 1").fetchone()
            metadata = json.loads(row[1])
            metadata["text_length"] += 1
            connection.execute(
                "UPDATE streams SET metadata=? WHERE id=?", (canonical_json(metadata), row[0])
            )
        elif target == "trigram":
            connection.execute("INSERT INTO substring(rowid,text) VALUES (?,?)", (999999, "孤立語"))
        else:
            connection.execute(
                "INSERT INTO short_substring(rowid,terms) VALUES (?,?)", (999999, "s6f727068616e")
            )
    manifest = read_json(manifest_path)
    manifest["index_sha256"] = sha256_file(db)
    manifest_path.write_bytes(canonical_json(manifest))
    verify_tubelex_index(private, public)  # Correct transfer checksums alone are insufficient.
    with pytest.raises(DataError, match="partition|Orphaned|eligibility|length|boundary"):
        verify_tubelex_index(private, public, deep=True)


@pytest.mark.parametrize("damage", ["truncated", "trailing", "unknown-size", "invalid-utf8"])
def test_private_chunk_decoding_is_bounded_and_strict(damage):
    from manabi_sentence_db.tubelex_index import _decode_text

    encoded = zstandard.ZstdCompressor(write_checksum=True).compress("今日は晴れです".encode())
    if damage == "truncated":
        encoded = encoded[:-1]
    elif damage == "trailing":
        encoded += b"extra"
    elif damage == "unknown-size":
        encoded = zstandard.ZstdCompressor(write_content_size=False).compress(b"text")
    else:
        encoded = zstandard.ZstdCompressor().compress(b"\xff")
    with pytest.raises(DataError):
        _decode_text(encoded)


@pytest.mark.parametrize("target", ["title", "timing", "tags"])
def test_verifier_rejects_rehashed_reference_text_and_bad_timing(tmp_path, target):
    from manabi_sentence_db.serialization import sha256_file

    _, private, public, private_manifest_path = build_fixture(tmp_path)
    export = public / "references.jsonl.zst"
    with export.open("rb") as source, zstandard.ZstdDecompressor().stream_reader(source) as reader:
        records = [json.loads(line) for line in reader.read().splitlines()]
    if target == "title":
        records[0]["title"] = "これは持ち出してはいけない本文です"
    elif target == "tags":
        records[0]["tags"].append("これは持ち出してはいけない本文です")
    else:
        records[0]["url"] += "999"
    encoded = b"".join(canonical_json(record) + b"\n" for record in records)
    export.write_bytes(zstandard.ZstdCompressor().compress(encoded))
    for path in (public / "manifest.json", private_manifest_path):
        manifest = read_json(path)
        manifest["asset"]["sha256"] = sha256_file(export)
        path.write_bytes(canonical_json(manifest))
    with pytest.raises(DataError, match="Unexpected text|timing disagree"):
        verify_tubelex_index(private, public)


def test_search_uses_factory_checks_instead_of_per_result_schema_validation(tmp_path, monkeypatch):
    base, private, public, _ = build_fixture(tmp_path)
    monkeypatch.setattr(
        "manabi_sentence_db.tubelex_index.validate_record",
        lambda *args: pytest.fail("hot schema validation"),
    )
    assert search_tubelex_index(private / "citations.private.sqlite3", "の")
    with pytest.raises(DataError, match="factory"):
        reference_record(
            AlignedSentence("", -1, 100, "punctuation"), video_id=VIDEO, snapshot_id="snapshot"
        )


def test_local_onnx_threshold_is_explicit_and_independent_of_directory_name(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    from manabi_sentence_db.tubelex_index import _local_sat

    calls = []

    class Model:
        def __init__(self, path, **kwargs):
            assert kwargs["ort_providers"] == ["CPUExecutionProvider"]
            options = kwargs["ort_kwargs"]["sess_options"]
            assert options.intra_op_num_threads == 2
            assert kwargs["from_pretrained_kwargs"]["local_files_only"] is True

        def split(self, text, **kwargs):
            calls.append(kwargs)
            return [text]

    monkeypatch.setitem(sys.modules, "wtpsplit", SimpleNamespace(SaT=Model))
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(SessionOptions=SimpleNamespace))
    monkeypatch.setattr("manabi_sentence_db.tubelex_index.version", lambda *args: "test")
    tokenizer = tmp_path / "tokenizer"
    tokenizer.mkdir()
    (tokenizer / "tokenizer.json").write_text("synthetic tokenizer")
    for name in ("sat-3l-sm", "arbitrary-folder"):
        model = tmp_path / name
        model.mkdir()
        (model / "model_optimized.onnx").write_bytes(b"synthetic model")
        segment, identity = _local_sat(model, tokenizer, threshold=0.25)
        assert segment("今日は晴れです") == ["今日は晴れです"]
        assert identity["backend"] == "onnx-cpu"
        assert identity["threshold"] == 0.25
    assert calls[0] == calls[1]
    assert calls[0]["threshold"] == 0.25


def test_model_does_not_override_publisher_sentence_boundaries():
    from manabi_sentence_db.tubelex import stream_units

    stream = caption_streams([Cue(0, 3000, "今日は図書館に行きます。明日は休みです")])[0]
    calls = []

    def segment(text):
        calls.append(text)
        return [text[:2], text[2:]]

    units = list(stream_units(stream, segment=segment))
    assert units[0][2] == "punctuation"
    assert stream.text[units[0][0] : units[0][1]] == "今日は図書館に行きます。"
    assert calls == ["明日は休みです"]


def test_query_reuses_the_already_decoded_chunk(tmp_path, monkeypatch):
    from manabi_sentence_db import tubelex_index

    _, private, _, _ = build_fixture(tmp_path)
    decode = tubelex_index._decode_text
    decoded = []

    def track(blob):
        decoded.append(blob)
        return decode(blob)

    monkeypatch.setattr(tubelex_index, "_decode_text", track)
    monkeypatch.setattr(
        tubelex_index,
        "assess_sentence",
        lambda *args, **kwargs: pytest.fail("query-time assessment"),
    )
    assert search_tubelex_index(private / "citations.private.sqlite3", "図書館")
    assert len(decoded) == 1


def test_source_eligibility_is_built_once_and_retains_safe_distant_tiles(tmp_path):
    text = "今日は本を読んでいます" * 100 + "性行為" + "今日は公園へ行きます" * 100
    db, _ = _build_vtt(tmp_path, f"WEBVTT\n\n00:00.000 --> 00:20.000\n{text}\n")
    assert search_tubelex_index(db, "本を読んでいます")
    assert search_tubelex_index(db, "公園へ行きます")
    assert search_tubelex_index(db, "性行為") == []
    verify_tubelex_index(db.parent, tmp_path / "public", deep=True)


def test_deep_verifier_rejects_nonzero_bitmap_padding(tmp_path):
    from manabi_sentence_db.serialization import sha256_file

    _, private, public, manifest_path = build_fixture(tmp_path)
    db = private / "citations.private.sqlite3"
    with closing(sqlite3.connect(db)) as connection, connection:
        connection.execute("UPDATE streams SET eligibility=?", (b"\xff",))
    manifest = read_json(manifest_path)
    manifest["index_sha256"] = sha256_file(db)
    manifest_path.write_bytes(canonical_json(manifest))
    with pytest.raises(DataError, match="eligibility"):
        verify_tubelex_index(private, public, deep=True)


def test_character_boundary_predictions_preserve_text_and_ignore_commas():
    from manabi_sentence_db.tubelex_boundaries import split_character_predictions

    text = "今日は晴れです 明日は雨です"

    def predict(fragment):
        return [[0.0, 0.0, 9.0, 0.0] if c == "す" else [9.0, 0.0, 0.0, 0.0] for c in fragment]

    parts = split_character_predictions(text, predict)
    assert parts == ["今日は晴れです ", "明日は雨です"]
    assert "".join(parts) == text
    assert split_character_predictions(text, lambda f: [[0.0, 9.0, 0.0, 0.0] for c in f]) == [text]


def test_character_model_window_edges_are_not_forced_sentence_boundaries():
    from manabi_sentence_db.tubelex_boundaries import split_character_predictions

    text = "今日は図書館で本を読んでから公園へ行きます"

    def predict(fragment):
        return [[9.0, 0.0, 0.0, 0.0] for _ in fragment[:-1]] + [[0.0, 0.0, 9.0, 0.0]]

    assert split_character_predictions(text, predict, window_chars=8, overlap_chars=2) == [text]


def test_character_model_window_starts_have_left_context():
    from manabi_sentence_db.tubelex_boundaries import split_character_predictions

    text = "今日は図書館で本を読んでから公園へ行きます"
    calls = []

    def predict(fragment):
        calls.append(fragment)
        # Simulate the model's known edge bias at the start of each new window.
        return [
            [0.0, 0.0, 9.0, 0.0] if i == 0 and len(calls) > 1 else [9.0, 0.0, 0.0, 0.0]
            for i in range(len(fragment))
        ]

    assert split_character_predictions(text, predict, window_chars=8, overlap_chars=2) == [text]
    assert len(calls) > 1


def test_character_model_overlap_assigns_each_boundary_exactly_once():
    from manabi_sentence_db.tubelex_boundaries import split_character_predictions

    sentence = "今日は晴れです"
    text = sentence * 300

    def predict(fragment):
        return [[0.0, 0.0, 9.0, 0.0] if char == "す" else [9.0, 0.0, 0.0, 0.0] for char in fragment]

    assert split_character_predictions(text, predict) == [sentence] * 300


@pytest.mark.parametrize("prediction", [[], [[float("nan"), 0.0, 0.0, 0.0]] * 4, [[0.0, 1.0]] * 4])
def test_character_model_rejects_bad_alignment_and_logits(prediction):
    from manabi_sentence_db.tubelex_boundaries import split_character_predictions

    with pytest.raises(DataError):
        split_character_predictions("今日は雨", lambda _: prediction)


def test_reusable_reader_opens_once_and_closes_on_exit(tmp_path, monkeypatch):
    from manabi_sentence_db import tubelex_index

    _, private, _, _ = build_fixture(tmp_path)
    original = tubelex_index._open_index
    opened = []

    def track(*args, **kwargs):
        connection = original(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(tubelex_index, "_open_index", track)
    reader = tubelex_index.TubelexReader(private / "citations.private.sqlite3")
    with reader:
        assert reader.search("図書館")
        assert reader.search("かばん")
        assert len(opened) == 1
        assert reader.build_id.startswith("tubelex-index_")
    reader.close()
    with pytest.raises(DataError, match="closed"):
        reader.search("図書館")
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute("SELECT 1")


def test_model_boundary_cannot_hide_a_borrowed_name_match(tmp_path, monkeypatch):
    text = "今日はWordですね"
    vtt = f"WEBVTT\n\n00:00.000 --> 00:02.000\n{text}\n"
    baseline_dir = tmp_path / "baseline"
    model_dir = tmp_path / "model"
    baseline_dir.mkdir()
    model_dir.mkdir()
    baseline, _ = _build_vtt(baseline_dir, vtt)
    monkeypatch.setattr(
        "manabi_sentence_db.tubelex_boundaries.local_japanese_character_model",
        lambda *args, **kwargs: (lambda text: ["今日は", "Word", "ですね"], {"engine": "test"}),
    )
    modeled, _ = _build_vtt(model_dir, vtt, ja_punct_model=tmp_path / "synthetic-model")
    assert search_tubelex_index(baseline, "Word")
    assert search_tubelex_index(modeled, "Word")


def test_cross_sentence_candidates_are_rejected_before_reference_hydration(tmp_path, monkeypatch):
    _, private, _, _ = build_fixture(tmp_path)
    monkeypatch.setattr(
        "manabi_sentence_db.tubelex_index._match_reference",
        lambda *args, **kwargs: pytest.fail("hydrated a known cross-sentence candidate"),
    )
    assert search_tubelex_index(private / "citations.private.sqlite3", "読みました。明日") == []


def test_punctuation_inside_a_quote_remains_searchable(tmp_path):
    text = "彼は「今日は雨。明日は晴れ」と言いました。"
    db, _ = _build_vtt(tmp_path, f"WEBVTT\n\n00:00.000 --> 00:03.000\n{text}\n")
    assert search_tubelex_index(db, "雨。明日")


def test_query_deadline_fails_explicitly_and_reader_remains_reusable(tmp_path, monkeypatch):
    from manabi_sentence_db import tubelex_index

    _, private, _, _ = build_fixture(tmp_path)
    with tubelex_index.TubelexReader(private / "citations.private.sqlite3", timeout_ms=1) as reader:
        ticks = iter([0.0, 0.01, 0.02, 0.03])
        monkeypatch.setattr(tubelex_index.time, "monotonic", lambda: next(ticks, 1.0))
        with pytest.raises(DataError, match="budget|deadline"):
            reader.search("図書館")
        monkeypatch.setattr(tubelex_index.time, "monotonic", lambda: 0.0)
        assert reader.search("図書館")


def test_query_deadline_interrupts_sqlite_work_and_clears_handler(tmp_path, monkeypatch):
    from manabi_sentence_db import tubelex_index

    _, private, _, _ = build_fixture(tmp_path)

    class SlowConnection(sqlite3.Connection):
        slow_once = True

        def execute(self, sql, parameters=()):
            if self.slow_once and "JOIN chunks" in sql:
                self.slow_once = False
                super().execute(
                    "WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<100000) "
                    "SELECT sum(x) FROM n"
                ).fetchone()
            return super().execute(sql, parameters)

    monkeypatch.setattr(
        tubelex_index,
        "_open_index",
        lambda path, **kwargs: sqlite3.connect(path, factory=SlowConnection),
    )
    with tubelex_index.TubelexReader(private / "citations.private.sqlite3", timeout_ms=1) as reader:
        ticks = iter(i * 0.0003 for i in range(100))
        monkeypatch.setattr(tubelex_index.time, "monotonic", lambda: next(ticks, 1.0))
        with pytest.raises(DataError, match="budget|deadline"):
            reader.search("図書館")
        # This recursive query must run after interruption without a stale handler.
        assert (
            reader._database.execute(
                "WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<1000) "
                "SELECT sum(x) FROM n"
            ).fetchone()[0]
            == 500500
        )
        monkeypatch.setattr(tubelex_index.time, "monotonic", lambda: 0.0)
        assert reader.search("図書館")


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), True, "1000", 60001])
def test_query_budget_rejects_invalid_settings_before_opening_database(timeout):
    from pathlib import Path

    from manabi_sentence_db.tubelex_index import TubelexReader

    with pytest.raises(DataError, match="budget|timeout"):
        TubelexReader(Path("/does/not/exist.sqlite3"), timeout_ms=timeout)


@pytest.mark.parametrize(
    "damage", ["list", "entries", "empty", "video", "digest", "skipped", "revision", "reason"]
)
def test_snapshot_manifest_shape_errors_are_controlled(tmp_path, damage):
    from manabi_sentence_db.serialization import digest_json

    build_fixture(tmp_path)
    path = tmp_path / "snapshot/manifest.json"
    manifest = read_json(path)
    if damage == "list":
        manifest = []
    else:
        if damage == "entries":
            manifest["entries"] = "invalid"
        elif damage == "empty":
            manifest["entries"] = []
        elif damage == "video":
            manifest["entries"][0]["video_id"] = None
        elif damage == "digest":
            manifest["entries"][0]["sha256"] = "bad digest"
        elif damage == "revision":
            manifest.pop("revision")
        elif damage == "reason":
            manifest["skipped"][0]["reason"] = {}
        else:
            manifest["skipped"] = ["invalid"]
        manifest["snapshot_id"] = (
            "tubelex_" + digest_json({k: v for k, v in manifest.items() if k != "snapshot_id"})[:32]
        )
    path.write_bytes(canonical_json(manifest))
    with pytest.raises(DataError):
        verify_tubelex_snapshot(path)


def test_interrupted_build_is_unusable_and_can_restart_offline(tmp_path, monkeypatch):
    from manabi_sentence_db import tubelex_index

    listing, local = inputs(tmp_path)
    snapshot = snapshot_tubelex(tmp_path / "snapshot", videos_csv=listing, captions_dir=local)
    base = tmp_path / "base.zip"
    base.write_bytes(b"unchanged CC artifact")
    failed, partial_references = tmp_path / "failed", tmp_path / "partial-references"

    def interrupted(*args, **kwargs):
        raise RuntimeError("synthetic interruption during export")

    with monkeypatch.context() as context:
        context.setattr(tubelex_index, "_match_reference", interrupted)
        with pytest.raises(RuntimeError, match="interruption"):
            build_tubelex_index(snapshot, base, failed, partial_references)
    assert not (failed / "manifest.private.json").exists()
    assert not (partial_references / "manifest.json").exists()
    with pytest.raises(DataError, match="Incomplete"):
        tubelex_index.TubelexReader(failed / "citations.private.sqlite3")
    monkeypatch.setattr(
        "manabi_sentence_db.tubelex._get", lambda *args, **kwargs: pytest.fail("network")
    )
    rebuilt, references = tmp_path / "rebuilt", tmp_path / "references"
    build_tubelex_index(snapshot, base, rebuilt, references)
    verify_tubelex_index(rebuilt, references, deep=True)
    assert base.read_bytes() == b"unchanged CC artifact"


def test_finished_index_reclaims_temporary_and_merged_pages(tmp_path):
    _, private, public, _ = build_fixture(tmp_path)
    with closing(sqlite3.connect(private / "citations.private.sqlite3")) as connection:
        assert connection.execute("PRAGMA freelist_count").fetchone()[0] == 0
    verify_tubelex_index(private, public, deep=True)


def test_deadline_discards_results_already_materialized(tmp_path, monkeypatch):
    from manabi_sentence_db import tubelex_index

    _, private, _, _ = build_fixture(tmp_path)
    now, hits = [0.0], []
    original = tubelex_index._match_reference

    def track(*args, **kwargs):
        record = original(*args, **kwargs)
        if record:
            hits.append(record)
            now[0] = 0.01
        return record

    monkeypatch.setattr(tubelex_index, "_match_reference", track)
    monkeypatch.setattr(tubelex_index.time, "monotonic", lambda: now[0])
    with tubelex_index.TubelexReader(private / "citations.private.sqlite3", timeout_ms=1) as reader:
        with pytest.raises(tubelex_index.QueryBudgetExceeded):
            reader.search("の")
    assert hits


@pytest.mark.parametrize("damage", ["missing-build", "invalid-build", "missing-base"])
def test_reader_rejects_invalid_identity_metadata_cleanly(tmp_path, damage):
    from manabi_sentence_db.tubelex_index import TubelexReader

    _, private, _, _ = build_fixture(tmp_path)
    db = private / "citations.private.sqlite3"
    with closing(sqlite3.connect(db)) as connection, connection:
        if damage == "invalid-build":
            connection.execute("UPDATE metadata SET value=? WHERE key='build_id'", (b"null",))
        else:
            key = "build_id" if damage == "missing-build" else "base_sha256"
            connection.execute("DELETE FROM metadata WHERE key=?", (key,))
    with pytest.raises(DataError, match="identity metadata"):
        TubelexReader(db)


def test_cli_reports_invalid_budget_without_printing_results(tmp_path, capsys):
    _, private, _, _ = build_fixture(tmp_path)
    assert (
        main(
            [
                "search-tubelex",
                "--index",
                str(private / "citations.private.sqlite3"),
                "--query",
                "図書館",
                "--timeout-ms",
                "0",
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    assert output.out == ""
    assert "budget" in output.err


def test_snapshot_manifest_encoding_error_is_controlled(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_bytes(b"\xff\xfeinvalid JSON")
    with pytest.raises(DataError):
        verify_tubelex_snapshot(path)


def test_packed_boundaries_keep_query_endpoints_and_quoted_punctuation(tmp_path):
    text = "春です。夏です。彼は「雨。晴れ」と言いました。"
    db, _ = _build_vtt(tmp_path, f"WEBVTT\n\n00:00.000 --> 00:03.000\n{text}\n")
    for query in ["春です。", "夏です", "雨。晴れ"]:
        assert search_tubelex_index(db, query)
    for query in ["。夏", "春です。夏", "。彼は"]:
        assert search_tubelex_index(db, query) == []
    with closing(sqlite3.connect(db)) as database:
        assert (
            database.execute("SELECT typeof(boundary) FROM units LIMIT 1").fetchone()[0]
            == "integer"
        )
        assert database.execute("SELECT boundary_bits FROM chunks LIMIT 1").fetchone()[0]
        assert not database.execute(
            "SELECT 1 FROM sqlite_schema WHERE name='boundaries'"
        ).fetchone()


@pytest.mark.parametrize("damage", ["flipped", "padding", "noncanonical", "oversized", "unit-code"])
def test_deep_verifier_rejects_packed_boundary_corruption(tmp_path, damage):
    from manabi_sentence_db.serialization import sha256_file

    _, private, public, manifest_path = build_fixture(tmp_path)
    db = private / "citations.private.sqlite3"
    with closing(sqlite3.connect(db)) as database, database:
        if damage == "unit-code":
            database.execute("UPDATE units SET boundary=999")
        else:
            row = database.execute(
                "SELECT id,boundary_bits,end-start FROM chunks LIMIT 1"
            ).fetchone()
            if damage == "flipped":
                bits = bytes([row[1][0] ^ 2]) + row[1][1:]
            elif damage == "padding":
                bits = (1 << row[2]).to_bytes((row[2] + 8) // 8, "little")
            elif damage == "noncanonical":
                bits = row[1] + b"\x00"
            else:
                bits = b"\xff" * 513
            database.execute("UPDATE chunks SET boundary_bits=? WHERE id=?", (bits, row[0]))
    manifest = read_json(manifest_path)
    manifest["index_sha256"] = sha256_file(db)
    manifest_path.write_bytes(canonical_json(manifest))
    with pytest.raises(DataError, match="boundary|display-unit"):
        verify_tubelex_index(private, public, deep=True)


def test_boundary_cache_reuses_predictions_without_changing_public_artifacts(tmp_path, monkeypatch):
    calls = []

    def factory(path, *, threshold):
        def split(text):
            calls.append(text)
            return [text]

        return split, {"engine": "fixture", "threshold": threshold}

    monkeypatch.setattr(
        "manabi_sentence_db.tubelex_boundaries.local_japanese_character_model", factory
    )
    listing, local = inputs(tmp_path)
    snapshot = snapshot_tubelex(tmp_path / "snapshot", videos_csv=listing, captions_dir=local)
    base = tmp_path / "base.cc"
    base.write_bytes(b"unchanged CC base")
    outputs = []
    cache = tmp_path / "cache"
    for name in ["cold", "warm"]:
        out = tmp_path / name
        manifest = build_tubelex_index(
            snapshot,
            base,
            out / "index",
            out / "references",
            ja_punct_model=tmp_path / "model",
            boundary_cache=cache,
        )
        verify_tubelex_index(out / "index", out / "references", deep=True)
        outputs.append(read_json(manifest))
    assert len(calls) == 1
    assert outputs[0]["stats"]["boundary-cache-misses"] == 1
    assert outputs[1]["stats"]["boundary-cache-hits"] == 1
    assert outputs[0]["build_id"] == outputs[1]["build_id"]
    assert (tmp_path / "cold/references/references.jsonl.zst").read_bytes() == (
        tmp_path / "warm/references/references.jsonl.zst"
    ).read_bytes()
    for path in cache.glob("*.json.zst"):
        raw = zstandard.ZstdDecompressor().decompress(path.read_bytes())
        assert calls[0].encode() not in raw
        assert "text" not in json.loads(raw)
    # Thresholds belong to the model profile and invalidate cached predictions.
    build_tubelex_index(
        snapshot,
        base,
        tmp_path / "changed/index",
        tmp_path / "changed/references",
        ja_punct_model=tmp_path / "model",
        boundary_cache=cache,
        ja_punct_threshold=0.8,
    )
    assert len(calls) == 2


@pytest.mark.parametrize("damage", ["truncated", "offsets", "checksum"])
def test_boundary_cache_corruption_stops_reuse(tmp_path, damage):
    from collections import Counter

    from manabi_sentence_db.serialization import digest_json
    from manabi_sentence_db.tubelex_cache import cached_segmenter

    text = "今日は図書館で本を読みます"
    cache = tmp_path / "cache"
    segment = cached_segmenter(lambda text: [text], {"engine": "fixture"}, cache, Counter())
    assert segment(text) == [text]
    path = next(cache.glob("*.json.zst"))
    if damage == "truncated":
        path.write_bytes(path.read_bytes()[:8])
    else:
        record = json.loads(zstandard.ZstdDecompressor().decompress(path.read_bytes()))
        if damage == "offsets":
            record["ends"] = [True]
            record["ends_sha256"] = digest_json(record["ends"])
        else:
            record["ends_sha256"] = "invalid"
        path.write_bytes(zstandard.ZstdCompressor().compress(canonical_json(record)))
    with pytest.raises(DataError):
        segment(text)


def test_interrupted_model_build_reuses_completed_cache_entries(tmp_path, monkeypatch):
    listing, local = inputs(tmp_path)
    (local / f"{OTHER}.info.json").write_bytes(canonical_json(info(OTHER)))
    (local / f"{OTHER}.ja.vtt").write_text(
        "WEBVTT\n\n00:00.000 --> 00:03.000\n明日は市場へ行きます\n"
    )
    snapshot = snapshot_tubelex(tmp_path / "snapshot", videos_csv=listing, captions_dir=local)
    base = tmp_path / "base.cc"
    base.write_bytes(b"CC base")
    calls = []
    failing = [True]

    def factory(*args, **kwargs):
        def segment(text):
            calls.append(text)
            if failing[0] and len(calls) == 2:
                raise RuntimeError("interrupted inference")
            return [text]

        return segment, {"engine": "fixture"}

    monkeypatch.setattr(
        "manabi_sentence_db.tubelex_boundaries.local_japanese_character_model", factory
    )
    options = {"ja_punct_model": tmp_path / "model", "boundary_cache": tmp_path / "cache"}
    with pytest.raises(RuntimeError, match="inference"):
        build_tubelex_index(snapshot, base, tmp_path / "failed", tmp_path / "partial", **options)
    assert len(list((tmp_path / "cache").glob("*.json.zst"))) == 1
    failing[0] = False
    calls.clear()
    manifest = build_tubelex_index(
        snapshot,
        base,
        tmp_path / "rebuilt",
        tmp_path / "references",
        **options,
    )
    assert calls == ["明日は市場へ行きます"]
    assert read_json(manifest)["stats"]["boundary-cache-hits"] == 1
    verify_tubelex_index(tmp_path / "rebuilt", tmp_path / "references", deep=True)


def test_quote_context_before_a_storage_chunk_remains_authoritative(tmp_path):
    text = "彼は「" + "あ" * 4000 + "春。夏" + "い" * 1000 + "」と言いました。"
    db, _ = _build_vtt(tmp_path, f"WEBVTT\n\n00:00.000 --> 00:20.000\n{text}\n")
    assert search_tubelex_index(db, "春。夏")
    verify_tubelex_index(db.parent, tmp_path / "public", deep=True)


def test_packed_sentence_boundary_at_storage_overlap_is_not_lost(tmp_path):
    text = "あ" * 3593 + "春です。夏です。" + "い" * 1000
    db, _ = _build_vtt(tmp_path, f"WEBVTT\n\n00:00.000 --> 00:20.000\n{text}\n")
    assert search_tubelex_index(db, "春です。")
    assert search_tubelex_index(db, "春です。夏") == []
    verify_tubelex_index(db.parent, tmp_path / "public", deep=True)


def test_cli_boundary_cache_requires_a_model(tmp_path, capsys):
    base, _, _, _ = build_fixture(tmp_path)
    assert (
        main(
            [
                "build-tubelex",
                "--snapshot",
                str(tmp_path / "snapshot"),
                "--base-artifact",
                str(base),
                "--private-output",
                str(tmp_path / "new-index"),
                "--references-output",
                str(tmp_path / "new-references"),
                "--boundary-cache",
                str(tmp_path / "cache"),
            ]
        )
        == 2
    )
    assert "requires" in capsys.readouterr().err
    assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize("where", ["snapshot", "references", "model"])
def test_boundary_cache_cannot_modify_inputs_or_artifact_directories(tmp_path, where):
    base, _, _, _ = build_fixture(tmp_path)
    references = tmp_path / "new-references"
    model = tmp_path / "model"
    cache = {
        "snapshot": tmp_path / "snapshot/cache",
        "references": references / "cache",
        "model": model / "cache",
    }[where]
    with pytest.raises(DataError, match="separate"):
        build_tubelex_index(
            tmp_path / "snapshot",
            base,
            tmp_path / "new-index",
            references,
            ja_punct_model=model,
            boundary_cache=cache,
        )
    assert not cache.exists()


def test_boundary_cache_never_writes_an_entry_it_cannot_read(tmp_path, monkeypatch):
    from collections import Counter

    from manabi_sentence_db import tubelex_cache

    monkeypatch.setattr(tubelex_cache, "MAX_INPUT_BYTES", 50)
    segment = tubelex_cache.cached_segmenter(
        lambda text: [text],
        {"engine": "fixture"},
        tmp_path / "cache",
        Counter(),
    )
    with pytest.raises(DataError, match="budget"):
        segment("今日は市場へ行きます")
    assert list((tmp_path / "cache").iterdir()) == []


@pytest.mark.parametrize("query", ["読みました。明日", "。明"])
def test_cross_sentence_grams_are_excluded_from_candidate_indexes(tmp_path, monkeypatch, query):
    _, private, _, _ = build_fixture(tmp_path)
    monkeypatch.setattr(
        "manabi_sentence_db.tubelex_index._decode_text",
        lambda *args: pytest.fail("decoded an impossible cross-sentence candidate"),
    )
    assert search_tubelex_index(private / "citations.private.sqlite3", query) == []


@pytest.mark.parametrize("damage", ["build-options", "stream-metadata"])
def test_build_verifier_rejects_nonobject_metadata_cleanly(tmp_path, damage):
    from manabi_sentence_db.serialization import sha256_file

    _, private, public, private_path = build_fixture(tmp_path)
    if damage == "build-options":
        for path in [private_path, public / "manifest.json"]:
            manifest = read_json(path)
            manifest["options"] = []
            path.write_bytes(canonical_json(manifest))
    else:
        db = private / "citations.private.sqlite3"
        with closing(sqlite3.connect(db)) as database, database:
            database.execute("UPDATE streams SET metadata=?", (b"[]",))
        manifest = read_json(private_path)
        manifest["index_sha256"] = sha256_file(db)
        private_path.write_bytes(canonical_json(manifest))
    with pytest.raises(DataError, match="options|metadata"):
        verify_tubelex_index(private, public, deep=True)


def test_shared_cached_text_keeps_each_videos_original_timing(tmp_path, monkeypatch):
    listing, local = inputs(tmp_path)
    text = "今日は図書館で本を読みます"
    (local / f"{VIDEO}.ja.vtt").write_text(f"WEBVTT\n\n00:00.000 --> 00:03.000\n{text}\n")
    (local / f"{OTHER}.info.json").write_bytes(canonical_json(info(OTHER)))
    (local / f"{OTHER}.ja.vtt").write_text(f"WEBVTT\n\n00:10.000 --> 00:13.000\n{text}\n")
    snapshot = snapshot_tubelex(tmp_path / "snapshot", videos_csv=listing, captions_dir=local)
    calls = []

    def factory(*args, **kwargs):
        def segment(text):
            calls.append(text)
            return [text]

        return segment, {"engine": "fixture"}

    monkeypatch.setattr(
        "manabi_sentence_db.tubelex_boundaries.local_japanese_character_model", factory
    )
    base = tmp_path / "base.cc"
    base.write_bytes(b"CC base")
    manifest = build_tubelex_index(
        snapshot,
        base,
        tmp_path / "index",
        tmp_path / "references",
        ja_punct_model=tmp_path / "model",
        boundary_cache=tmp_path / "cache",
    )
    results = search_tubelex_index(tmp_path / "index/citations.private.sqlite3", "図書館")
    assert {r["native_id"].split(":")[0]: r["locator"]["start_seconds"] for r in results} == {
        VIDEO: 0.0,
        OTHER: 10.0,
    }
    assert calls == [text]
    assert read_json(manifest)["stats"]["boundary-cache-hits"] == 1
    verify_tubelex_index(tmp_path / "index", tmp_path / "references", deep=True)


def test_reference_inventory_includes_sentence_starting_inside_a_cue(tmp_path):
    vtt = """WEBVTT

00:00.000 --> 00:01.000
昨日は

00:01.000 --> 00:03.000
雨でした。今日は晴れです。明日も

00:03.000 --> 00:04.000
晴れるでしょう。
"""
    db, manifest = _build_vtt(tmp_path, vtt)
    with (tmp_path / "public/references.jsonl.zst").open("rb") as raw:
        with zstandard.ZstdDecompressor().stream_reader(raw) as decoded:
            exported = [json.loads(line) for line in decoded.read().splitlines()]
    expected = []
    for query in ["雨でした", "今日は晴れ", "晴れるでしょう"]:
        results = search_tubelex_index(db, query)
        assert len(results) == 1
        assert results[0] in exported
        expected.extend(results)
    assert len({r["id"] for r in expected}) == 3
    assert manifest["references"] == 3
    verify_tubelex_index(db.parent, tmp_path / "public", deep=True)


def test_caption_identifiers_are_ordinals_and_do_not_duplicate_source_text(tmp_path):
    source_identifier = "識別用の文章が字幕の識別子にも含まれています"
    vtt = f"WEBVTT\n\n{source_identifier}\n00:00.000 --> 00:02.000\n今日は晴れです。\n"
    cue = parse_vtt(vtt)[0]
    assert cue.origins[0].cue_ids == ("cue-1",)
    db, _ = _build_vtt(tmp_path, vtt)
    with closing(sqlite3.connect(db)) as connection:
        identifiers = [json.loads(r[0]) for r in connection.execute("SELECT cue_ids FROM origins")]
    assert identifiers == [["cue-1"]]
    assert source_identifier.encode() not in db.read_bytes()


def test_repeated_author_cue_ids_keep_distinct_source_ordinals():
    vtt = """WEBVTT

同じ識別子
00:00.000 --> 00:02.000
今日は晴れです。

同じ識別子
00:01.000 --> 00:03.000
今日は晴れです。
"""
    cues = parse_vtt(vtt)
    assert len(cues) == 1
    assert cues[0].origins[0].cue_ids == ("cue-1", "cue-2")


@pytest.mark.parametrize(
    "query", [None, 42, "今日は".encode(), "\ud800", "\udfff", "の\x7f", "の\x85"]
)
def test_invalid_literal_inputs_fail_as_controlled_errors_before_database_open(query):
    from pathlib import Path

    with pytest.raises(DataError):
        search_tubelex_index(Path("/does/not/exist.sqlite3"), query)


@pytest.mark.parametrize("limit", [True, False, 1.5, 250.0, "10", None])
def test_result_limit_requires_an_integer_before_database_open(limit):
    from pathlib import Path

    with pytest.raises(DataError):
        search_tubelex_index(Path("/does/not/exist.sqlite3"), "今日は", limit=limit)


def test_unicode_literal_search_matches_an_independent_sentence_oracle(tmp_path):
    import unicodedata

    from manabi_sentence_db.tubelex_index import TubelexReader

    # Explicit sentence boundaries are authored here rather than obtained from
    # the implementation's segmenter. Each cue has one truthful timing envelope.
    authored = [
        ["今日は図書館に行きます。", "明日は公園で待ちます。"],
        ["彼は「雨。晴れ」と言いました。"],
        ["今日はcaféでe\u0301clairを食べます。"],
        ["今日は🍵を飲みます。", "価格はＡＢＣで決まります。"],
        ["今日は𠮷田さんと話します。"],
        ['式はA+BまたはX"Yです。'],
        ["今日は Word2 と café を見ます。"],
    ]
    authored = [[unicodedata.normalize("NFC", text) for text in parts] for parts in authored]
    cues = [
        f"00:{i * 7:02}.000 --> 00:{i * 7 + 3:02}.000\n{''.join(parts)}"
        for i, parts in enumerate(authored)
    ]
    db, _ = _build_vtt(tmp_path, "WEBVTT\n\n" + "\n\n".join(cues) + "\n")
    queries = {
        text[a : a + width]
        for parts in authored
        for text in parts
        for width in range(1, 9)
        for a in range(len(text) - width + 1)
    }
    queries.update(
        ["ます。明日", "ます。価格", "🍵を飲みます。価格", "ABC", "Café", "𠮷田", "e\u0301clair"]
    )
    with TubelexReader(db) as reader:
        for query in sorted(queries):
            expected = {
                (float(i * 7), float(i * 7 + 3))
                for i, parts in enumerate(authored)
                if any(unicodedata.normalize("NFC", query) in text for text in parts)
            }
            actual = {
                (r["locator"]["start_seconds"], r["locator"]["end_seconds"])
                for r in reader.search(query)
            }
            assert actual == expected, repr(query)
    verify_tubelex_index(db.parent, tmp_path / "public", deep=True)


@pytest.mark.parametrize("label", ["NOTEBOOK", "STYLE-12", "REGION-12", "WEBVTT-12"])
def test_cue_identifiers_resembling_metadata_are_not_discarded(tmp_path, label):
    vtt = f"WEBVTT\n\n{label}\n00:00.000 --> 00:02.000\n今日は図書館へ行きます。\n"
    cues = parse_vtt(vtt)
    assert len(cues) == 1 and cues[0].text == "今日は図書館へ行きます。"
    assert cues[0].origins[0].cue_ids == ("cue-1",)
    db, _ = _build_vtt(tmp_path, vtt)
    assert search_tubelex_index(db, "図書館")


@pytest.mark.parametrize("header", ["WEBVTTBAD", "WEBVTT --> invalid"])
def test_malformed_webvtt_signature_is_not_treated_as_a_valid_header(header):
    with pytest.raises(DataError):
        parse_vtt(header + "\n\n00:00.000 --> 00:02.000\n今日は晴れです。\n")


def test_real_webvtt_comments_and_style_blocks_do_not_become_captions():
    vtt = """WEBVTT Japanese captions
Kind: captions
Language: ja

NOTE a comment with a timing-like line
00:00.000 --> 00:02.000
これはコメントの文章です。

STYLE
::cue { color: lime; }

REGION
id:main

cue-one
00:03.000 --> 00:05.000
今日は晴れです。
"""
    cues = parse_vtt(vtt)
    assert len(cues) == 1
    assert cues[0].text == "今日は晴れです。"
    assert cues[0].origins[0].cue_ids == ("cue-1",)


@pytest.mark.parametrize("label", ["STYLE", "REGION", "WEBVTT"])
def test_metadata_keywords_can_identify_later_timed_cues(label):
    vtt = (
        "WEBVTT\n\n00:00.000 --> 00:02.000\n最初の文章です。\n\n"
        f"{label}\n00:03.000 --> 00:05.000\n次の文章です。\n"
    )
    assert [c.text for c in parse_vtt(vtt)] == ["最初の文章です。", "次の文章です。"]


def test_missing_fourgram_rejects_real_trigram_candidates_without_decompression(tmp_path, monkeypatch):
    from manabi_sentence_db import tubelex_index

    text = "今日は東京大学で勉強します。明日は京大阪という店で会います。"
    db, _ = _build_vtt(tmp_path, f"WEBVTT\n\n00:00.000 --> 00:03.000\n{text}\n")
    with closing(sqlite3.connect(db)) as connection:
        assert connection.execute(
            'SELECT count(*) FROM substring WHERE substring MATCH ?', ('"東京大" AND "京大阪"',),
        ).fetchone()[0] == 1
    with tubelex_index.TubelexReader(db) as reader:
        with monkeypatch.context() as context:
            context.setattr(tubelex_index, "_decode_text", lambda _: pytest.fail("decoded impossible literal"))
            assert reader.search("東京大阪") == []
        assert reader.last_search_stats["global_literal_rejections"] == 1
        assert reader.last_search_stats["decoded_chunks"] == 0
        assert reader.search("東京大学")


def test_global_fourgrams_and_hash_collisions_are_not_accepted_as_literal_matches(tmp_path, monkeypatch):
    from manabi_sentence_db import tubelex_index

    # All fourgrams and trigrams exist; their ordering still has to be verified.
    text = "今日は東京大阪の店へ行きます。明日は京大阪京という店へ行きます。"
    db, _ = _build_vtt(tmp_path, f"WEBVTT\n\n00:00.000 --> 00:03.000\n{text}\n")
    with tubelex_index.TubelexReader(db) as reader:
        assert reader.search("東京大阪京") == []
        assert reader.last_search_stats["decoded_chunks"] == 1
    other = tmp_path / "collisions"
    other.mkdir()
    # A collision may keep an impossible candidate, but cannot create a hit.
    monkeypatch.setattr(tubelex_index, "_literal_keys", lambda _: {b"samehash"})
    db, _ = _build_vtt(other, f"WEBVTT\n\n00:00.000 --> 00:03.000\n{text}\n")
    assert search_tubelex_index(db, "東京大阪京") == []
    assert search_tubelex_index(db, "東京大阪")


def test_deep_verification_checks_complete_global_fourgram_coverage(tmp_path):
    from manabi_sentence_db.serialization import sha256_file

    _, private, references, _ = build_fixture(tmp_path)
    db = private / "citations.private.sqlite3"
    with closing(sqlite3.connect(db)) as connection, connection:
        bits = bytearray(connection.execute("SELECT bits FROM literal_filter").fetchone()[0])
        point = next(i for i, byte in enumerate(bits) if byte)
        bits[point] &= bits[point] - 1
        connection.execute("UPDATE literal_filter SET bits=?", (bytes(bits),))
    path = private / "manifest.private.json"
    manifest = read_json(path)
    manifest["index_sha256"] = sha256_file(db)
    manifest["stats"]["literal-filter-set-bits"] -= 1
    path.write_bytes(canonical_json(manifest))
    with pytest.raises(DataError, match="literal-filter"):
        verify_tubelex_index(private, references, deep=True)


@pytest.mark.parametrize("target", ["snapshot", "model", "references"])
def test_outputs_cannot_modify_snapshot_or_model_directories(tmp_path, target):
    listing, local = inputs(tmp_path)
    manifest = snapshot_tubelex(tmp_path / "snapshot", videos_csv=listing, captions_dir=local)
    base = tmp_path / "base.zip"
    base.write_bytes(b"authored base")
    model = tmp_path / "model"
    model.mkdir()
    (model / "sentinel").write_bytes(b"keep unchanged")
    private, references = tmp_path / "index", tmp_path / "references"
    options = {}
    if target == "snapshot":
        private = manifest.parent / "index"
    elif target == "model":
        private = model / "index"
        options["ja_punct_model"] = model
    else:
        references = manifest.parent / "references"
    with pytest.raises(DataError, match="separate.*inputs"):
        build_tubelex_index(manifest, base, private, references, **options)
    assert not private.exists() and not references.exists()
    assert (model / "sentinel").read_bytes() == b"keep unchanged"


def test_sat_pytorch_version_changes_prediction_cache_identity(tmp_path, monkeypatch):
    from manabi_sentence_db import tubelex_index
    from manabi_sentence_db.tubelex_cache import cached_segmenter

    model, tokenizer = tmp_path / "model", tmp_path / "tokenizer"
    model.mkdir()
    tokenizer.mkdir()
    (model / "model.safetensors").write_bytes(b"authored weights")
    (tokenizer / "tokenizer.json").write_bytes(b"authored tokenizer")
    calls, stats = [], Counter()
    for torch_version in ["first", "second"]:
        monkeypatch.setattr(tubelex_index, "version", lambda name: torch_version if name == "torch" else "test")
        _, _, identity = tubelex_index._describe_sat(model, tokenizer)

        def predict(text):
            calls.append(torch_version)
            return [text]

        segment = cached_segmenter(predict, identity, tmp_path / "cache", stats)
        assert segment("今日は図書館で本を読みます") == ["今日は図書館で本を読みます"]
    assert calls == ["first", "second"]
    assert stats["boundary-cache-misses"] == 2
