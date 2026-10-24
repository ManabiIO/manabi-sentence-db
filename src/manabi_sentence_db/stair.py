"""Stream original Japanese caption text, never images or tokenized duplicates."""

import codecs
import hashlib
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from pathlib import Path

from .json_stream import array_items
from .serialization import DataError, canonical_json, safe_relative

MEMBERS = {"stair_captions_v1.2_train.json", "stair_captions_v1.2_val.json"}


def iter_documents(manifest, snapshot_dir):
    source = manifest["source"]
    revision = source["acquisition"]["revision"]
    url = f"{source['homepage']}/blob/{revision}/stair_captions_v1.2.tar.gz"
    with tempfile.TemporaryDirectory(prefix="stair-identities-") as temporary:
        with closing(sqlite3.connect(Path(temporary) / "ids.sqlite")) as ledger:
            ledger.execute("CREATE TABLE seen(id INTEGER PRIMARY KEY)")
            seen_members = set()
            for entry in manifest["files"]:
                if entry["role"] not in {"stair-tar", "stair-captions"}:
                    continue
                with tarfile.open(safe_relative(snapshot_dir, entry["path"]), mode="r|gz") as archive:
                    for member in archive:
                        if member.name not in MEMBERS:
                            continue
                        if member.name in seen_members or not member.isfile():
                            raise DataError("Invalid or duplicate STAIR member")
                        seen_members.add(member.name)
                        if member.size > 256 * 1024**2:
                            raise DataError("Oversized STAIR caption member")
                        with archive.extractfile(member) as raw_stream:
                            with codecs.getreader("utf-8")(raw_stream) as stream:
                                for row in array_items(stream, "annotations"):
                                    if not isinstance(row, dict):
                                        raise DataError("Invalid STAIR caption")
                                    identity, image_id = row.get("id"), row.get("image_id")
                                    if (type(identity) is not int or identity < 0
                                            or type(image_id) is not int or image_id < 0
                                            or not isinstance(row.get("caption"), str)):
                                        raise DataError("Invalid STAIR caption identity/text")
                                    try:
                                        ledger.execute("INSERT INTO seen VALUES (?)", (identity,))
                                    except sqlite3.IntegrityError as error:
                                        raise DataError("Duplicate STAIR caption identity") from error
                                    yield {
                                        "native_id": str(identity),
                                        "language": "ja",
                                        "title": f"STAIR Captions · Caption {identity}",
                                        "url": url,
                                        "license": source["license"],
                                        "attribution": source["attribution"],
                                        "revision": {"id": revision, "url": url},
                                        "tags": ["image-caption", f"image-id:{image_id}",
                                                 "context:image-not-included"],
                                        "authorship": "human",
                                        "language_origin": "original_japanese",
                                        "content_type": "caption",
                                        "source_text_hash": hashlib.sha256(
                                            canonical_json(row)
                                        ).hexdigest(),
                                        "sentences": [{"native_id": str(identity),
                                                       "text": row["caption"], "tags": [],
                                                       "content_flags": [], "translations": []}],
                                    }
            if seen_members != MEMBERS:
                raise DataError("Missing STAIR train/validation text member")
