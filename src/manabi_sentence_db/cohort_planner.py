"""Metadata-only complete-work planning; does not read source ZIPs or sentence text."""

import collections
import hashlib
import json
import sqlite3
import stat
from contextlib import closing
from pathlib import Path

from .serialization import DataError

MAX_SELECTED_WORKS = 80000


def readonly(path):
    connection = sqlite3.connect(Path(path).resolve(strict=True).as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA cache_size=-2048")
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute("BEGIN")
    return connection


def plan(inventory, consumer, occurrence_budget, prior_ids=()):
    if (
        isinstance(occurrence_budget, bool)
        or not isinstance(occurrence_budget, int)
        or occurrence_budget <= 0
    ):
        raise DataError("occurrence budget must be a positive integer")
    if not isinstance(prior_ids, (list, tuple, set)):
        raise DataError("prior IDs must be a collection of work-ID strings")
    excluded = {_text(value, "prior work ID", 256) for value in prior_ids}
    excluded.update(
        _text(row[0], "consumer work ID", 256) for row in consumer.execute("SELECT id FROM works")
    )
    queues = collections.defaultdict(collections.deque)
    builds = {}
    considered = 0
    seen = set()
    for identity, archive, build, topic, priority, existing, kept in inventory.execute(
        "SELECT id,archive,build,topic,priority,existing,kept FROM works ORDER BY topic,priority,id"
    ):
        _text(identity, "work ID", 256)
        _text(archive, "archive")
        _text(build, "build ID")
        _text(topic, "topic")
        _text(priority, "priority")
        if identity in seen:
            raise DataError("duplicate inventory work ID: " + identity)
        seen.add(identity)
        if type(existing) is not int or existing not in (0, 1):
            raise DataError("existing must be integer 0 or 1")
        if type(kept) is not int or kept < 0:
            raise DataError("kept must be a nonnegative integer")
        if archive in builds and builds[archive] != build:
            raise DataError("conflicting build IDs for archive: " + archive)
        builds[archive] = build
        # Inventory flags describe an older consumer; current IDs are authoritative.
        if identity in excluded or kept <= 0:
            continue
        considered += 1
        queues[topic].append(
            dict(
                id=identity,
                archive=archive,
                build_id=build,
                topic=topic,
                cached_v11_kept_occurrences=kept,
            )
        )
    chunks, chunk, estimate, per_archive = [], [], 0, collections.Counter()
    while queues:
        for topic in sorted(tuple(queues)):
            row = queues[topic].popleft()
            if not queues[topic]:
                del queues[topic]
            size = row["cached_v11_kept_occurrences"]
            if chunk and (
                estimate + size > occurrence_budget
                or per_archive[row["archive"]] >= MAX_SELECTED_WORKS
            ):
                chunks.append(chunk)
                chunk, estimate, per_archive = [], 0, collections.Counter()
            chunk.append(row)
            estimate += size
            per_archive[row["archive"]] += 1
    if chunk:
        chunks.append(chunk)
    assert sum(map(len, chunks)) == considered
    return chunks


def emit(chunks, output, budget, receipts=None):
    output = Path(output)
    parent = output.parent.resolve(strict=True)
    if output.parent.absolute() != parent or output.name in ("", ".", ".."):
        raise DataError("output parent must be canonical and contain no symlinks")
    if output.exists() or output.is_symlink():
        raise DataError("output must be a fresh directory")
    output = parent / output.name
    output.mkdir(mode=0o700)
    manifest = dict(
        contract="metadata-only-whole-work-cohort-plan-v1",
        input_receipts=receipts,
        occurrence_budget=budget,
        estimate_policy="cached wikipedia-example-quality-v11",
        v12_refinement_pending=True,
        native_eligibility_pending=True,
        counts_are_occurrences_not_distinct_or_novel_texts=True,
        no_source_text=True,
        total_works=sum(map(len, chunks)),
        chunks=[],
    )
    for index, rows in enumerate(chunks, 1):
        directory = output / ("chunk-%04d" % index)
        directory.mkdir()
        archives = collections.defaultdict(list)
        for row in rows:
            archives[row["archive"]].append(row)
        entries = []
        for ordinal, (archive, group) in enumerate(sorted(archives.items()), 1):
            filename = "archive-%04d.selection.json" % ordinal
            selection = dict(
                schema_version=1,
                build_id=group[0]["build_id"],
                work_ids=sorted(r["id"] for r in group),
            )
            assert len(selection["work_ids"]) <= MAX_SELECTED_WORKS
            (directory / filename).write_text(
                json.dumps(selection, ensure_ascii=False, indent=2) + "\n"
            )
            entries.append(
                dict(
                    archive=archive,
                    selection=filename,
                    works=len(group),
                    build_id=selection["build_id"],
                )
            )
        manifest["chunks"].append(
            dict(
                directory=directory.name,
                works=len(rows),
                cached_v11_kept_occurrences=sum(r["cached_v11_kept_occurrences"] for r in rows),
                by_topic=dict(sorted(collections.Counter(r["topic"] for r in rows).items())),
                oversized_single_work=len(rows) == 1
                and rows[0]["cached_v11_kept_occurrences"] > budget,
                archives=entries,
                ordered_work_ids=[r["id"] for r in rows],
            )
        )
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def _text(value, field, limit=None):
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(ord(char) < 32 for char in value)
        or (limit is not None and len(value) > limit)
    ):
        raise DataError(f"{field} must be a nonempty valid string")
    return value


def input_signature(path):
    """Cheap receipt including WAL state; never hash the large SQLite inputs."""

    def signature(candidate):
        if not candidate.exists():
            return None
        value = candidate.stat()
        if not stat.S_ISREG(value.st_mode):
            raise DataError("input must be a regular file: " + str(candidate))
        return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns]

    return {
        "path": str(path),
        "stat": signature(path),
        "wal_stat": signature(Path(str(path) + "-wal")),
    }


def load_prior(path):
    path = Path(path).resolve(strict=True)
    before = input_signature(path)
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise DataError("prior selection must be an object")
        if "work_ids" in value:
            if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
                raise DataError("prior allowlist requires schema version 1")
            _text(value.get("build_id"), "prior build ID")
            ids = value["work_ids"]
            if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_SELECTED_WORKS:
                raise DataError("prior work_ids must be an array of 1..80000 IDs")
        else:
            selected = value.get("selected")
            if not isinstance(selected, list) or any(not isinstance(r, dict) for r in selected):
                raise DataError("prior selected must be an array of objects")
            ids = [row.get("id") for row in selected]
        ids = [_text(identity, "prior work ID", 256) for identity in ids]
        if len(set(ids)) != len(ids):
            raise DataError("duplicate prior work IDs")
    except (ValueError, TypeError, KeyError) as error:
        raise DataError("invalid prior selection: " + str(error)) from error
    if before != input_signature(path):
        raise DataError("prior selection changed during planning")
    return ids, {**before, "sha256": hashlib.sha256(raw).hexdigest()}


def plan_cohorts(inventory, consumer, occurrence_budget, output, prior_selections=()):
    """Plan complete works using metadata snapshots, then emit archive-bound allowlists.

    The budget is a per-chunk operational estimate, never an admission quota.
    Cached v11 counts require v12 refinement and native eligibility verification.
    """
    inventory = Path(inventory).resolve(strict=True)
    consumer = Path(consumer).resolve(strict=True)
    signatures = [input_signature(path) for path in (inventory, consumer)]
    prior_ids, receipts = set(), []
    for path in prior_selections:
        ids, receipt = load_prior(path)
        prior_ids.update(ids)
        receipts.append(receipt)
    try:
        with closing(readonly(inventory)) as inv, closing(readonly(consumer)) as current:
            chunks = plan(inv, current, occurrence_budget, prior_ids)
            inv.commit()
            current.commit()
    except sqlite3.Error as error:
        raise DataError("invalid cohort metadata database: " + str(error)) from error
    if signatures != [input_signature(path) for path in (inventory, consumer)]:
        raise DataError("input changed during planning; no output written")
    for receipt in receipts:
        if input_signature(Path(receipt["path"])) != {
            k: v for k, v in receipt.items() if k != "sha256"
        }:
            raise DataError("prior selection changed during planning; no output written")
    return emit(
        chunks,
        output,
        occurrence_budget,
        {"inventory": signatures[0], "consumer": signatures[1], "prior_selections": receipts},
    )
