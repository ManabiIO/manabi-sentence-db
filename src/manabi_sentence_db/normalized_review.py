"""Bounded assistant review packets; these are not corpus validation receipts."""

import os
import zipfile
from pathlib import Path

import zstandard

from .licenses import validate_rights
from .normalized_database import _check_text, _manifest, _rows
from .review_sampling import TopicReviewSampler, _string
from .serialization import DataError, canonical_json, sha256_file


def _signature(path):
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def build_topic_review(archives: list[Path], topics_by_work: dict[str, str], output: Path,
                       *, archive_sha256: dict[str, str], seed: str, per_topic: int = 10):
    """Write a deterministic Zstandard JSON packet after two bounded streaming passes.

    Expected ZIP hashes bind every input. Only occurrence members and selected
    archives' work/sentence members are checked, not the whole normalized corpus.
    """
    if not archives or not isinstance(topics_by_work, dict) or not topics_by_work:
        raise DataError("Archives and work topic mapping must be nonempty")
    for work, topic in topics_by_work.items():
        _string(work, "work ID")
        _string(topic, "topic")
    sampler = TopicReviewSampler(sorted(set(topics_by_work.values())), seed=seed,
                                 per_topic=per_topic)
    paths = [Path(path).resolve(strict=True) for path in archives]
    if any(not path.is_file() for path in paths):
        raise DataError("Review inputs must be regular files")
    names = [path.name for path in paths]
    if len(set(names)) != len(names):
        raise DataError("Review archive basenames must be unique")
    if not isinstance(archive_sha256, dict) or set(archive_sha256) != set(names):
        raise DataError("Expected archive SHA-256 keys must bind every input basename")
    if any(not isinstance(value, str) or len(value) != 64
           or any(char not in "0123456789abcdef" for char in value)
           for value in archive_sha256.values()):
        raise DataError("Invalid expected archive SHA-256")
    output = Path(output).absolute()
    if output != output.resolve() or not output.parent.is_dir():
        raise DataError("Use a canonical existing output parent outside symlinks")
    if output.exists() or output.is_symlink():
        raise DataError("Choose a fresh review output path")
    paths.sort(key=lambda path: path.name)
    signatures = {path: _signature(path) for path in paths}
    inputs = []
    for path in paths:
        if sha256_file(path) != archive_sha256[path.name]:
            raise DataError("Expected archive checksum differs: " + path.name)
        with zipfile.ZipFile(path) as archive:
            manifest = _manifest(archive)
            inputs.append({"archive": path.name, "sha256": archive_sha256[path.name],
                           "build_id": manifest.get("build_id")})
            for row in _rows(archive, "occurrences", manifest):
                work = row.get("work_id")
                if not isinstance(work, str) or work not in topics_by_work:
                    raise DataError("Missing topic mapping for occurrence work")
                sampler.add(topics_by_work[work], row.get("sentence_id"), work, path.name)
    samples = sampler.results()
    candidates = [candidate for group in samples.values() for candidate in group]
    records = {}
    for path in paths:
        selected = [candidate for candidate in candidates if candidate.archive == path.name]
        if not selected:
            continue
        works, sentences = {}, {}
        work_ids = {candidate.work_id for candidate in selected}
        sentence_ids = {candidate.sentence_id for candidate in selected}
        with zipfile.ZipFile(path) as archive:
            manifest = _manifest(archive)
            for table, wanted, retained in (("works", work_ids, works),
                                            ("sentences", sentence_ids, sentences)):
                for row in _rows(archive, table, manifest):
                    identity = row.get("id")
                    if identity not in wanted:
                        continue
                    if identity in retained:
                        raise DataError("Duplicate sampled " + table + " identity")
                    if table == "works":
                        validate_rights(row, source_url_key="url")
                    else:
                        _check_text(row, sentence=True)
                    retained[identity] = row
                if retained.keys() != wanted:
                    raise DataError("Missing sampled " + table + " identity")
        records[path.name] = (works, sentences)
    cases = [{"topic": candidate.topic, "archive": candidate.archive,
              "work": records[candidate.archive][0][candidate.work_id],
              "sentence": records[candidate.archive][1][candidate.sentence_id]}
             for candidate in candidates]
    packet = {"schema_version": 1, "kind": "normalized-topic-review", "seed": seed,
              "assistant_only": True, "human_review": False, "review_pending": True,
              "inputs": inputs, "sampling": {
                  "algorithm": "sha256-bottom-k-topic-sentence-v1", "per_topic": per_topic,
                  "identity": ["topic", "sentence_id"],
                  "citation_tiebreak": ["archive", "work_id"],
                  "validation_scope": "expected-input-hashes-and-sampled-records"},
              "cases": cases}
    compressed = zstandard.ZstdCompressor(write_checksum=True).compress(canonical_json(packet) + b"\n")
    for path in paths:
        if _signature(path) != signatures[path]:
            raise DataError("Review input changed during scanning: " + path.name)
    if output != output.resolve() or not output.parent.is_dir():
        raise DataError("Review output parent changed")
    with output.open("xb") as stream:
        stream.write(compressed)
        stream.flush()
        os.fsync(stream.fileno())
    return {"output": str(output), "sha256": sha256_file(output), "size_bytes": len(compressed),
            "by_topic": {topic: len(group) for topic, group in samples.items()},
            "assistant_only": True, "human_review": False, "review_pending": True}
