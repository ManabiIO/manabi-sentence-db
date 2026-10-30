"""Reviewed Japanese Tales; fail closed on changed text, credit, or layout."""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser

from .segments import CONTEXT_BREAK
from .serialization import DataError, safe_relative

URL = "https://scp-jp.wikidot.com/aptitude"
# Source identity also fixes the extraction boundary. New pages require review,
# an explicit entry here, and a separately pinned source manifest.
REVIEWED = {
    "scp-jp-aptitude-ja": ("aptitude", "justified-div"),
    "scp-jp-duck-merchant-ja": ("a-duck-and-a-merchant", "direct-paragraphs"),
    "scp-jp-id-photo-ja": ("id-photo", "direct-paragraphs"),
    "scp-jp-fixed-point-ja": ("fixed-point-observation", "direct-paragraphs"),
    "scp-jp-shaving-ja": ("feeling-good-after-shaving", "direct-paragraphs"),
}
# Legacy cached manifests predate the optional scene pin. Bind those sources to
# their reviewed layout too, rather than accepting a newly inserted rule.
REVIEWED_SCENE_BREAKS = {
    "scp-jp-duck-merchant-ja": [4, 9, 59],
    "scp-jp-shaving-ja": [38],
}
ROLE = "scp-curated-html"
RUBY_TRANSFORMATION = "publisher-ruby-base-text-v1"


def reviewed_page(source):
    slug, boundary = REVIEWED.get(source["id"], (None, None))
    url = f"https://scp-jp.wikidot.com/{slug}"
    if slug is None or source["acquisition"]["url"] != url:
        raise DataError("Only the reviewed narrative work URLs are allowed")
    return slug, url, boundary

MAX_HTML_BYTES = 256 * 1024
VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
INLINE = {"p", "br", "span", "a", "strong", "em", "b", "i"}


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def text(self):
        return "".join(
            child if isinstance(child, str) else "\n" if child.tag == "br" else child.text()
            for child in self.children
        )


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)
            if len(self.stack) > 100:
                raise DataError("Curated narrative HTML is too deeply nested")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _one(nodes, description):
    if len(nodes) != 1:
        raise DataError(f"Expected one curated narrative {description}")
    return nodes[0]


def extract(data, source, *, check_hash=True):
    """Return reviewed paragraph units; no scripts, links, or media are fetched."""
    paragraphs, digest, _ = _extract(data, source, check_hash=check_hash)
    return paragraphs, digest


def _extract(data, source, *, check_hash=True):
    pin = source["acquisition"]
    _, _, boundary = reviewed_page(source)
    if (
        source["license"]
        != {"id": "CC-BY-SA-3.0", "url": "https://creativecommons.org/licenses/by-sa/3.0/"}
    ):
        raise DataError("Only the reviewed narrative license is allowed")
    if len(data) > MAX_HTML_BYTES:
        raise DataError("Oversized curated narrative HTML")
    page = Page()
    page.feed(data.decode("utf-8"))
    nodes = list(page.root.walk())

    def by_id(identity):
        return _one([n for n in nodes if n.attrs.get("id") == identity], identity)

    if by_id("page-title").text().strip() != pin["title"]:
        raise DataError("Curated narrative title changed")
    credit_view = by_id("u-credit-view")
    credits = [n for n in credit_view.walk() if "credit" in n.attrs.get("class", "").split()]
    credit = re.sub(r"\s+", " ", _one(credits, "credit").text()).strip()
    if credit != f"タイトル: {pin['title']} 著者: {pin.get('credit_author', pin['author'])} 作成年: {pin['year']}":
        raise DataError("Curated narrative attribution changed")
    license_links = [
        n.attrs.get("href", "")
        for n in credit_view.walk()
        if n.tag == "a" and "creativecommons.org/licenses/" in n.attrs.get("href", "")
    ]
    if license_links != ["https://creativecommons.org/licenses/by-sa/3.0/deed.ja"]:
        raise DataError("Curated narrative license changed")
    info = by_id("page-info")
    if not re.match(rf"ページリビジョン:\s*{re.escape(str(pin['revision']))},", info.text()):
        raise DataError("Curated narrative revision changed")
    timestamps = [
        int(value[5:])
        for n in info.walk()
        for value in n.attrs.get("class", "").split()
        if re.fullmatch(r"time_[0-9]+", value)
    ]
    expected_time = int(datetime.fromisoformat(pin["timestamp"].replace("Z", "+00:00")).timestamp())
    if timestamps != [expected_time]:
        raise DataError("Curated narrative revision timestamp changed")
    tags_node = _one([n for n in nodes if "page-tags" in n.attrs.get("class", "").split()], "tags")
    tags = {n.text().strip() for n in tags_node.walk() if n.tag == "a"}
    if not {"jp", "tale"} <= tags:
        raise DataError("Curated narrative original-Japanese tags changed")
    content = by_id("page-content")
    if boundary == "justified-div":
        body = _one(
            [n for n in content.children if isinstance(n, Node) and n.tag == "div"
             and n.attrs == {"style": "text-align: justify;"}],
            "body boundary",
        )
        children = body.children
    else:
        # Reviewed pages put prose directly under page-content. Deliberately do
        # not descend into credit, rating, navigation, media or other modules.
        children = [n for n in content.children if isinstance(n, Node) and n.tag in {"p", "hr"}]
    paragraphs, reviewed_paragraphs = [], []
    scene_breaks, pending_break = [], False
    for child in children:
        if isinstance(child, str):
            if child.strip():
                raise DataError("Unexpected text outside narrative paragraphs")
            continue
        if child.tag == "hr":
            # Consecutive rules represent one boundary. Leading/trailing rules
            # do not create a break between narrative paragraphs.
            pending_break = bool(paragraphs)
            continue
        if child.tag != "p" or any(n.tag not in INLINE for n in child.walk()):
            raise DataError("Unexpected narrative media or content structure")

        # HTML source newlines are collapsible whitespace; authored <br> is a
        # line break. Preserve Japanese indentation and paragraph boundaries.
        def inline(node, *, retain_readings=False, ruby_annotation=False):
            classes = node.attrs.get("class", "").split()
            if not retain_readings:
                if "rt" in classes:
                    if node.tag != "span" or not ruby_annotation or "ruby" in classes:
                        raise DataError("Unexpected narrative ruby annotation")
                    return ""
                if "ruby" in classes:
                    if ruby_annotation:
                        raise DataError("Nested narrative ruby layout")
                    annotations = [
                        n for n in node.children
                        if isinstance(n, Node) and "rt" in n.attrs.get("class", "").split()
                    ]
                    if (
                        node.tag != "span" or len(annotations) != 1
                        or any(isinstance(c, Node) for c in annotations[0].children)
                    ):
                        raise DataError("Unexpected narrative ruby layout")
                    base = "".join(
                        re.sub(r"[\t\r\n ]+", " ", c) if isinstance(c, str)
                        else inline(c, ruby_annotation=True)
                        for c in node.children
                    )
                    if not base.strip() or not annotations[0].text().strip():
                        raise DataError("Empty narrative ruby base or annotation")
                    return base
            return "".join(
                re.sub(r"[\t\r\n ]+", " ", c)
                if isinstance(c, str)
                else "\n"
                if c.tag == "br"
                else inline(c, retain_readings=retain_readings)
                for c in node.children
            )

        text = "\n".join(line.strip(" \t\r\n") for line in inline(child).split("\n")).strip(
            " \t\r\n"
        )
        if not text and boundary == "direct-paragraphs":
            continue  # Publisher spacing-only paragraphs are not sentence units.
        if not text or len(text) > 20_000:
            raise DataError("Invalid curated narrative paragraph")
        if pending_break:
            scene_breaks.append(len(paragraphs))
            pending_break = False
        paragraphs.append(text)
        # Keep the existing reviewed-body pin over complete source inline text,
        # including readings. The derived surface text has its own digest below;
        # changed readings cannot bypass snapshot review just because we omit them.
        reviewed_paragraphs.append("\n".join(
            line.strip(" \t\r\n")
            for line in inline(child, retain_readings=True).split("\n")
        ).strip(" \t\r\n"))
    body_text = "\n\n".join(paragraphs)
    digest = hashlib.sha256(body_text.encode()).hexdigest()
    reviewed_digest = hashlib.sha256("\n\n".join(reviewed_paragraphs).encode()).hexdigest()
    if not 1 <= len(paragraphs) <= 100 or (check_hash and reviewed_digest != pin["body_sha256"]):
        raise DataError("Curated narrative body changed; review and pin a new snapshot")
    expected_breaks = pin.get("scene_breaks", REVIEWED_SCENE_BREAKS.get(source["id"], []))
    if check_hash and scene_breaks != expected_breaks:
        raise DataError("Curated narrative scene breaks changed; review and pin a new snapshot")
    return paragraphs, digest, scene_breaks


def iter_documents(manifest, snapshot_dir):
    source = manifest["source"]
    entries = [item for item in manifest["files"] if item["role"] == ROLE]
    entry = _one(entries, "snapshot")
    path = safe_relative(snapshot_dir, entry["path"])
    if path.stat().st_size > MAX_HTML_BYTES:
        raise DataError("Oversized curated narrative HTML")
    paragraphs, digest, scene_breaks = _extract(path.read_bytes(), source)
    slug, url, _ = reviewed_page(source)
    pin, position, sentences = source["acquisition"], 0, []
    for ordinal, paragraph in enumerate(paragraphs):
        if ordinal in scene_breaks:
            sentences.append(CONTEXT_BREAK)
        sentences.append(
            {
                "native_id": f"paragraph:{ordinal}",
                "text": paragraph,
                "source_range": {
                    "unit": "character",
                    "start": position,
                    "end": position + len(paragraph),
                },
                "tags": ["narrative", "paragraph-unit"],
                "translations": [],
                "content_flags": [],
            }
        )
        position += len(paragraph) + 2
    yield {
        "native_id": slug,
        "language": "ja",
        "title": pin["title"],
        "url": url,
        "license": source["license"],
        "attribution": source["attribution"],
        "revision": {"id": str(pin["revision"]), "timestamp": pin["timestamp"], "url": url},
        "authorship": "unknown",
        "language_origin": "original_japanese",
        "content_type": "narrative",
        "tags": ["narrative", "fiction", "curated", "publisher-tag:jp", "publisher-tag:tale"],
        "source_text_hash": digest,
        "sentences": sentences,
    }
