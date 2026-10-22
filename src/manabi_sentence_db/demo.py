"""A completely offline synthetic demonstration; no fetched corpus is committed."""

from __future__ import annotations

from pathlib import Path

from .serialization import digest_json, sha256_file, write_json
from .snapshot import snapshot_identity

XML = """<?xml version="1.0" encoding="UTF-8"?>
<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/" version="0.11">
<page><title>公園の散歩</title><ns>0</ns><id>1</id><revision><id>11</id>
<timestamp>2026-01-01T00:00:00Z</timestamp><model>wikitext</model><format>text/x-wiki</format>
<text xml:space="preserve">今日は公園まで歩きました。小さな犬が木の下で休んでいます。
[[Category:散歩]]</text></revision></page>
<page><title>図書館</title><ns>0</ns><id>2</id><revision><id>12</id>
<timestamp>2026-01-01T00:00:00Z</timestamp><model>wikitext</model><format>text/x-wiki</format>
<text xml:space="preserve">駅の近くに新しい図書館ができました。週末には友達と本を読みに行きます。</text>
</revision></page></mediawiki>
"""


def create_demo_snapshot(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=False)
    source = {
        "schema_version": 1,
        "id": "demo-ja",
        "title": "Synthetic demonstration",
        "language": "ja",
        "adapter": "wikimedia",
        "homepage": "https://example.org/",
        "license": {"id": "CC0-1.0", "url": "https://creativecommons.org/publicdomain/zero/1.0/"},
        "attribution": {
            "text": "Manabi Sentence DB contributors; synthetic test text.",
            "url": "https://github.com/ManabiIO/manabi-sentence-db",
        },
        "license_evidence": ["https://creativecommons.org/publicdomain/zero/1.0/"],
        "acquisition": {
            "wiki_id": "demo",
            "api_url": "https://example.org/w/api.php",
            "export_kind": "content-current",
            "sample_titles": [],
        },
    }
    raw = output / "synthetic.xml"
    raw.write_text(XML, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "source_id": source["id"],
        "source": source,
        "source_config_sha256": digest_json(source),
        "retrieved_at": "2026-01-01T00:00:00Z",
        "mode": "sample",
        "upstream_date": None,
        "request": {"synthetic": True},
        "files": [
            {
                "path": raw.name,
                "role": "mediawiki-xml",
                "sha256": sha256_file(raw),
                "size": raw.stat().st_size,
                "url": "https://example.org/synthetic.xml",
            }
        ],
    }
    manifest["snapshot_id"] = snapshot_identity(manifest)
    write_json(output / "manifest.json", manifest)
    return output / "manifest.json"
