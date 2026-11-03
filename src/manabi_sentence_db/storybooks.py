"""Pinned Storybooks Japan text, with each work's explicit commercial license."""

import hashlib
import re
from collections import Counter

from .html_tree import Element, Tree
from .segments import CONTEXT_BREAK
from .serialization import DataError, safe_relative

HOMEPAGE = "https://global-asp.github.io/storybooks-japan/stories/ja/"
REPOSITORY = "https://github.com/global-asp/storybooks-japan"
RAW = "https://raw.githubusercontent.com/global-asp/storybooks-japan/"
MAX_BYTES = 256 * 1024
TRANSFORMATION = "storybooks-japanese-page-units-v1"
LICENSES = {
    "storybooks-japan-ja": {"id": "CC-BY-3.0", "url": "https://creativecommons.org/licenses/by/3.0/"},
    "storybooks-japan-by4-ja": {"id": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
}
LICENSE_ROLE = "storybooks-site-mit-license"


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _one(items, label):
    if len(items) != 1:
        raise DataError("Storybooks requires one " + label)
    return items[0]


def validate_source(source):
    acquisition = source["acquisition"]
    commit = acquisition.get("version")
    if (source["id"] not in LICENSES or source["language"] != "ja"
            or source["license"] != LICENSES[source["id"]] or source["homepage"] != HOMEPAGE
            or not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit)):
        raise DataError("Invalid Storybooks identity, language, license or pinned commit")
    files = acquisition.get("files")
    if not isinstance(files, dict) or not 1 <= len(files) <= 100:
        raise DataError("Storybooks requires a bounded explicit story inventory")
    pins = [("site_license", acquisition.get("site_license"), RAW + commit + "/LICENSE")]
    for identity, pin in files.items():
        if not isinstance(identity, str) or not re.fullmatch(r"[0-9]{4}", identity):
            raise DataError("Invalid Storybooks story identity")
        if not isinstance(pin, dict) or set(pin) != {"url", "size", "sha256", "metadata", "omitted_pages"}:
            raise DataError("Invalid Storybooks story pin")
        metadata = pin["metadata"]
        if (not isinstance(metadata, dict) or set(metadata) != {
                "title", "author", "illustrator", "translator", "source_url", "level", "pages"}
                or any(not isinstance(metadata[k], str) or not 1 <= len(metadata[k]) <= 1000
                       for k in ("title", "author", "illustrator", "translator", "source_url"))
                or not re.fullmatch(r"https://africanstorybook\.org/reader\.php\?id=[0-9]+", metadata["source_url"])
                or type(metadata["level"]) is not int or metadata["level"] not in range(1, 6)
                or type(metadata["pages"]) is not int or not 1 <= metadata["pages"] <= 100):
            raise DataError("Invalid Storybooks work/translation credit inventory")
        omitted = pin["omitted_pages"]
        if not isinstance(omitted, dict) or len(omitted) >= metadata["pages"]:
            raise DataError("Invalid Storybooks omission inventory")
        for page, omission in omitted.items():
            if (not isinstance(page, str) or not re.fullmatch(r"[1-9][0-9]*", page)
                    or int(page) > metadata["pages"] or not isinstance(omission, dict)
                    or set(omission) != {"sha256", "reason"}
                    or not isinstance(omission["sha256"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", omission["sha256"])
                    or omission["reason"] not in {"demonstrated-source-typo", "incomplete-source-unit"}):
                raise DataError("Invalid Storybooks exact-page quality exclusion")
        pins.append((identity, pin, RAW + commit + f"/stories/ja/{identity}/index.html"))
    for identity, pin, url in pins:
        if (not isinstance(pin, dict) or pin.get("url") != url
                or type(pin.get("size")) is not int or not 0 < pin["size"] <= MAX_BYTES
                or not isinstance(pin.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])
                or (identity == "site_license" and set(pin) != {"url", "size", "sha256"})):
            raise DataError("Invalid Storybooks immutable file pin")


def parts(data, identity, license):
    """Read primary Japanese columns once; never fetch images, audio or links."""
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
        raise DataError("Oversized or empty Storybooks HTML")
    tree = Tree(data)
    nodes = list(tree.root.walk())
    # Pinned templates contain a duplicate navigation class. Reject ambiguous
    # attributes on extracted metadata/content, without parsing unrelated UI.
    if any(n.duplicate_attrs for n in nodes if n.tag == "link" or
           (n.tag == "a" and "creativecommons.org/licenses/" in n.attrs.get("href", ""))):
        raise DataError("Duplicate Storybooks rights attributes")
    links = {n.attrs["href"] for n in nodes if n.tag == "a"
             and "creativecommons.org/licenses/" in n.attrs.get("href", "")}
    if links != {license["url"] + "deed.ja"}:
        raise DataError("Storybooks work license is not the selected commercial grant")
    canonical = _one([n.attrs.get("href") for n in nodes
                      if n.tag == "link" and n.attrs.get("rel") == "canonical"], "canonical URL")
    if canonical not in {HOMEPAGE + identity + "/", HOMEPAGE.replace(".io/", ".io//") + identity + "/"}:
        raise DataError("Storybooks canonical work URL differs")
    cover = _one([n for n in nodes if n.attrs.get("id") == "text01"], "cover")
    if any(n.duplicate_attrs for n in cover.walk()):
        raise DataError("Duplicate Storybooks credit attributes")
    heading = _one([n for n in cover.walk() if n.tag == "h1"], "title")
    title = _one([n for n in heading.walk() if n.tag == "span"
                  and "def" in (n.attrs.get("class") or "").split()], "Japanese title").text().strip()
    credits = {}
    roles = {"作者": "author", "絵": "illustrator", "翻訳": "translator", "言語": "language", "レベル": "level"}
    for node in cover.walk():
        if node.tag != "h3":
            continue
        icons = [n for n in node.walk() if n.tag == "span" and n.attrs.get("data-tooltip") in roles]
        if icons:
            role = roles[_one(icons, "credit role").attrs["data-tooltip"]]
            if role in credits:
                raise DataError("Duplicate Storybooks credit")
            credits[role] = node.text().strip()
    if set(credits) != set(roles.values()) or credits.pop("language") != "日本語":
        raise DataError("Missing Storybooks Japanese work/translation attribution")
    level = re.fullmatch(r"レベル ([1-5])", credits.pop("level"))
    if not level:
        raise DataError("Unknown Storybooks publisher reading level")
    source = _one([n for n in nodes if n.tag == "h5" and n.text().startswith("出所:")], "original work attribution")
    original = _one([n.attrs.get("href") for n in source.walk() if n.tag == "a"
                     and re.fullmatch(r"https://africanstorybook\.org/reader\.php\?id=[0-9]+", n.attrs.get("href", ""))], "original work URL")
    columns = [n for n in nodes if n.tag == "div" and "def" in (n.attrs.get("class") or "").split()]
    units = []
    for column in columns:
        # Structural whitespace is outside h3. Preserve authored text inside it.
        children = [n for n in column.children if isinstance(n, Element)]
        if (len(children) != 1 or children[0].tag != "h3"
                or any(n.tag not in {"div", "h3"} or n.duplicate_attrs for n in column.walk())
                or any(isinstance(n, str) and n.strip() for n in column.children)):
            raise DataError("Unreviewed Storybooks narrative markup")
        text = children[0].text().strip()
        if not text or len(text) > 20000:
            raise DataError("Invalid Storybooks narrative page")
        units.append(text)
    pages = [n.attrs["id"] for n in nodes if re.fullmatch(r"text[0-9]{2,3}", n.attrs.get("id", ""))]
    expected = [f"text{i:02d}" for i in range(1, len(units) + 2)]
    if pages != expected:
        raise DataError("Storybooks page inventory/ordering differs")
    return dict(title=title, **credits, source_url=original, level=int(level[1]), pages=len(units)), units


def extract(data, source, identity, *, stats=None):
    validate_source(source)
    pin = source["acquisition"]["files"][identity]
    if len(data) != pin["size"] or _hash(data) != pin["sha256"]:
        raise DataError("Storybooks source bytes differ from their pin")
    metadata, pages = parts(data, identity, source["license"])
    if metadata != pin["metadata"]:
        raise DataError("Storybooks work credit/title/page inventory changed")
    stats = stats if stats is not None else Counter()
    sentences, position = [], 0
    for number, text in enumerate(pages, 1):
        stats["publisher_pages_seen"] += 1
        start = position
        position += len(text) + 2
        omission = pin["omitted_pages"].get(str(number))
        if omission:
            if _hash(text.encode()) != omission["sha256"]:
                raise DataError("Storybooks excluded source page changed")
            stats["rejected:storybooks-" + omission["reason"]] += 1
            sentences.append(CONTEXT_BREAK)
        else:
            sentences.append(dict(native_id=f"{identity}:page:{number}", text=text,
                                  source_range=dict(unit="character", start=start, end=start + len(text)),
                                  tags=[], content_flags=[], translations=[]))
    url = HOMEPAGE + identity + "/"
    return dict(native_id=identity, language="ja", title=metadata["title"], url=url,
                license=source["license"], attribution=dict(url=url, text=(
                    f"{metadata['title']} — {metadata['author']} (text); {metadata['translator']} "
                    f"(Japanese translation); {metadata['illustrator']} (original illustration credit; "
                    f"no images imported). African Storybook / Storybooks Japan. Original work: "
                    f"{metadata['source_url']}. {source['license']['id']}. Japanese page text extracted "
                    "and split into sentences; selected source-quality exclusions retain context gaps.")),
                revision=dict(id=source["acquisition"]["version"],
                              url=REPOSITORY + "/blob/" + source["acquisition"]["version"] + f"/stories/ja/{identity}/index.html"),
                authorship="unknown", language_origin="unknown", content_type="narrative",
                source_text_hash=_hash("\n\n".join(pages).encode()),
                tags=["translation:source-language-unknown", "translation:method-unknown",
                      "children-literature", f"publisher-reading-level:{metadata['level']}"],
                sentences=sentences)


def iter_documents(manifest, snapshot_dir, *, stats=None):
    source = manifest["source"]
    validate_source(source)
    pins = {"storybook-" + identity: pin for identity, pin in source["acquisition"]["files"].items()}
    pins[LICENSE_ROLE] = source["acquisition"]["site_license"]
    entries = manifest["files"]
    if len(entries) != len(pins) or {row["role"] for row in entries} != set(pins):
        raise DataError("Storybooks snapshot inventory differs")
    # Validate the wrapper grant before yielding, even for --max-documents 1.
    for row in sorted(entries, key=lambda row: (row["role"] != LICENSE_ROLE, row["role"])):
        pin = pins[row["role"]]
        path = safe_relative(snapshot_dir, row["path"])
        if path.is_symlink() or not path.is_file() or path.stat().st_size != pin["size"] or row["url"] != pin["url"]:
            raise DataError("Invalid Storybooks snapshot file")
        data = path.read_bytes()
        if _hash(data) != pin["sha256"]:
            raise DataError("Storybooks snapshot content differs")
        if row["role"] == LICENSE_ROLE:
            if not data.startswith(b"The MIT License (MIT)"):
                raise DataError("Storybooks HTML wrapper license differs")
            continue
        yield extract(data, source, row["role"].removeprefix("storybook-"), stats=stats)
