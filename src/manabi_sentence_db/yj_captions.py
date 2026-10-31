"""Pinned original Japanese caption text, streamed without image imports."""

import codecs
import hashlib
import sqlite3
import stat
import tempfile
import zipfile
from collections import Counter
from contextlib import closing
from pathlib import Path

from .json_stream import array_items
from .serialization import DataError, canonical_json, safe_relative, sha256_file
from .text import is_complete_sentence

ROLE = "yj-captions-zip"
REVISION = "2f2d6de87ce90b7ff1fd318efef17b1ce0e127db"
SHA256 = "e2978ac2770f571a012d280ffe9c69f3612be9c104d3cd5cf7116249a4006503"
HOMEPAGE = "https://github.com/yahoojapan/YJCaptions"
MEMBER = "yjcaptions26k_clean.json"
MAX_MEMBER_BYTES = 28825849
MAX_ARCHIVE_BYTES = 4257429


def iter_documents(manifest, snapshot_dir, *, stats=None):
    stats = stats if stats is not None else Counter()
    source = manifest["source"]
    acquisition = source["acquisition"]
    url = f"{HOMEPAGE}/blob/{REVISION}/yjcaptions26k.zip"
    if (acquisition.get("revision") != REVISION or source["homepage"] != HOMEPAGE
            or acquisition.get("sha256") != SHA256
            or type(acquisition.get("size")) is not int
            or acquisition.get("size") != MAX_ARCHIVE_BYTES
            or acquisition.get("url") != f"https://raw.githubusercontent.com/yahoojapan/YJCaptions/{REVISION}/yjcaptions26k.zip"
            or source["license"] != {"id": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"}):
        raise DataError("YJ Captions requires the reviewed revision, publisher and caption license")
    entries = [entry for entry in manifest["files"] if entry["role"] == ROLE]
    if len(entries) != 1:
        raise DataError("Expected exactly one YJ Captions archive")
    path = safe_relative(snapshot_dir, entries[0]["path"])
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise DataError("Oversized YJ Captions archive")
    if sha256_file(path) != SHA256:
        raise DataError("YJ Captions archive checksum differs from reviewed release")
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) != 1 or infos[0].filename != MEMBER:
                raise DataError("Invalid YJ Captions ZIP inventory")
            member = infos[0]
            mode = member.external_attr >> 16
            if (member.is_dir() or (stat.S_IFMT(mode) not in (0, stat.S_IFREG))
                    or member.flag_bits & 1 or not 0 < member.file_size <= MAX_MEMBER_BYTES):
                raise DataError("Invalid or oversized YJ Captions regular member")
            with tempfile.TemporaryDirectory(prefix="yj-caption-identities-") as temporary:
                with closing(sqlite3.connect(Path(temporary) / "ids.sqlite")) as ledger:
                    ledger.execute("CREATE TABLE seen(id INTEGER PRIMARY KEY)")
                    with archive.open(member) as raw:
                        with codecs.getreader("utf-8")(raw) as stream:
                            for row in array_items(stream, "annotations"):
                                stats["publisher_captions_seen"] += 1
                                if not isinstance(row, dict):
                                    raise DataError("Invalid YJ caption row")
                                identity, image_id, text = row.get("id"), row.get("image_id"), row.get("caption")
                                if (type(identity) is not int or not 0 <= identity <= 2**63 - 1
                                        or type(image_id) is not int or not 0 <= image_id <= 2**63 - 1
                                        or not isinstance(text, str) or not text.strip()
                                        or len(text) > 10000):
                                    raise DataError("Invalid YJ caption identity/text")
                                try:
                                    ledger.execute("INSERT INTO seen VALUES (?)", (identity,))
                                except sqlite3.IntegrityError as error:
                                    raise DataError("Duplicate YJ caption identity") from error
                                if not is_complete_sentence(text, "ja"):
                                    stats["rejected:yj-incomplete-caption"] += 1
                                    continue
                                yield {
                                    "native_id": str(identity), "language": "ja",
                                    "title": f"YJ Captions · Caption {identity}", "url": url,
                                    "license": source["license"], "attribution": source["attribution"],
                                    "revision": {"id": REVISION, "url": url},
                                    "tags": ["image-caption", f"image-id:{image_id}", "context:image-not-included"],
                                    "authorship": "human", "language_origin": "original_japanese",
                                    "content_type": "caption",
                                    "source_text_hash": hashlib.sha256(canonical_json(row)).hexdigest(),
                                    "sentences": [{"native_id": str(identity), "text": text,
                                                   "tags": [], "content_flags": [], "translations": []}],
                                }
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, UnicodeError) as error:
        raise DataError("Invalid YJ Captions ZIP/JSON encoding") from error
