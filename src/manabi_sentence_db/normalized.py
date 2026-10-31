"""Portable normalized JSONL interchange, with a disk-backed deduplication ledger.

Exact NFC sentence text is identity; occurrences retain their independent rights.
No probabilistic normalization is allowed to collapse distinct original spellings.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import zipfile
from contextlib import ExitStack
from pathlib import Path

import zstandard

from .serialization import DataError, canonical_json, digest_json


def sentence_identity(language: str, text: str) -> str:
    return "s_" + hashlib.sha256(canonical_json([language, text])).hexdigest()


def export_normalized(build: Path, output: Path, *, source_id=None, catalog=None,
                      work_selection=None) -> Path:
    from .build import iter_records, verify_build

    catalog = catalog or verify_build(build)
    selected = None
    if work_selection is not None:
        if (not isinstance(work_selection, dict)
                or set(work_selection) != {"schema_version", "build_id", "work_ids"}
                or type(work_selection["schema_version"]) is not int
                or work_selection["schema_version"] != 1
                or work_selection["build_id"] != catalog["build_id"]):
            raise DataError("Work selection must bind schema version 1 to this exact build")
        identities = work_selection["work_ids"]
        if (not isinstance(identities, list) or not identities
                or any(not isinstance(value, str) or not value.strip() or len(value) > 256
                       for value in identities)
                or len(set(identities)) != len(identities)):
            raise DataError("Work selection requires unique, nonempty work-ID strings")
        selected = set(identities)
        unmatched = set(identities)
        work_selection = {**work_selection, "work_ids": sorted(identities)}
    if output.exists() or output.is_symlink():
        raise DataError(f"Output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".normalized-", dir=output.parent) as temporary:
        root = Path(temporary)
        with sqlite3.connect(root / "ledger.sqlite") as db, ExitStack() as stack:
            db.execute("CREATE TABLE seen(id TEXT PRIMARY KEY) WITHOUT ROWID")
            names = ("works", "sentences", "occurrences", "translations", "references")
            # Keep bulk source text compressed throughout staging. The public
            # ZIP still contains ordinary JSONL members for existing consumers.
            handles = {
                name: stack.enter_context(zstandard.open(
                    root / f"{name}.jsonl.zst", "wb",
                    cctx=zstandard.ZstdCompressor(level=3, write_checksum=True),
                ))
                for name in names
            }
            counts = dict.fromkeys(names, 0)
            digests = {name: hashlib.sha256() for name in names}

            def write(name, value):
                data = canonical_json(value) + b"\n"
                handles[name].write(data)
                digests[name].update(data)
                counts[name] += 1

            try:
                for record in iter_records(build, catalog, source_id):
                    if selected is not None:
                        if record["kind"] != "document" or record["id"] not in selected:
                            continue
                        unmatched.discard(record["id"])
                    if record["kind"] == "reference":
                        write("references", record)
                        continue
                    work = {k: v for k, v in record.items() if k != "sentences"}
                    # A latest revision date is NOT a publication date.
                    work.setdefault("published_at", None)
                    work.setdefault("language_origin", "unknown")
                    work.setdefault("authorship", "unknown")
                    snapshot = next(
                        s for s in catalog["snapshots"] if s["snapshot_id"] == record["snapshot_id"]
                    )
                    work["snapshot_manifest"] = snapshot["manifest"]
                    write("works", work)
                    items = record["sentences"]
                    for index, item in enumerate(items):
                        identity = sentence_identity(record["language"], item["text"])
                        if db.execute(
                            "INSERT OR IGNORE INTO seen VALUES (?)", (identity,)
                        ).rowcount:
                            write(
                                "sentences",
                                {
                                    "id": identity,
                                    "language": record["language"],
                                    "text": item["text"],
                                    "text_sha256": item["text_sha256"],
                                },
                            )
                        occurrence = {
                            k: v
                            for k, v in item.items()
                            if k not in ("text", "text_sha256", "translations")
                        }
                        occurrence.update(
                            sentence_id=identity,
                            work_id=record["id"],
                            previous_id=(
                                items[index - 1]["id"]
                                if index and items[index - 1]["ordinal"] == item["ordinal"] - 1
                                else None
                            ),
                            next_id=(
                                items[index + 1]["id"]
                                if index + 1 < len(items)
                                and items[index + 1]["ordinal"] == item["ordinal"] + 1
                                else None
                            ),
                        )
                        write("occurrences", occurrence)
                        for translation in item["translations"]:
                            write(
                                "translations",
                                dict(translation, sentence_id=identity, occurrence_id=item["id"]),
                            )
            finally:
                for handle in handles.values():
                    handle.close()
            if selected is not None and unmatched:
                raise DataError("Selected works absent from build/source: "
                                + ", ".join(sorted(unmatched)[:5]))
        manifest = {
            "schema_version": 2,
            "kind": "normalized-corpus",
            "build_id": catalog["build_id"],
            "scope": "sample" if selected is not None else catalog["scope"],
            "source_id": source_id,
            "counts": counts,
            "identity": "sha256(canonical_json([language,NFC_text]))",
            "members": {f"{name}.jsonl": digests[name].hexdigest() for name in names},
        }
        if selected is not None:
            manifest.update(work_selection=work_selection,
                            work_selection_sha256=digest_json(work_selection))
        _write_normalized_archive(root, build, catalog, source_id, manifest, compressed_tables=True)
        with zipfile.ZipFile(root / "corpus.zip") as archive:
            if archive.testzip() is not None:
                raise DataError("Normalized archive failed CRC verification")
        os.replace(root / "corpus.zip", output)
    return output


def _write_normalized_archive(root, build, catalog, source_id, manifest, *, compressed_tables=False):
    """Stream verified staging files with reproducible ZIP transport metadata.

    Embedded provenance bytes are unchanged. Byte reproducibility assumes the
    same Python/zlib runtime, not identical compressed output across codecs.
    """
    def info(name):
        member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        member.compress_type = zipfile.ZIP_DEFLATED
        member.create_system = 3
        member.external_attr = 0o100644 << 16
        return member

    with zipfile.ZipFile(
        root / "corpus.zip", "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        def write_file(path, name, *, compressed=False, expected_hash=None):
            digest = hashlib.sha256()
            with archive.open(info(name), "w", force_zip64=True) as outgoing:
                with (zstandard.open(path, "rb") if compressed else path.open("rb")) as incoming:
                    for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                        outgoing.write(chunk)
                        digest.update(chunk)
            if expected_hash is not None and digest.hexdigest() != expected_hash:
                raise DataError(f"Normalized staging bytes changed: {name}")

        for name in ("works", "sentences", "occurrences", "translations", "references"):
            member = f"{name}.jsonl"
            write_file(root / (member + ".zst" if compressed_tables else member), member,
                       compressed=compressed_tables, expected_hash=manifest["members"][member])
        archive.writestr(info("manifest.json"), canonical_json(manifest), compresslevel=6)
        for name in ("licenses.json", "catalog.json"):
            write_file(build / name, name)
        for snapshot in catalog["snapshots"]:
            if source_id is None or snapshot["source_id"] == source_id:
                write_file(build / snapshot["manifest"], snapshot["manifest"])
