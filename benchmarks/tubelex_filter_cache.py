"""Default-budget cache component stress; no caption or search artifacts created.

Authored negative Bloom byte fixtures model working-set sizes, not real corpus
fingerprint frequencies, SQLite open costs, OS cold I/O or production latency.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from manabi_sentence_db import tubelex_batch as batch
from manabi_sentence_db.serialization import canonical_json


def benchmark(output):
    output = Path(output).absolute()
    if output.parent.resolve() != output.parent or output.exists() or output.is_symlink():
        raise ValueError("Use a fresh output outside symlinks")
    output.mkdir(mode=0o700)
    reports = []
    original_read, original_factory = batch._read_collection, batch.TubelexReader
    try:
        for shards, size in [(8, 1024**2), (64, 256 * 1024), (32, 1024**2),
                             (16, 2 * 1024**2), (8, 4 * 1024**2)]:
            path = output / f"filter-{size}.bin"
            if not path.exists():
                path.write_bytes(bytes(size))
            document = {"shards": [{"part": f"part-{n}", "build_id": "fixture"} for n in range(shards)]}
            batch._read_collection = lambda _: (output, document)

            class Database:
                def set_progress_handler(self, *args):
                    pass

            class Reader:
                def __init__(self, *args, _cached_literal_filter=None):
                    self._literal_filter = (_cached_literal_filter if _cached_literal_filter is not None
                                            else path.read_bytes())
                    self._database = Database()
                    self.build_id = "fixture"

                def close(self):
                    pass

            batch.TubelexReader = Reader
            runs = []
            with batch.TubelexCollectionReader(output) as reader:
                for repeat in range(8):
                    start = time.perf_counter_ns()
                    assert reader.search("不存在404Z") == []
                    runs.append({"ms": (time.perf_counter_ns() - start) / 1e6,
                                 "stats": dict(reader.last_search_stats)})
                    assert reader.filter_bytes <= 16 * 1024**2 and len(reader.readers) <= 8
                buffers = {id(bits): len(bits) for bits in reader.filters.values()}
                buffers.update({id(r._literal_filter): len(r._literal_filter) for r in reader.readers.values()})
                reports.append({"shards": shards, "filter_bytes_per_shard": size,
                    "working_set_bytes": shards * size, "cache_budget_bytes": reader.max_filter_bytes,
                    "max_open_shards": reader.max_open_shards,
                    "cold_ms": runs[0]["ms"], "warm_median_ms": statistics.median(r["ms"] for r in runs[1:]),
                    "warm_reader_opens": [r["stats"]["reader_opens"] for r in runs[1:]],
                    "retained_filter_bytes": reader.filter_bytes,
                    "unique_cache_plus_open_reader_payload_bytes": sum(buffers.values()), "runs": runs})
    finally:
        batch._read_collection, batch.TubelexReader = original_read, original_factory
    result = {"profiles": reports, "limits": __doc__.strip(),
              "defaults_changed": False,
              "fixture": "All synthetic shards read the same zero-filled file per size; warm byte loading/eviction only. The filter budget includes payloads held by open readers; when the working set exceeds it, readers may be reopened on later queries, trading throughput for bounded filter memory. Retained payload bytes are not peak RSS."}
    (output / "report.json").write_bytes(canonical_json(result))
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    benchmark(parser.parse_args().output)
