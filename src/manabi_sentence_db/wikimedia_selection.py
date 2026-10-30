"""Bounded, reproducible metadata sampling over already downloaded Wikimedia.

Topic routing allocates a mixed acquisition pilot, not learner-quality labels.
The normal extraction, rights and sentence gates must still run on the selection.
"""

from __future__ import annotations

import hashlib
import heapq
import re
from collections import Counter
from pathlib import Path

from .serialization import (
    DataError,
    atomic_replace_file,
    digest_json,
    require_new_directory,
    write_json,
)
from .snapshot import verify_snapshot
from .wikimedia import (
    MAX_WIKITEXT_CHARACTERS,
    _api_pages,
    _snapshot_path,
    _xml_pages,
)

POLICY = "wikimedia-balanced-metadata-v1"
MAX_SELECTED = 50_000
TOPICS = {
    "food": r"料理|食文化|食品|食材|調理|食事|飲料|菓子",
    "home": r"家事|日常生活|日用品|住宅|家具|衣服|被服|家電|園芸",
    "travel": r"旅行|観光|交通|鉄道|自転車|道路|公共交通",
    "learning": r"教育|学習|学校|図書館|言語|読書",
    "health": r"健康|栄養|衛生|睡眠|運動会|身体運動|運動生理|公衆衛生",
    "culture": r"文化|音楽|美術|工芸|祭|遊び|スポーツ|娯楽",
    "society": r"社会|経済|労働|職業|情報|通信|防災|安全",
    "science": r"科学|数学|物理|化学|技術|生物|地学|天文|医療|医学",
    "history": r"歴史|時代|古代|中世|近代|史跡|遺跡",
    "nature": r"自然環境|自然地理|自然現象|自然保護|自然災害|生態|気象|環境問題|季節|農業|植物|動物",
}
_TOPICS = {key: re.compile(value) for key, value in TOPICS.items()}
_CATEGORIES = re.compile(r"\[\[\s*(?:Category|カテゴリ|カテゴリー)\s*:\s*([^\]\n|]+)", re.I)
_LIST = re.compile(r"曖昧さ回避|一覧|索引|(?:^|の)リスト$")
_VARIETY = re.compile(
    r"人物|[0-9]+年生|[0-9]+年没|存命|生年|没年|の選手|選手$|の俳優|の女優|の歌手|の政治家"
    r"|漫画作品|映画作品|の漫画$|楽曲$|アルバム$|小説$|テレビドラマ|テレビ番組|ラジオ番組"
    r"|アニメ作品|ゲーム作品|年のコンピュータゲーム|コマーシャルソング"
    r"|の鉄道駅|の駅$|の鉄道路線|の企業|の会社|の小学校|の中学校|の高等学校"
    r"|の(?:公立|私立|国立|市立|県立|都立|府立|村立|町立|官立)?大学$|NGC天体|IC天体"
)
_INDIRECT = re.compile(r"出身|所属|を題材|コマーシャルソング|東京俳優生活協同組合|主婦と生活社")


def classify(title: str, categories: list[str], priority: str) -> tuple[str, list[str]]:
    """Keep entities in the general mix instead of using incidental categories."""
    if _LIST.search(title) or any(_LIST.search(category) for category in categories):
        return "excluded-list", []
    if any(_VARIETY.search(category) for category in categories):
        return "general", []
    direct = [category for category in categories if not _INDIRECT.search(category)]
    matches = [topic for topic, pattern in _TOPICS.items()
               if any(pattern.search(category) for category in direct)]
    if not matches:
        return "general", []
    topic = matches[int(priority[:8], 16) % len(matches)]
    evidence = sorted({category for category in direct if _TOPICS[topic].search(category)})
    return topic, [category[:160] for category in evidence[:8]]


def _limits(per_topic, general):
    if any(type(value) is not int or value < 0 for value in (per_topic, general)):
        raise DataError("Selection quotas must be nonnegative integers")
    total = len(TOPICS) * per_topic + general
    if not 1 <= total <= MAX_SELECTED:
        raise DataError(f"Combined selection quota must be 1..{MAX_SELECTED}")
    return dict.fromkeys(TOPICS, per_topic) | {"general": general}


def _implementation_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def sample_pages(pages, *, snapshot_id, per_topic, general, seed="", progress=None):
    """Retain only the requested top-k metadata, independent of scan order."""
    limits = _limits(per_topic, general)
    if not isinstance(seed, str) or len(seed) > 200:
        raise DataError("Selection seed must be at most 200 characters")
    heaps = {topic: [] for topic in limits}
    retained = {}
    counts = Counter()
    for page in pages:
        counts["pages_seen"] += 1
        if progress and counts["pages_seen"] % 50_000 == 0:
            progress(f"Metadata scanned {counts['pages_seen']} pages")
        identity = page["native_id"]
        if not re.fullmatch(r"[1-9][0-9]*", identity) or not page["revision_id"] or not page["title"]:
            counts["invalid-identity"] += 1
            continue
        if len(page["text"]) > MAX_WIKITEXT_CHARACTERS:
            counts["page-text-limit"] += 1
            continue
        priority = digest_json([POLICY, snapshot_id, seed, identity])
        categories = sorted({match.strip() for match in _CATEGORIES.findall(page["text"])})
        topic, evidence = classify(page["title"], categories, priority)
        counts["routed:" + topic] += 1
        if topic not in limits or limits[topic] == 0:
            continue
        row = {
            "native_id": identity, "revision_id": page["revision_id"],
            "title": page["title"][:500], "topic": topic,
            "category_evidence": evidence, "source_characters": len(page["text"]),
        }
        if identity in retained:
            if retained[identity] != row:
                raise DataError("Conflicting retained Wikimedia page identity")
            counts["duplicate-retained-page"] += 1
            continue
        heap = heaps[topic]
        item = (-int(priority, 16), identity, row)
        if len(heap) < limits[topic]:
            heapq.heappush(heap, item)
        elif item[:2] > heap[0][:2]:
            evicted = heapq.heapreplace(heap, item)
            del retained[evicted[1]]
        else:
            continue
        retained[identity] = row
    rows = sorted(retained.values(), key=lambda row: int(row["native_id"]))
    return rows, dict(counts)


def select_wikimedia_documents(snapshot, output, *, per_topic=1000, general=2000,
                               seed="", progress=None):
    """Verify cached inputs and produce a normal snapshot-bound build allowlist.

    Completion is represented by selection.json, written last. An interrupted
    scan has no valid allowlist and must be retried in a fresh output directory.
    No snapshot acquisition or sentence extraction takes place here.
    """
    limits = _limits(per_topic, general)
    if not isinstance(seed, str) or len(seed) > 200:
        raise DataError("Selection seed must be at most 200 characters")
    snapshot, output = Path(snapshot).absolute(), Path(output).absolute()
    if snapshot.resolve(strict=True) != snapshot:
        raise DataError("Use a snapshot manifest outside symlinks")
    if output.is_symlink() or output.parent.resolve(strict=True) != output.parent:
        raise DataError("Use an output directory outside symlinks")
    if output.exists():
        raise DataError("Use a fresh selection output directory")
    implementation = _implementation_sha256()
    manifest = verify_snapshot(snapshot)
    if (manifest["source"]["adapter"] != "wikimedia"
            or manifest["source"]["language"].split("-", 1)[0] != "ja"):
        raise DataError("Balanced topic selection supports Japanese Wikimedia only")
    entries = [entry for entry in manifest["files"]
               if entry["role"] in {"mediawiki-xml", "mediawiki-api"}]
    if not entries:
        raise DataError("Snapshot has no Wikimedia content files")
    require_new_directory(output)
    output.mkdir(mode=0o700)

    def pages():
        for entry in entries:
            if progress:
                progress("Metadata scanning " + entry["path"])
            path = _snapshot_path(snapshot.parent, entry["path"])
            yield from (_xml_pages(path) if entry["role"] == "mediawiki-xml" else _api_pages(path))

    rows, counts = sample_pages(pages(), snapshot_id=manifest["snapshot_id"],
                                per_topic=per_topic, general=general, seed=seed, progress=progress)
    if not rows:
        raise DataError("No Wikimedia pages matched nonzero selection quotas")
    selection = {"schema_version": 1, "source_id": manifest["source_id"],
                 "snapshot_id": manifest["snapshot_id"],
                 "page_ids": [row["native_id"] for row in rows]}
    if _implementation_sha256() != implementation:
        raise DataError("Wikimedia selection implementation changed during the scan")
    report = {
        "policy": POLICY, "implementation_sha256": implementation,
        "selection_sha256": digest_json(selection), "snapshot_scope": manifest["mode"],
        "quotas": limits, "seed": seed, "counts": counts,
        "selected_counts": dict(Counter(row["topic"] for row in rows)), "articles": rows,
        "note": "Metadata routing is a sampling heuristic, not sentence quality, human review or licensing approval. Build the selection through normal extraction and rights/quality gates. No topics certify contemporary language. Title/category metadata is retained; article-body and sentence text is not copied.",
    }
    write_json(output / "selection-report.json", report)
    staged = output / ".selection.json.part"
    write_json(staged, selection)
    atomic_replace_file(staged, output / "selection.json")
    return output / "selection.json"
