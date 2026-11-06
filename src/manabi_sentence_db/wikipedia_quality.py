"""Cheap, source-specific admission rules for Japanese Wikipedia examples.

These inspect sentence form, not article topic or author expertise. Ordinary
science/history prose remains eligible. Thresholds are deliberately explicit;
this is neither a readability model nor a calibrated JLPT assessment.
"""

import hashlib
import re
import unicodedata

WIKIPEDIA_QUALITY_VERSION = "wikipedia-example-quality-v11"

# Exact, unchanged texts assessed in the November 3–4 assistant source reviews.
# Hashes keep these local findings from becoming broad grammatical/topic bans.
# See docs/sources.md; retained occurrences are still marked unreviewed.
REVIEWED_EXCLUSIONS = {
    "608065e2355bdf498bc4c7825f39f432141a8d593ff92b9f6c67e70c866ec278":
        "wikipedia-reviewed-wording",  # 太陽水殺菌: 人々がで
    "bd14efee27e62bde28c3cebb5c4baf46b61914d7eb7a895ad4f6e1a95b5fc1bc":
        "wikipedia-reviewed-wording",  # ラボ情報管理システム: を合理化が
    "72878917af406ce63269af69ad1c99bc06a4058d08e8215275f58c5f17e2fae5":
        "wikipedia-reviewed-wording",  # 金山寺味噌: 容器に中に
    "1481b9cbf22716cddda77e95e7da329bcbbedc803d305135c2a737a29bd456f0":
        "wikipedia-reviewed-explicit-violence",  # ロシア睡眠実験: graphic passage
    "d4342a9d819d3a41567127cd238d517460d57b596e63fda81079f31b0430bccb":
        "wikipedia-reviewed-wording",  # 代替肉: 取り入れるこに
    "02e776d8a557349c5a23fda8c9d0b25c3d7af0b4fe05047971f080d72fcb83fd":
        "wikipedia-reviewed-wording",  # パラサイト・イヴ: contradictory active/passive wording
    "08295fa53420b4b07a1602e68f436ffb38295d258874264d113e76c65bc71ee4":
        "wikipedia-reviewed-wording",  # Server Message Block: 相互運用性に問題を解消
    "41dd307b8471fcb47f225c44b75b1cdfb1b2b8023f83c83530db58515326a42f":
        "wikipedia-dependent-fragment",  # 作業環境測定士: detached table-symbol legend
    "ee71edcfe1521aa298fe01070a6d37970d8de9b3a3b09a4f1051f4436077b721":
        "wikipedia-reviewed-explicit-violence",  # detailed self-harm passage
    "2f31c87fd9948e985754df1a51790cebb0613d4f7f98ff41fb6042c639e37447":
        "wikipedia-reviewed-wording",  # ハタハタ: November 4 successor sample 45
    "3ef65cb8567645d70180565a1cc7a13020cd0a4df80fc6291f27cdaa5159cd5d":
        "wikipedia-dependent-fragment",  # 中村勝平: November 4 successor sample 49
    "707b7bc90e1e715b01d738177b39645825331228fb4bb56eac13c628f6bdbe23":
        "wikipedia-reviewed-wording",  # 北区 (香港): November 4 successor sample 69
    "276443fec36b7dcfa8f0ad2aae71bb6238a04568977482f44f67f422723709bc":
        "wikipedia-reviewed-wording",  # 下水道: November 4 successor sample 90
    "71c50770dbf1b907aaf42bcca8e7c4d4d7ac0a6ce65e0a9d7208c80ec8dbb2c9":
        "wikipedia-reviewed-wording",  # 国際園芸博覧会: November 4 successor sample 134
    "a19817971d95931406db1bffb65d964ae74d848c3c599dd1b2e1a153986eae5a":
        "wikipedia-reviewed-wording",  # エコール・デ・ボザール: November 4 successor sample 145
    "3445592c0948196fb8b37848ba8fd89f9743c9f1826d99af87fbd2eb2ae003f4":
        "wikipedia-dependent-fragment",  # ウォルステンホルム素数: November 4 successor sample 208
    "d4826cbe2b594aa926c31f525f976bf24c38ac38dba53a56da3f749c6131a17d":
        "wikipedia-reviewed-wording",  # アルゴリズム制: November 4 successor sample 235
    "a101c7a02c0966bf920a467462912ae63354083ca2146ec6374684168b4a6690":
        "wikipedia-dependent-fragment",  # 真室川町路線バス: November 4 successor sample 260
}

_NUMBERS = re.compile(r"[0-9０-９]+(?:[.,．][0-9０-９]+)*")
_KANJI = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LONG_COMPOUNDS = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]{5,}")
_HIRAGANA = re.compile(r"[ぁ-ゖ]")
_LATIN = re.compile(r"[A-Za-zＡ-Ｚａ-ｚ]")
_EQUATION = re.compile(r"[A-Za-zＡ-Ｚａ-ｚ0-9０-９α-ωΑ-Ω]\s*[=＝<>＜＞≤≥≠≈]")
_PARENS = {"（": "）", "(": ")", "［": "］", "[": "]"}
_FOLLOWING_MATERIAL = re.compile(
    r"(?:以下|次)の(?:よう|とおり|通り)|(?:以下|次)に(?:示|挙げ|述べ)"
    r"|^(?:以下|上記|上述|前述|後述)(?:は|の|を|に|で)"
    r"|(?:下記|下表|次表|上表|右表|左表|上図|下図)"
    r"(?:の(?:とおり|通り|よう)|(?:に|を)(?:示|掲げ|参照)|参照)"
)
_ORPHAN = re.compile(
    r"^(?:(?:は(?!虫類|虫|行)|を)(?=[一-鿿A-Za-z0-9α-ωΑ-Ω])"
    r"|が(?=[一-鿿ァ-ヺA-Za-z0-9α-ωΑ-Ω])"
    r"|の(?=[A-Za-zＡ-Ｚａ-ｚ0-9０-９]))"
)
_DANGLING_LIST = re.compile(
    # A terminal introduction has no components/reasons in this sentence.
    # Do not match 以下 as a numerical bound or a quoted expression.
    r"(?:以下|下記)(?:から構成され(?:る|ている)|の理由による)[。．.!！?？]?\Z"
    # This particle-led classification is left over after an omitted list.
    r"|^と[、，,][0-9０-９一二三四五六七八九十]+(?:種類|種|つ)に"
    r"(?:区分|分類|大別)され(?:る|ている)[。．.!！?？]?\Z"
)
# These are complete references to other material, not independent examples.
# Ordinary uses of 参照 and instructions to ask someone remain valid prose.
_CROSS_REFERENCE_ONLY = re.compile(
    r"^(?:詳しく|くわしく|詳細(?:について)?|詳しい内容)は"
    r"[^。｡！？!?]{1,100}を参照(?:のこと|されたい|すること)?[。．.!！?？]?\Z"
)
# Removed display formulas can leave only this terminal explanation. Require
# the entire copula-led remnant; a sentence naming what has that meaning stays.
_FORMULA_REMNANT = re.compile(
    r"^(?:である|ではない|でない)こと(?:を(?:意味する|示す|表す)|が(?:分か|わか)る)"
    r"[。．.!！?？]?\Z"
    # An omitted display can also leave only its relation or result. Match
    # whole remnants, not complete prose that names the value or expression.
    r"|^(?:である|であった|です|で与えられる|で定義される|と表される|となる"
    r"|が成り立つ(?:ことである)?)"
    r"[。．.!！?？]?\Z"
    r"|^という形で与えられる[^。｡！？!?]{0,60}[。．.!！?？]?\Z"
    # No condition/reference target remains after the omitted display/link.
    r"|^の(?:下|もと)に考え(?:る|られる)[。．.!！?？]?\Z"
    r"|^[（(]\s*(?:例えば|たとえば)?\s*参照\s*[）)][。．.!！?？]?\Z"
    # Whole relation phrases whose missing formula was their only argument.
    r"|^(?:のようである|と分解することができる|と言い換えることもできる)"
    r"[。．.!！?？]?\Z"
)
_MISSING_LIST = re.compile(
    # Require a literal forward reference and a list-introducing predicate.
    # Keep inline lists, numerical 以下, and ordinary mentions of facilities.
    r"^(?:以下|下記)[、，,][^。｡！？!?]{0,80}"
    r"(?:挙げる|列挙する|示す|紹介する|記載する)[。．.!！?？]?\Z"
    r"|(?:以下|下記|次)の(?:施設|項目|種類|条件|要件|特徴|例|もの)"
    r"(?:が(?:ある|存在する)|を(?:挙げる|列挙する|示す|紹介する|記載する))"
    r"[。．.!！?？]?\Z"
    r"|(?:以下|下記|次)の(?:施設|項目|種類|条件|要件|特徴|例|もの|場合)"
    r"が(?:ある|挙げられる)[。．.!！?？]?\Z"
)
_DETACHED_LABEL = re.compile(
    # A dropped inline subject/object can leave only its particle before a
    # comma. Keep quoted particle mentions and conjunction が、 untouched.
    r"^[、，,]|^[はをの][、，,]"
    r"|^第[0-9０-９一二三四五六七八九十百]+(?:巻|話)登場[。．.!！?？]?\Z"
)
# A terminal topic particle has lost its predicate; quoted mentions of the
# particle and complete clauses do not end in this bare form.
_DANGLING_TOPIC = re.compile(r"には[。．.!！?？]\Z")
# Require a list noun so 下の通り (a street below) remains ordinary prose.
_LIST_REFERENCE = re.compile(
    r"(?:内訳|項目|分類|条件|特徴|要件)は(?:下|上)の(?:通り|とおり)"
    r"(?:である|です)[。．.!！?？]?\Z"
)
_UNBOUND_EXAMPLE = re.compile(r"^のような[、，,]")
_MISSING_UNIT_TABLE = re.compile(
    # A table introduction with only a terminal unit label, not the data.
    # Require both a table-content noun and a terminal presentation predicate.
    # Generic unit explanations and ordinary population prose remain eligible.
    r"(?:推移|一覧|内訳)を[^。｡！？!?]{0,80}(?:示す|示した|示している)"
    r"\s*[（(]\s*単位\s*[:：]\s*[^。｡！？!?()（）]{1,20}[）)]"
    r"[。．.!！?？]?\Z"
)
_NUMBERED_REQUIREMENTS = re.compile(
    r"(?:以下|下記)の?[0-9０-９一二三四五六七八九十]+"
    r"(?:つ(?:の(?:条件|要件|事項))?|項目|条件|要件)(?:の?(?:全て|すべて))?を満たす"
    r"(?:必要がある|ことが必要である|ものであることを求めている)?[。．.!！?？]?\Z"
)
# Require several distinct terms plus structural density. A single term, or
# repeated mentions of one term, never establishes specialist density.
_SPECIALIST = (
    "固有値", "固有ベクトル", "微分方程式", "偏微分", "位相空間", "多様体",
    "可換", "準同型", "テンソル", "ハミルトニアン", "ラグランジアン",
    "波動関数", "量子化", "摂動", "縮退", "フェルミ", "ボソン",
    "塩基配列", "転写因子", "遺伝子発現", "ポリメラーゼ", "リン酸化",
    "触媒活性", "配位子", "求核", "求電子", "立体異性", "モル濃度",
    "帰無仮説", "有意水準", "尤度", "共分散", "漸近", "確率密度",
    "格子欠陥", "不対電子", "共有結合", "物性", "表面再構成", "ダングリングボンド",
    "直観論理", "結合子", "双対", "線形含意", "シークエント", "部分構造論理", "カット規則",
    "棘条", "軟条", "小離鰭", "臀鰭", "背鰭", "腹鰭", "側線鱗", "尾叉長", "黒色素胞",
    "バナッハ空間", "ノルム空間", "ヒルベルト空間", "内積", "スカラー倍",
    "共形場理論", "弦理論", "ヴィラソロ代数",
    "フェレドキシン", "リンゴ酸脱水素酵素", "イソクエン酸脱水素酵素",
    "アルギナーゼ", "シキミ酸経路", "フェニルアラニンアンモニア分解酵素", "ペルオキシダーゼ",
    # The November 6 cost pilot exposed dense passages not covered by the
    # earlier vocabulary. The existing three-distinct-terms + structure gate
    # still applies; a field name or one repeated term never rejects a sentence.
    "反応中間体", "素反応", "平行反応",
    "mRNA", "ゲノム", "リボソーム", "宿主細胞",
    "逆ミルズ比", "回帰分析", "セレクションバイアス",
    "脊髄", "神経活動", "発火パターン",
)
_SPECIALIST_PATTERN = re.compile("|".join(sorted(_SPECIALIST, key=len, reverse=True)))


def assess_wikipedia_sentence(text: str) -> tuple[str | None, list[str]]:
    """Return a rejection reason and retained heuristic style tags.

    Work on unchanged text; never simplify formulas or rewrite source sentences.
    Called only after the shared malformed-text/rights extraction gates.
    """
    reviewed_reason = REVIEWED_EXCLUSIONS.get(hashlib.sha256(text.encode("utf-8")).hexdigest())
    if reviewed_reason:
        return reviewed_reason, []
    length = len(text)
    if length > 180:
        return "wikipedia-long-sentence", []
    if (_FOLLOWING_MATERIAL.search(text) or _ORPHAN.search(text)
            or _DANGLING_LIST.search(text) or _CROSS_REFERENCE_ONLY.search(text)
            or _FORMULA_REMNANT.search(text) or _NUMBERED_REQUIREMENTS.search(text)
            or _MISSING_LIST.search(text) or _UNBOUND_EXAMPLE.search(text)
            or _MISSING_UNIT_TABLE.search(text) or _DETACHED_LABEL.search(text)
            or _DANGLING_TOPIC.search(text) or _LIST_REFERENCE.search(text)):
        return "wikipedia-dependent-fragment", []
    symbols = sum(unicodedata.category(char) == "Sm" for char in text)
    if symbols >= 3 or (
        _EQUATION.search(text) and (symbols >= 2 or re.search(r"\^[0-9０-９]", text))
    ) or (
        symbols >= 2 and any(char in text for char in "⇒⇔∧∨∀∃∈⊂⊆⊢⊨")
    ):
        return "wikipedia-formula-heavy", []
    if length >= 35:
        latin = len(_LATIN.findall(text))
        numbers = _NUMBERS.findall(text)
        numeric_chars = sum(len(number) for number in numbers)
        if latin >= 18 and latin / length >= 0.35:
            return "wikipedia-latin-heavy", []
        if len(numbers) >= 6 and numeric_chars / length >= 0.12:
            return "wikipedia-number-heavy", []
        if len(_HIRAGANA.findall(text)) / length < 0.08:
            return "wikipedia-low-prose", []
    stack = []
    parenthetic_chars = 0
    maximum_depth = 0
    for char in text:
        if char in _PARENS:
            stack.append(_PARENS[char])
            maximum_depth = max(maximum_depth, len(stack))
        elif stack and char == stack[-1]:
            stack.pop()
        elif stack:
            parenthetic_chars += 1
    if length >= 70 and (
        maximum_depth >= 3 or parenthetic_chars / length >= 0.40
    ):
        return "wikipedia-parenthetical-density", []
    if length >= 100 and sum(text.count(char) for char in "、，,；;") >= 7:
        return "wikipedia-enumeration-heavy", []
    # Several long written compounds in one example impose a reading burden
    # even outside a known specialist lexicon. One organization/place name is
    # insufficient, and short ordinary nonfiction stays eligible.
    if length >= 55 and len(_LONG_COMPOUNDS.findall(text)) >= 4:
        return "wikipedia-compound-density", []
    distinct_terms = len(set(_SPECIALIST_PATTERN.findall(text)))
    kanji_ratio = len(_KANJI.findall(text)) / max(length, 1)
    if distinct_terms >= 3 and (length >= 45 or kanji_ratio >= 0.50):
        return "wikipedia-specialist-density", []
    tags = ["style:specialist-vocabulary"] if distinct_terms >= 2 else []
    return None, tags
