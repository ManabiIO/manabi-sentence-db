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
from pathlib import Path

from .build import iter_records, verify_build
from .serialization import DataError, canonical_json, sha256_file


def sentence_identity(language: str, text: str) -> str:
    return "s_" + hashlib.sha256(canonical_json([language, text])).hexdigest()


def export_normalized(build: Path, output: Path, *, source_id=None, catalog=None) -> Path:
    catalog = catalog or verify_build(build)
    if output.exists() or output.is_symlink():
        raise DataError(f"Output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".normalized-", dir=output.parent) as temporary:
        root = Path(temporary)
        with sqlite3.connect(root / "ledger.sqlite") as db:
            db.execute("CREATE TABLE seen(id TEXT PRIMARY KEY) WITHOUT ROWID")
            names = ("works", "sentences", "occurrences", "translations", "references")
            handles = {name: (root / f"{name}.jsonl").open("wb") for name in names}
            counts = dict.fromkeys(names, 0)

            def write(name, value):
                handles[name].write(canonical_json(value) + b"\n")
                counts[name] += 1

            try:
                for record in iter_records(build, catalog, source_id):
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
                            previous_id=items[index - 1]["id"] if index else None,
                            next_id=items[index + 1]["id"] if index + 1 < len(items) else None,
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
        manifest = {
            "schema_version": 2,
            "kind": "normalized-corpus",
            "build_id": catalog["build_id"],
            "scope": catalog["scope"],
            "source_id": source_id,
            "counts": counts,
            "identity": "sha256(canonical_json([language,NFC_text]))",
            "members": {f"{name}.jsonl": sha256_file(root / f"{name}.jsonl") for name in names},
        }
        # Fixed member timestamps make identical records reproducible.
        with zipfile.ZipFile(
            root / "corpus.zip", "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            for name in names:
                info = zipfile.ZipInfo(f"{name}.jsonl")
                info.compress_type = zipfile.ZIP_DEFLATED
                with archive.open(info, "w", force_zip64=True) as outgoing:
                    with (root / f"{name}.jsonl").open("rb") as incoming:
                        import shutil

                        shutil.copyfileobj(incoming, outgoing)
            archive.writestr("manifest.json", canonical_json(manifest))
            archive.write(build / "licenses.json", "licenses.json")
            archive.write(build / "catalog.json", "catalog.json")
            for snapshot in catalog["snapshots"]:
                if source_id is None or snapshot["source_id"] == source_id:
                    archive.write(build / snapshot["manifest"], snapshot["manifest"])
        with zipfile.ZipFile(root / "corpus.zip") as archive:
            if archive.testzip() is not None:
                raise DataError("Normalized archive failed CRC verification")
        os.replace(root / "corpus.zip", output)
    return output
