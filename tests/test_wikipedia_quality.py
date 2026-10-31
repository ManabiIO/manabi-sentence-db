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
    "は虫類は卵を産む。",
    "は行の発音を練習した。",
    "「下記」という表現の意味を辞書で調べた。",
    "この商品は三千円以下で買うことができる。",
    "十歳以下の子供は、保護者と一緒に参加する。",
    "材料は水、塩、砂糖から構成される。",
    "予定を変更した理由は、電車が止まったためである。",
    "「以下から構成される」という表現を使った。",
    "これは衣かつぎとして食べるのに最も適しているためである。",
    "中緯度各地に同様の気候があるが、地域により時期は若干ずれる。",
    "1989年にはスローフード運動の国際化が行われた。",
])
def test_accessible_prose_including_science_and_dates_is_retained(text):
    assert assess_wikipedia_sentence(text) == (None, [])


@pytest.mark.parametrize(("text", "reason"), [
    ("地域には" + "多くの人が暮らしており、" * 18 + "毎日電車で通勤している。", "long-sentence"),
    ("この関係はE=mc^2によって表される。", "formula-heavy"),
    ("x＝y＋zかつa＞bであると仮定する。", "formula-heavy"),
    ("この式では、P ⇒ Q という命題から P ∧ Q という結論が得られる。", "formula-heavy"),
    ("値は、12、24、36、48、60、72、84の順であり、表にまとめられている。", "number-heavy"),
    ("International Association of Very Specialized Researchersは、この分野の専門家を対象に活動を行っている。", "latin-heavy"),
    ("日本国東京都特別区内交通運輸事業関係法規施行条例改正案附則施行期日決定。", "low-prose"),
    ("この地域は" + "山や川、田畑や森林、" * 9 + "美しい自然に囲まれている。", "enumeration-heavy"),
    ("これは、固有値と固有ベクトルを持つテンソルの性質であり、微分方程式における解の存在条件とその一意性を記述するための一般的な理論である。", "specialist-density"),
    ("市の講座では、海洋生物学、情報工学研究、環境経済学、応用言語学について、各分野の専門家が順番に詳しく説明する予定である。", "compound-density"),
    ("この方式（" + "詳しい内容（さらに別の条件（ここでは省略される）を含む）についての説明が続く。" * 2 + "）を採用している。", "parenthetical-density"),
    ("は反対の性質を持つ。", "dependent-fragment"),
    ("この結果は次のようにまとめられる。", "dependent-fragment"),
    ("以下は、主な分類である。", "dependent-fragment"),
    ("この結晶では、格子欠陥の周囲にある不対電子と共有結合が、表面の物性を変化させる重要な原因となっている。", "specialist-density"),
    ("距離は参加者の所属する学年により下記の通り異なる。", "dependent-fragment"),
    ("部品の配置は下図に示した通りである。", "dependent-fragment"),
    ("と、3種類に区分される。", "dependent-fragment"),
    ("と、三つに分類されている。", "dependent-fragment"),
    ("ベッドシートは多くの国々でペアで使用され、（ベッドシートのペアとしての）ベッドシーツは以下から構成される。", "dependent-fragment"),
    ("こういった構造が利用されるのは、主に以下の理由による。", "dependent-fragment"),
])
def test_dense_examples_are_excluded_with_specific_reasons(text, reason):
    assert assess_wikipedia_sentence(text)[0] == "wikipedia-" + reason


def test_repetition_of_one_specialist_term_is_not_multiple_evidence():
    text = "固有値を調べ、固有値の意味を確認し、固有値についてもう一度説明する。"
    assert assess_wikipedia_sentence(text) == (None, [])
    assert assess_wikipedia_sentence("固有値と固有ベクトルの関係を学ぶ。")[1] == [
        "style:specialist-vocabulary"
    ]


def test_list_introduction_exclusion_keeps_other_work_sentences_and_context_gaps():
    source = yaml.safe_load((Path(__file__).parents[1] / "sources/wikipedia-ja.yaml").read_text())
    texts = ["ベッドシートは寝具の一つである。", "主に以下の理由による。",
             "洗濯して清潔に保つことが大切である。"]
    raw = dict(native_id="list-gap", language="ja", title="架空の寝具記事",
               url="https://example.invalid/bedding", license=source["license"],
               attribution=source["attribution"], sentences=[{"text": text} for text in texts])
    stats = Counter()
    record = canonical_document(raw, dict(source_id="wikipedia-ja", snapshot_id="fixture", source=source),
                                stats, set())
    assert [(sentence["ordinal"], sentence["text"]) for sentence in record["sentences"]] == [
        (0, texts[0]), (2, texts[2])]
    assert record["license"] == source["license"]
    assert record["attribution"] == source["attribution"]
    assert WIKIPEDIA_QUALITY_VERSION in record["transformations"]
    assert stats["rejected:wikipedia-dependent-fragment"] == 1


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


@pytest.mark.parametrize('text', [
    'であることを意味する。', 'ではないことを示す。', 'でないことがわかる。',
    '詳しくは国道19号を参照。', '詳細については別の記事を参照のこと。',
    'くわしくは公式資料を参照されたい。',
    '適法な業務請負の要件について、以下4つの全てを満たすものであることを求めている。',
    '申請者は下記の三つの条件を満たす必要がある。',
    '応募者は以下２項目を満たす。',
])
def test_formula_remnants_cross_references_and_missing_numbered_requirements_are_rejected(text):
    assert assess_wikipedia_sentence(text) == ('wikipedia-dependent-fragment', [])


@pytest.mark.parametrize('text', [
    'この記号は、入口が右側にあることを意味する。',
    'である調は、説明文などで使われる文体である。',
    '「であることを意味する」という文が残っていた。',
    '詳しくは先生に聞いてください。',
    '詳しく書いた説明書を参照した。',
    '彼は国道19号の地図を参照してから出発した。',
    '参加費は千円以下であることを求めている。',
    '三つの条件を満たす必要がある。',
    '要件は以下の三つで、年齢、住所、本人確認である。',
    '申請者は年齢、住所、本人確認の三つの条件を満たす必要がある。',
    '「以下の三つ」という表現を例に挙げている。',
])
def test_fragment_rules_preserve_complete_explanations_instructions_and_inline_requirements(text):
    assert assess_wikipedia_sentence(text) == (None, [])


def test_refined_fragment_gate_keeps_other_article_sentences_and_original_ordinals():
    source = yaml.safe_load((Path(__file__).parents[1] / 'sources/wikipedia-ja.yaml').read_text())
    texts = ['公園の入口には案内板がある。', 'であることを意味する。',
             '詳しくは公式資料を参照。', '申請者は以下4つを満たす必要がある。',
             '毎年多くの人が公園を訪れる。']
    raw = dict(native_id='refined-gap', language='ja', title='架空の公園記事',
               url='https://example.invalid/park', license=source['license'],
               attribution=source['attribution'],
               sentences=[{'text': text, 'source_ordinal': i * 2} for i, text in enumerate(texts)])
    stats = Counter()
    record = canonical_document(raw, dict(source_id='wikipedia-ja', snapshot_id='fixture', source=source), stats, set())
    assert [(s['ordinal'], s['text']) for s in record['sentences']] == [(0, texts[0]), (8, texts[4])]
    assert record['license'] == source['license'] and record['attribution'] == source['attribution']
    assert 'wikipedia-example-quality-v5' in record['transformations']
    assert stats['rejected:wikipedia-dependent-fragment'] == 3
