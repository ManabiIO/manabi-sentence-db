"""Read a pinned Tatoeba snapshot without network access.

The detailed TSV exports are unquoted, tab-separated UTF-8. Sentence text is not
CSV-unquoted or backslash-unescaped. Joins live in a temporary SQLite database;
only the current document and its direct translations are materialized in RAM.
"""

from __future__ import annotations

import bz2
import sqlite3
import tempfile
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

# Generous enough for real exports, but a corrupt field cannot consume all RAM.
MAX_FIELD_CHARS = 1_048_576
_NULL_VALUES = {"", r"\N", "0000-00-00 00:00:00"}
_LANGUAGES = {"jpn": "ja", "eng": "en"}


def _snapshot_path(snapshot_dir: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe Tatoeba snapshot path: {relative!r}")
    root = snapshot_dir.resolve()
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Tatoeba snapshot path escapes its directory: {relative!r}")
    if not resolved.is_file():
        raise ValueError(f"Missing Tatoeba snapshot file: {relative}")
    return resolved


def _rows(path: Path, columns: int) -> Iterator[tuple[int, list[str]]]:
    """Read finite-size TSV records, retaining quotes and literal backslashes."""
    opener = bz2.open if path.suffix == ".bz2" else open
    max_row = columns * (MAX_FIELD_CHARS + 1) + 2
    with opener(path, "rt", encoding="utf-8", newline="") as stream:
        line_number = 0
        while line := stream.readline(max_row + 1):
            line_number += 1
            if len(line) > max_row:
                raise ValueError(f"{path.name}:{line_number}: TSV row exceeds size limit")
            line = line.removesuffix("\n").removesuffix("\r")
            if not line:
                continue
            fields = line.split("\t")
            if len(fields) != columns:
                raise ValueError(
                    f"{path.name}:{line_number}: expected {columns} TSV fields, got {len(fields)}"
                )
            if any(len(field) > MAX_FIELD_CHARS for field in fields):
                raise ValueError(f"{path.name}:{line_number}: TSV field exceeds size limit")
            yield line_number, fields


def _sentence_id(value: str, path: Path, line: int) -> int:
    if not value.isascii() or not value.isdecimal() or len(value) > 19:
        raise ValueError(f"{path.name}:{line}: invalid Tatoeba sentence ID")
    result = int(value)
    if not 0 < result <= 9_223_372_036_854_775_807:
        raise ValueError(f"{path.name}:{line}: Tatoeba sentence ID is out of range")
    return result


def _timestamp(value: str, path: Path, line: int) -> str | None:
    if value in _NULL_VALUES:
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{path.name}:{line}: invalid Tatoeba modification date") from exc
    # Tatoeba exports database dates in UTC; old unknown dates are omitted above.
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sentences(path: Path, language: str) -> Iterator[tuple[int, str, str | None, str | None]]:
    for line, fields in _rows(path, 6):
        native_id, actual_language, text, owner, _added, modified = fields
        identifier = _sentence_id(native_id, path, line)
        if actual_language != language:
            raise ValueError(
                f"{path.name}:{line}: expected language {language}, got {actual_language!r}"
            )
        if not text.strip() or text == r"\N":
            continue
        yield (
            identifier,
            text,
            None if owner in _NULL_VALUES else owner,
            _timestamp(modified, path, line),
        )


def _url(identifier: int) -> str:
    return f"https://tatoeba.org/en/sentences/show/{identifier}"


def _attribution(identifier: int, owner: str | None) -> dict[str, str]:
    # Exported ownership is not an assertion of sole authorship. The sentence
    # page provides the history, including earlier contributors and edits.
    ownership = f"current owner: {owner}" if owner else "no current owner in export"
    return {
        "text": f"Tatoeba contributors, sentence {identifier} ({ownership})",
        "url": _url(identifier),
    }


def _prepare_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=FILE;
        PRAGMA cache_size=-8192;
        CREATE TABLE sentences (
            id INTEGER PRIMARY KEY, text TEXT NOT NULL, owner TEXT, modified TEXT
        );
        CREATE TABLE links (
            sentence_id INTEGER NOT NULL, target_id INTEGER NOT NULL,
            PRIMARY KEY (sentence_id, target_id)
        ) WITHOUT ROWID;
        CREATE INDEX links_target ON links(target_id);
        CREATE TABLE translations (
            id INTEGER PRIMARY KEY, language TEXT NOT NULL, text TEXT NOT NULL,
            owner TEXT
        );
        CREATE TABLE tags (
            sentence_id INTEGER NOT NULL, tag TEXT NOT NULL,
            PRIMARY KEY (sentence_id, tag)
        ) WITHOUT ROWID;
        """
    )


def iter_documents(manifest: dict, snapshot_dir: Path) -> Iterator[dict]:
    """Yield raw source documents for the central corpus builder.

    ``sentences-jpn`` is required. ``tags``/``tags-jpn``, direct ``links``, and
    ``sentences-eng`` are optional. Other ``sentences-<ISO-639-3>`` roles can add
    translations; their registered three-letter language code is retained unless
    a preferred code is in the small alias map above. No link traversal occurs.

    The snapshot loader is responsible for validating input checksums. This
    adapter validates local paths and TSV structure and performs no downloads.
    Closing the iterator early closes SQLite and removes its temporary files.
    """
    source = manifest["source"]
    primary_language = source.get("acquisition", {}).get("source_language", "jpn")
    primary_role = f"sentences-{primary_language}"
    files: dict[str, list[Path]] = {}
    for item in manifest["files"]:
        role = item.get("role", "")
        if role.startswith("sentences-") or role in {"links", "tags", "tags-jpn"}:
            files.setdefault(role, []).append(_snapshot_path(snapshot_dir, item["path"]))
    if primary_role not in files:
        raise ValueError(f"Tatoeba snapshot requires a {primary_role!r} file")

    license_info = dict(source["license"])
    with tempfile.TemporaryDirectory(prefix="manabi-tatoeba-") as temp_dir:
        connection = sqlite3.connect(Path(temp_dir) / "joins.sqlite3")
        try:
            _prepare_database(connection)
            for path in files[primary_role]:
                try:
                    connection.executemany(
                        "INSERT INTO sentences VALUES (?, ?, ?, ?)",
                        _sentences(path, primary_language),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ValueError(f"{path.name}: duplicate primary sentence ID") from exc
            connection.commit()

            def direct_links(path: Path) -> Iterator[tuple[int, int]]:
                for line, fields in _rows(path, 2):
                    first = _sentence_id(fields[0], path, line)
                    second = _sentence_id(fields[1], path, line)
                    if first != second:
                        yield first, second

            for path in files.get("links", []):
                connection.executemany(
                    """
                    INSERT OR IGNORE INTO links(sentence_id, target_id)
                    SELECT ?1, ?2 WHERE EXISTS (SELECT 1 FROM sentences WHERE id=?1)
                    UNION ALL
                    SELECT ?2, ?1 WHERE EXISTS (SELECT 1 FROM sentences WHERE id=?2)
                    """,
                    direct_links(path),
                )
            connection.commit()

            for role in sorted(files):
                if not role.startswith("sentences-") or role == primary_role:
                    continue
                language = role.removeprefix("sentences-")
                for path in files[role]:
                    rows = (
                        (identifier, _LANGUAGES.get(language, language), text, owner)
                        for identifier, text, owner, _modified in _sentences(path, language)
                    )
                    try:
                        connection.executemany(
                            """
                            INSERT INTO translations(id, language, text, owner)
                            SELECT ?1, ?2, ?3, ?4
                            WHERE EXISTS (SELECT 1 FROM links WHERE target_id=?1)
                            """,
                            rows,
                        )
                    except sqlite3.IntegrityError as exc:
                        raise ValueError(f"{path.name}: duplicate translation sentence ID") from exc
            connection.commit()

            def sentence_tags(path: Path) -> Iterator[tuple[int, str]]:
                for line, fields in _rows(path, 2):
                    identifier = _sentence_id(fields[0], path, line)
                    if fields[1].strip() and fields[1] != r"\N":
                        yield identifier, fields[1]

            for role in ("tags", "tags-jpn"):
                for path in files.get(role, []):
                    connection.executemany(
                        """
                        INSERT OR IGNORE INTO tags(sentence_id, tag)
                        SELECT ?1, ?2 WHERE EXISTS (SELECT 1 FROM sentences WHERE id=?1)
                        """,
                        sentence_tags(path),
                    )
            connection.commit()

            for identifier, text, owner, modified in connection.execute(
                "SELECT id, text, owner, modified FROM sentences ORDER BY id"
            ):
                tags = [
                    row[0]
                    for row in connection.execute(
                        "SELECT tag FROM tags WHERE sentence_id=? ORDER BY tag", (identifier,)
                    )
                ]
                translations = []
                for target_id, language, translated_text, target_owner in connection.execute(
                    """
                    SELECT t.id, t.language, t.text, t.owner
                    FROM links AS l JOIN translations AS t ON t.id=l.target_id
                    WHERE l.sentence_id=? ORDER BY t.language, t.id
                    """,
                    (identifier,),
                ):
                    translations.append(
                        {
                            "language": language,
                            "text": translated_text,
                            "source_url": _url(target_id),
                            "license": dict(license_info),
                            "attribution": _attribution(target_id, target_owner),
                            "native_id": str(target_id),
                            "alignment": "direct-link",
                        }
                    )
                revision = {"url": _url(identifier)}
                if modified:
                    revision["timestamp"] = modified
                yield {
                    "native_id": str(identifier),
                    "title": f"Tatoeba sentence {identifier}",
                    "url": _url(identifier),
                    "language": source["language"],
                    "license": dict(license_info),
                    "attribution": _attribution(identifier, owner),
                    "revision": revision,
                    "tags": [],
                    "sentences": [
                        {
                            "text": text,
                            "native_id": str(identifier),
                            "tags": tags,
                            "content_flags": [],
                            "translations": translations,
                        }
                    ],
                }
        finally:
            connection.close()
