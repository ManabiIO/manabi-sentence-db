from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

import yaml

from .build import build_corpus, iter_records, verify_build
from .database import build_database
from .package import package_build
from .serialization import DataError
from .snapshot import SnapshotError, create_snapshot, verify_snapshot
from .transport import snapshot_pack, snapshot_unpack
from .validation import load_source, validator


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Build attributed sentence corpora from explicit immutable snapshots"
    )
    root.add_argument("--sources-dir", type=Path, default=Path("sources"))
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("sources", help="List reviewed source configurations (offline)")
    commands.add_parser("validate-config", help="Validate source catalog and schemas (offline)")
    snapshot = commands.add_parser(
        "snapshot", help="Explicitly acquire redistributable corpus source data"
    )
    snapshot.add_argument("--source", required=True, help="Source ID, or all")
    snapshot.add_argument("--output", type=Path, required=True)
    snapshot.add_argument("--mode", choices=["sample", "full"], default="sample")
    snapshot.add_argument("--date", help="Exact Wikimedia export date, YYYY-MM-DD")
    snapshot.add_argument("--title", action="append", dest="titles")
    snapshot.add_argument(
        "--translations", action="append", default=[], help="Optional Tatoeba target language (en)"
    )
    snapshot.add_argument("--max-files", type=int)
    snapshot.add_argument(
        "--refresh",
        action="store_true",
        help="Check upstream again, preserving the existing snapshot",
    )
    snapshot.add_argument("--user-agent", default=os.getenv("SENTENCE_DB_USER_AGENT"))
    verify = commands.add_parser(
        "verify-snapshot", help="Verify a snapshot's metadata and every raw file offline"
    )
    verify.add_argument("--snapshot", type=Path, required=True)
    pack = commands.add_parser(
        "snapshot-pack", help="Split a snapshot into verified transport assets offline"
    )
    pack.add_argument("--snapshot", type=Path, required=True)
    pack.add_argument("--output", type=Path, required=True)
    pack.add_argument("--part-bytes", type=int, default=1024**3)
    unpack = commands.add_parser(
        "snapshot-unpack", help="Restore locally downloaded snapshot assets offline"
    )
    unpack.add_argument("--bundle", type=Path, required=True)
    unpack.add_argument("--output", type=Path, required=True)
    select = commands.add_parser(
        "select-wikimedia", help="Sample balanced Japanese article metadata from cached snapshots"
    )
    select.add_argument("--snapshot", type=Path, required=True)
    select.add_argument("--output", type=Path, required=True)
    select.add_argument("--per-topic", type=int, default=1000)
    select.add_argument("--general", type=int, default=2000)
    select.add_argument("--seed", default="")
    select.add_argument("--progress", action="store_true")
    build = commands.add_parser(
        "build", help="Compile verified snapshots into canonical JSONL/YAML offline"
    )
    build.add_argument("--snapshot", type=Path, action="append", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--format", choices=["jsonl", "yaml"], default="jsonl")
    build.add_argument("--shard-compression", choices=("none", "zstd"), default="none")
    build.add_argument("--progress", action="store_true", help="Write build progress to stderr")
    build.add_argument("--shard-bytes", type=int, default=4 * 1024**2)
    build.add_argument("--shard-documents", type=int, default=500)
    build.add_argument(
        "--max-documents", type=int, help="Limit documents per source; output is labeled sample"
    )
    build.add_argument("--exclude-flag", action="append", default=[])
    build.add_argument("--document-selection", type=Path,
                       help="Snapshot-bound Wikimedia page-ID allowlist JSON")
    build.add_argument(
        "--include-sexual-content",
        action="store_true",
        help="Retain flagged text; never implies review/safety",
    )
    database = commands.add_parser("build-db", help="Compile validated YAML to SQLite offline")
    database.add_argument("--build", type=Path, required=True)
    database.add_argument("--output", type=Path, required=True)
    database.add_argument("--source", help="Optional source partition")
    normalized_db = commands.add_parser(
        "build-normalized-db", help="Compile v2 normalized JSONL ZIP to relational SQLite"
    )
    normalized_db.add_argument("--archive", type=Path, required=True)
    normalized_db.add_argument("--output", type=Path, required=True)
    normalized_export = commands.add_parser(
        "export-normalized", help="Export all or explicitly selected complete works offline"
    )
    normalized_export.add_argument("--build", type=Path, required=True)
    normalized_export.add_argument("--output", type=Path, required=True)
    normalized_export.add_argument("--source")
    normalized_export.add_argument("--work-selection", type=Path,
                                   help="JSON work allowlist bound to the exact build ID")
    package = commands.add_parser(
        "package", help="Package YAML ZIPs and per-source SQLite.zst files offline"
    )
    package.add_argument("--build", type=Path, required=True)
    package.add_argument("--output", type=Path, required=True)
    package.add_argument("--archive-bytes", type=int, default=128 * 1024**2)
    package.add_argument("--part-bytes", type=int, default=1024**3)
    package.add_argument("--yaml-only", action="store_true")
    check = commands.add_parser(
        "verify-build", help="Verify all artifacts and validate canonical records offline"
    )
    check.add_argument("--build", type=Path, required=True)
    coverage = commands.add_parser(
        "vocabulary-coverage", help="Compare analyzed vocabulary breadth and marginal source coverage offline"
    )
    coverage.add_argument("--archive", type=Path, action="append", required=True)
    coverage.add_argument("--analysis", type=Path, required=True)
    coverage.add_argument("--analyzer", required=True, help="Exact tokenizer/lexicon configuration identity")
    coverage.add_argument("--metadata", type=Path, help="Optional checked analysis-export sidecar")
    coverage.add_argument("--baseline-source", action="append", default=[])
    coverage.add_argument("--target-vocabulary", type=Path, help="Optional JSON array of target lemmas")
    coverage.add_argument("--output", type=Path, required=True)
    tubelex_snapshot = commands.add_parser(
        "snapshot-tubelex", help="Opt-in Japanese manual captions; PRIVATE compressed snapshot"
    )
    tubelex_snapshot.add_argument("--output", type=Path, required=True)
    tubelex_snapshot.add_argument("--videos-csv", type=Path, help="Local TUBELEX videos-ja.csv")
    tubelex_snapshot.add_argument("--captions-dir", type=Path, help="Offline .info.json/.ja.vtt import")
    tubelex_snapshot.add_argument("--cache", type=Path, help="Reusable PRIVATE compressed caption cache")
    tubelex_snapshot.add_argument("--max-videos", type=int, default=10)
    tubelex_snapshot.add_argument("--offset", type=int, default=0, help="Start after N eligible video IDs")
    tubelex_snapshot.add_argument("--delay", type=float, default=5)
    tubelex_snapshot.add_argument("--yt-dlp", default="yt-dlp", help="Installed metadata extractor")
    tubelex_snapshot.add_argument("--user-agent", default=os.getenv("SENTENCE_DB_USER_AGENT"))
    external = commands.add_parser(
        "build-tubelex", help="Offline private citation sidecar bound to a prebuilt corpus release"
    )
    external.add_argument("--snapshot", type=Path, required=True)
    external.add_argument("--base-artifact", type=Path, required=True)
    external.add_argument("--private-output", type=Path, required=True)
    external.add_argument("--references-output", type=Path, required=True)
    external.add_argument("--boundary-mode", choices=["hybrid", "punctuation"], default="hybrid")
    external.add_argument("--pause-ms", type=int, default=800)
    external.add_argument("--sat-model", type=Path, help="Optional local SaT model directory")
    external.add_argument("--sat-tokenizer", type=Path, help="Local tokenizer directory for SaT")
    external.add_argument("--sat-threshold", type=float, default=0.25, help="Explicit boundary threshold; 0.25 for SaT SM")
    external.add_argument("--ja-punct-model", type=Path, help="Optional local four-label Japanese character ONNX model")
    external.add_argument("--ja-punct-threshold", type=float, default=0.5)
    external.add_argument("--boundary-cache", type=Path,
                          help="Optional PRIVATE reusable model-offset cache; one writer per cache")
    external_search = commands.add_parser(
        "search-tubelex", help="Search PRIVATE literal substring index; emit only external references"
    )
    search_target = external_search.add_mutually_exclusive_group(required=True)
    search_target.add_argument("--index", type=Path)
    search_target.add_argument("--collection", type=Path, help="Completed private shard collection")
    external_search.add_argument("--base-artifact", type=Path, help="Check base release compatibility")
    external_search.add_argument("--query", required=True)
    external_search.add_argument("--limit", type=int, default=250)
    external_search.add_argument("--selection", choices=["first", "diverse"], default="first",
                                 help="Collection only: opt-in video diversity; shares the full work/deadline budget")
    external_search.add_argument("--timeout-ms", type=int, default=1000,
                                 help="Query budget in milliseconds (1..60000); no partial results")
    external_search.add_argument("--max-decoded-chunks", type=int, default=2048)
    external_search.add_argument("--stats", action="store_true", help="Text-free work counters on stderr")
    external_verify = commands.add_parser(
        "verify-tubelex", help="Verify a closed private citation index and its text-free export offline"
    )
    external_verify.add_argument("--private-build", type=Path, required=True)
    external_verify.add_argument("--references", type=Path, required=True)
    external_verify.add_argument("--base-artifact", type=Path)
    external_verify.add_argument("--deep", action="store_true", help="Check coverage, complete postings and cue-derived reference inventory")
    batch = commands.add_parser("build-tubelex-batch", help="Resume immutable private snapshot shards")
    batch.add_argument("--snapshot", type=Path, action="append", required=True)
    batch.add_argument("--base-artifact", type=Path, required=True)
    batch.add_argument("--output", type=Path, required=True)
    batch.add_argument("--boundary-mode", choices=["hybrid", "punctuation"], default="hybrid")
    batch.add_argument("--pause-ms", type=int, default=800)
    batch.add_argument("--sat-model", type=Path)
    batch.add_argument("--sat-tokenizer", type=Path)
    batch.add_argument("--sat-threshold", type=float, default=0.25)
    batch.add_argument("--ja-punct-model", type=Path)
    batch.add_argument("--ja-punct-threshold", type=float, default=0.5)
    batch.add_argument("--boundary-cache", type=Path)
    collection_verify = commands.add_parser("verify-tubelex-collection")
    collection_verify.add_argument("--collection", type=Path, required=True)
    collection_verify.add_argument("--base-artifact", type=Path)
    collection_verify.add_argument("--deep", action="store_true")
    review = commands.add_parser("prepare-tubelex-review", help="Compressed private blind review packet")
    review.add_argument("--snapshot", type=Path, action="append", required=True)
    review.add_argument("--output", type=Path, required=True)
    review.add_argument("--per-video", type=int, default=4)
    review.add_argument("--window-chars", type=int, default=200)
    review.add_argument("--max-videos", type=int, default=20, help="Uniformly sample at most this many videos")
    review.add_argument("--exclude-packet", type=Path, action="append", default=[])
    review.add_argument("--exclude-scope", choices=["videos", "windows"], default="videos")
    playback = commands.add_parser("prepare-tubelex-playback-review", help="Text-free clips for independent listening review")
    playback.add_argument("--references", type=Path, action="append", required=True)
    playback.add_argument("--output", type=Path, required=True)
    playback.add_argument("--max-cases", type=int, default=40)
    playback_score = commands.add_parser("score-tubelex-playback-review", help="Score separately declared listening labels")
    playback_score.add_argument("--packet", type=Path, required=True)
    playback_score.add_argument("--labels", type=Path, required=True)
    score = commands.add_parser("score-tubelex-review", help="Score independent private boundary labels")
    score.add_argument("--packet", type=Path, required=True)
    score.add_argument("--labels", type=Path, required=True)
    score.add_argument("--ja-punct-model", type=Path)
    score.add_argument("--ja-punct-threshold", type=float, default=0.5)
    score.add_argument("--pause-ms", type=int, default=800)
    score.add_argument("--legacy-punctuation-policy", action="store_true")
    demo = commands.add_parser(
        "demo", help="Run the complete pipeline with original synthetic fixtures, offline"
    )
    demo.add_argument("--output", type=Path, default=Path("build/demo"))
    return root


def _sources(directory: Path) -> dict:
    paths = sorted(directory.glob("*.yaml"))
    if not paths:
        raise DataError(f"No source configurations found in {directory}")
    sources = {}
    for path in paths:
        source = load_source(path)
        if source["id"] in sources:
            raise DataError(f"Duplicate source ID: {source['id']}")
        sources[source["id"]] = source
    return sources


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        match args.command:
            case "sources" | "validate-config":
                sources = _sources(args.sources_dir)
                validator("record")
                if args.command == "sources":
                    for source in sources.values():
                        print(
                            f"{source['id']}\t{source['language']}\t{source['license']['id']}\t{source['title']}"
                        )
                else:
                    print(f"Validated {len(sources)} source configurations and schemas")
            case "snapshot":
                sources = _sources(args.sources_dir)
                if args.source != "all" and args.source not in sources:
                    raise DataError(f"Unknown source: {args.source}")
                if args.source == "all" and args.titles:
                    raise DataError("--title requires a single Wikimedia source")
                selected = (
                    list(sources.values()) if args.source == "all" else [sources[args.source]]
                )
                failures = []
                for source in selected:
                    if (
                        args.source == "all"
                        and args.mode == "sample"
                        and source["adapter"] != "wikimedia"
                    ):
                        print(
                            f"Skipping {source['id']}: samples use Wikimedia's page API; bulk datasets need --mode full",
                            file=sys.stderr,
                        )
                        continue
                    try:
                        manifest = create_snapshot(
                            source,
                            args.output / source["id"] if args.source == "all" else args.output,
                            mode=args.mode,
                            date=args.date
                            if args.source != "all" or source["adapter"] == "wikimedia"
                            else None,
                            titles=args.titles,
                            max_files=args.max_files
                            if args.source != "all" or source["adapter"] == "wikimedia"
                            else None,
                            refresh=args.refresh,
                            user_agent=args.user_agent,
                            translations=args.translations
                            if args.source != "all" or source["adapter"] == "tatoeba"
                            else None,
                        )
                        print(manifest)
                    except SnapshotError as exc:
                        if args.source != "all":
                            raise
                        failures.append(source["id"])
                        print(f"{source['id']}: {exc}", file=sys.stderr)
                if failures:
                    raise DataError(
                        f"Sources failed: {', '.join(failures)}. Completed snapshots remain usable."
                    )
            case "verify-snapshot":
                manifest = verify_snapshot(args.snapshot)
                print(manifest["snapshot_id"])
            case "snapshot-pack":
                print(snapshot_pack(args.snapshot, args.output, args.part_bytes))
            case "snapshot-unpack":
                print(snapshot_unpack(args.bundle, args.output))
            case "select-wikimedia":
                from .wikimedia_selection import select_wikimedia_documents

                print(select_wikimedia_documents(
                    args.snapshot, args.output, per_topic=args.per_topic, general=args.general,
                    seed=args.seed,
                    progress=(lambda message: print(message, file=sys.stderr, flush=True))
                    if args.progress else None,
                ))
            case "build":
                excluded = set(args.exclude_flag)
                if not args.include_sexual_content:
                    excluded.add("sexual-content")
                print(
                    build_corpus(
                        args.snapshot,
                        args.output,
                        shard_bytes=args.shard_bytes,
                        shard_compression=args.shard_compression,
                        shard_documents=args.shard_documents,
                        excluded_flags=excluded,
                        max_documents=args.max_documents,
                        record_format=args.format,
                        document_selection=args.document_selection,
                        progress=(lambda message: print(message, file=sys.stderr, flush=True))
                        if args.progress else None,
                    )
                )
            case "build-normalized-db":
                from .normalized_database import build_normalized_database

                print(build_normalized_database(args.archive, args.output))
            case "export-normalized":
                from .normalized import export_normalized
                from .serialization import read_json

                selection = None
                if args.work_selection is not None:
                    if args.work_selection.stat().st_size > 16 * 1024**2:
                        raise DataError("Work selection exceeds 16 MiB")
                    selection = read_json(args.work_selection)
                print(export_normalized(args.build, args.output, source_id=args.source,
                                        work_selection=selection))
            case "build-db":
                print(build_database(args.build, args.output, source_id=args.source))
            case "package":
                print(
                    package_build(
                        args.build,
                        args.output,
                        archive_bytes=args.archive_bytes,
                        part_bytes=args.part_bytes,
                        include_sqlite=not args.yaml_only,
                    )
                )
            case "verify-build":
                catalog = verify_build(args.build)
                count = sum(1 for _ in iter_records(args.build, catalog))
                print(f"Verified {count} canonical documents in {catalog['build_id']}")
            case "vocabulary-coverage":
                from .coverage import vocabulary_coverage

                print(vocabulary_coverage(
                    args.archive, args.analysis, args.output, analyzer=args.analyzer,
                    baseline_sources=args.baseline_source, target_vocabulary=args.target_vocabulary,
                    metadata=args.metadata,
                ))
            case "demo":
                from .demo import create_demo_snapshot

                if args.output.exists():
                    raise DataError("Demo output already exists; choose a new --output directory")
                manifest = create_demo_snapshot(args.output / "snapshot")
                build_corpus([manifest], args.output / "corpus")
                build_database(args.output / "corpus", args.output / "corpus.sqlite3")
                print(package_build(args.output / "corpus", args.output / "release"))
            case "snapshot-tubelex":
                from .tubelex import snapshot_tubelex

                options = {"user_agent": args.user_agent} if args.user_agent else {}
                print(snapshot_tubelex(
                    args.output, videos_csv=args.videos_csv, captions_dir=args.captions_dir,
                    cache=args.cache, max_videos=args.max_videos, delay=args.delay,
                    yt_dlp=args.yt_dlp, **options,
                    offset=args.offset,
                ))
            case "build-tubelex":
                from .tubelex_index import build_tubelex_index

                print(build_tubelex_index(
                    args.snapshot, args.base_artifact, args.private_output, args.references_output,
                    boundary_mode=args.boundary_mode, pause_ms=args.pause_ms,
                    sat_model=args.sat_model, sat_tokenizer=args.sat_tokenizer,
                    sat_threshold=args.sat_threshold,
                    ja_punct_model=args.ja_punct_model, ja_punct_threshold=args.ja_punct_threshold,
                    boundary_cache=args.boundary_cache,
                ))
            case "search-tubelex":
                from .tubelex_index import TubelexReader

                if args.selection != "first" and not args.collection:
                    raise DataError("Diverse selection requires --collection")
                if args.collection:
                    from .tubelex_batch import TubelexCollectionReader

                    reader = TubelexCollectionReader(
                        args.collection, base_artifact=args.base_artifact, timeout_ms=args.timeout_ms,
                        max_decoded_chunks=args.max_decoded_chunks,
                    )
                else:
                    reader = TubelexReader(
                        args.index, base_artifact=args.base_artifact, timeout_ms=args.timeout_ms,
                        max_decoded_chunks=args.max_decoded_chunks,
                    )
                with reader:
                    selection = {"selection": args.selection} if args.collection else {}
                    records = reader.search(args.query, limit=args.limit, **selection)
                    print(json.dumps(records, ensure_ascii=False))
                    if args.stats:
                        print(json.dumps(reader.last_search_stats, sort_keys=True), file=sys.stderr)
            case "verify-tubelex":
                from .tubelex_index import verify_tubelex_index

                print(json.dumps(verify_tubelex_index(
                    args.private_build, args.references, base_artifact=args.base_artifact, deep=args.deep,
                ), sort_keys=True))
            case "build-tubelex-batch":
                from .tubelex_batch import build_tubelex_collection

                print(build_tubelex_collection(
                    args.snapshot, args.base_artifact, args.output,
                    boundary_mode=args.boundary_mode, pause_ms=args.pause_ms,
                    sat_model=args.sat_model, sat_tokenizer=args.sat_tokenizer,
                    sat_threshold=args.sat_threshold, ja_punct_model=args.ja_punct_model,
                    ja_punct_threshold=args.ja_punct_threshold, boundary_cache=args.boundary_cache,
                ))
            case "verify-tubelex-collection":
                from .tubelex_batch import verify_tubelex_collection

                print(json.dumps(verify_tubelex_collection(
                    args.collection, base_artifact=args.base_artifact, deep=args.deep,
                ), sort_keys=True))
            case "prepare-tubelex-review":
                from .tubelex_review import prepare_tubelex_review

                print(json.dumps(prepare_tubelex_review(
                    args.snapshot, args.output, per_video=args.per_video, window_chars=args.window_chars,
                    max_videos=args.max_videos, exclude_packets=args.exclude_packet,
                    exclude_scope=args.exclude_scope,
                ), sort_keys=True))
            case "prepare-tubelex-playback-review":
                from .tubelex_review import prepare_tubelex_playback_review

                print(json.dumps(prepare_tubelex_playback_review(
                    args.references, args.output, max_cases=args.max_cases,
                ), sort_keys=True))
            case "score-tubelex-playback-review":
                from .tubelex_review import score_tubelex_playback_review

                print(json.dumps(score_tubelex_playback_review(args.packet, args.labels), sort_keys=True))
            case "score-tubelex-review":
                from .tubelex_review import score_tubelex_review

                segment = None
                if args.ja_punct_model:
                    from .tubelex_boundaries import local_japanese_character_model

                    segment, _ = local_japanese_character_model(
                        args.ja_punct_model, threshold=args.ja_punct_threshold,
                    )
                print(json.dumps(score_tubelex_review(
                    args.packet, args.labels, segment=segment, pause_ms=args.pause_ms,
                    refine_punctuated=not args.legacy_punctuation_policy,
                ), sort_keys=True))
        return 0
    except (DataError, SnapshotError, OSError, sqlite3.Error, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

