"""Offline snapshot -> canonical YAML; no source requests or download fallbacks."""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import platform
import shutil
import sqlite3
import subprocess
import tempfile
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml
import zstandard

from . import PROCESSOR_VERSION, SCHEMA_VERSION
from .segments import PUBLISHER_CONTEXT_VERSION, publisher_items
from .serialization import (
    DataError,
    StrictLoader,
    canonical_json,
    digest_json,
    parse_json,
    read_json,
    require_new_directory,
    safe_relative,
    sha256_file,
    write_json,
)
from .text import PUBLISHER_SEGMENTER_VERSION
from .validation import text_sha256, validate, validate_record


class _AliasFreeSafeDumper(yaml.SafeDumper):
    """Shared Python metadata objects must still be plain portable YAML values."""

    def ignore_aliases(self, data):
        return True


def _identity(prefix: str, *parts: str) -> str:
    return prefix + digest_json(list(parts))[:32]


def _normalized_text(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip())


def canonical_document(
    raw: dict, manifest: dict, stats: Counter, excluded_flags: set[str]
) -> dict | None:
    from .text import assess_sentence, style_tags

    source_id = manifest["source_id"]
    wikipedia_quality = source_id.startswith("wikipedia-") and raw["language"].split("-", 1)[0] == "ja"
    native_id = str(raw["native_id"])
    record = {
        "schema_version": SCHEMA_VERSION,
        "kind": "document",
        "id": _identity("doc_", source_id, native_id),
        "source_id": source_id,
        "snapshot_id": manifest["snapshot_id"],
        "native_id": native_id,
        "language": raw["language"],
        "title": raw["title"],
        "url": raw["url"],
        "license": raw["license"],
        "attribution": raw["attribution"],
        "tags": sorted(set(raw.get("tags", []))),
        "transformations": (
            [
                "wikitext-prose-extraction",
                "sentence-segmentation",
                "conservative-quotation-exclusion",
            ]
            if manifest["source"]["adapter"] == "wikimedia"
            else ["publisher-html-narrative-extraction", "publisher-paragraph-unit"]
            if manifest["source"]["adapter"] == "scp-curated"
            else ["publisher-sentence-unit"]
        )
        + ["NFC", "edge-whitespace-trim"],
        "sentences": [],
    }
    if raw.get("revision"):
        record["revision"] = raw["revision"]
    if manifest["source"]["adapter"] == "wikimedia" and all(
        "source_ordinal" in item for item in raw["sentences"]
    ):
        from .wikimedia import WIKIMEDIA_CONTEXT_VERSION

        record["transformations"].append(WIKIMEDIA_CONTEXT_VERSION)
    if manifest["source"]["adapter"] == "scp-curated":
        from .scp_curated import RUBY_TRANSFORMATION

        record["transformations"].append(RUBY_TRANSFORMATION)
    if wikipedia_quality:
        from .wikipedia_quality import WIKIPEDIA_QUALITY_VERSION

        record["transformations"].append(WIKIPEDIA_QUALITY_VERSION)
    if manifest["source"]["adapter"] == "kyoto-wikipedia":
        record["transformations"] += ["kyoto-final-checked-pairs-v1", "conservative-quotation-exclusion"]
    for field in (
        "published_at",
        "language_origin",
        "authorship",
        "content_type",
        "source_text_hash",
    ):
        if raw.get(field) is not None:
            record[field] = raw[field]
    occurrences: Counter = Counter()
    for ordinal, item in enumerate(publisher_items(raw, manifest, stats, excluded_flags)):
        if item is None:
            if manifest["source"]["adapter"] in {"wikimedia", "kyoto-wikipedia", "alt-parallel"}:
                raise DataError("Unexpected context marker in presegmented source")
            if PUBLISHER_CONTEXT_VERSION not in record["transformations"]:
                record["transformations"].append(PUBLISHER_CONTEXT_VERSION)
            continue
        if manifest["source"]["adapter"] in {"kyoto-wikipedia", "alt-parallel"}:
            # Keep gaps from excluded pairs; spreadsheet/paragraph positions do
            # not authorize joining prose across omitted source material.
            ordinal = item["source_ordinal"]
        elif manifest["source"]["adapter"] == "wikimedia":
            # Old caller-supplied records without positions retain their former
            # behavior; only current extraction earns the context transformation.
            ordinal = item.get("source_ordinal", ordinal)
        text = _normalized_text(item["text"])
        accepted, flags, reason = assess_sentence(text, raw["language"])
        quality_tags = []
        if accepted and wikipedia_quality:
            from .wikipedia_quality import assess_wikipedia_sentence

            reason, quality_tags = assess_wikipedia_sentence(text)
            accepted = reason is None
        stats["sentences_seen"] += 1
        if manifest["source"]["adapter"] == "tatoeba":
            upstream_tags = {tag.casefold().strip() for tag in item.get("tags", [])}
            if any(tag == "@change" or tag.startswith("@change ") for tag in upstream_tags):
                accepted, reason = False, "upstream-needs-correction"
            elif upstream_tags.intersection({"archaic", "old-fashioned"}):
                accepted, reason = False, "archaic-language"
            elif upstream_tags.intersection({"unnatural", "possibly unnatural"}):
                accepted, reason = False, "upstream-unnatural"
            if "vulgar" in upstream_tags:
                flags.append("profanity")
            if "sexual" in upstream_tags:
                flags.append("sexual-content")
        if item.get("generation", {}).get("kind") == "machine":
            accepted, reason = False, "machine-generated"
        if "＊＊" in text:
            accepted, reason = False, "masked-personal-information"
        if not accepted:
            stats[f"rejected:{reason or 'quality'}"] += 1
            continue
        flags = sorted(set(flags) | set(item.get("content_flags", [])))
        for flag in flags:
            stats[f"flagged:{flag}"] += 1
        if excluded_flags.intersection(flags):
            stats["rejected:content-policy"] += 1
            continue
        text_hash = text_sha256(text)
        occurrences[text_hash] += 1
        # Source IDs survive text edits when upstream supplies a sentence ID.
        # Prose sentence identity follows exact text and occurrence, so an insertion
        # before a sentence does not renumber every later sentence in the article.
        local_id = str(item.get("native_id") or f"{text_hash}:{occurrences[text_hash]}")
        sentence_id = _identity("sent_", source_id, native_id, local_id)
        sentence = {
            "id": sentence_id,
            "ordinal": ordinal,
            "text": text,
            "text_sha256": text_hash,
            "tags": sorted(set(item.get("tags", [])) | set(style_tags(text, raw["language"])) | set(quality_tags)),
            "content_flags": flags,
            "review_state": "unreviewed",
            "translations": [],
        }
        if item.get("source_unit"):
            unit = dict(item["source_unit"])
            unit["translations"] = _canonical_translations(
                unit["translations"], unit["id"]
            )
            sentence["source_unit"] = unit
            if PUBLISHER_SEGMENTER_VERSION not in record["transformations"]:
                record["transformations"].append(PUBLISHER_SEGMENTER_VERSION)
        if item.get("source_range"):
            sentence["source_range"] = item["source_range"]
        if item.get("native_id") is not None:
            sentence["native_id"] = str(item["native_id"])
        if item.get("generation"):
            sentence["generation"] = item["generation"]
        sentence["translations"] = _canonical_translations(
            item.get("translations", []), sentence_id
        )
        record["sentences"].append(sentence)
        stats["sentences"] += 1
        stats["translations"] += len(sentence["translations"])
    if not record["sentences"]:
        stats["documents_without_sentences"] += 1
        return None
    validate_record(record)
    return record


def _canonical_translations(originals: list, owner_id: str) -> list:
    result = []
    for original in originals:
        text = _normalized_text(original["text"])
        if not text:
            continue
        translation = dict(original, text=text, text_sha256=text_sha256(text))
        if "native_id" in translation:
            translation["native_id"] = str(translation["native_id"])
        translation["id"] = _identity(
            "tr_", owner_id, translation["language"],
            translation.get("native_id", translation["text_sha256"]), translation["source_url"],
        )
        result.append(translation)
    return sorted(result, key=lambda value: (value["language"], value["id"]))


def _all_translations(sentence):
    return sentence["translations"] + sentence.get("source_unit", {}).get("translations", [])


def _processor_fingerprint() -> str:
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted([*root.rglob("*.py"), *root.rglob("*.json")]):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_revision() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _runtime_versions() -> dict:
    dependencies = {}
    for name in [
        "PyYAML", "jsonschema", "mwparserfromhell", "defusedxml", "zstandard", "xlrd"
    ]:
        dependencies[name] = importlib.metadata.version(name)
    return {
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "dependencies": dependencies,
    }


def _git_dirty() -> bool | None:
    try:
        return bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=Path(__file__).parent,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return None


class ShardWriter:
    def __init__(
        self,
        root: Path,
        source_id: str,
        language: str,
        max_bytes: int,
        max_documents: int,
        record_format="yaml",
        shard_compression="none",
    ):
        self.shard_compression = shard_compression
        self.compressor = None
        self.record_format = record_format
        self.root = root
        self.source_id = source_id
        self.language = language
        self.max_bytes = max_bytes
        self.max_documents = max_documents
        self.entries: list[dict] = []
        self.handle = None
        self.temporary: Path | None = None
        self.digest = hashlib.sha256()
        self.count = 0
        self.size = 0
        self.sentences = 0
        self.filename = ""

    def append(self, record: dict) -> tuple[str, int]:
        data = (
            yaml.dump(
                record, Dumper=_AliasFreeSafeDumper, allow_unicode=True,
                sort_keys=False, explicit_start=True, width=120
            ).encode("utf-8")
            if self.record_format == "yaml"
            else canonical_json(record) + b"\n"
        )
        if len(data) > 32 * 1024 * 1024:
            raise DataError(f"Document exceeds the 32 MiB canonical-record bound: {record['id']}")
        if self.handle and (
            self.count >= self.max_documents or self.size + len(data) > self.max_bytes
        ):
            self.close()
        if not self.handle:
            self.filename = f"{self.record_format}/{self.language}/{self.source_id}/{len(self.entries):06d}.{self.record_format}"
            if self.shard_compression == "zstd":
                self.filename += ".zst"
            target = safe_relative(self.root, self.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            self.temporary = target.with_name(f".{target.name}.part")
            self.handle = self.temporary.open("xb")
            if self.shard_compression == "zstd":
                self.compressor = zstandard.ZstdCompressor(level=9, write_checksum=True).compressobj()
        index = self.count
        encoded = self.compressor.compress(data) if self.compressor else data
        self.handle.write(encoded)
        self.digest.update(encoded)
        self.count += 1
        self.sentences += len(record.get("sentences", []))
        self.size += len(data)
        return self.filename, index

    def close(self):
        if self.handle is None:
            return
        try:
            if self.compressor is not None:
                tail = self.compressor.flush()
                self.handle.write(tail)
                self.digest.update(tail)
                self.compressor = None
        finally:
            try:
                self.handle.close()
            finally:
                self.handle = None
        assert self.temporary is not None
        expected_hash = self.digest.hexdigest()
        if (
            sha256_file(self.temporary) != expected_hash
        ):
            raise DataError(f"Shard bytes changed while writing: {self.filename}")
        stored_size = self.temporary.stat().st_size
        os.replace(self.temporary, self.root / self.filename)
        self.temporary = None
        self.entries.append(
            {
                "path": self.filename,
                "source_id": self.source_id,
                "language": self.language,
                "documents": self.count,
                "sentences": self.sentences,
                "size": stored_size,
                "sha256": expected_hash,
            }
        )
        self.count = self.size = self.sentences = 0
        self.digest = hashlib.sha256()

    def abort(self):
        """Discard an unfinished shard without publishing it during error cleanup."""
        try:
            if self.handle is not None:
                self.handle.close()
        finally:
            self.handle = None
            if self.temporary is not None:
                self.temporary.unlink(missing_ok=True)
                self.temporary = None


def build_corpus(
    snapshot_paths: list[Path],
    output: Path,
    *,
    shard_bytes=4 * 1024 * 1024,
    shard_documents=500,
    excluded_flags: set[str] | None = None,
    max_documents: int | None = None,
    record_format: str = "yaml",
    shard_compression: str = "none",
    document_selection: Path | None = None,
    progress=None,
) -> Path:
    from .snapshot import verify_snapshot

    require_new_directory(output)
    if shard_compression not in {"none", "zstd"}:
        raise DataError("Unsupported shard compression")
    if record_format not in {"yaml", "jsonl"}:
        raise DataError("Unsupported record format")
    if not snapshot_paths or shard_bytes < 1024 or shard_documents < 1:
        raise DataError("Provide snapshots and positive shard limits (at least 1024 bytes)")
    if max_documents is not None and max_documents < 1:
        raise DataError("max_documents must be positive")
    if document_selection is not None and max_documents is not None:
        raise DataError("document_selection cannot be combined with max_documents")
    excluded_flags = {"sexual-content"} if excluded_flags is None else excluded_flags
    notify = progress or (lambda _: None)
    inputs = []
    for path in snapshot_paths:
        notify("Verifying cached snapshot bytes")
        inputs.append((path, verify_snapshot(path)))
    selection = None
    page_ids = None
    if document_selection is not None:
        from .document_selection import validate_selection

        selection = read_json(document_selection.resolve())
        page_ids = validate_selection(selection, [m for _, m in inputs])
        selection = {**selection, "page_ids": sorted(page_ids, key=int)}
    inputs.sort(key=lambda pair: pair[1]["source_id"])
    if len({manifest["source_id"] for _, manifest in inputs}) != len(inputs):
        raise DataError("A build must use exactly one snapshot per source")
    for _, manifest in inputs:
        validate(manifest["source"], "source")
    processor_hash = _processor_fingerprint()
    runtime = _runtime_versions()
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    stats: Counter = Counter()
    writers = []
    ledger = None
    licenses = {}
    try:
        ledger = sqlite3.connect(staging / "identities.sqlite3")
        ledger.execute(
            "CREATE TABLE identities(kind TEXT, id TEXT, PRIMARY KEY(kind,id)) WITHOUT ROWID"
        )
        entries = []
        sources = []
        snapshots = []
        index_temporary = staging / ".documents.jsonl.part"
        index_digest = hashlib.sha256()
        with index_temporary.open("wb") as index:
            import json

            for manifest_path, manifest in inputs:
                source = manifest["source"]
                source_id = manifest["source_id"]
                if source["id"] != source_id:
                    raise DataError(
                        "Snapshot source identity disagrees with its source configuration"
                    )
                if source["adapter"] == "wikimedia":
                    from .wikimedia import iter_documents
                elif source["adapter"] == "tatoeba":
                    from .tatoeba import iter_documents
                elif source["adapter"] == "realpersonachat":
                    from .realpersonachat import iter_documents
                elif source["adapter"] == "mrmp":
                    from .mrmp import iter_documents
                elif source["adapter"] == "jmultiwoz":
                    from .jmultiwoz import iter_documents
                elif source["adapter"] == "stair":
                    from .stair import iter_documents
                elif source["adapter"] == "scp-curated":
                    from .scp_curated import iter_documents
                elif source["adapter"] == "jec-basic":
                    from .jec_basic import iter_documents
                elif source["adapter"] == "alt-parallel":
                    from .alt_parallel import iter_documents
                elif source["adapter"] == "kyoto-wikipedia":
                    from .kyoto_wikipedia import iter_documents
                else:
                    raise DataError(f"Unsupported adapter: {source['adapter']}")
                writer = ShardWriter(
                    staging,
                    source_id,
                    source["language"],
                    shard_bytes,
                    shard_documents,
                    record_format,
                    shard_compression,
                )
                writers.append(writer)
                source_stats: Counter = Counter()
                notify(f"{source_id}: processing cached snapshot")
                documents = (
                    iter_documents(
                        manifest, manifest_path.parent, stats=source_stats,
                        **({"page_ids": page_ids} if selection is not None
                           and selection["source_id"] == source_id else {}),
                        **({"progress": progress} if source["adapter"] == "wikimedia" else {}),
                    )
                    if source["adapter"] in {"wikimedia", "jec-basic", "kyoto-wikipedia", "alt-parallel"}
                    else iter_documents(manifest, manifest_path.parent)
                )
                for raw in documents:
                    if (
                        max_documents is not None
                        and source_stats["documents_seen"] >= max_documents
                    ):
                        break
                    source_stats["documents_seen"] += 1
                    if raw["language"] != source["language"]:
                        raise DataError("Adapter returned a document with an unexpected language")
                    record = canonical_document(raw, manifest, source_stats, excluded_flags)
                    if record is None:
                        continue
                    for license_value in [
                        record["license"],
                        *[
                            tr["license"]
                            for sentence in record["sentences"]
                            for tr in _all_translations(sentence)
                        ],
                    ]:
                        previous = licenses.setdefault(license_value["id"], license_value)
                        if previous != license_value:
                            raise DataError(
                                f"Conflicting notices for license {license_value['id']}"
                            )
                    try:
                        ledger.execute(
                            "INSERT INTO identities VALUES ('document',?)", (record["id"],)
                        )
                        for sentence in record["sentences"]:
                            ledger.execute(
                                "INSERT INTO identities VALUES ('sentence',?)", (sentence["id"],)
                            )
                    except sqlite3.IntegrityError as exc:
                        raise DataError(
                            f"Duplicate upstream identity in snapshot: {record['id']}"
                        ) from exc
                    shard, position = writer.append(record)
                    index_line = (
                        json.dumps(
                            {
                                "id": record["id"],
                                "source_id": source_id,
                                "native_id": record["native_id"],
                                "title": record["title"],
                                "shard": shard,
                                "position": position,
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        + "\n"
                    ).encode("utf-8")
                    index.write(index_line)
                    index_digest.update(index_line)
                    source_stats["documents"] += 1
                    if source_stats["documents"] % 500 == 0:
                        notify(f"{source_id}: wrote {source_stats['documents']} documents; "
                               f"{source_stats['sentences']} sentences")
                writer.close()
                notify(f"{source_id}: finished {source_stats['documents']} documents; "
                       f"{source_stats['sentences']} sentences")
                entries.extend(writer.entries)
                sources.append({"source": source, "statistics": dict(sorted(source_stats.items()))})
                stats.update(source_stats)
                provenance_path = f"provenance/{source_id}.snapshot.json"
                (staging / "provenance").mkdir(exist_ok=True)
                shutil.copyfile(manifest_path, staging / provenance_path)
                snapshots.append(
                    {
                        "source_id": source_id,
                        "snapshot_id": manifest["snapshot_id"],
                        "mode": manifest["mode"],
                        "manifest": provenance_path,
                        "manifest_sha256": sha256_file(manifest_path),
                    }
                )
        if sha256_file(index_temporary) != index_digest.hexdigest():
            raise DataError("Document index bytes changed while writing")
        os.replace(index_temporary, staging / "documents.jsonl")
        ledger.commit()
        ledger.close()
        ledger = None
        (staging / "identities.sqlite3").unlink()
        if not stats["documents"]:
            raise DataError(
                "No usable sentences were extracted; inspect source selection and extraction policy"
            )
        options = {
            "record_format": record_format,
            "shard_bytes": shard_bytes,
            "shard_documents": shard_documents,
            "excluded_flags": sorted(excluded_flags),
            "max_documents_per_source": max_documents,
        }
        if shard_compression != "none":
            options["shard_compression"] = shard_compression
        if selection is not None:
            options["document_selection"] = selection
            options["document_selection_sha256"] = digest_json(selection)
        if _processor_fingerprint() != processor_hash:
            raise DataError(
                "Processor files changed during the build; rebuild with a stable checkout"
            )
        build_id = (
            "build_"
            + digest_json(
                {
                    "processor": processor_hash,
                    "runtime": runtime,
                    "options": options,
                    "snapshots": [m["snapshot_id"] for _, m in inputs],
                }
            )[:32]
        )
        write_json(
            staging / "licenses.json",
            {
                "notice": "Source texts and translations retain their own licenses; this is not a relicensing grant.",
                "licenses": [licenses[key] for key in sorted(licenses)],
            },
        )
        catalog = {
            "schema_version": SCHEMA_VERSION,
            "build_id": build_id,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "scope": "sample"
            if selection is not None or max_documents or any(m["mode"] != "full" for _, m in inputs)
            else "full",
            "processor_version": PROCESSOR_VERSION,
            "processor_sha256": processor_hash,
            "git_revision": _git_revision(),
            "git_dirty": _git_dirty(),
            "runtime": runtime,
            "python_version": platform.python_version(),
            "sqlite_version": sqlite3.sqlite_version,
            "options": options,
            "sources": sources,
            "snapshots": snapshots,
            "shards": entries,
            "statistics": dict(sorted(stats.items())),
            "document_index": {
                "path": "documents.jsonl",
                "sha256": sha256_file(staging / "documents.jsonl"),
            },
            "licenses": {"path": "licenses.json", "sha256": sha256_file(staging / "licenses.json")},
        }
        write_json(staging / "catalog.json", catalog)
        # Compare every completed artifact with its intended bytes again before
        # making the build visible. A later truncated/corrupted shard must never
        # become a successful build merely because it was valid when first closed.
        notify("Verifying completed corpus artifacts")
        verify_build(staging)
        notify("Publishing verified corpus")
        os.replace(staging, output)
        return output / "catalog.json"
    finally:
        if ledger is not None:
            ledger.close()
        for writer in writers:
            writer.abort()
        if staging.exists():
            shutil.rmtree(staging)


def verify_build(build: Path) -> dict:
    """Validate the catalog and bind every artifact to its exact source snapshot.

    Raw source blobs need not be present when consuming a release. The copied
    snapshot manifests still have self-verifying identities and are compared
    with the catalog's complete source configurations.
    """
    import re

    from .licenses import validate_license
    from .snapshot import snapshot_identity

    catalog = read_json(build / "catalog.json")
    if not isinstance(catalog, dict):
        raise DataError("Corpus catalog must be an object")
    if (
        type(catalog.get("schema_version")) is not int
        or catalog["schema_version"] != SCHEMA_VERSION
    ):
        raise DataError("Unsupported corpus schema version")
    for field in ("sources", "snapshots", "shards"):
        if not isinstance(catalog.get(field), list) or not catalog[field]:
            raise DataError(f"Catalog {field} must be a nonempty list")
    for field in ("document_index", "licenses", "options", "statistics"):
        if not isinstance(catalog.get(field), dict):
            raise DataError(f"Catalog {field} must be an object")
    for field, expected_path in (
        ("document_index", "documents.jsonl"),
        ("licenses", "licenses.json"),
    ):
        if catalog[field].get("path") != expected_path:
            raise DataError(f"Schema v1 requires the canonical metadata path {expected_path}")

    def positive(value, name, *, zero=False):
        if type(value) is not int or value < (0 if zero else 1):
            raise DataError(f"Invalid catalog {name}")

    def digest(value):
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise DataError("Invalid catalog SHA-256")

    def counts(value, label):
        if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
            raise DataError(f"Invalid {label} statistics")
        for name, count in value.items():
            positive(count, f"{label} count {name}", zero=True)

    sources = {}
    totals: Counter = Counter()
    for entry in catalog["sources"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("source"), dict):
            raise DataError("Malformed catalog source entry")
        source = entry["source"]
        validate(source, "source")
        validate_license(source["license"])
        if source["id"] in sources:
            raise DataError("Duplicate catalog source ID")
        sources[source["id"]] = source
        counts(entry.get("statistics"), source["id"])
        totals.update(entry["statistics"])
    counts(catalog["statistics"], "combined")
    if totals != Counter(catalog["statistics"]):
        raise DataError("Catalog statistics disagree with source totals")

    options = catalog["options"]
    _record_encoding(catalog)
    positive(options.get("shard_bytes"), "shard_bytes")
    positive(options.get("shard_documents"), "shard_documents")
    if options.get("max_documents_per_source") is not None:
        positive(options["max_documents_per_source"], "max_documents_per_source")
    flags = options.get("excluded_flags")
    if not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags):
        raise DataError("Invalid catalog content-filter configuration")
    digest(catalog.get("processor_sha256"))

    used_paths: set[str] = set()

    def artifact(entry, path_key="path", hash_key="sha256"):
        if not isinstance(entry, dict):
            raise DataError("Malformed catalog artifact entry")
        name = entry.get(path_key)
        path = safe_relative(build, name)
        # Resolve symlinks before checking uniqueness, so aliases cannot
        # duplicate a shard under different catalog paths.
        canonical = str(path)
        if canonical in used_paths:
            raise DataError(f"Duplicate catalog artifact path: {name}")
        used_paths.add(canonical)
        digest(entry.get(hash_key))
        if not path.is_file() or sha256_file(path) != entry[hash_key]:
            raise DataError(f"Missing or corrupt build artifact: {name}")
        if "size" in entry:
            positive(entry["size"], "artifact size", zero=True)
            if path.stat().st_size != entry["size"]:
                raise DataError(f"Incorrect artifact size: {name}")
        return path

    snapshot_sources = set()
    snapshot_ids = set()
    modes = []
    for entry in catalog["snapshots"]:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("source_id"), str)
            or entry["source_id"] not in sources
        ):
            raise DataError("Snapshot refers to an unknown source")
        source_id = entry["source_id"]
        digest(entry.get("snapshot_id"))
        if source_id in snapshot_sources or entry.get("snapshot_id") in snapshot_ids:
            raise DataError("Duplicate catalog snapshot identity")
        snapshot_sources.add(source_id)
        snapshot_ids.add(entry.get("snapshot_id"))
        manifest = read_json(artifact(entry, "manifest", "manifest_sha256"))
        try:
            if (
                manifest["schema_version"] != SCHEMA_VERSION
                or manifest["source_id"] != source_id
                or manifest["source"] != sources[source_id]
                or manifest["source_config_sha256"] != digest_json(sources[source_id])
                or manifest["snapshot_id"] != entry["snapshot_id"]
                or manifest["snapshot_id"] != snapshot_identity(manifest)
                or manifest["mode"] != entry["mode"]
                or manifest["mode"] not in {"sample", "full", "partial"}
            ):
                raise DataError("Snapshot provenance disagrees with catalog identity/source/scope")
        except (KeyError, TypeError) as exc:
            raise DataError("Malformed snapshot provenance") from exc
        modes.append(entry["mode"])
    if snapshot_sources != set(sources):
        raise DataError("Every source must have exactly one snapshot")
    selection = options.get("document_selection")
    if selection is not None:
        if options.get("max_documents_per_source") is not None:
            raise DataError("document_selection cannot be combined with max_documents")
        from .document_selection import validate_selection

        validate_selection(selection, [
            {"source_id": entry["source_id"], "snapshot_id": entry["snapshot_id"],
             "source": sources[entry["source_id"]]}
            for entry in catalog["snapshots"]
        ])
        if options.get("document_selection_sha256") != digest_json(selection):
            raise DataError("Document selection digest mismatch")
    elif "document_selection_sha256" in options:
        raise DataError("Document selection digest has no selection")
    expected_scope = (
        "sample"
        if selection is not None or options.get("max_documents_per_source")
        or any(mode != "full" for mode in modes)
        else "full"
    )
    if catalog.get("scope") != expected_scope:
        raise DataError("Catalog scope contradicts snapshot/build selection")
    runtime = catalog.get("runtime")
    if not isinstance(runtime, dict) or not isinstance(runtime.get("dependencies"), dict):
        raise DataError("Catalog must record processor runtime and dependency versions")
    if runtime.get("python") != catalog.get("python_version") or runtime.get(
        "sqlite"
    ) != catalog.get("sqlite_version"):
        raise DataError("Catalog runtime versions disagree")
    if any(not isinstance(value, str) or not value for value in runtime["dependencies"].values()):
        raise DataError("Invalid dependency version metadata")
    expected_id = (
        "build_"
        + digest_json(
            {
                "processor": catalog["processor_sha256"],
                "runtime": runtime,
                "options": options,
                "snapshots": [entry["snapshot_id"] for entry in catalog["snapshots"]],
            }
        )[:32]
    )
    if catalog.get("build_id") != expected_id:
        raise DataError("Catalog build identity mismatch")

    shard_totals: Counter = Counter()
    for entry in catalog["shards"]:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("source_id"), str)
            or entry["source_id"] not in sources
        ):
            raise DataError("Shard refers to an unknown source")
        source = sources[entry["source_id"]]
        if entry.get("language") != source["language"]:
            raise DataError("Shard language disagrees with its source")
        positive(entry.get("documents"), "shard document count")
        positive(entry.get("sentences"), "shard sentence count", zero=True)
        if "size" not in entry:
            raise DataError("Shard is missing its byte size")
        _record_encoding(catalog, entry["path"])
        artifact(entry)
        shard_totals["documents"] += entry["documents"]
        shard_totals["sentences"] += entry["sentences"]
    if any(shard_totals[key] != catalog["statistics"].get(key, 0) for key in shard_totals):
        raise DataError("Shard counts disagree with catalog statistics")
    artifact(catalog["document_index"])
    licenses = read_json(artifact(catalog["licenses"]))
    if not isinstance(licenses, dict) or not isinstance(licenses.get("licenses"), list):
        raise DataError("Malformed license catalog")
    license_ids = set()
    for value in licenses["licenses"]:
        if not isinstance(value, dict) or not isinstance(value.get("id"), str):
            raise DataError("Malformed license entry")
        validate_license(value)
        if value["id"] in license_ids:
            raise DataError("Duplicate license catalog entry")
        license_ids.add(value["id"])
    return catalog


def _record_encoding(catalog, path=None):
    options = catalog["options"]
    record_format = options.get("record_format", "yaml")
    compression = options.get("shard_compression", "none")
    if (not isinstance(record_format, str) or not isinstance(compression, str)
            or record_format not in {"yaml", "jsonl"} or compression not in {"none", "zstd"}):
        raise DataError("Unsupported canonical record format/compression")
    if path is not None:
        suffix = "." + record_format + (".zst" if compression == "zstd" else "")
        if not isinstance(path, str) or not path.endswith(suffix):
            raise DataError("Shard path disagrees with canonical format/compression")
    return record_format, compression


def _shard_records(build, catalog, entry):
    """Decode one checked frame and bound each canonical record before parsing."""
    record_format, compression = _record_encoding(catalog, entry["path"])
    decoder = zstandard.ZstdDecompressor(max_window_size=64 * 1024 * 1024).decompressobj() if compression == "zstd" else None
    limit = 32 * 1024 * 1024
    pending = bytearray()
    search_from = 0
    separator = b"\n" if record_format == "jsonl" else b"\n---\n"
    total = 0
    def parse(data):
        try:
            text = data.decode("utf-8")
            return parse_json(text) if record_format == "jsonl" else yaml.load(text, Loader=StrictLoader)
        except (UnicodeError, yaml.YAMLError) as exc:
            raise DataError("Malformed canonical shard record") from exc
    try:
        with safe_relative(build, entry["path"]).open("rb") as source:
            for chunk in iter(lambda: source.read(128 if decoder else 65536), b""):
                if decoder:
                    if decoder.eof:
                        raise DataError("Trailing bytes after canonical zstd frame")
                    chunk = decoder.decompress(chunk)
                    if decoder.unused_data:
                        raise DataError("Trailing bytes after canonical zstd frame")
                total += len(chunk)
                if total > entry["documents"] * limit:
                    raise DataError("Canonical shard exceeds decompressed record bound")
                pending.extend(chunk)
                consumed = 0
                while (position := pending.find(separator, search_from)) >= 0:
                    end = position + 1
                    if end - consumed > limit:
                        raise DataError("Canonical record exceeds 32 MiB bound")
                    record = parse(pending[consumed:end])
                    consumed = end
                    search_from = end
                    yield record
                # Compact once per input chunk. Only the new bytes and the
                # delimiter-sized overlap need scanning on the next iteration;
                # copying/rescanning a growing 32 MiB record is quadratic.
                if consumed:
                    del pending[:consumed]
                search_from = max(0, len(pending) - len(separator) + 1)
                if len(pending) > limit:
                    raise DataError("Canonical record exceeds 32 MiB bound")
            if decoder and not decoder.eof:
                raise DataError("Truncated canonical zstd frame")
            if pending:
                yield parse(pending)
    except zstandard.ZstdError as exc:
        raise DataError(f"Invalid canonical zstd frame: {exc}") from exc


def iter_records(build: Path, catalog: dict, source_id: str | None = None):
    """Validate records with a disk-backed identity ledger, including YAML-only use."""
    import json

    sources = {item["source"]["id"]: item["source"] for item in catalog["sources"]}
    snapshots = {item["source_id"]: item["snapshot_id"] for item in catalog["snapshots"]}
    selection = catalog["options"].get("document_selection")
    selected_ids = frozenset(selection["page_ids"]) if selection else None
    licensed = {
        value["id"]: value
        for value in read_json(safe_relative(build, catalog["licenses"]["path"]))["licenses"]
    }

    def index_rows(handle):
        def unique_pairs(pairs):
            row = {}
            for key, value in pairs:
                if key in row:
                    raise DataError("Duplicate document index key")
                row[key] = value
            return row

        for line in handle:
            try:
                row = json.loads(line, object_pairs_hook=unique_pairs)
            except (ValueError, TypeError) as exc:
                raise DataError("Malformed document index row") from exc
            if not isinstance(row, dict):
                raise DataError("Document index rows must be objects")
            if source_id is None or row.get("source_id") == source_id:
                yield row

    with tempfile.TemporaryDirectory(prefix="sentence-db-validate-") as temporary:
        ledger = sqlite3.connect(Path(temporary) / "identities.sqlite3")
        ledger.execute(
            "CREATE TABLE identities(kind TEXT, id TEXT, PRIMARY KEY(kind,id)) WITHOUT ROWID"
        )
        try:
            with safe_relative(build, catalog["document_index"]["path"]).open(
                encoding="utf-8"
            ) as index:
                rows = index_rows(index)
                for entry in catalog["shards"]:
                    if source_id is not None and entry["source_id"] != source_id:
                        continue
                    count = sentence_count = 0
                    for record in _shard_records(build, catalog, entry):
                        validate_record(record)
                        if (selection and record["source_id"] == selection["source_id"]
                                and record["native_id"] not in selected_ids):
                            raise DataError("Document is outside the selected Wikimedia pages")
                        if (
                            record["source_id"] != entry["source_id"]
                            or record["language"] != entry["language"]
                            or record["snapshot_id"] != snapshots[entry["source_id"]]
                        ):
                            raise DataError(
                                "Record source/language/snapshot does not match its shard"
                            )
                        if (
                            record["kind"] == "document"
                            and record["license"] != sources[record["source_id"]]["license"]
                        ):
                            raise DataError(
                                "Record license disagrees with current source adapter policy"
                            )
                        expected = {
                            "id": record["id"],
                            "source_id": record["source_id"],
                            "native_id": record["native_id"],
                            "title": record["title"],
                            "shard": entry["path"],
                            "position": count,
                        }
                        if next(rows, None) != expected:
                            raise DataError(
                                "Document index disagrees with canonical record order/identity"
                            )
                        try:
                            ledger.execute(
                                "INSERT INTO identities VALUES ('document',?)", (record["id"],)
                            )
                            ledger.execute(
                                "INSERT INTO identities VALUES ('native-document',?)",
                                (digest_json([record["source_id"], record["native_id"]]),),
                            )
                            ordinals = set()
                            for sentence in record.get("sentences", []):
                                if sentence["ordinal"] in ordinals:
                                    raise DataError("Duplicate sentence ordinal in document")
                                ordinals.add(sentence["ordinal"])
                                ledger.execute(
                                    "INSERT INTO identities VALUES ('sentence',?)",
                                    (sentence["id"],),
                                )
                                for translation in sentence["translations"]:
                                    ledger.execute(
                                        "INSERT INTO identities VALUES ('translation',?)",
                                        (translation["id"],),
                                    )
                            for value in [
                                record.get("license"),
                                *[
                                    tr["license"]
                                    for sentence in record.get("sentences", [])
                                    for tr in _all_translations(sentence)
                                ],
                            ]:
                                if value is not None and licensed.get(value["id"]) != value:
                                    raise DataError(
                                        "Record license is absent or differs from release notices"
                                    )
                        except sqlite3.IntegrityError as exc:
                            raise DataError("Duplicate identity in canonical corpus") from exc
                        count += 1
                        sentence_count += len(record.get("sentences", []))
                        yield record
                    if count != entry["documents"] or sentence_count != entry["sentences"]:
                        raise DataError("Shard record/sentence counts disagree with catalog")
                if next(rows, None) is not None:
                    raise DataError("Document index contains extra entries")
        finally:
            ledger.close()

