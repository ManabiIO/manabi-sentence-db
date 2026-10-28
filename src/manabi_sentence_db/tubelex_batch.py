"""Resumable immutable private shards; one bounded budget across combined search."""

from __future__ import annotations

import hashlib
import heapq
import re
import shutil
import tempfile
import uuid
from collections import OrderedDict
from importlib.metadata import PackageNotFoundError, version
from inspect import Parameter, signature
from pathlib import Path

from .serialization import (
    DataError,
    canonical_json,
    digest_json,
    read_json,
    safe_relative,
    sha256_file,
)
from .tubelex import PROCESSOR, _read_bounded, _write_new_bytes, verify_tubelex_snapshot
from .tubelex_index import (
    DEFAULT_MAX_DECODED_CHUNKS,
    DEFAULT_QUERY_TIMEOUT_MS,
    TubelexReader,
    _canonical_query,
    _describe_sat,
    _index_build_id,
    _index_options,
    _literal_keys,
    _literal_maybe_contains,
    _model_identity,
    _QueryBudget,
    _search_database,
    _validate_boundary_settings,
    build_tubelex_index,
    verify_tubelex_index,
)

_BUILD_DEFAULTS = {
    name: parameter.default
    for name, parameter in signature(build_tubelex_index).parameters.items()
    if parameter.kind == Parameter.KEYWORD_ONLY
}
COLLECTION_VERSION = 2
_SHARD_FILES = (
    "index/citations.private.sqlite3", "index/manifest.private.json",
    "references/references.jsonl.zst", "references/manifest.json",
)


def _profile(options):
    if set(options) - _BUILD_DEFAULTS.keys():
        raise DataError("Unsupported citation build options")
    options = {**_BUILD_DEFAULTS, **options}
    settings = {}
    for key, value in options.items():
        if key == "boundary_cache":
            continue
        if isinstance(value, Path):
            path = value.resolve(strict=True)
            settings[key] = {"path": str(path), "sha256": _model_identity(path)}
        else:
            settings[key] = value
    try:
        canonical_json(settings)
    except (ValueError, TypeError) as exc:
        raise DataError("Invalid or nonfinite citation build options") from exc
    _validate_boundary_settings(options)
    model_info = None
    if options["ja_punct_model"]:
        from .tubelex_boundaries import describe_japanese_character_model

        _, _, model_info = describe_japanese_character_model(
            options["ja_punct_model"], threshold=options["ja_punct_threshold"],
        )
    elif options["sat_model"]:
        _, _, model_info = _describe_sat(
            options["sat_model"], options["sat_tokenizer"], threshold=options["sat_threshold"],
        )
    runtimes = {}
    if any(options.get(key) for key in ("sat_model", "ja_punct_model")):
        for package in ("wtpsplit", "onnxruntime", "numpy", "torch", "transformers", "tokenizers"):
            try:
                runtimes[package] = version(package)
            except PackageNotFoundError:
                runtimes[package] = None
    return {
        "processor": PROCESSOR,
        "model": model_info,
        "settings": settings,
        "runtimes": runtimes,
        "implementation": {
            name: sha256_file(Path(__file__).with_name(name))
            for name in ("tubelex.py", "tubelex_index.py", "tubelex_boundaries.py", "tubelex_cache.py", "text.py")
        },
    }


def _planned_options(profile):
    settings, model = profile["settings"], profile["model"]
    configured = {**settings, "boundary_cache": None}
    _validate_boundary_settings(configured)
    if profile["processor"] != PROCESSOR:
        raise DataError("Unsupported collection processor; rebuild the collection plan")
    if not settings["ja_punct_model"] and not settings["sat_model"]:
        if model is not None:
            raise DataError("Collection model disagrees with build plan")
    elif settings["ja_punct_model"]:
        if (
            not isinstance(model, dict) or model.get("engine") != "ja-character-onnx"
            or model.get("threshold") != settings["ja_punct_threshold"]
            or model.get("runtime") != profile["runtimes"]["onnxruntime"]
        ):
            raise DataError("Collection Japanese model disagrees with build plan")
    elif (
        not isinstance(model, dict) or model.get("engine") != "wtpsplit"
        or model.get("threshold") != settings["sat_threshold"]
        or model.get("model_sha256") != settings["sat_model"]["sha256"]
        or model.get("tokenizer_sha256") != settings["sat_tokenizer"]["sha256"]
        or model.get("version") != profile["runtimes"]["wtpsplit"]
        or model.get("backend") not in {"onnx-cpu", "pytorch"}
        or (model.get("backend") == "pytorch" and model.get("torch") != profile["runtimes"]["torch"])
    ):
        raise DataError("Collection SaT model disagrees with build plan")
    return _index_options(settings["boundary_mode"], settings["pause_ms"], model)


def _check_shard(private, entry, plan):
    expected_options = _planned_options(plan["profile"])
    expected_id = _index_build_id(entry["snapshot_id"], plan["base_sha256"], expected_options)
    if (
        private["snapshot_id"] != entry["snapshot_id"]
        or private["base_artifact_sha256"] != plan["base_sha256"]
        or private["processor"] != plan["profile"]["processor"]
        or private["options"] != expected_options or private["build_id"] != expected_id
    ):
        raise DataError("Completed shard options or identity disagree with collection plan")


def _seal_shard(part, entry, plan):
    _write_new_bytes(part / "binding.private.json", canonical_json({
        "kind": "private-tubelex-shard-binding", "schema_version": 1,
        "profile_sha256": digest_json(plan["profile"]), "snapshot_id": entry["snapshot_id"],
        "base_sha256": plan["base_sha256"],
        "files": {name: sha256_file(safe_relative(part, name)) for name in _SHARD_FILES},
    }))


def _verify_bound_shard(part, entry, plan):
    from .serialization import parse_json

    try:
        private = read_json(part / "index/manifest.private.json")
        _check_shard(private, entry, plan)
        path = safe_relative(part, "binding.private.json")
        binding = parse_json(_read_bounded(path))
        if (
            not isinstance(binding, dict) or binding.get("kind") != "private-tubelex-shard-binding"
            or type(binding.get("schema_version")) is not int or binding["schema_version"] != 1
            or binding["profile_sha256"] != digest_json(plan["profile"])
            or binding["snapshot_id"] != entry["snapshot_id"]
            or binding["base_sha256"] != plan["base_sha256"]
            or not isinstance(binding["files"], dict) or set(binding["files"]) != set(_SHARD_FILES)
        ):
            raise DataError("Completed shard binding disagrees with collection plan profile")
        if "binding_sha256" in entry and sha256_file(path) != entry["binding_sha256"]:
            raise DataError("Completed shard binding checksum mismatch")
        for name, expected in binding["files"].items():
            if sha256_file(safe_relative(part, name)) != expected:
                raise DataError("Completed shard file changed after its deep verification")
        database = safe_relative(part, "index/citations.private.sqlite3")
        if any(database.with_name(database.name + suffix).exists() for suffix in ("-wal", "-journal")):
            raise DataError("Completed shard must be a closed SQLite artifact")
        return private
    except DataError:
        raise
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise DataError("Missing or invalid completed-shard plan binding; rebuild the shard") from exc


def _retire_partial(stage, *, trash=None):
    trash = (trash or (Path.home() / ".Trash")).resolve()
    trash.mkdir(exist_ok=True)
    retired = Path(tempfile.mkdtemp(prefix="tubelex-partial-", dir=trash))
    shutil.move(str(stage), str(retired / stage.name))


def build_tubelex_collection(
    snapshots: list[Path], base_artifact: Path, output: Path, **options,
) -> Path:
    """Resume the identical plan, verifying/reusing complete shards after failures.

    Snapshot batches must be disjoint. Changing the corpus, processing profile,
    model bytes or runtimes requires a fresh collection, never mixing revisions.
    """
    if not snapshots or len(snapshots) > 4096:
        raise DataError("Provide 1..4096 disjoint completed caption snapshots")
    base_artifact = base_artifact.resolve(strict=True)
    if not base_artifact.is_file():
        raise DataError("Base artifact must be a downloaded release file")
    entries, videos, inputs = [], set(), []
    for number, snapshot in enumerate(snapshots):
        snapshot = snapshot.resolve(strict=True)
        if snapshot.is_dir():
            snapshot = (snapshot / "manifest.json").resolve(strict=True)
        manifest = verify_tubelex_snapshot(snapshot)
        for item in manifest["entries"]:
            if item["video_id"] in videos:
                raise DataError("Caption snapshot batches must not contain duplicate videos")
            videos.add(item["video_id"])
        inputs.append(snapshot.parent if snapshot.is_file() else snapshot)
        entries.append({
            "snapshot": str(snapshot), "snapshot_id": manifest["snapshot_id"],
            "part": f"parts/{number:05}-{manifest['snapshot_id'][8:]}",
        })
    if output.is_symlink():
        raise DataError("Collection destination must not be a symlink")
    output = output.resolve()
    for protected in [*inputs, base_artifact, options.get("boundary_cache"),
                      options.get("sat_model"), options.get("sat_tokenizer"),
                      options.get("ja_punct_model")]:
        if protected is not None:
            protected = Path(protected).resolve()
            if output == protected or output.is_relative_to(protected) or protected.is_relative_to(output):
                raise DataError("Collection must be separate from all inputs and caches")
    plan = {
        "kind": "private-tubelex-build-plan", "schema_version": COLLECTION_VERSION,
        "base_sha256": sha256_file(base_artifact), "profile": _profile(options), "shards": entries,
    }
    if output.exists():
        if not output.is_dir() or not (output / "plan.json").is_file():
            raise DataError("Existing collection destination has no valid build plan")
        if read_json(output / "plan.json") != plan:
            raise DataError("Collection plan changed; choose a fresh destination")
    else:
        output.mkdir(parents=True, mode=0o700)
        _write_new_bytes(output / "plan.json", canonical_json(plan))
    completed = output / "collection.private.json"
    if completed.exists():
        _, document = _read_collection(output)
        for entry in document["shards"]:
            _verify_bound_shard(safe_relative(output, entry["part"]), entry, plan)
        return completed
    (output / "parts").mkdir(exist_ok=True)
    receipts = []
    for entry in entries:
        part = safe_relative(output, entry["part"])
        if not part.exists():
            stage = output / "parts" / f".partial-{uuid.uuid4().hex}"
            stage.mkdir(mode=0o700)
            try:
                build_tubelex_index(
                    Path(entry["snapshot"]), base_artifact, stage / "index", stage / "references",
                    **options,
                )
                verified = verify_tubelex_index(stage / "index", stage / "references", deep=True)
                _check_shard(read_json(stage / "index/manifest.private.json"), entry, plan)
                _seal_shard(stage, entry, plan)
                stage.rename(part)
            except BaseException as exc:
                # Only the freshly created, task-owned incomplete shard moves.
                try:
                    _retire_partial(stage)
                except OSError as cleanup_error:
                    exc.add_note(f"Incomplete shard retained at {stage}: {cleanup_error}")
                raise
        else:
            private = _verify_bound_shard(part, entry, plan)
            verified = {"build_id": private["build_id"], "references": private["references"]}
        private = read_json(part / "index/manifest.private.json")
        _check_shard(private, entry, plan)
        receipts.append({
            "part": entry["part"], "build_id": verified["build_id"],
            "snapshot_id": entry["snapshot_id"], "references": verified["references"],
            "index_sha256": private["index_sha256"],
            "binding_sha256": sha256_file(part / "binding.private.json"),
        })
    document = {
        "kind": "private-tubelex-collection", "schema_version": COLLECTION_VERSION, "publish": False,
        "plan_sha256": digest_json(plan), "base_sha256": plan["base_sha256"],
        "shards": receipts, "references": sum(p["references"] for p in receipts),
    }
    _write_new_bytes(completed, canonical_json(document))
    return completed


def _read_collection(path: Path):
    path = path.resolve(strict=True)
    root = path if path.is_dir() else path.parent
    try:
        document = read_json(root / "collection.private.json")
        plan = read_json(root / "plan.json")
        if not isinstance(document, dict) or not isinstance(plan, dict):
            raise DataError("Collection and plan must be JSON objects")
        if (
            type(document.get("schema_version")) is not int
            or document["schema_version"] != COLLECTION_VERSION
            or type(plan.get("schema_version")) is not int
            or plan["schema_version"] != COLLECTION_VERSION
        ):
            raise DataError("Unsupported collection plan format; rebuild from the cached snapshots")
        if (
            document["kind"] != "private-tubelex-collection"
            or plan["kind"] != "private-tubelex-build-plan"
            or document["publish"] is not False or document["plan_sha256"] != digest_json(plan)
            or document["base_sha256"] != plan["base_sha256"]
            or not isinstance(document["base_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", document["base_sha256"])
            or not isinstance(document["shards"], list) or not isinstance(plan["shards"], list)
            or not 1 <= len(document["shards"]) <= 4096
            or len(document["shards"]) != len(plan["shards"])
            or type(document["references"]) is not int or document["references"] < 0
            or document["references"] != sum(p["references"] for p in document["shards"])
        ):
            raise DataError("Invalid or incomplete private citation collection")
        options = _planned_options(plan["profile"])
        snapshots = set()
        for number, (actual, expected) in enumerate(zip(document["shards"], plan["shards"])):
            identity = expected["snapshot_id"]
            if (
                not isinstance(identity, str) or not re.fullmatch(r"tubelex_[0-9a-f]{32}", identity)
                or identity in snapshots or expected["part"] != f"parts/{number:05}-{identity[8:]}"
                or type(actual["references"]) is not int or actual["references"] < 0
                or not isinstance(actual["index_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", actual["index_sha256"])
                or not isinstance(actual["binding_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", actual["binding_sha256"])
                or actual["build_id"] != _index_build_id(identity, plan["base_sha256"], options)
            ):
                raise DataError("Citation shard options or identity disagree with collection plan")
            snapshots.add(identity)
            if any(actual[key] != expected[key] for key in ("part", "snapshot_id")):
                raise DataError("Citation shard disagrees with collection plan")
            safe_relative(root, actual["part"])
    except DataError:
        raise
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise DataError("Invalid or incomplete private citation collection") from exc
    return root, document


def verify_tubelex_collection(path: Path, *, base_artifact=None, deep=False):
    root, document = _read_collection(path)
    plan = read_json(root / "plan.json")
    if base_artifact and sha256_file(base_artifact) != document["base_sha256"]:
        raise DataError("Citation collection belongs to a different base artifact")
    for entry in document["shards"]:
        part = safe_relative(root, entry["part"])
        _verify_bound_shard(part, entry, plan)
        verified = verify_tubelex_index(part / "index", part / "references", deep=deep)
        private = read_json(part / "index/manifest.private.json")
        _check_shard(private, entry, plan)
        if (
            verified["build_id"] != entry["build_id"]
            or verified["references"] != entry["references"]
            or private["index_sha256"] != entry["index_sha256"]
            or private["snapshot_id"] != entry["snapshot_id"]
            or private["base_artifact_sha256"] != document["base_sha256"]
        ):
            raise DataError("Citation collection receipt disagrees with shard")
    return {"shards": len(document["shards"]), "references": document["references"], "deep": bool(deep)}


class _DiverseReferences:
    """Bounded round-robin-by-video selection with query-stable tie ordering.

    Eviction removes a video's last retained slot. Its next candidate therefore
    has the evicted priority, which cannot beat the improving heap cutoff.
    Remembering retained IDs suffices even when an evicted clip appears again;
    the shard scanner shares this set instead of retaining all matching IDs.
    """
    def __init__(self, query, limit):
        self.query, self.limit = query, limit
        self.heap, self.ids, self.counts = [], set(), {}

    def accepts_video(self, video):
        if len(self.heap) < self.limit:
            return True
        ordinal = self.counts.get(video, 0)
        order = int.from_bytes(hashlib.sha256((self.query + "\0" + video).encode()).digest(), "big")
        priority = (-ordinal, -order, -int.from_bytes(video.encode(), "big"))
        return priority > self.heap[0][:3]

    def add(self, record):
        if record["id"] in self.ids:
            return
        video = record["native_id"].split(":", 1)[0]
        ordinal = self.counts.get(video, 0)
        order = int.from_bytes(hashlib.sha256((self.query + "\0" + video).encode()).digest(), "big")
        priority = (-ordinal, -order, -int.from_bytes(video.encode(), "big"))
        if len(self.heap) == self.limit and priority <= self.heap[0][:3]:
            return
        item = (*priority, record)
        retired = heapq.heappushpop(self.heap, item) if len(self.heap) == self.limit else None
        if retired is None:
            heapq.heappush(self.heap, item)
        else:
            old = retired[3]
            self.ids.remove(old["id"])
            old_video = old["native_id"].split(":", 1)[0]
            self.counts[old_video] -= 1
            if not self.counts[old_video]:
                del self.counts[old_video]
        self.ids.add(record["id"])
        self.counts[video] = self.counts.get(video, 0) + 1

    def results(self):
        return [item[3] for item in sorted(self.heap, key=lambda item: item[:3], reverse=True)]


class TubelexCollectionReader:
    """Deterministic first matches with an LRU of read-only shard connections.

    Verify once before activation. The deadline and decode budget cover the
    entire request; shard results are discarded if a later shard fails.
    """

    def __init__(self, path, *, base_artifact=None, timeout_ms=DEFAULT_QUERY_TIMEOUT_MS,
                 max_decoded_chunks=DEFAULT_MAX_DECODED_CHUNKS, max_open_shards=8,
                 max_filter_bytes=16 * 1024**2):
        if type(timeout_ms) is not int or not 1 <= timeout_ms <= 60_000:
            raise DataError("Query timeout budget must be an integer from 1 to 60000 ms")
        _QueryBudget(timeout_ms, max_decoded_chunks)
        if type(max_open_shards) is not int or not 1 <= max_open_shards <= 64:
            raise DataError("Use 1..64 open shard connections")
        if type(max_filter_bytes) is not int or not 0 <= max_filter_bytes <= 64 * 1024**2:
            raise DataError("Use a filter cache of 0..64 MiB")
        self.root, self.document = _read_collection(Path(path))
        if base_artifact and sha256_file(base_artifact) != self.document["base_sha256"]:
            raise DataError("Citation collection belongs to a different base artifact")
        self.timeout_ms, self.max_decoded_chunks = timeout_ms, max_decoded_chunks
        self.max_open_shards = max_open_shards
        self.readers = OrderedDict()
        self.filters = OrderedDict()
        self.filter_bytes = 0
        self.max_filter_bytes = max_filter_bytes
        self.closed = False
        self.last_search_stats = None

    def search(self, query, *, limit=250, selection="first"):
        if self.closed:
            raise DataError("Citation collection reader is closed")
        query = _canonical_query(query, limit)
        if selection not in ("first", "diverse"):
            raise DataError("Choose first or diverse collection selection")
        collector = _DiverseReferences(query, limit) if selection == "diverse" else None
        budget = _QueryBudget(self.timeout_ms, self.max_decoded_chunks)
        budget.stats.update({key: 0 for key in (
            "filter_cache_hits", "filter_cache_misses", "filter_cache_evictions",
            "reader_opens", "reader_reuses", "shards_examined",
        )})
        results, seen = [], set()
        try:
            if len(query) >= 4:
                budget.literal_keys = _literal_keys([query])
            for entry in self.document["shards"]:
                budget.check()
                part = entry["part"]
                budget.stats["shards_examined"] += 1
                bits = self.filters.get(part)
                budget.stats["filter_cache_hits" if bits is not None else "filter_cache_misses"] += 1
                if bits is not None:
                    self.filters.move_to_end(part)
                    if budget.literal_keys is not None and not all(
                        _literal_maybe_contains(bits, key) for key in budget.literal_keys
                    ):
                        budget.stats["global_literal_rejections"] = budget.stats.get("global_literal_rejections", 0) + 1
                        continue
                reader = self.readers.pop(part, None)
                if reader is None:
                    budget.stats["reader_opens"] += 1
                    if len(self.readers) == self.max_open_shards:
                        _, retired = self.readers.popitem(last=False)
                        retired.close()
                    reader = TubelexReader(
                        safe_relative(self.root, part) / "index/citations.private.sqlite3",
                        _cached_literal_filter=bits,
                    )
                    if reader.build_id != entry["build_id"]:
                        reader.close()
                        raise DataError("Citation collection shard identity mismatch")
                else:
                    budget.stats["reader_reuses"] += 1
                self.readers[part] = reader
                if part not in self.filters and len(reader._literal_filter) <= self.max_filter_bytes:
                    while self.filters and self.filter_bytes + len(reader._literal_filter) > self.max_filter_bytes:
                        _, retired_bits = self.filters.popitem(last=False)
                        self.filter_bytes -= len(retired_bits)
                        budget.stats["filter_cache_evictions"] += 1
                    self.filters[part] = reader._literal_filter
                    self.filter_bytes += len(reader._literal_filter)
                arguments = {"collector": collector} if collector is not None else {}
                matches = _search_database(
                    reader._database, query, limit - len(results), self.timeout_ms, budget=budget,
                    literal_filter=reader._literal_filter, **arguments,
                )
                for record in matches:
                    if record["id"] not in seen:
                        seen.add(record["id"])
                        results.append(record)
                        if len(results) == limit:
                            break
                if len(results) == limit:
                    break
            if collector is not None:
                results = collector.results()
            budget.check()
            self.last_search_stats = {**budget.stats, "outcome": "complete", "results": len(results)}
            return results
        except BaseException:
            self.last_search_stats = {**budget.stats, "outcome": "error", "results": 0}
            raise

    def close(self):
        for reader in self.readers.values():
            reader.close()
        self.readers.clear()
        self.filters.clear()
        self.filter_bytes = 0
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
