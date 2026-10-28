from collections import Counter
from pathlib import Path

import pytest
import yaml

from manabi_sentence_db.build import canonical_document
from manabi_sentence_db.wikipedia_quality import (
    WIKIPEDIA_QUALITY_VERSION,
    assess_wikipedia_sentence,
)


@pytest.mark.parametrize("text", [
    "水は温めると蒸発し、冷やすと凍る。",
    "地球のまわりを月が回っている。",
    "この研究では、子供たちの生活について調べた。",
    "二酸化炭素は地球の気温に影響を与えている。",
    "細胞の中には遺伝子があり、体の働きに関わっている。",
    "朝の気温はマイナス3度だったが、昼には10度まで上がった。",
    "2011年3月11日に大きな地震が発生した。",
    "JR東日本は、東京と周辺の地域で鉄道を運行している。",
    "固有値について学ぶには、まず行列の基本を理解する必要がある。",
    "日本の人口は約1億人であり、多くの人が都市で生活している。",
    "公園（駅の近くにある）には大きな池があり、春になると多くの人が訪れる。",
    "国際連合教育科学文化機関は、世界の文化や教育に関する活動を行い、多くの国と協力している。",
])
def test_accessible_prose_including_science_and_dates_is_retained(text):
    assert assess_wikipedia_sentence(text) == (None, [])


@pytest.mark.parametrize(("text", "reason"), [
    ("地域には" + "多くの人が暮らしており、" * 18 + "毎日電車で通勤している。", "long-sentence"),
    ("この関係はE=mc^2によって表される。", "formula-heavy"),
    ("x＝y＋zかつa＞bであると仮定する。", "formula-heavy"),
    ("値は、12、24、36、48、60、72、84の順であり、表にまとめられている。", "number-heavy"),
    ("International Association of Very Specialized Researchersは、この分野の専門家を対象に活動を行っている。", "latin-heavy"),
    ("日本国東京都特別区内交通運輸事業関係法規施行条例改正案附則施行期日決定。", "low-prose"),
    ("この地域は" + "山や川、田畑や森林、" * 9 + "美しい自然に囲まれている。", "enumeration-heavy"),
    ("これは、固有値と固有ベクトルを持つテンソルの性質であり、微分方程式における解の存在条件とその一意性を記述するための一般的な理論である。", "specialist-density"),
    ("市の講座では、海洋生物学、情報工学研究、環境経済学、応用言語学について、各分野の専門家が順番に詳しく説明する予定である。", "compound-density"),
    ("この方式（" + "詳しい内容（さらに別の条件（ここでは省略される）を含む）についての説明が続く。" * 2 + "）を採用している。", "parenthetical-density"),
])
def test_dense_examples_are_excluded_with_specific_reasons(text, reason):
    assert assess_wikipedia_sentence(text)[0] == "wikipedia-" + reason


def test_repetition_of_one_specialist_term_is_not_multiple_evidence():
    text = "固有値を調べ、固有値の意味を確認し、固有値についてもう一度説明する。"
    assert assess_wikipedia_sentence(text) == (None, [])
    assert assess_wikipedia_sentence("固有値と固有ベクトルの関係を学ぶ。")[1] == [
        "style:specialist-vocabulary"
    ]


@pytest.mark.parametrize("source_id", ["wikipedia-ja", "wikivoyage-ja", "tatoeba-ja"])
def test_build_applies_gate_only_to_japanese_wikipedia_and_keeps_ordinal_gaps(source_id):
    source = yaml.safe_load((Path(__file__).parents[1] / "sources/wikipedia-ja.yaml").read_text())
    source["id"] = source_id
    formula = "この関係はE=mc^2によって表される。"
    raw = {
        "native_id": "1", "language": "ja", "title": "架空の文章",
        "url": "https://example.invalid/article", "license": source["license"],
        "attribution": source["attribution"],
        "sentences": [{"text": text} for text in (
            "公園には大きな池がある。", formula, "毎年多くの人が訪れる。"
        )],
    }
    stats = Counter()
    record = canonical_document(raw, {
        "source_id": source_id, "snapshot_id": "fixture", "source": source,
    }, stats, set())
    if source_id == "wikipedia-ja":
        assert [s["ordinal"] for s in record["sentences"]] == [0, 2]
        assert stats["rejected:wikipedia-formula-heavy"] == 1
        assert WIKIPEDIA_QUALITY_VERSION in record["transformations"]
    else:
        assert len(record["sentences"]) == 3
        assert WIKIPEDIA_QUALITY_VERSION not in record["transformations"]
    assert stats["sentences_seen"] == 3


def test_wikipedia_policy_is_not_applied_to_other_languages():
    source = yaml.safe_load((Path(__file__).parents[1] / "sources/wikipedia-ja.yaml").read_text())
    source.update(id="wikipedia-en", language="en")
    raw = {
        "native_id": "1", "language": "en", "title": "Example",
        "url": "https://example.invalid/article", "license": source["license"],
        "attribution": source["attribution"],
        "sentences": [{"text": "The relation is given by E=mc^2."}],
    }
    record = canonical_document(raw, {
        "source_id": source["id"], "snapshot_id": "fixture", "source": source,
    }, Counter(), set())
    assert len(record["sentences"]) == 1
    assert WIKIPEDIA_QUALITY_VERSION not in record["transformations"]
