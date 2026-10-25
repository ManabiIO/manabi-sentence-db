"""Diverse scans must bound all result bookkeeping, including deduplication."""
import hashlib
import random

from test_tubelex import _build_vtt

from manabi_sentence_db import tubelex_index as index
from manabi_sentence_db.tubelex_batch import _DiverseReferences


def exhaustive_selection(records, query, limit):
    seen, counts, ranked = set(), {}, []
    for record in records:
        if record["id"] in seen:
            continue
        seen.add(record["id"])
        video = record["native_id"].split(":")[0]
        ordinal = counts.get(video, 0)
        counts[video] = ordinal + 1
        order = int.from_bytes(hashlib.sha256((query + "\0" + video).encode()).digest(), "big")
        ranked.append(((ordinal, order, int.from_bytes(video.encode(), "big")), record))
    return [record for _, record in sorted(ranked, key=lambda pair: pair[0])[:limit]]


def test_diverse_scan_bounds_deduplication_by_result_cap(tmp_path, monkeypatch):
    def timestamp(seconds):
        return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}.000"

    vtt = "WEBVTT\n\n" + "\n\n".join(
        f"{timestamp(n * 4)} --> {timestamp(n * 4 + 3)}\n今日は図書館へ行きます。今日は本を読みます。"
        for n in range(120)
    )
    path, _ = _build_vtt(tmp_path, vtt)
    observed_sizes = []
    original = index._match_reference

    def measured(*args, **kwargs):
        observed_sizes.append(len(kwargs["seen_refs"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(index, "_match_reference", measured)
    pool = _DiverseReferences("今日は", 3)
    with index.TubelexReader(path) as reader:
        assert index._search_database(reader._database, "今日は", 3, 1000, collector=pool) == []
        assert len(observed_sizes) >= 240  # Includes repeated same-cue matches.
        assert max(observed_sizes) <= 3
        # The exhaustive first-match path is independent of the diverse pool.
        monkeypatch.setattr(index, "_match_reference", original)
        assert pool.results() == reader.search("今日は", limit=3)


def test_bounded_diversity_matches_exhaustive_deduplication_after_evictions():
    rng = random.Random(20261025)
    for case in range(1000):
        query, limit = str(case), rng.randint(1, 25)
        records = []
        for number in range(rng.randint(1, 40)):
            video = f"{number:011}"
            for clip in range(rng.randint(1, 20)):
                record = {"id": f"r{number}-{clip}", "native_id": f"{video}:{clip}:999"}
                records.extend([record] * rng.randint(1, 4))
        rng.shuffle(records)
        pool = _DiverseReferences(query, limit)
        for record in records:
            pool.add(record)
            assert len(pool.ids) == len(pool.heap) <= limit
            assert sum(pool.counts.values()) == len(pool.heap)
        assert pool.results() == exhaustive_selection(records, query, limit), case


def test_query_reads_stream_metadata_once_across_repeated_matches_and_chunks(tmp_path):
    path, _ = _build_vtt(tmp_path, "WEBVTT\n\n00:00.000 --> 00:03.000\n" +
                         "今日は図書館で本を読みます。" * 800 + "\n")
    statements = []
    with index.TubelexReader(path, timeout_ms=10000) as reader:
        reader._database.set_trace_callback(statements.append)
        pool = _DiverseReferences("今日は", 3)
        index._search_database(reader._database, "今日は", 3, 10000, collector=pool)
    metadata_reads = [sql for sql in statements if sql.startswith("SELECT video_id,metadata,eligibility FROM streams")]
    assert len(metadata_reads) == 1


def test_origin_range_uses_one_statement_and_rejects_missing_alignment(tmp_path):
    import pytest

    from manabi_sentence_db.serialization import DataError

    path, _ = _build_vtt(tmp_path, "WEBVTT\n\n00:00.000 --> 00:03.000\n今日は図書館へ行きます。\n\n"
                         "00:03.000 --> 00:06.000\n明日は公園へ行きます。\n")
    statements = []
    with index.TubelexReader(path) as reader:
        db = reader._database
        stream_id = db.execute("SELECT id FROM streams LIMIT 1").fetchone()[0]
        expected = db.execute("SELECT start,end,start_ms,end_ms FROM origins WHERE stream_id=? ORDER BY start", (stream_id,)).fetchall()
        db.set_trace_callback(statements.append)
        assert index._origins(db, stream_id, 2, expected[-1][1]) == expected
        assert len(statements) == 1
        with pytest.raises(DataError, match="alignment"):
            index._origins(db, stream_id + 100, 0, 1)
