"""Explicit, immutable upstream acquisition. Corpus builds never call this module."""

from __future__ import annotations

import hashlib
import http.client
import json
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date as Date
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from .serialization import canonical_json, read_json, sha256_file

DEFAULT_USER_AGENT = "ManabiSentenceDB/0.1 (+https://github.com/ManabiIO/manabi-sentence-db)"
METADATA_LIMIT = 16 * 1024 * 1024
READ_SIZE = 1024 * 1024
RETRIES = 4
RETRY_STATUSES = {429, 500, 502, 503, 504}
_last_request_at = 0.0


class SnapshotError(ValueError):
    """A source could not be snapshotted or an existing snapshot is invalid."""


def safe_filename(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or ":" in value
        or "\x00" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or Path(value).is_absolute()
    ):
        raise SnapshotError(f"Unsafe snapshot filename: {value!r}")
    return value


def _https(url: str) -> str:
    if not isinstance(url, str):
        raise SnapshotError("Expected an HTTPS source URL string")
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or any(ord(char) < 32 for char in url)
    ):
        raise SnapshotError(f"Expected an HTTPS source URL: {url!r}")
    return url


class _HTTPSRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _delay(headers: Any, attempt: int) -> float:
    delay = min(2**attempt, 30)
    value = headers.get("Retry-After") if headers else None
    if value:
        try:
            delay = max(delay, float(value))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                delay = max(delay, (retry_at - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError):
                pass
    if delay > 60:
        raise SnapshotError(f"Server requested a {delay:.0f}s pause; retry this snapshot later")
    return max(0, delay)


def _open(url: str, user_agent: str):
    global _last_request_at
    request = urllib.request.Request(_https(url), headers={"User-Agent": user_agent})
    opener = urllib.request.build_opener(_HTTPSRedirects())
    for attempt in range(RETRIES):
        time.sleep(max(0, 1 - (time.monotonic() - _last_request_at)))
        _last_request_at = time.monotonic()
        try:
            return opener.open(request, timeout=60)
        except urllib.error.HTTPError as error:
            if error.code not in RETRY_STATUSES or attempt == RETRIES - 1:
                raise SnapshotError(f"Download failed ({error.code}): {url}") from error
            time.sleep(_delay(error.headers, attempt))
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == RETRIES - 1:
                raise SnapshotError(f"Download failed: {url}: {error}") from error
            time.sleep(_delay(None, attempt))
    raise AssertionError("unreachable")


def _metadata(url: str, user_agent: str) -> bytes:
    with _open(url, user_agent) as response:
        data = response.read(METADATA_LIMIT + 1)
    if len(data) > METADATA_LIMIT:
        raise SnapshotError(f"Upstream metadata exceeds {METADATA_LIMIT} bytes: {url}")
    return data


def _api_json(url: str, user_agent: str) -> bytes:
    for attempt in range(RETRIES):
        with _open(url, user_agent) as response:
            data = response.read(METADATA_LIMIT + 1)
            headers = response.headers
        if len(data) > METADATA_LIMIT:
            raise SnapshotError("API sample is too large; select fewer pages")
        document = json.loads(data)
        error = document.get("error")
        if not error:
            return data
        if error.get("code") not in {"maxlag", "ratelimited"} or attempt == RETRIES - 1:
            raise SnapshotError(f"MediaWiki API error: {error.get('code')}: {error.get('info')}")
        time.sleep(max(5, _delay(headers, attempt)))
    raise AssertionError("unreachable")


def _record(path: Path, role: str, url: str, **extra: Any) -> dict:
    return {
        "path": path.name,
        "role": role,
        "url": url,
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
        **extra,
    }


def _save_metadata(directory: Path, name: str, role: str, url: str, data: bytes) -> dict:
    path = directory / safe_filename(name)
    path.write_bytes(data)
    return _record(path, role, url)


def _download(
    directory: Path,
    name: str,
    role: str,
    url: str,
    user_agent: str,
    *,
    expected_sha256: str | None = None,
    expected_sha1: str | None = None,
    expected_size: int | None = None,
) -> dict:
    path = directory / safe_filename(name)
    if path.exists():
        raise SnapshotError(f"Duplicate upstream filename: {name}")
    temporary = path.with_name(path.name + ".part")
    for attempt in range(RETRIES):
        digest = hashlib.sha256()
        legacy_digest = hashlib.sha1()  # Legacy upstream integrity, never our content identity.
        size = 0
        try:
            with _open(url, user_agent) as response, temporary.open("xb") as target:
                for chunk in iter(lambda: response.read(READ_SIZE), b""):
                    size += len(chunk)
                    if expected_size is not None and size > expected_size:
                        raise SnapshotError(f"Upstream size changed: {name}")
                    digest.update(chunk)
                    legacy_digest.update(chunk)
                    target.write(chunk)
                content_length = response.headers.get("Content-Length")
                if content_length and size != int(content_length):
                    raise ConnectionError(f"Truncated download: {name}")
            if expected_size is not None and size != expected_size:
                raise ConnectionError(f"Truncated download: {name}")
            if expected_sha256 and digest.hexdigest() != expected_sha256:
                raise SnapshotError(f"Upstream SHA-256 mismatch: {name}")
            if expected_sha1 and legacy_digest.hexdigest() != expected_sha1:
                raise SnapshotError(f"Upstream SHA-1 mismatch: {name}")
            temporary.rename(path)
            break
        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            http.client.IncompleteRead,
        ) as error:
            if attempt == RETRIES - 1:
                raise SnapshotError(f"Download interrupted repeatedly: {name}") from error
            time.sleep(_delay(None, attempt))
        finally:
            temporary.unlink(missing_ok=True)
    return {
        "path": name,
        "role": role,
        "url": url,
        "sha256": digest.hexdigest(),
        "size": size,
        **({"upstream_sha1": expected_sha1} if expected_sha1 else {}),
    }


def _sample(source: dict, directory: Path, titles: list[str], user_agent: str) -> list[dict]:
    if not titles or len(titles) > 10:
        raise SnapshotError("A Wikimedia sample requires between 1 and 10 page titles")
    if any(not isinstance(title, str) or not title or "|" in title for title in titles):
        raise SnapshotError("Sample titles must be nonempty strings without '|'")
    parameters = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "prop": "revisions",
        "rvprop": "ids|timestamp|content",
        "rvslots": "main",
        "redirects": "1",
        "maxlag": "5",
        "titles": "|".join(titles),
    }
    url = source["acquisition"]["api_url"] + "?" + urllib.parse.urlencode(parameters)
    data = _api_json(url, user_agent)
    parsed = json.loads(data)
    pages = parsed.get("query", {}).get("pages", [])
    if not pages or any("missing" in page or not page.get("revisions") for page in pages):
        raise SnapshotError("One or more sample pages are missing or have no accessible revision")
    if "continue" in parsed:
        raise SnapshotError("Sample response was truncated; select fewer pages")
    return [_save_metadata(directory, "sample.json", "mediawiki-api", url, data)]


def _content_export(
    source: dict, directory: Path, date: str, max_files: int | None, user_agent: str
) -> list[dict]:
    wiki = source["acquisition"]["wiki_id"]
    if not re.fullmatch(r"[a-z][a-z0-9_]*", wiki):
        raise SnapshotError("Invalid Wikimedia database ID")
    base = f"https://dumps.wikimedia.org/other/mediawiki_content_current/{wiki}/{date}/xml/bzip2/"
    url = base + "SHA256SUMS"
    data = _metadata(url, user_agent)
    files = [_save_metadata(directory, "SHA256SUMS", "upstream-checksums", url, data)]
    entries = []
    names: set[str] = set()
    for line in data.decode("utf-8").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})\s+\*?(.+)", line)
        if not match:
            raise SnapshotError("Malformed upstream SHA256SUMS")
        digest, name = match.groups()
        safe_filename(name)
        if name in names or not name.endswith(".xml.bz2"):
            raise SnapshotError(f"Unexpected or duplicate export filename: {name}")
        names.add(name)
        entries.append((name, digest))
    if not entries:
        raise SnapshotError("The upstream export contains no XML files")
    for name, digest in sorted(entries)[:max_files]:
        files.append(
            _download(
                directory,
                name,
                "mediawiki-xml",
                base + urllib.parse.quote(name),
                user_agent,
                expected_sha256=digest,
            )
        )
    return files


def _legacy_export(
    source: dict, directory: Path, date: str, max_files: int | None, user_agent: str
) -> list[dict]:
    wiki = source["acquisition"]["wiki_id"]
    if not re.fullmatch(r"[a-z][a-z0-9_]*", wiki):
        raise SnapshotError("Invalid Wikimedia database ID")
    base = f"https://dumps.wikimedia.org/{wiki}/{date.replace('-', '')}/"
    url = base + "dumpstatus.json"
    data = _metadata(url, user_agent)
    files = [_save_metadata(directory, "dumpstatus.json", "upstream-index", url, data)]
    job = json.loads(data).get("jobs", {}).get("articlesdump", {})
    if job.get("status") != "done":
        raise SnapshotError("The explicit legacy articles dump is not complete")
    entries = job.get("files", {})
    if not entries:
        raise SnapshotError("The legacy articles dump contains no files")
    for name, details in sorted(entries.items())[:max_files]:
        safe_filename(name)
        if not name.endswith(".xml.bz2"):
            raise SnapshotError(f"Unexpected legacy articles file: {name}")
        expected_url = urllib.parse.urljoin(base, details["url"])
        if expected_url != base + name:
            raise SnapshotError("Legacy dump index points outside its dated directory")
        sha1 = details.get("sha1")
        if not isinstance(sha1, str) or not re.fullmatch(r"[0-9a-f]{40}", sha1):
            raise SnapshotError("Legacy dump has no valid upstream SHA-1")
        files.append(
            _download(
                directory,
                name,
                "mediawiki-xml",
                expected_url,
                user_agent,
                expected_sha1=sha1,
                expected_size=details["size"],
            )
        )
    return files


def _tatoeba(source: dict, directory: Path, translations: list[str], user_agent: str) -> list[dict]:
    files = []
    requested = set(translations)
    if requested - {"eng", "en"}:
        raise SnapshotError("The initial Tatoeba adapter supports English translations only")
    for entry in source["acquisition"]["files"]:
        role = entry["role"]
        if role in {"sentences-eng", "links"} and not requested:
            continue
        name = urllib.parse.unquote(urllib.parse.urlsplit(entry["url"]).path.rsplit("/", 1)[-1])
        files.append(_download(directory, name, role, entry["url"], user_agent))
    roles = {item["role"] for item in files}
    if "sentences-jpn" not in roles or (requested and not {"sentences-eng", "links"} <= roles):
        raise SnapshotError("Tatoeba source configuration lacks required export roles")
    return files


def snapshot_identity(manifest: dict) -> str:
    identity = {
        "schema_version": manifest["schema_version"],
        "source_id": manifest["source_id"],
        "source_config_sha256": manifest["source_config_sha256"],
        "mode": manifest["mode"],
        "upstream_date": manifest["upstream_date"],
        "request": manifest["request"],
        "files": manifest["files"],
    }
    return hashlib.sha256(canonical_json(identity)).hexdigest()


def verify_snapshot(manifest_path: Path) -> dict:
    manifest_path = Path(manifest_path)
    try:
        manifest = read_json(manifest_path)
        if not isinstance(manifest, dict):
            raise SnapshotError("Snapshot manifest must be an object")
        if (
            type(manifest["schema_version"]) is not int
            or manifest["schema_version"] != 1
            or manifest["mode"] not in {"sample", "full", "partial"}
        ):
            raise SnapshotError("Unsupported snapshot version or scope")
        if not isinstance(manifest["source_id"], str) or not re.fullmatch(
            r"[a-z][a-z0-9-]+", manifest["source_id"]
        ):
            raise SnapshotError("Invalid snapshot source ID")
        if not isinstance(manifest["source"], dict):
            raise SnapshotError("Snapshot source configuration must be an object")
        if manifest["source_id"] != manifest["source"]["id"]:
            raise SnapshotError("Snapshot source identity mismatch")
        if (
            manifest["source_config_sha256"]
            != hashlib.sha256(canonical_json(manifest["source"])).hexdigest()
        ):
            raise SnapshotError("Snapshot source configuration hash mismatch")
        if manifest["snapshot_id"] != snapshot_identity(manifest):
            raise SnapshotError("Snapshot manifest identity mismatch")
        retrieved = datetime.fromisoformat(manifest["retrieved_at"])
        if retrieved.tzinfo is None:
            raise SnapshotError("Snapshot acquisition time must include a timezone")
        if (
            manifest["upstream_date"] is not None
            and Date.fromisoformat(manifest["upstream_date"]).isoformat()
            != manifest["upstream_date"]
        ):
            raise SnapshotError("Invalid upstream date")
        request = manifest["request"]
        if not isinstance(request, dict):
            raise SnapshotError("Snapshot request must be an object")
        if request == {"synthetic": True}:
            if manifest["mode"] != "sample" or manifest["upstream_date"] is not None:
                raise SnapshotError("Synthetic fixtures must remain samples")
        else:
            if (
                request.get("mode") not in {"sample", "full"}
                or request.get("date") != manifest["upstream_date"]
            ):
                raise SnapshotError("Snapshot request and scope disagree")
            maximum = request.get("max_files")
            if maximum is not None and (
                type(maximum) is not int or maximum < 1 or request["mode"] != "full"
            ):
                raise SnapshotError("Invalid snapshot chunk limit")
            expected_mode = "partial" if maximum is not None else request["mode"]
            if expected_mode != manifest["mode"]:
                raise SnapshotError("Snapshot scope does not describe the acquisition request")
        names = set()
        if not isinstance(manifest["files"], list) or not manifest["files"]:
            raise SnapshotError("Snapshot has no files")
        for entry in manifest["files"]:
            if (
                not isinstance(entry, dict)
                or type(entry.get("size")) is not int
                or entry["size"] < 0
            ):
                raise SnapshotError("Invalid snapshot file size")
            if not isinstance(entry.get("sha256"), str) or not re.fullmatch(
                r"[0-9a-f]{64}", entry["sha256"]
            ):
                raise SnapshotError("Invalid snapshot file SHA-256")
            if not isinstance(entry.get("role"), str) or not entry["role"]:
                raise SnapshotError("Missing snapshot file role")
            _https(entry["url"])
            name = safe_filename(entry["path"])
            if name == "manifest.json":
                raise SnapshotError("Reserved snapshot filename")
            if name in names:
                raise SnapshotError(f"Duplicate snapshot file: {name}")
            names.add(name)
            path = manifest_path.parent / name
            if path.is_symlink() or not path.is_file():
                raise SnapshotError(f"Missing snapshot file: {name}")
            if path.stat().st_size != entry["size"] or sha256_file(path) != entry["sha256"]:
                raise SnapshotError(f"Snapshot content mismatch: {name}")
    except SnapshotError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise SnapshotError(f"Malformed snapshot manifest: {error}") from error
    return manifest


def manifest_files(manifest_path: Path, role: str | None = None) -> list[tuple[dict, Path]]:
    manifest = verify_snapshot(manifest_path)
    return [
        (entry, Path(manifest_path).parent / entry["path"])
        for entry in manifest["files"]
        if role is None or entry["role"] == role
    ]


def create_snapshot(
    source: dict,
    output: Path,
    mode: str = "sample",
    date: str | None = None,
    titles: list[str] | None = None,
    max_files: int | None = None,
    refresh: bool = False,
    user_agent: str | None = None,
    translations: list[str] | None = None,
) -> Path:
    """Create an immutable snapshot; unchanged repeated requests make zero HTTP calls.

    A changed refresh is stored in an ID-suffixed sibling, preserving the old snapshot.
    The returned path is always the actual manifest, which callers must retain.
    """
    output = Path(output)
    adapter = source["adapter"]
    if mode not in {"sample", "full"}:
        raise SnapshotError("Snapshot mode must be sample or full")
    if titles is not None and mode != "sample":
        raise SnapshotError("--title applies only to Wikimedia API samples")
    if translations and adapter != "tatoeba":
        raise SnapshotError("--translations applies only to Tatoeba acquisition")
    if max_files is not None and (type(max_files) is not int or max_files < 1):
        raise SnapshotError("max_files must be a positive integer")
    if max_files is not None and mode != "full":
        raise SnapshotError("max_files is only valid for full export acquisition")
    if date is not None:
        if mode != "full":
            raise SnapshotError(
                "--date applies only to full Wikimedia exports; samples pin current revisions"
            )
        try:
            if Date.fromisoformat(date).isoformat() != date:
                raise ValueError
        except ValueError as error:
            raise SnapshotError("Snapshot date must be YYYY-MM-DD") from error
    source_hash = hashlib.sha256(canonical_json(source)).hexdigest()
    requested_titles = sorted(set(titles or source["acquisition"].get("sample_titles", [])))
    requested_translations = sorted(set(translations or []))
    request = {
        "mode": mode,
        "date": date,
        "titles": requested_titles if mode == "sample" else [],
        "max_files": max_files,
        "translations": requested_translations,
    }
    existing_manifest = output / "manifest.json"
    existing = None
    if existing_manifest.exists():
        existing = verify_snapshot(existing_manifest)
        if not refresh:
            if existing["source_config_sha256"] != source_hash or existing["request"] != request:
                raise SnapshotError(
                    "Existing snapshot has a different request; use a new output or --refresh"
                )
            return existing_manifest
    elif output.exists():
        raise SnapshotError(f"Snapshot destination exists without a manifest: {output}")
    if adapter == "wikimedia" and mode == "full" and date is None:
        raise SnapshotError("Full Wikimedia acquisition requires an explicit --date YYYY-MM-DD")
    if adapter == "tatoeba" and (mode != "full" or max_files is not None):
        raise SnapshotError(
            "Tatoeba uses full language exports; sample/max-files modes are Wikimedia-only"
        )
    if adapter == "tatoeba" and date is not None:
        raise SnapshotError(
            "Tatoeba exports are current files; omit --date and retain the captured hashes"
        )
    agent = user_agent or DEFAULT_USER_AGENT
    if not agent.strip() or "\n" in agent or "\r" in agent:
        raise SnapshotError("Invalid User-Agent")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        if adapter == "wikimedia":
            if mode == "sample":
                files = _sample(source, staging, requested_titles, agent)
            elif source["acquisition"]["export_kind"] == "content-current":
                files = _content_export(source, staging, date, max_files, agent)
            elif source["acquisition"]["export_kind"] == "legacy-articles":
                files = _legacy_export(source, staging, date, max_files, agent)
            else:
                raise SnapshotError("Unknown Wikimedia export kind")
        elif adapter == "tatoeba":
            files = _tatoeba(source, staging, requested_translations, agent)
        elif adapter == "scp-curated":
            from .scp_curated import ROLE, extract, reviewed_page
            if mode != "full" or date or max_files or titles:
                raise SnapshotError("The curated narrative uses its complete one-work allowlist")
            slug, url, _ = reviewed_page(source)
            data = _metadata(url, agent)
            extract(data, source)
            files = [_save_metadata(staging, f"{slug}.html", ROLE, url, data)]
        elif adapter in {"realpersonachat", "jmultiwoz", "stair", "jec-basic", "kyoto-wikipedia"}:
            if mode != "full" or date or max_files or titles:
                raise SnapshotError(
                    f"{source['title']} uses a pinned full archive; sample with build --max-documents"
                )
            filename, role = {
                "realpersonachat": ("realpersonachat.zip", "realpersonachat-zip"),
                "jmultiwoz": ("jmultiwoz.zip", "jmultiwoz-zip"),
                "stair": ("stair.tar.gz", "stair-tar"),
                "jec-basic": ("jec-basic-v1-3.zip", "jec-basic-zip"),
                "kyoto-wikipedia": ("wiki_corpus_2.01.tar.gz", "kyoto-wikipedia-tar"),
            }[adapter]
            files = [_download(
                staging, filename, role, source["acquisition"]["url"], agent,
                expected_sha256=source["acquisition"].get("sha256"),
                expected_size=source["acquisition"].get("size"),
            )]
        else:
            raise SnapshotError(f"Unsupported source adapter: {adapter}")
        manifest = {
            "schema_version": 1,
            "source_id": source["id"],
            "source": source,
            "source_config_sha256": source_hash,
            "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "mode": "partial" if max_files is not None else mode,
            "upstream_date": date,
            "request": request,
            "files": files,
        }
        manifest["snapshot_id"] = snapshot_identity(manifest)
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        if existing and existing["snapshot_id"] == manifest["snapshot_id"]:
            return existing_manifest
        destination = (
            output
            if existing is None
            else output.with_name(f"{output.name}-{manifest['snapshot_id'][:12]}")
        )
        if destination.exists():
            prior = verify_snapshot(destination / "manifest.json")
            if prior["snapshot_id"] != manifest["snapshot_id"]:
                raise SnapshotError(f"Snapshot destination collision: {destination}")
            return destination / "manifest.json"
        staging.rename(destination)
        return destination / "manifest.json"
    finally:
        if staging.exists():
            shutil.rmtree(staging)

