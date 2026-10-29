"""Cheap, source-specific admission rules for Japanese Wikipedia examples.

These inspect sentence form, not article topic or author expertise. Ordinary
science/history prose remains eligible. Thresholds are deliberately explicit;
this is neither a readability model nor a calibrated JLPT assessment.
"""

import re
import unicodedata

WIKIPEDIA_QUALITY_VERSION = "wikipedia-example-quality-v3"

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
_ORPHAN = re.compile(r"^(?:は(?!虫類|虫|行)|を)(?=[一-鿿A-Za-z0-9])")
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
)
_SPECIALIST_PATTERN = re.compile("|".join(sorted(_SPECIALIST, key=len, reverse=True)))


def assess_wikipedia_sentence(text: str) -> tuple[str | None, list[str]]:
    """Return a rejection reason and retained heuristic style tags.

    Work on unchanged text; never simplify formulas or rewrite source sentences.
    Called only after the shared malformed-text/rights extraction gates.
    """
    length = len(text)
    if length > 180:
        return "wikipedia-long-sentence", []
    if _FOLLOWING_MATERIAL.search(text) or _ORPHAN.search(text):
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
