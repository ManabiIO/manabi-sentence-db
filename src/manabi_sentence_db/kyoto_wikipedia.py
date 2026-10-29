"""Stream original NICT Kyoto Wikipedia XML and final human translations.

Publisher sentence pairs stay intact. CSV headings and translator comments are
not examples, and missing/excluded source rows retain their ordinal gaps.
"""

import csv
import hashlib
import io
import re
import tarfile
from pathlib import Path
from urllib.parse import urlencode

from defusedxml.ElementTree import fromstring

from .serialization import DataError, safe_relative
from .text import is_complete_sentence
from .wikimedia import _EXCLUDED_SECTIONS

ROLE = "kyoto-wikipedia-tar"
INDEX = "Wiki_Corpus_List_2.01.csv"
CATEGORIES = {"BDS", "BLD", "CLT", "EPR", "FML", "GNM", "HST", "LTT", "PNM", "RLW", "ROD", "SAT", "SCL", "SNT", "TTL"}
MAX_MEMBER_BYTES = 16 * 1024**2
NOTICE = (
    "The translated sentences used in this service contain English contents which is "
    "translated by the National Institute of Information and Communications Technology "
    "(NICT) from Japanese sentences on Wikipedia. Our use of this data is licensed by "
    "the Creative Comons Attribution-Share-Alike License 3.0. Please refer to "
    "http://creativecommons.org/licenses/by-sa/3.0/ or "
    "http://alaginrc.nict.go.jp/WikiCorpus/ for details."
)
REPAIR_MEMBER = "GNM/GNM00155.xml"
REPAIR_SHA256 = "d132655cade52c6b252eb2e68745e6ee8e812684cafbcbf873deb42c3b88017b"
_SKIP_SECTIONS = _EXCLUDED_SECTIONS | {"和歌", "短歌", "俳句", "漢詩", "詩歌", "古文", "原文引用"}
_SOURCE_DEFECT = re.compile(
    r"(?:原文|日本語|日本文).{0,20}(?:誤字|脱字|誤記|誤り|間違|不完全|文字化け)"
    r"|(?:誤字|脱字|文字化け).{0,15}原文|不完全な文|古文|俳句|和歌|意味解釈が困難"
)


def _sentences(node, excluded=False):
    if node.tag == "sec":
        excluded = excluded or node.findtext("tit/j", "").strip().casefold() in _SKIP_SECTIONS
    if node.tag == "sen":
        yield node, excluded
    else:
        for child in node:
            yield from _sentences(child, excluded)


def _read(archive, member):
    if not member.isfile() or member.size > MAX_MEMBER_BYTES:
        raise DataError("Invalid or oversized Kyoto corpus member")
    with archive.extractfile(member) as stream:
        return stream.read()


def _member_name(member):
    name = member.name
    if member.isdir() and name.rstrip("/") in CATEGORIES:
        return "directory"
    if name in {INDEX, "kyoto_lexicon.csv", "readme.pdf"}:
        return "metadata"
    match = re.fullmatch(r"([A-Z]{3})/\1[0-9]{5}\.xml", name)
    if not match or match[1] not in CATEGORIES:
        raise DataError(f"Unexpected Kyoto archive member: {name}")
    return "article"


def _index(path, acquisition):
    seen, articles, metadata = set(), set(), {}
    with tarfile.open(path, "r|gz") as archive:
        for member in archive:
            if member.name in seen:
                raise DataError("Duplicate Kyoto archive member")
            seen.add(member.name)
            kind = _member_name(member)
            if kind == "directory":
                continue
            if not member.isfile() or member.size > MAX_MEMBER_BYTES:
                raise DataError("Invalid or oversized Kyoto corpus member")
            if kind == "article":
                articles.add(member.name)
            elif member.name in {INDEX, "readme.pdf"}:
                data = _read(archive, member)
                key = "index_sha256" if member.name == INDEX else "readme_sha256"
                if hashlib.sha256(data).hexdigest() != acquisition[key]:
                    raise DataError("Kyoto metadata checksum mismatch")
                metadata[member.name] = data
    if set(metadata) != {INDEX, "readme.pdf"}:
        raise DataError("Missing Kyoto index or license/process documentation")
    rows = {}
    for row in csv.DictReader(io.StringIO(metadata[INDEX].decode("utf-8-sig"))):
        filename, page_id = row.get("File name", ""), row.get("Wikipedia ID", "")
        if not re.fullmatch(r"[A-Z]{3}[0-9]{5}\.xml", filename) or not re.fullmatch(r"[1-9][0-9]*", page_id):
            raise DataError("Invalid Kyoto article index identity")
        name = filename[:3] + "/" + filename
        if name in rows:
            raise DataError("Duplicate Kyoto article index identity")
        rows[name] = row
    if set(rows) != articles or len(rows) != acquisition["article_count"]:
        raise DataError("Kyoto article inventory differs from pinned release")
    return rows


def article_document(data, name, row, source, stats):
    digest = hashlib.sha256(data).hexdigest()
    repaired = name == REPAIR_MEMBER and digest == REPAIR_SHA256
    if repaired:
        # The pinned publisher XML has one bare ampersand in a contributor name.
        # Escape XML syntax only; parsed attribution retains the exact literal &.
        old = b"AEONseven&i(id:89677)"
        if data.count(old) != 1:
            raise DataError("Reviewed Kyoto XML repair no longer matches")
        data = data.replace(old, b"AEONseven&amp;i(id:89677)")
        stats["xml_entity_repairs"] += 1
    try:
        root = fromstring(data, forbid_dtd=True)
    except Exception as error:
        raise DataError(f"Invalid Kyoto XML: {name}") from error
    if root.tag != "art" or root.attrib != {"orl": "ja", "trl": "en"}:
        raise DataError("Unexpected Kyoto article language/root")
    allowed = {"art", "inf", "tit", "sec", "par", "sen", "j", "e", "cmt", "copyright"}
    if any(n.tag not in allowed for n in root.iter()):
        raise DataError("Unexpected Kyoto XML structure")
    title = root.findtext("tit/j", "").strip()
    dump = root.findtext("inf", "").strip()
    if not title or dump not in {"jawiki-20080607-pages-articles.xml", "jawiki-20090527-pages-articles.xml"}:
        raise DataError("Missing Kyoto article title or source dump identity")
    copyrights = root.findall("copyright")
    if len(copyrights) != 1 or len(copyrights[0]):
        raise DataError("Missing or ambiguous Kyoto article attribution")
    credit = (copyrights[0].text or "").strip()
    if "Creative Commons Attribution-Share-Alike License 3.0" not in credit:
        raise DataError("Missing Kyoto article license notice")
    page = "https://ja.wikipedia.org/w/index.php?" + urlencode({"curid": row["Wikipedia ID"]})
    history = page + "&action=history"
    attribution = {"text": credit + "\n" + NOTICE, "url": history}
    translation_rights = source["license"]
    sentences, seen = [], set()
    for node, excluded_section in _sentences(root):
        stats["publisher_pairs_seen"] += 1
        identity = node.get("id", "")
        if not re.fullmatch(r"[1-9][0-9]*", identity) or identity in seen:
            raise DataError("Invalid or duplicate Kyoto sentence ID")
        seen.add(identity)
        ordinal = int(identity) - 1
        japanese = node.findall("j")
        final = [n for n in node.findall("e") if n.attrib == {"type": "check", "ver": "1"}]
        if len(japanese) != 1 or len(final) != 1 or len(japanese[0]) or len(final[0]):
            raise DataError("Missing or ambiguous Kyoto final sentence pair")
        text, translated = japanese[0].text or "", final[0].text or ""
        reason = None
        comments = "\n".join(n.text or "" for n in node.findall("cmt"))
        if excluded_section:
            reason = "excluded-section"
        elif _SOURCE_DEFECT.search(comments):
            reason = "source-noted-defect-or-classical-quotation"
        elif not text.strip() or not translated.strip():
            reason = "missing-final-translation"
        elif any(char in text for char in "「」『』“”"):
            reason = "embedded-quotation-or-title"
        elif not is_complete_sentence(text):
            reason = "incomplete-prose"
        if reason:
            stats["rejected:kyoto-" + reason] += 1
            continue
        sentences.append({
            "native_id": identity, "source_ordinal": ordinal, "text": text,
            "source_range": {"unit": "utterance", "start": ordinal, "end": ordinal + 1},
            "tags": ["translation:final-checked"], "content_flags": [],
            "translations": [{
                "native_id": identity + ":check:1", "language": "en", "text": translated,
                "source_url": source["homepage"], "license": translation_rights,
                "attribution": {"text": NOTICE, "url": source["homepage"]},
                "generation": {"kind": "human", "agent": "NICT"}, "alignment": "human",
            }],
        })
    return {
        "native_id": name, "language": "ja", "title": title, "url": page,
        "license": source["license"], "attribution": attribution,
        "revision": {"id": "2.01:" + dump, "url": source["acquisition"]["url"]},
        "source_text_hash": digest, "authorship": "unknown", "language_origin": "original_japanese",
        "content_type": "encyclopedia", "tags": ["category:" + row["Category"], "translation:final-checked"]
        + (["kyoto:primary-translator:" + row["Translator ID"]] if row.get("Translator ID") else [])
        + (["publisher:xml-entity-repaired"] if repaired else []), "sentences": sentences,
    }


def iter_documents(manifest, snapshot_dir: Path, *, stats):
    source = manifest["source"]
    entries = [e for e in manifest["files"] if e["role"] == ROLE]
    if len(entries) != 1:
        raise DataError("Kyoto requires exactly one pinned source archive")
    path = safe_relative(snapshot_dir, entries[0]["path"])
    index = _index(path, source["acquisition"])
    with tarfile.open(path, "r|gz") as archive:
        for member in archive:
            if _member_name(member) == "article":
                yield article_document(_read(archive, member), member.name, index[member.name], source, stats)
