"""Tighten Wikipedia admission using verified compressed canonical records.

This is a one-way filter, not re-extraction: previously rejected text cannot be
recovered. Retained text, public IDs, rights and source positions stay intact.
"""

import logging
import os
import re
import shutil
import tempfile
import uuid
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .serialization import (
    DataError,
    canonical_json,
    digest_json,
    read_json,
    safe_relative,
    sha256_file,
    write_json,
)
from .validation import validate_record
from .wikipedia_quality import WIKIPEDIA_QUALITY_VERSION, assess_wikipedia_sentence

PARENT_PATH = "lineage/parent.catalog.json"


def verify_refinement(catalog, artifact):
    """Validate the optional parent receipt without requiring the old shards."""
    receipt = catalog["options"].get("refinement")
    parent_entry = catalog.get("refinement_parent")
    if receipt is None and parent_entry is None:
        return
    if (not isinstance(receipt, dict)
            or set(receipt) != {"policy", "parent_build_id", "parent_catalog_sha256"}
            or not isinstance(receipt["policy"], str)
            or not re.fullmatch(r"wikipedia-example-quality-v[1-9][0-9]*", receipt["policy"])
            or not isinstance(parent_entry, dict) or parent_entry.get("path") != PARENT_PATH
            or parent_entry.get("sha256") != receipt["parent_catalog_sha256"]):
        raise DataError("Invalid Wikipedia refinement receipt")
    parent = read_json(artifact(parent_entry))
    try:
        parent_id = "build_" + digest_json({
            "processor": parent["processor_sha256"], "runtime": parent["runtime"],
            "options": parent["options"],
            "snapshots": [row["snapshot_id"] for row in parent["snapshots"]],
        })[:32]
        ignored = {"record_format", "shard_compression", "refinement"}
        if (parent["build_id"] != parent_id or receipt["parent_build_id"] != parent_id
                or parent["schema_version"] != catalog["schema_version"]
                or parent["snapshots"] != catalog["snapshots"]
                or parent["scope"] != catalog["scope"]
                or [row["source"] for row in parent["sources"]]
                != [row["source"] for row in catalog["sources"]]
                or parent["licenses"]["sha256"] != catalog["licenses"]["sha256"]
                or {key: value for key, value in parent["options"].items() if key not in ignored}
                != {key: value for key, value in catalog["options"].items() if key not in ignored}):
            raise DataError("Refinement parent/source/selection binding differs")
    except (KeyError, TypeError, ValueError) as exc:
        raise DataError("Invalid refinement parent catalog binding") from exc


def _retire(stage):
    if not stage.exists():
        return
    try:
        trash = Path.home() / ".Trash"
        if trash.resolve() != trash:
            raise DataError("Use a canonical Trash destination")
        trash.mkdir(exist_ok=True)
        shutil.move(str(stage), str(trash / (stage.name + "-" + uuid.uuid4().hex)))
    except (OSError, DataError):
        logging.getLogger(__name__).warning("Preserved failed refinement at %s", stage, exc_info=True)


def refine_wikipedia(build, output, *, progress=None):
    """Recheck retained Wikipedia sentences offline, with compressed staging."""
    from . import PROCESSOR_VERSION
    from .build import (
        ShardWriter,
        _git_dirty,
        _git_revision,
        _processor_fingerprint,
        _runtime_versions,
        iter_records,
        verify_build,
    )
    build, output = Path(build).absolute(), Path(output).absolute()
    if build.resolve(strict=True) != build or not build.is_dir():
        raise DataError("Use a canonical input build directory outside symlinks")
    if (output.exists() or output.is_symlink()
            or output.parent.resolve(strict=True) != output.parent):
        raise DataError("Use a fresh output outside symlinks with an existing parent")
    notify = progress or (lambda _: None)
    notify("Verifying canonical input; raw snapshots are not required")
    original = verify_build(build)
    parent_sha = sha256_file(build / "catalog.json")
    processor, runtime = _processor_fingerprint(), _runtime_versions()
    catalog = deepcopy(original)
    catalog["options"].update(record_format="jsonl", shard_compression="zstd", refinement={
        "policy": WIKIPEDIA_QUALITY_VERSION, "parent_build_id": original["build_id"],
        "parent_catalog_sha256": parent_sha,
    })
    sources = {row["source"]["id"]: row for row in catalog["sources"]}
    stage = Path(tempfile.mkdtemp(prefix="." + output.name + "-", dir=output.parent))
    writers = {}
    shard_order, collected = [], {}

    def collect(source_id):
        writer = writers[source_id]
        shard_order.extend(writer.entries[collected.get(source_id, 0):])
        collected[source_id] = len(writer.entries)

    try:
        input_totals, kept = Counter(), Counter()
        active = None
        with (stage / "documents.jsonl").open("xb") as index:
            for record in iter_records(build, original):
                source_id = record["source_id"]
                stats = sources[source_id]["statistics"]
                input_totals[(source_id, "documents")] += 1
                input_totals[(source_id, "sentences")] += len(record.get("sentences", []))
                if (record["kind"] == "document" and source_id.startswith("wikipedia-")
                        and record["language"].split("-", 1)[0] == "ja"):
                    accepted = []
                    for sentence in record["sentences"]:
                        reason, tags = assess_wikipedia_sentence(sentence["text"])
                        stats["refinement:checked"] = stats.get("refinement:checked", 0) + 1
                        if reason:
                            stats["rejected:" + reason] = stats.get("rejected:" + reason, 0) + 1
                            stats["sentences"] -= 1
                            stats["translations"] = stats.get("translations", 0) - len(sentence["translations"])
                        else:
                            accepted.append(dict(sentence, tags=sorted(set(sentence["tags"]) | set(tags))))
                    if not accepted:
                        stats["documents"] -= 1
                        stats["documents_without_sentences"] = stats.get("documents_without_sentences", 0) + 1
                        continue
                    record = dict(record, sentences=accepted,
                                  transformations=list(record["transformations"]))
                    if WIKIPEDIA_QUALITY_VERSION not in record["transformations"]:
                        record["transformations"].append(WIKIPEDIA_QUALITY_VERSION)
                validate_record(record)
                # Valid canonical catalogs may interleave sources. Close at
                # transitions so shard order and document-index order agree.
                if active is not None and active != source_id:
                    writers[active].close()
                    collect(active)
                active = source_id
                if source_id not in writers:
                    writers[source_id] = ShardWriter(stage, source_id, record["language"],
                        catalog["options"]["shard_bytes"], catalog["options"]["shard_documents"],
                        "jsonl", "zstd")
                shard, position = writers[source_id].append(record)
                collect(source_id)
                index.write(canonical_json({key: record[key] for key in
                    ("id", "source_id", "native_id", "title")} | {"shard": shard, "position": position}) + b"\n")
                kept["documents"] += 1
                if kept["documents"] % 500 == 0:
                    notify(f"refined {kept['documents']} retained documents")
        for row in original["sources"]:
            for key in ("documents", "sentences"):
                if input_totals[(row["source"]["id"], key)] != row["statistics"].get(key, 0):
                    raise DataError("Original per-source counts differ; refuse to repair the input")
        for source_id, writer in writers.items():
            writer.close()
            collect(source_id)
        if not kept["documents"]:
            raise DataError("No usable documents remain after Wikipedia refinement")
        for entry in [*catalog["snapshots"], catalog["licenses"]]:
            name = entry.get("manifest", entry.get("path"))
            target = safe_relative(stage, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise DataError("Refinement artifact paths collide")
            shutil.copyfile(safe_relative(build, name), target)
        parent = stage / PARENT_PATH
        parent.parent.mkdir(parents=True)
        shutil.copyfile(build / "catalog.json", parent)
        catalog["refinement_parent"] = {"path": PARENT_PATH, "sha256": parent_sha}
        catalog["shards"] = shard_order
        catalog["document_index"]["sha256"] = sha256_file(stage / "documents.jsonl")
        catalog["statistics"] = dict(sum((Counter(row["statistics"]) for row in catalog["sources"]), Counter()))
        catalog.update(processor_version=PROCESSOR_VERSION, processor_sha256=processor,
                       runtime=runtime, python_version=runtime["python"], sqlite_version=runtime["sqlite"],
                       git_revision=_git_revision(), git_dirty=_git_dirty(),
                       built_at=datetime.now(timezone.utc).isoformat())
        catalog["build_id"] = "build_" + digest_json({
            "processor": processor, "runtime": runtime, "options": catalog["options"],
            "snapshots": [row["snapshot_id"] for row in catalog["snapshots"]],
        })[:32]
        write_json(stage / "catalog.json", catalog)
        verify_build(stage)
        for _ in iter_records(stage, catalog):
            pass
        if (sha256_file(build / "catalog.json") != parent_sha
                or verify_build(build) != original or _processor_fingerprint() != processor):
            raise DataError("Input or refinement implementation changed during processing")
        # Refuse a destination occupied during validation.
        if output.exists() or output.is_symlink():
            raise DataError("Refinement output appeared during processing")
        os.rename(stage, output)
        return output / "catalog.json"
    finally:
        for writer in writers.values():
            if writer.handle is not None:
                try:
                    writer.handle.close()
                except OSError:
                    logging.getLogger(__name__).warning("Could not close refinement shard", exc_info=True)
                writer.handle = None
        _retire(stage)
