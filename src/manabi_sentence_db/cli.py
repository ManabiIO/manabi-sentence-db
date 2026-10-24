from __future__ import annotations

import argparse
import json
import os
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
        "snapshot", help="Explicitly acquire source data; the only upstream network command"
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
    build = commands.add_parser(
        "build", help="Compile verified snapshots into canonical JSONL/YAML offline"
    )
    build.add_argument("--snapshot", type=Path, action="append", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--format", choices=["jsonl", "yaml"], default="jsonl")
    build.add_argument("--shard-bytes", type=int, default=4 * 1024**2)
    build.add_argument("--shard-documents", type=int, default=500)
    build.add_argument(
        "--max-documents", type=int, help="Limit documents per source; output is labeled sample"
    )
    build.add_argument("--exclude-flag", action="append", default=[])
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
            case "build":
                excluded = set(args.exclude_flag)
                if not args.include_sexual_content:
                    excluded.add("sexual-content")
                print(
                    build_corpus(
                        args.snapshot,
                        args.output,
                        shard_bytes=args.shard_bytes,
                        shard_documents=args.shard_documents,
                        excluded_flags=excluded,
                        max_documents=args.max_documents,
                        record_format=args.format,
                    )
                )
            case "build-normalized-db":
                from .normalized_database import build_normalized_database

                print(build_normalized_database(args.archive, args.output))
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
        return 0
    except (DataError, SnapshotError, OSError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

