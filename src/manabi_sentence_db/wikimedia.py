"""Stream saved Wikimedia XML/API snapshots into attributed prose documents.

No requests, template expansion, or live lookups occur here. Unknown inline
templates are marked rather than removed, so their surrounding words cannot be
silently joined into an invented example sentence. Raw snapshot verification is
the caller's responsibility; paths are independently confined to the snapshot.
"""

from __future__ import annotations

import bz2
import copy
import gzip
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO
from urllib.parse import quote, urlencode, urlsplit

import mwparserfromhell
from defusedxml.ElementTree import iterparse
from mwparserfromhell import nodes

from .text import OMITTED_MARKUP, is_complete_sentence, split_sentences

WIKIMEDIA_PROCESSOR_VERSION = "wikimedia-prose-v1"

_EXCLUDED_SECTIONS = {
    "脚注", "注釈", "出典", "参考文献", "関連項目", "外部リンク", "脚注と出典",
    "出典・脚注", "ソース", "引用", "引用文", "原文", "歌詞", "references", "notes",
    "sources", "external links", "see also", "bibliography", "quotations",
}
_RESTRICTED_TEMPLATES = {
    "copyvio", "copyright violation", "copyrightviolation", "db-copyvio", "db", "delete",
    "sd", "speedydelete", "削除依頼", "即時削除", "著作権侵害", "転載",
}
_REMOVED_TAGS = {
    "table", "gallery", "math", "chem", "score", "timeline", "mapframe", "maplink",
    "pre", "code", "source", "syntaxhighlight", "blockquote", "q", "poem", "hiero",
    "script", "style", "iframe", "object", "audio", "video", "sup", "sub", "del",
    "s", "strike", "noinclude", "includeonly", "input", "form",
}
_INLINE_TAGS = {"b", "i", "em", "strong", "span", "small", "abbr", "u", "mark", "rb"}
_FILE_NAMESPACES = {"file", "image", "ファイル", "画像", "media", "メディア"}
_CATEGORY_NAMESPACES = {"category", "カテゴリ", "カテゴリー"}
_LIST_LINE = re.compile(r"^\s*[*#;:|!]|^\s*----+\s*$")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(element, name: str):
    return (child for child in element if _local_name(child.tag) == name)


def _child(element, name: str):
    return next(_children(element, name), None)


def _child_text(element, name: str, default: str = "") -> str:
    child = _child(element, name)
    return child.text if child is not None and child.text is not None else default


@contextmanager
def _open_input(path: Path) -> Iterator[BinaryIO]:
    if path.suffix == ".bz2":
        with bz2.open(path, "rb") as handle:
            yield handle
    elif path.suffix == ".gz":
        with gzip.open(path, "rb") as handle:
            yield handle
    else:
        with path.open("rb") as handle:
            yield handle


def _snapshot_path(snapshot_dir: Path, relative: str) -> Path:
    root = snapshot_dir.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root) or Path(relative).is_absolute():
        raise ValueError(f"Snapshot input escapes its directory: {relative}")
    return candidate


def _xml_pages(path: Path) -> Iterator[dict]:
    with _open_input(path) as handle:
        context = iterparse(handle, events=("start", "end"), forbid_dtd=True)
        _, root = next(context)
        if _local_name(root.tag) != "mediawiki":
            raise ValueError(f"Not a MediaWiki XML export: {path.name}")
        for event, page in context:
            if event != "end" or _local_name(page.tag) != "page":
                continue
            try:
                if _child_text(page, "ns") != "0" or _child(page, "redirect") is not None:
                    continue
                revisions = list(_children(page, "revision"))
                if not revisions:
                    continue
                revision = max(
                    revisions,
                    key=lambda item: (_child_text(item, "timestamp"), int(_child_text(item, "id", "0"))),
                )
                content = revision
                slots = _child(revision, "slots")
                if slots is not None:
                    content = next(
                        (slot for slot in _children(slots, "slot") if slot.get("role") == "main"),
                        None,
                    )
                    if content is None:
                        continue
                if _child_text(content, "model", "wikitext") != "wikitext":
                    continue
                text = _child(content, "text")
                if text is None or "deleted" in text.attrib or text.text is None:
                    continue
                yield {
                    "native_id": _child_text(page, "id"),
                    "title": _child_text(page, "title"),
                    "revision_id": _child_text(revision, "id"),
                    "timestamp": _child_text(revision, "timestamp"),
                    "text": text.text,
                }
            finally:
                # clear() alone leaves millions of empty page objects on root.
                page.clear()
                root.remove(page)


def _api_pages(path: Path) -> Iterator[dict]:
    with _open_input(path) as handle:
        payload = json.load(handle)
    if "error" in payload:
        raise ValueError(f"Saved MediaWiki API response contains an error: {path.name}")
    pages = payload.get("query", {}).get("pages", [])
    if isinstance(pages, dict):
        pages = list(pages.values())
    for page in pages:
        if page.get("ns") != 0 or any(key in page for key in ("missing", "invalid", "redirect")):
            continue
        revisions = page.get("revisions", [])
        if not revisions:
            continue
        revision = max(revisions, key=lambda item: (item.get("timestamp", ""), item.get("revid", 0)))
        content = revision.get("slots", {}).get("main", revision)
        if content.get("contentmodel", page.get("contentmodel", "wikitext")) != "wikitext":
            continue
        if any(key in content or key in revision for key in ("texthidden", "suppressed")):
            continue
        text = content.get("content", content.get("*"))
        if not isinstance(text, str):
            continue
        yield {
            "native_id": str(page.get("pageid", "")),
            "title": page.get("title", ""),
            "revision_id": str(revision.get("revid", "")),
            "timestamp": revision.get("timestamp", ""),
            "text": text,
        }


def _template_name(template) -> str:
    name = str(template.name).strip().replace("_", " ").lower()
    while True:
        prefix = next(
            (item for item in ("template:", "テンプレート:", "subst:", "safesubst:") if name.startswith(item)),
            None,
        )
        if prefix is None:
            break
        name = name[len(prefix):].strip()
    return name


def _render(code) -> str:
    parts: list[str] = []
    for node in code.nodes:
        if isinstance(node, nodes.Text):
            parts.append(str(node.value))
        elif isinstance(node, nodes.HTMLEntity):
            parts.append(node.normalize())
        elif isinstance(node, nodes.Comment):
            continue
        elif isinstance(node, nodes.Template) or isinstance(node, nodes.Argument):
            parts.append(OMITTED_MARKUP)
        elif isinstance(node, nodes.Heading):
            parts.append("\n\n")
        elif isinstance(node, nodes.Wikilink):
            target = str(node.title).strip()
            namespace = target.lstrip(":").partition(":")[0].lower()
            if ":" in target and namespace in _CATEGORY_NAMESPACES:
                # A leading colon makes this a visible category link.
                if target.startswith(":"):
                    parts.append(_render(node.text) if node.text is not None else target[1:])
                continue
            if ":" in target and (namespace in _FILE_NAMESPACES or re.fullmatch(r"[a-z-]{2,12}", namespace)):
                parts.append(OMITTED_MARKUP)
                continue
            parts.append(_render(node.text) if node.text is not None else target)
        elif isinstance(node, nodes.ExternalLink):
            parts.append(_render(node.title) if node.title is not None else "")
        elif isinstance(node, nodes.Tag):
            tag = str(node.tag).strip().lower()
            if tag in {"ref", "references", "rt", "rp"}:
                continue
            if any(str(attr.name).lower() in {"style", "hidden"} for attr in node.attributes):
                parts.append(OMITTED_MARKUP)
            elif tag in {"li", "dd", "dt"} and node.wiki_markup:
                # mwparserfromhell represents the leading wiki list marker as
                # a tag. Keep it until line filtering below, not as a word.
                parts.append(str(node.wiki_markup))
            elif tag in _REMOVED_TAGS:
                # Keep the marker inline: inserting a boundary here could
                # admit an orphan suffix such as "と言った。" after a quote.
                parts.append(OMITTED_MARKUP)
            elif tag in {"br", "hr"}:
                parts.append("\n\n")
            elif tag in _INLINE_TAGS or tag == "ruby":
                if node.contents is not None:
                    parts.append(_render(node.contents))
            elif tag in {"p", "div", "section"}:
                if node.contents is not None:
                    parts.append("\n\n" + _render(node.contents) + "\n\n")
            else:
                parts.append(OMITTED_MARKUP)
        else:
            parts.append(OMITTED_MARKUP)
    return "".join(parts)


def extract_prose(wikitext: str, language: str = "ja") -> tuple[list[str], list[str]]:
    """Return complete prose sentences and original category tags.

    Copyright/deletion notices reject the page. Lists, tables, quote blocks,
    reference sections and media captions are not prose examples. Sentences
    with Japanese corner quotes are conservatively excluded because embedded
    quotations need not share the article license (this also loses some title
    mentions). Unknown templates leave a sentinel which the shared quality
    filter rejects. These heuristics cannot identify every third-party passage.
    """
    if re.match(r"\s*#(?:redirect|転送|リダイレクト)\b", wikitext, re.I):
        return [], []
    code = mwparserfromhell.parse(wikitext)
    if any(_template_name(template) in _RESTRICTED_TEMPLATES for template in code.filter_templates()):
        return [], []
    categories: set[str] = set()
    for link in code.filter_wikilinks():
        target = str(link.title).strip()
        namespace, separator, title = target.partition(":")
        if separator and namespace.lower() in _CATEGORY_NAMESPACES and title.strip():
            categories.add("category:" + title.strip())
    selected: list[str] = []
    ignored_level: int | None = None
    for node in code.nodes:
        if isinstance(node, nodes.Heading):
            title = node.title.strip_code().strip().lower()
            if ignored_level is not None and node.level <= ignored_level:
                ignored_level = None
            if title in _EXCLUDED_SECTIONS:
                ignored_level = node.level
            selected.append("\n\n")
        elif ignored_level is None:
            selected.append(_render(mwparserfromhell.wikicode.Wikicode([node])))
    plain = "".join(selected)
    lines = [line for line in plain.splitlines() if not _LIST_LINE.match(line)]
    sentences = [
        sentence
        for sentence in split_sentences("\n".join(lines), language)
        if is_complete_sentence(sentence, language) and not any(mark in sentence for mark in "「」『』")
    ]
    return sentences, sorted(categories)


def iter_documents(manifest: dict, snapshot_dir: Path) -> Iterator[dict]:
    source = manifest["source"]
    language = source["language"]
    origin = urlsplit(source.get("acquisition", {}).get("api_url") or source["homepage"])
    base = f"{origin.scheme}://{origin.netloc}"
    for entry in manifest["files"]:
        role = entry["role"]
        if role not in {"mediawiki-xml", "mediawiki-api"}:
            continue
        path = _snapshot_path(snapshot_dir, entry["path"])
        pages = _xml_pages(path) if role == "mediawiki-xml" else _api_pages(path)
        for page in pages:
            if not page["native_id"] or not page["revision_id"] or not page["title"]:
                continue
            sentences, tags = extract_prose(page["text"], language)
            if not sentences:
                continue
            title = page["title"]
            url = f"{base}/wiki/{quote(title.replace(' ', '_'), safe='()')}"
            history = f"{base}/w/index.php?{urlencode({'title': title, 'action': 'history'})}"
            revision = {
                "id": page["revision_id"],
                "url": f"{base}/w/index.php?oldid={quote(page['revision_id'], safe='')}",
                "history_url": history,
            }
            if page["timestamp"]:
                revision["timestamp"] = page["timestamp"]
            yield {
                "native_id": page["native_id"],
                "title": title,
                "url": url,
                "language": language,
                "license": copy.deepcopy(source["license"]),
                "attribution": {
                    "text": f"{title} — {source['title']} contributors; see revision history",
                    "url": history,
                },
                "revision": revision,
                "tags": tags,
                "sentences": [
                    {"text": text, "tags": [], "content_flags": [], "translations": []}
                    for text in sentences
                ],
            }
