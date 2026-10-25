"""Offline cold/rebuild/resume profiles; output is private, captions stay compressed.

Run from the repository with its Python environment (or the provisioned model
runtime), with --snapshot, --base-artifact and a fresh --output directory.
Nested timings report inclusive and exclusive time; do not sum inclusive phases.
"""
from __future__ import annotations

import argparse
import functools
import json
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from manabi_sentence_db import (
    tubelex,
    tubelex_batch,
    tubelex_boundaries,
    tubelex_cache,
    tubelex_index,
)
from manabi_sentence_db.serialization import canonical_json, read_json


class Timings:
    def __init__(self):
        self.phases, self.stack = {}, []

    @contextmanager
    def measure(self, phase):
        frame = [time.perf_counter_ns(), 0]
        self.stack.append(frame)
        try:
            yield
        finally:
            elapsed = time.perf_counter_ns() - frame[0]
            self.stack.pop()
            if self.stack:
                self.stack[-1][1] += elapsed
            row = self.phases.setdefault(phase, Counter())
            row.update(calls=1, inclusive_ns=elapsed, exclusive_ns=elapsed - frame[1])


@contextmanager
def instrument():
    active = [None]
    originals = []

    def wrap(module, name, phase, factory=False):
        original = getattr(module, name)

        @functools.wraps(original)
        def call(*args, **kwargs):
            if active[0] is None:
                return original(*args, **kwargs)
            with active[0].measure(phase):
                result = original(*args, **kwargs)
            if factory:
                segment, identity = result

                def infer(text):
                    with active[0].measure("boundary_inference"):
                        return list(segment(text))
                return infer, identity
            return result

        originals.append((module, name, original))
        setattr(module, name, call)

    for module in (tubelex, tubelex_index, tubelex_batch):
        wrap(module, "sha256_file", "file_hashing")
    for module in (tubelex, tubelex_index, tubelex_batch):
        wrap(module, "verify_tubelex_snapshot", "snapshot_integrity")
    wrap(tubelex, "_read_compressed", "caption_decompression")
    wrap(tubelex_cache, "_read_compressed", "prediction_cache_decompression")
    wrap(tubelex_index, "_decode_text", "index_decompression")
    wrap(tubelex_index, "parse_vtt", "caption_parsing")
    wrap(tubelex_batch, "build_tubelex_index", "shard_build")
    wrap(tubelex_batch, "verify_tubelex_index", "shard_deep_verification")
    wrap(tubelex_batch, "_verify_bound_shard", "sealed_shard_verification")
    wrap(tubelex_batch, "_model_identity", "model_hashing")
    wrap(tubelex_index, "_model_identity", "model_hashing")
    wrap(tubelex_index, "_local_sat", "model_setup", factory=True)
    wrap(tubelex_boundaries, "local_japanese_character_model", "model_setup", factory=True)
    try:
        yield active
    finally:
        for module, name, original in reversed(originals):
            setattr(module, name, original)


def benchmark(snapshots, base, output, *, model=None, threshold=0.5):
    output = Path(output).absolute()
    if output.parent.resolve() != output.parent or output.exists() or output.is_symlink():
        raise ValueError("Use a fresh output outside symlinks")
    output.mkdir(mode=0o700)
    options = {}
    if model:
        options = dict(ja_punct_model=Path(model).resolve(strict=True),
                       ja_punct_threshold=threshold, boundary_cache=output / "cache")
    reports = []
    with instrument() as active:
        def run(name, destination):
            timing = active[0] = Timings()
            start = time.perf_counter()
            try:
                with timing.measure("end_to_end"):
                    result = tubelex_batch.build_tubelex_collection(snapshots, base, destination, **options)
            finally:
                active[0] = None
            report = {"mode": name, "wall_seconds": time.perf_counter() - start,
                      "phases": timing.phases}
            document = read_json(result)
            report["shards"] = []
            for entry in document["shards"]:
                part = result.parent / entry["part"]
                private = read_json(part / "index/manifest.private.json")
                report["shards"].append({"build_id": private["build_id"],
                    "index_sha256": private["index_sha256"],
                    "export_sha256": private["asset"]["sha256"],
                    "stored_build_stats": private["stats"]})
            reports.append(report)
            print(json.dumps({"mode": name, "wall_seconds": report["wall_seconds"]}), flush=True)
            return result

        run("cold_prediction_cache", output / "cold")
        run("fresh_rebuild_warm_prediction_cache", output / "rebuild")
        run("completed_resume", output / "cold")
        # Controlled interruption before a second shard tests resumability, not
        # a claim about any particular OS/process crash point.
        if len(snapshots) > 1:
            original = tubelex_batch.build_tubelex_index
            calls = 0

            def interrupt(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("benchmark interruption before second shard")
                return original(*args, **kwargs)

            tubelex_batch.build_tubelex_index = interrupt
            try:
                try:
                    run("controlled_interruption", output / "interrupted")
                except RuntimeError as error:
                    if str(error) != "benchmark interruption before second shard":
                        raise
            finally:
                tubelex_batch.build_tubelex_index = original
            run("interrupted_resume", output / "interrupted")
    signatures = [[(s["build_id"], s["index_sha256"], s["export_sha256"]) for s in r["shards"]]
                  for r in reports]
    assert all(value == signatures[0] for value in signatures), "Rebuild/resume changed index or citations"
    summary = {"runs": reports, "logical_artifacts_identical": True,
               "input_snapshots": [str(p) for p in snapshots],
               "model": bool(model), "model_threshold": threshold if model else None,
               "limits": "Offline warm-filesystem samples; nested inclusive phases overlap. No caption/audio quality judgment, full-corpus throughput or production latency claim."}
    (output / "report.json").write_bytes(canonical_json(summary))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", action="append", type=Path, required=True)
    parser.add_argument("--base-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ja-punct-model", type=Path)
    parser.add_argument("--ja-punct-threshold", type=float, default=0.5)
    args = parser.parse_args()
    benchmark(args.snapshot, args.base_artifact, args.output,
              model=args.ja_punct_model, threshold=args.ja_punct_threshold)


if __name__ == "__main__":
    main()
