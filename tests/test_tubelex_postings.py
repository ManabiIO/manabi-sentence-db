"""Checksums and internally consistent FTS trees do not prove posting completeness."""
import sqlite3

import pytest
from test_tubelex import build_fixture

from manabi_sentence_db.serialization import DataError, read_json, sha256_file, write_json
from manabi_sentence_db.tubelex_index import _candidate_spans, _decode_text, verify_tubelex_index


@pytest.mark.parametrize("table,damage", [
    ("short_substring", "missing"), ("substring", "missing"),
    ("short_substring", "extra"), ("substring", "extra"),
])
def test_deep_verification_binds_all_postings_after_rehash(tmp_path, table, damage):
    _, private, public, manifest_path = build_fixture(tmp_path)
    path = private / "citations.private.sqlite3"
    with sqlite3.connect(path) as db:
        rowid, blob, bitmap = db.execute("SELECT id,text_zstd,boundary_bits FROM chunks LIMIT 1").fetchone()
        text = _decode_text(blob)
        parts = _candidate_spans(text, bitmap)
        if table == "short_substring":
            terms = {"s" + part[i:i+w].encode().hex() for part in parts
                     for w in (1, 2) for i in range(len(part)-w+1)}
            original = " ".join(sorted(terms))
            if damage == "missing":
                # Retain the old verifier's first-character probe.
                terms.remove(next(t for t in sorted(terms) if len(t) > 7))
            else:
                terms.add("s" + "偽語".encode().hex())
            replacement, column = " ".join(sorted(terms)), "terms"
        else:
            original = "\x1f".join(parts)
            replacement = original[:1] if damage == "missing" else original + "偽単語"
            column = "text"
        db.execute(f"INSERT INTO {table}({table},rowid,{column}) VALUES ('delete',?,?)", (rowid, original))
        db.execute(f"INSERT INTO {table}(rowid,{column}) VALUES (?,?)", (rowid, replacement))
        db.execute(f"INSERT INTO {table}({table}) VALUES ('optimize')")
        db.execute(f"INSERT INTO {table}({table},rank) VALUES ('integrity-check',0)")
    manifest = read_json(manifest_path)
    manifest["index_sha256"] = sha256_file(path)
    write_json(manifest_path, manifest)
    assert verify_tubelex_index(private, public)["deep"] is False
    with pytest.raises(DataError, match="postings"):
        verify_tubelex_index(private, public, deep=True)


@pytest.mark.parametrize("text", ["AÄaä CAFÉ café", "𠀀😊𠮷🙂日本語", "ガガとéとé", "短。次！終？", "一", "Ab"])
def test_complete_postings_match_sqlite_unicode_and_short_chunks(tmp_path, text):
    from test_tubelex import _build_vtt
    db, _ = _build_vtt(tmp_path, f"WEBVTT\n\n00:00.000 --> 00:03.000\n{text}\n")
    result = verify_tubelex_index(db.parent, tmp_path / "public", deep=True)
    assert result["posting_verification"] == "complete-term-document-v1"


def test_deep_verification_rejects_terms_reassigned_to_other_chunks(tmp_path):
    from test_tubelex import _build_vtt
    text = "図書館" + "あ" * 5000 + "公園の本"
    db_path, _ = _build_vtt(tmp_path, f"WEBVTT\n\n00:00.000 --> 00:10.000\n{text}\n")
    with sqlite3.connect(db_path) as db:
        documents = [(row, "\x1f".join(_candidate_spans(_decode_text(blob), bitmap)))
                     for row, blob, bitmap in db.execute("SELECT id,text_zstd,boundary_bits FROM chunks")]
        assert len(documents) == 2
        for row, value in documents:
            db.execute("INSERT INTO substring(substring,rowid,text) VALUES('delete',?,?)", (row, value))
        for (row, _), (_, value) in zip(documents, reversed(documents)):
            db.execute("INSERT INTO substring(rowid,text) VALUES(?,?)", (row, value))
        db.execute("INSERT INTO substring(substring) VALUES('optimize')")
        db.execute("INSERT INTO substring(substring,rank) VALUES('integrity-check',0)")
    manifest = read_json(db_path.parent / "manifest.private.json")
    manifest["index_sha256"] = sha256_file(db_path)
    write_json(db_path.parent / "manifest.private.json", manifest)
    with pytest.raises(DataError, match="postings"):
        verify_tubelex_index(db_path.parent, tmp_path / "public", deep=True)


@pytest.mark.parametrize("text", [
    "今日は図書館へ行きます。あ",
    "今日は図書館へ行きます。" + "あ" * 4081 + "終。明日は公園へ行きます。",
], ids=["single-character-tail", "storage-chunk-edge"])
def test_boundary_before_last_chunk_character_builds_and_keeps_exact_search(tmp_path, text):
    from test_tubelex import _build_vtt

    from manabi_sentence_db.tubelex_index import TubelexReader

    path, _ = _build_vtt(tmp_path, f"WEBVTT\n\n00:00.000 --> 00:20.000\n{text}\n")
    assert verify_tubelex_index(path.parent, tmp_path / "public", deep=True)["deep"]
    with TubelexReader(path) as reader:
        assert reader.search("図書館")
        assert reader.search("す。あ") == []
        assert reader.search("終。明") == []
        if text.endswith("あ"):
            assert reader.search("あ")


@pytest.mark.parametrize("length", [2, 8, 9, 4096])
def test_boundary_bitmap_accepts_last_interior_offset_and_rejects_end(length):
    from manabi_sentence_db.tubelex_index import _decode_boundary_bitmap

    valid = (1 << (length - 1)).to_bytes((length + 7) // 8, "little")
    assert _decode_boundary_bitmap(valid, length) == 1 << (length - 1)
    invalid = (1 << length).to_bytes((length + 8) // 8, "little")
    with pytest.raises(DataError, match="boundary bitmap"):
        _decode_boundary_bitmap(invalid, length)
