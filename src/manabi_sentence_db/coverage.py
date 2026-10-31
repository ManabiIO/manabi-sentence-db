"""Offline vocabulary breadth measurement using an explicitly identified analyzer."""

import os
import re
import sqlite3
import tempfile
import unicodedata
import zipfile
from contextlib import closing
from pathlib import Path

from .normalized_database import _check_text, _manifest, _rows
from .serialization import DataError, parse_json, read_json, sha256_file, write_json

SENTENCE_ID = re.compile(r"s_[a-f0-9]{64}\Z")
MAX_ANALYSIS_ROW_BYTES = 1024 * 1024


def _lemma(value):
    if (not isinstance(value, str) or not value or len(value) > 256
            or unicodedata.normalize("NFC", value) != value
            or any(unicodedata.category(c) == "Cc" for c in value)):
        raise DataError("Vocabulary lemmas must be nonempty NFC strings of at most 256 characters")
    return value


def _ingest_archive(db, path, archive_index, claimed_sources):
    current_sources = set()
    with zipfile.ZipFile(path) as archive:
        manifest = _manifest(archive)
        for row in _rows(archive, "works", manifest):
            source_id = row.get("source_id")
            if not isinstance(source_id, str) or not source_id:
                raise DataError("Missing corpus source identity")
            current_sources.add(source_id)
            db.execute("INSERT INTO works VALUES (?,?,?)", (row["id"], source_id, archive_index))
        if claimed_sources.intersection(current_sources):
            raise DataError("Use exactly one corpus archive per source, not overlapping snapshots")
        claimed_sources.update(current_sources)
        for row in _rows(archive, "sentences", manifest):
            _check_text(row, sentence=True)
            db.execute("INSERT OR IGNORE INTO sentences VALUES (?)", (row["id"],))
            db.execute("INSERT INTO members VALUES (?,?)", (archive_index, row["id"]))
        for row in _rows(archive, "occurrences", manifest):
            work = db.execute("SELECT source,archive FROM works WHERE id=?", (row["work_id"],)).fetchone()
            if work is None or work[1] != archive_index or not db.execute(
                "SELECT 1 FROM members WHERE archive=? AND sentence=?",
                (archive_index, row["sentence_id"]),
            ).fetchone():
                raise DataError("Occurrence refers to a missing work or sentence in its archive")
            db.execute("INSERT OR IGNORE INTO source_sentences VALUES (?,?)",
                       (work[0], row["sentence_id"]))
        # Consume the remaining members too; their counts and digests must verify.
        for table in ("translations", "references"):
            for _ in _rows(archive, table, manifest):
                pass
        return {"path": str(path), "sha256": sha256_file(path), "build_id": manifest["build_id"],
                "scope": manifest["scope"], "sources": sorted(current_sources)}


def vocabulary_coverage(
    archives: list[Path], analysis: Path, output: Path, *, analyzer: str,
    baseline_sources=(), target_vocabulary: Path | None = None, metadata: Path | None = None,
) -> Path:
    """Compare distinct lemmas and marginal coverage without mistaking missing analysis for zero.

    Analysis rows are ``{sentence_id, lemmas: [NFC strings]}``. This module does
    not tokenize text or estimate JLPT. Homographs remain as distinguished (or
    conflated) by the explicitly supplied analyzer's lemma identities.
    """
    if not analyzer.strip() or not archives:
        raise DataError("Corpus archives and an explicit analyzer identity are required")
    if output.exists() or output.is_symlink():
        raise DataError("Choose a new coverage report path")
    baseline_sources = sorted(set(baseline_sources))
    analysis_digest = sha256_file(analysis)
    if metadata is not None and metadata.stat().st_size > 16 * 1024**2:
        raise DataError("Oversized analysis metadata")
    provenance = read_json(metadata) if metadata else None
    if provenance is not None and (
        not isinstance(provenance, dict) or provenance.get("schema_version") != 1
        or provenance.get("analyzer") != analyzer or provenance.get("sha256") != analysis_digest
    ):
        raise DataError("Analysis metadata identity or SHA-256 disagrees with the supplied export")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".coverage-", dir=output.parent) as temporary:
        with closing(sqlite3.connect(Path(temporary) / "coverage.sqlite")) as db:
            db.executescript("""
                CREATE TABLE works(id TEXT PRIMARY KEY, source TEXT NOT NULL, archive INTEGER);
                CREATE TABLE sentences(id TEXT PRIMARY KEY);
                CREATE TABLE members(archive INTEGER,sentence TEXT,PRIMARY KEY(archive,sentence));
                CREATE TABLE source_sentences(source TEXT,sentence TEXT,PRIMARY KEY(source,sentence));
                CREATE INDEX source_sentence_id ON source_sentences(sentence);
                CREATE TABLE analyzed(sentence TEXT PRIMARY KEY);
                CREATE TABLE lemmas(sentence TEXT,lemma TEXT,PRIMARY KEY(sentence,lemma));
                CREATE INDEX lemma_text ON lemmas(lemma);
                CREATE TABLE baseline_sources(source TEXT PRIMARY KEY);
                CREATE TABLE baseline_lemmas(lemma TEXT PRIMARY KEY);
                CREATE TABLE targets(lemma TEXT PRIMARY KEY);
            """)
            sources = set()
            try:
                corpus_inputs = [_ingest_archive(db, path, index, sources)
                                 for index, path in enumerate(archives)]
                if not set(baseline_sources) <= sources:
                    raise DataError("Baseline source does not occur in the supplied corpora")
                rows = 0
                with analysis.open("rb") as stream:
                    while line := stream.readline(MAX_ANALYSIS_ROW_BYTES + 1):
                        if len(line) > MAX_ANALYSIS_ROW_BYTES:
                            raise DataError("Oversized analysis row")
                        row = parse_json(line)
                        if (not isinstance(row, dict) or set(row) != {"sentence_id", "lemmas"}
                                or not isinstance(row["sentence_id"], str)
                                or SENTENCE_ID.fullmatch(row["sentence_id"]) is None
                                or not isinstance(row["lemmas"], list) or len(row["lemmas"]) > 2000):
                            raise DataError("Invalid vocabulary analysis row")
                        db.execute("INSERT INTO analyzed VALUES (?)", (row["sentence_id"],))
                        db.executemany("INSERT INTO lemmas VALUES (?,?)",
                                       [(row["sentence_id"], word)
                                        for word in sorted({_lemma(v) for v in row["lemmas"]})])
                        rows += 1
                if provenance is not None and provenance.get("exported_sentence_count") != rows:
                    raise DataError("Analysis metadata count disagrees with the export")
                if sha256_file(analysis) != analysis_digest:
                    raise DataError("Vocabulary analysis changed while it was being read")
                targets = []
                if target_vocabulary is not None:
                    if target_vocabulary.stat().st_size > 32 * 1024**2:
                        raise DataError("Oversized target vocabulary")
                    targets = read_json(target_vocabulary)
                    if not isinstance(targets, list) or len(targets) > 1_000_000:
                        raise DataError("Target vocabulary must be a JSON array of lemmas")
                    targets = sorted({_lemma(v) for v in targets})
                    if not targets:
                        raise DataError("Target vocabulary must not be empty")
                    db.executemany("INSERT INTO targets VALUES (?)", [(v,) for v in targets])
                db.executemany("INSERT INTO baseline_sources VALUES (?)", [(v,) for v in baseline_sources])
                db.execute("INSERT INTO baseline_lemmas SELECT DISTINCT l.lemma FROM lemmas l "
                           "JOIN source_sentences s ON s.sentence=l.sentence "
                           "JOIN baseline_sources b ON b.source=s.source")
            except sqlite3.IntegrityError as error:
                raise DataError("Duplicate corpus or analysis identity") from error

            def scalar(query, args=()):
                return db.execute(query, args).fetchone()[0]

            comparisons = []
            for source in sorted(sources):
                total = scalar("SELECT COUNT(*) FROM source_sentences WHERE source=?", (source,))
                analyzed = scalar("SELECT COUNT(*) FROM source_sentences s JOIN analyzed a "
                                  "ON a.sentence=s.sentence WHERE s.source=?", (source,))
                shared = scalar(
                    "SELECT COUNT(*) FROM source_sentences s WHERE s.source=? AND EXISTS "
                    "(SELECT 1 FROM source_sentences b JOIN baseline_sources bs "
                    "ON bs.source=b.source WHERE b.sentence=s.sentence)", (source,)
                )
                lexical_join = (" FROM lemmas l JOIN source_sentences s "
                                "ON s.sentence=l.sentence WHERE s.source=?")
                unique = scalar("SELECT COUNT(DISTINCT l.lemma)" + lexical_join, (source,))
                novel = scalar("SELECT COUNT(DISTINCT l.lemma)" + lexical_join
                               + " AND NOT EXISTS (SELECT 1 FROM baseline_lemmas b WHERE b.lemma=l.lemma)",
                               (source,))
                target_seen = scalar("SELECT COUNT(DISTINCT l.lemma)" + lexical_join
                                     + " AND EXISTS (SELECT 1 FROM targets t WHERE t.lemma=l.lemma)",
                                     (source,)) if targets else None
                novel_target = scalar("SELECT COUNT(DISTINCT l.lemma)" + lexical_join
                                      + " AND EXISTS (SELECT 1 FROM targets t WHERE t.lemma=l.lemma)"
                                      + " AND NOT EXISTS (SELECT 1 FROM baseline_lemmas b WHERE b.lemma=l.lemma)",
                                      (source,)) if targets else None
                comparisons.append({"source_id": source, "unique_sentences": total,
                                    "sentences_shared_with_baseline": shared,
                                    "novel_sentences_vs_baseline": total-shared,
                                    "analyzed_sentences": analyzed, "missing_analysis": total-analyzed,
                                    "analysis_coverage": analyzed/total if total else None,
                                    "unique_lemmas": unique, "novel_lemmas_vs_baseline": novel,
                                    "target_lemmas_seen": target_seen,
                                    "novel_target_lemmas_vs_baseline": novel_target,
                                    "target_vocabulary_coverage": target_seen/len(targets) if targets else None})
            combined_target = scalar(
                "SELECT COUNT(*) FROM targets t WHERE EXISTS "
                "(SELECT 1 FROM lemmas l JOIN source_sentences s ON s.sentence=l.sentence "
                "WHERE l.lemma=t.lemma)"
            ) if targets else None
            baseline_target = scalar(
                "SELECT COUNT(*) FROM targets t JOIN baseline_lemmas b ON b.lemma=t.lemma"
            ) if targets else None
            report = {
                "schema_version": 1, "kind": "vocabulary-coverage", "analyzer": analyzer,
                "analysis_sha256": analysis_digest, "analysis_metadata": provenance,
                "corpora": corpus_inputs, "baseline_sources": baseline_sources,
                "analysis_rows": rows,
                "analysis_rows_outside_corpora": scalar("SELECT COUNT(*) FROM analyzed a WHERE NOT EXISTS "
                                                        "(SELECT 1 FROM sentences s WHERE s.id=a.sentence)"),
                "unique_sentences": scalar("SELECT COUNT(*) FROM sentences"),
                "target_vocabulary_sha256": sha256_file(target_vocabulary) if target_vocabulary else None,
                "target_vocabulary_size": len(targets) if targets else None,
                "combined_target_lemmas_seen": combined_target,
                "combined_target_vocabulary_coverage": combined_target/len(targets) if targets else None,
                "baseline_target_lemmas_seen": baseline_target,
                "baseline_target_vocabulary_coverage": baseline_target/len(targets) if targets else None,
                "sources": comparisons,
                "interpretation": "Coverage uses supplied analysis only; missing analysis is unknown. "
                                  "Sentence novelty is exact normalized text identity, independent "
                                  "of analysis availability; it does not establish semantic novelty. "
                                  "Marginal vocabulary is against the fixed union of baseline sources, "
                                  "not a sentence-count ranking or proof of independent, natural examples.",
            }
            staged = Path(temporary) / "report.json"
            write_json(staged, report)
            os.replace(staged, output)
    return output
