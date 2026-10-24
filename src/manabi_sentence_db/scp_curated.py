"""One reviewed Japanese Tale; fail closed on changed text, credit, or layout."""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser

from .serialization import DataError, safe_relative

URL = "https://scp-jp.wikidot.com/aptitude"
ROLE = "scp-curated-html"
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
    pin = source["acquisition"]
    if (
        source["id"] != "scp-jp-aptitude-ja"
        or pin["url"] != URL
        or source["license"]
        != {"id": "CC-BY-SA-3.0", "url": "https://creativecommons.org/licenses/by-sa/3.0/"}
    ):
        raise DataError("Only the reviewed aptitude work and license are allowed")
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
    if credit != f"タイトル: {pin['title']} 著者: {pin['author']} 作成年: {pin['year']}":
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
    body = _one(
        [
            n
            for n in content.children
            if isinstance(n, Node)
            and n.tag == "div"
            and n.attrs == {"style": "text-align: justify;"}
        ],
        "body boundary",
    )
    paragraphs = []
    for child in body.children:
        if isinstance(child, str):
            if child.strip():
                raise DataError("Unexpected text outside narrative paragraphs")
            continue
        if child.tag != "p" or any(n.tag not in INLINE for n in child.walk()):
            raise DataError("Unexpected narrative media or content structure")

        # HTML source newlines are collapsible whitespace; authored <br> is a
        # line break. Preserve Japanese indentation and paragraph boundaries.
        def inline(node):
            return "".join(
                re.sub(r"[\t\r\n ]+", " ", c)
                if isinstance(c, str)
                else "\n"
                if c.tag == "br"
                else inline(c)
                for c in node.children
            )

        text = "\n".join(line.strip(" \t\r\n") for line in inline(child).split("\n")).strip(
            " \t\r\n"
        )
        if not text or len(text) > 20_000:
            raise DataError("Invalid curated narrative paragraph")
        paragraphs.append(text)
    body_text = "\n\n".join(paragraphs)
    digest = hashlib.sha256(body_text.encode()).hexdigest()
    if not 1 <= len(paragraphs) <= 100 or (check_hash and digest != pin["body_sha256"]):
        raise DataError("Curated narrative body changed; review and pin a new snapshot")
    return paragraphs, digest


def iter_documents(manifest, snapshot_dir):
    source = manifest["source"]
    entries = [item for item in manifest["files"] if item["role"] == ROLE]
    entry = _one(entries, "snapshot")
    path = safe_relative(snapshot_dir, entry["path"])
    if path.stat().st_size > MAX_HTML_BYTES:
        raise DataError("Oversized curated narrative HTML")
    paragraphs, digest = extract(path.read_bytes(), source)
    pin, position, sentences = source["acquisition"], 0, []
    for ordinal, paragraph in enumerate(paragraphs):
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
        "native_id": "aptitude",
        "language": "ja",
        "title": pin["title"],
        "url": URL,
        "license": source["license"],
        "attribution": source["attribution"],
        "revision": {"id": str(pin["revision"]), "timestamp": pin["timestamp"], "url": URL},
        "authorship": "unknown",
        "language_origin": "original_japanese",
        "content_type": "narrative",
        "tags": ["narrative", "fiction", "curated", "publisher-tag:jp", "publisher-tag:tale"],
        "source_text_hash": digest,
        "sentences": sentences,
    }
