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
    assert WIKIPEDIA_QUALITY_VERSION in record['transformations']
    assert stats['rejected:wikipedia-dependent-fragment'] == 3


@pytest.mark.parametrize('text', [
    'である。', 'であった。', 'です。',
    'で与えられる。', 'で定義される。', 'と表される。', 'となる。',
    'が成り立つことである。', 'がゼロ切断の外側で完全であることを言う。',
    'という形で与えられる1次元写像である。',
    '以下、主に原材料として使われる素材を挙げる。',
    '園内には以下の施設が存在する。', 'ここでは次の例を示す。',
])
def test_missing_display_and_list_remnants_are_not_standalone_examples(text):
    assert assess_wikipedia_sentence(text) == ('wikipedia-dependent-fragment', [])


@pytest.mark.parametrize('text', [
    'α と σ はパラメータ（定数係数）である。',
    '値は測定結果で与えられる。', 'この量は距離と時間の比で定義される。',
    '記号は丸で表される。', '水を冷やすと氷となる。',
    '二つの数が等しいとき、この関係が成り立つ。',
    'この式は単純な形という形で与えられる写像である。',
    'がん患者を支える活動が行われている。',
    'がま口は、小銭などを入れる袋である。',
    '園内には図書館と運動施設が存在する。',
    '園内には以下の施設、図書館と体育館がある。',
    '以下、図書館の中では静かにしてください。',
    '五歳以下の子供に遊び方を紹介する。',
    '「以下の施設が存在する」という説明がある。',
    '彼は次の例を示す前に、前の問題を復習した。',
    '内積について、先生に質問した。',
    'フェレドキシンは植物の中にあるタンパク質である。',
])
def test_structural_tightening_keeps_named_relations_inline_lists_and_copulas(text):
    assert assess_wikipedia_sentence(text) == (None, [])


@pytest.mark.parametrize('text', [
    '次元が3以上のノルム空間において、内積とスカラー倍の条件を満たすためには、その空間がヒルベルト空間であることが必要である。',
    'この反応では、リンゴ酸脱水素酵素、アルギナーゼ、シキミ酸経路のフェニルアラニンアンモニア分解酵素がそれぞれ異なる働きを持つ。',
])
def test_multiple_specialist_math_or_biochemical_terms_need_structural_density(text):
    assert assess_wikipedia_sentence(text)[0] == 'wikipedia-specialist-density'


def test_single_new_specialist_term_and_repetition_are_not_density():
    assert assess_wikipedia_sentence('内積について調べ、内積を計算し、内積の意味を説明した。') == (None, [])
    assert assess_wikipedia_sentence('ノルム空間と内積の関係を調べる。') == (
        None, ['style:specialist-vocabulary'])


def test_v6_filters_keep_original_positions_and_rights_in_other_sentences():
    source = yaml.safe_load((Path(__file__).parents[1] / 'sources/wikipedia-ja.yaml').read_text())
    texts = ['公園の入口には案内板がある。', '園内には以下の施設が存在する。',
             'で与えられる。', 'がゼロ切断の外側で完全であることを言う。',
             'α と σ はパラメータ（定数係数）である。']
    raw = dict(native_id='v6-gap', language='ja', title='架空の記事',
               url='https://example.invalid/v6', license=source['license'],
               attribution=source['attribution'],
               sentences=[{'text': text, 'source_ordinal': i * 2} for i, text in enumerate(texts)])
    stats = Counter()
    record = canonical_document(raw, dict(source_id='wikipedia-ja', snapshot_id='fixture', source=source), stats, set())
    assert [(s['ordinal'], s['text']) for s in record['sentences']] == [(0, texts[0]), (8, texts[4])]
    assert record['license'] == source['license'] and record['attribution'] == source['attribution']
    assert WIKIPEDIA_QUALITY_VERSION in record['transformations']
    assert stats['rejected:wikipedia-dependent-fragment'] == 3


@pytest.mark.parametrize('text', [
    'の下に考える。', 'のもとに考えられる。',
    '（例えば 参照）。', '(たとえば 参照)。', '（参照）。',
])
def test_missing_condition_and_parenthetical_reference_targets_are_rejected(text):
    assert assess_wikipedia_sentence(text) == ('wikipedia-dependent-fragment', [])


@pytest.mark.parametrize('text', [
    'この条件の下に考える。', '一定の条件のもとに考えられる。',
    'のどの調子について考える。',
    '詳しい方法（例えば参考文献を参照）について説明する。',
    '「の下に考える」という断片が残っていた。',
    '記号の意味を説明した（例えば図を参照）。',
    '（例えば）別の方法も考えられる。',
])
def test_named_conditions_references_and_quoted_remnants_are_retained(text):
    assert assess_wikipedia_sentence(text) == (None, [])


@pytest.mark.parametrize("text", [
    "のような、いくつかの計算式に現れる。",
    "のような，説明の一部が残る。",
    "地域の人口の推移を調査に基づき示す（単位：人）。",
    "年度ごとの内訳を示した(単位:件)。",
])
def test_unbound_formula_examples_and_unit_labeled_missing_tables_are_rejected(text):
    assert assess_wikipedia_sentence(text) == ("wikipedia-dependent-fragment", [])


@pytest.mark.parametrize("text", [
    "このような、いくつかの例が見られる。",
    "円のような形に整える。",
    "「のような、」という断片が残っていた。",
    "地域の人口の推移を調べた。",
    "人口の推移を示す指標の単位は人である。",
    "表の単位は人である。",
    "速度を示す（単位：キロメートル毎時）。",
    "人口の推移は増加傾向を示す（単位：人）。",
    "袖なしの服を着た。",
    "医師が手術で傷んだ組織を取り除いた。",
])
def test_related_complete_prose_nominal_forms_and_clinical_text_stay_eligible(text):
    assert assess_wikipedia_sentence(text) == (None, [])


def test_reviewed_exact_text_exclusions_are_hash_pinned_without_rewriting(monkeypatch):
    import hashlib

    from manabi_sentence_db import wikipedia_quality

    text = "これは合成の除外テスト文です。"
    monkeypatch.setattr(wikipedia_quality, "REVIEWED_EXCLUSIONS", {
        hashlib.sha256(text.encode()).hexdigest(): "wikipedia-reviewed-wording",
    })
    assert assess_wikipedia_sentence(text) == ("wikipedia-reviewed-wording", [])
    assert assess_wikipedia_sentence("これは合成の保持テスト文です。") == (None, [])


@pytest.mark.parametrize("text", [
    "のようである。", "と分解することができる。", "と言い換えることもできる。",
    "また、反則の具体例は次の場合がある。",
    "具体的な応用分野としては、以下のものが挙げられる。",
    "、この言語は日常会話で用いられる。",
    "第9巻登場。", "第１２話登場。",
])
def test_detached_relations_missing_lists_and_installment_labels_are_rejected(text):
    assert assess_wikipedia_sentence(text) == ("wikipedia-dependent-fragment", [])


@pytest.mark.parametrize("text", [
    "この図は花のようである。",
    "水は水素と酸素に分解することができる。",
    "この言葉は、自由と言い換えることもできる。",
    "彼は「のようである」という断片を見つけた。",
    "次の場合があるかどうか調べる。",
    "次の場合、担当者に連絡してください。",
    "例として、水、塩、砂糖が挙げられる。",
    "「以下のものが挙げられる」という表現を使った。",
    "第9巻に登場する人物である。", "第9巻では主人公が登場。",
    "2009年3月18日、長男誕生。",
    "ホテイチクはマダケ属に属する竹の一種。",
    "母親の支援は子供の成長に役立つ。",
])
def test_v9_preserves_named_relations_inline_lists_nominal_prose_and_dates(text):
    assert assess_wikipedia_sentence(text) == (None, [])


def test_v9_admission_preserves_original_positions_and_attribution():
    source = yaml.safe_load((Path(__file__).parents[1] / "sources/wikipedia-ja.yaml").read_text())
    texts = ["水は私たちの生活に欠かせない。", "と分解することができる。",
             "具体的な用途には以下のものが挙げられる。", "水は水素と酸素からできている。"]
    raw = dict(native_id="v9-gap", language="ja", title="架空の水の記事",
               url="https://example.invalid/water", license=source["license"],
               attribution=source["attribution"],
               sentences=[{"text": text, "source_ordinal": i * 2} for i, text in enumerate(texts)])
    stats = Counter()
    record = canonical_document(raw, dict(source_id="wikipedia-ja", snapshot_id="fixture", source=source),
                                stats, set())
    assert [(s["ordinal"], s["text"]) for s in record["sentences"]] == [(0, texts[0]), (6, texts[3])]
    assert record["license"] == source["license"]
    assert record["attribution"] == source["attribution"]
    assert stats["rejected:wikipedia-dependent-fragment"] == 2


@pytest.mark.parametrize("text", [
    "代表的な事例の内訳は下の通りである。",
    "主な条件は上のとおりです。",
    "近世以降の鬼瓦には。",
    "のCMに登場する人物について説明する。",
    "の15個のみである。",
])
def test_v10_rejects_missing_list_topic_predicate_and_leading_genitive(text):
    assert assess_wikipedia_sentence(text) == ("wikipedia-dependent-fragment", [])


@pytest.mark.parametrize("text", [
    "近世以降の鬼瓦には多くの種類がある。",
    "「には」という表現を使った。",
    "この説明では、助詞を「には」。",
    "この道は坂の下の通りに続いている。",
    "自宅の住所は坂の下の通りである。",
    "条件は下の通りにある店舗で働くことです。",
    "特徴は上の通りからもよく見える。",
    "条件は年齢と住所の二つである。",
    "のどが痛いので病院へ行く。",
    "のれんを店の入口に掛けた。",
    "15個のみである。",
    "このCMに登場する人物について説明する。",
    "この数の15個のみである。",
])
def test_v10_preserves_complete_clauses_quoted_particles_and_ordinary_no_words(text):
    assert assess_wikipedia_sentence(text) == (None, [])


# Exact unchanged CC BY-SA Wikipedia examples and citations: docs/sources.md.
@pytest.mark.parametrize(("text", "reason"), [
    ("餌は、端脚類、橈脚類、オキアミ類、アミ類、イカ類、魚類を捕食している。", "wikipedia-reviewed-wording"),
    ("8月30日 正八位。", "wikipedia-dependent-fragment"),
    ("香港で最も北に位置する区でそう名付けられて、香港と中国本土が陸地連接区の二つの一つ（もう一つは元朗区）。", "wikipedia-reviewed-wording"),
    ("近代式下水道は18世紀以降に水系伝染病予防や地域環境改善の施設としして建設されたものをいうが、日本で最初といわれることもある東京の神田下水も当初は雨水排除が目的であった。", "wikipedia-reviewed-wording"),
    ("日本では1985年8月に社団法人日本造園建設業協会が国際園芸家協会 (AIPH) に加盟し、その後国際園芸博覧会の招請している。", "wikipedia-reviewed-wording"),
    ("こうして1819年に、名称を国立の美術学校（エコール・ナシオナル・シュペリウール・デ・ボザール）に改称となった。", "wikipedia-reviewed-wording"),
    ("素数 p > 7 は、次の合同関係を満たすときウォルステンホルム素数という。", "wikipedia-dependent-fragment"),
    ("アルゴリズム制は電子政府の文献において補足されない、または公的な行政の実践における、新しい問題を提起する。", "wikipedia-reviewed-wording"),
    ("括弧内は一部便のみ経由。", "wikipedia-dependent-fragment"),
 ])
def test_v10_withholds_demonstrated_exact_errors_without_rewriting(text, reason):
    assert assess_wikipedia_sentence(text) == (reason, [])


def test_v10_retains_correct_related_wording_and_source_gaps():
    source = yaml.safe_load((Path(__file__).parents[1] / "sources/wikipedia-ja.yaml").read_text())
    texts = ["魚は小さなエビやイカを捕食している。", "近世以降の鬼瓦には。",
             "近代式下水道は地域環境を改善する施設として建設された。"]
    raw = dict(native_id="v10-gap", language="ja", title="架空の例文集",
               url="https://example.invalid/examples", license=source["license"],
               attribution=source["attribution"],
               sentences=[{"text": text, "source_ordinal": i * 3} for i, text in enumerate(texts)])
    stats = Counter()
    record = canonical_document(raw, dict(source_id="wikipedia-ja", snapshot_id="fixture", source=source),
                                stats, set())
    assert [(s["ordinal"], s["text"]) for s in record["sentences"]] == [(0, texts[0]), (6, texts[2])]
    assert record["license"] == source["license"]
    assert record["attribution"] == source["attribution"]
    assert all(s["review_state"] == "unreviewed" for s in record["sentences"])
    assert WIKIPEDIA_QUALITY_VERSION in record["transformations"]


@pytest.mark.parametrize("text", [
    "は、1950年以降もいちじるしくロマン派的な様式で作曲し続けている。",
    "を、詳しく説明している。",
    "の、長い歴史が記録されている。",
])
def test_v11_withholds_unquoted_comma_led_orphan_particles(text):
    assert assess_wikipedia_sentence(text) == ("wikipedia-dependent-fragment", [])


@pytest.mark.parametrize("text", [
    "「は、」という書き方について説明した。",
    "が、すぐに考え直した。",
    "は虫類は丸い卵を産む。",
    "彼は、1950年以降も作曲し続けている。",
    "その意味を、詳しく説明している。",
    "その町の、長い歴史が記録されている。",
    "mRNAは体の中で作られる。",
    "ゲノムについて学び、ゲノムの働きを調べ、ゲノムについて発表した。",
    "この講座では、回帰分析の基本を例を使いながら分かりやすく説明する。",
    "脊髄の働きについて、図を使って説明した。",
    "実験では、反応中間体の性質について詳しく調べた。",
])
def test_v11_keeps_complete_ordinary_and_introductory_science_prose(text):
    assert assess_wikipedia_sentence(text) == (None, [])


# Unchanged CC-BY-SA-4.0 pilot examples; article links in docs/sources.md.
@pytest.mark.parametrize("text", [
    "ある反応中間体（あるいは反応物）から2つの素反応が分岐する場合の連続反応は平行反応（parallel reaction）と呼ばれる。",
    "ポリオウイルスはプラス鎖RNAウイルスであるため、ウイルス粒子内に包み込まれたゲノムは、そのままの状態でmRNAとして機能し、宿主細胞のリボソームによって直ちに翻訳される。",
    "一般的な逆ミルズ比の適用例は、回帰分析でのセレクションバイアスの影響を補正する際に用いる。",
    "ヤツメウナギの脊髄を身体から取り出し、その神経活動を記録した研究によれば、身体から取り出した脊髄の神経活動は、身体内に存在したときと非常に似た発火パターンを示したことから、この発火パターンは Fictive locomotion（Fictiveは Fiction の形容詞）とよばれている。",
])
def test_v11_withholds_multiple_distinct_terms_in_dense_specialist_prose(text):
    assert assess_wikipedia_sentence(text) == ("wikipedia-specialist-density", [])


def test_v11_keeps_two_terms_as_style_metadata():
    assert assess_wikipedia_sentence("ゲノムとmRNAの関係を学ぶ。") == (
        None, ["style:specialist-vocabulary"],
    )
