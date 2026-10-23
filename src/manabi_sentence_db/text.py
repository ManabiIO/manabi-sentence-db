"""Conservative text segmentation and transparent, deliberately limited quality rules.

These rules select contemporary-looking Japanese; they are neither a language-era
classifier nor a safety classifier. A missing content flag never means safe.
Sentence-level sources may contain valid unpunctuated utterances, so completion is
checked separately by the Wikimedia prose adapter.
"""

from __future__ import annotations

import re
import unicodedata

TEXT_PROCESSOR_VERSION = "ja-conservative-v3"
OMITTED_MARKUP = "\ufffc"

_PAIRS = {
    "「": "」", "『": "』", "（": "）", "【": "】", "〈": "〉", "《": "》",
    "〔": "〕", "［": "］", "｛": "｝", "(": ")", "“": "”",
}
# A curly apostrophe can occur inside a word (it’s), so it is not balanced as
# an opening/closing delimiter, but is retained after terminal punctuation.
_CLOSERS = "".join(_PAIRS.values()) + "’\"'"
_JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
# Historical kana can occur in modern names, and short spellings such as てふ
# can cross modern word boundaries (見て + ふと). Neither is sufficient evidence
# to discard a sentence. Keep the more specific constructions, and require a
# hiragana ending before sentence-final 候 so nouns such as 気候, 兆候 and 居候
# are not mistaken for the historical auxiliary. This remains a heuristic, not
# a complete era detector; explicit source-era tags are handled by the builder.
_ARCHAIC = re.compile(
    r"(?:なりけり|ありけり|ざりけり|給ふ|給へ|思ひ|言ふ)"
    r"|(?<=[ぁ-ゖ])候(?=[。！？!?」』）]|$)"
)
_MARKUP = re.compile(r"\ufffc|\{\{|\}\}|\[\[|\]\]|<[^>]+>|https?://|ISBN\s*[0-9]")
_METADATA = re.compile(r"^(?:[*#;:|]|Category:|カテゴリ:|ファイル:|File:|出典[:：]|注釈[:：])", re.I)
_FLAGS = {
    "sexual-content": re.compile(r"性交|性行為|セックス|ポルノ|強姦|レイプ|性的虐待|児童ポルノ"),
    "violence": re.compile(r"殺人|殺害|虐殺|拷問|斬首|暴行|惨殺|銃殺"),
    "self-harm": re.compile(r"自殺|自傷|リストカット"),
    "profanity": re.compile(r"くそったれ|クソ野郎|死ね|くたばれ"),
}


def style_tags(text: str, language: str = "ja") -> list[str]:
    """Weak style evidence is searchable metadata, not proof of source era."""
    if language.split("-", 1)[0] == "ja" and "べからず" in text:
        return ["style:classical-construction"]
    return []


def _normalize(text: str) -> str:
    # NFC preserves compatibility characters and punctuation unlike NFKC.
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def split_sentences(text: str, language: str = "ja") -> list[str]:
    """Split punctuation-delimited sentences without crossing source line boundaries.

    Closing quotes stay attached. A quoted question followed by a Japanese
    reporting particle (``「本当？」と聞いた。``) remains one sentence. Decimal
    points are not terminators in the generic non-Japanese fallback. Only the
    Japanese rules are currently used by the shipped Wikimedia sources.
    """
    japanese = language.split("-", 1)[0] == "ja"
    endings = "。！？!?" if japanese else ".!?。！？"
    result: list[str] = []
    for raw_line in _normalize(text).split("\n"):
        line = re.sub(r"[\t \u3000]+", " ", raw_line).strip()
        if not line:
            continue
        start = 0
        i = 0
        stack: list[str] = []
        while i < len(line):
            if line[i] not in endings:
                if line[i] in _PAIRS:
                    stack.append(_PAIRS[line[i]])
                elif stack and line[i] == stack[-1]:
                    stack.pop()
                i += 1
                continue
            if (
                line[i] == "."
                and i > 0
                and i + 1 < len(line)
                and line[i - 1].isdigit()
                and line[i + 1].isdigit()
            ):
                i += 1
                continue
            end = i + 1
            while end < len(line) and line[end] in endings:
                end += 1
            before_closers = end
            while end < len(line) and line[end] in _CLOSERS:
                if stack and line[end] == stack[-1]:
                    stack.pop()
                end += 1
            if stack:
                # A full stop inside an unfinished quotation or parenthesis
                # cannot terminate the enclosing sentence.
                i = end
                continue
            # Reporting clauses attach to the preceding quoted utterance.
            if (
                japanese
                and end > before_closers
                and line[end:].lstrip().startswith(
                    ("と", "って", "など", "や", "を", "は", "が", "に", "の", "で", "も", "から", "まで")
                )
            ):
                i = end
                continue
            sentence = line[start:end].strip()
            if sentence:
                result.append(sentence)
            start = end
            i = end
        remainder = line[start:].strip()
        if remainder:
            result.append(remainder)
    return result


def is_complete_sentence(text: str, language: str = "ja") -> bool:
    """Require terminal punctuation for prose extracted from documents."""
    stripped = text.rstrip().rstrip(_CLOSERS).rstrip()
    endings = "。！？!?" if language.split("-", 1)[0] == "ja" else ".!?。！？"
    return bool(stripped) and stripped[-1] in endings


def assess_sentence(text: str, language: str = "ja") -> tuple[bool, list[str], str | None]:
    """Return (accepted, heuristic content flags, rejection reason).

    Flags are intentionally a small, inspectable lexicon. Clinical/news contexts
    can be flagged too, and unrecognized harmful text can pass. Do not advertise
    this output as child-safe or as human-reviewed.
    """
    flags = sorted(name for name, pattern in _FLAGS.items() if pattern.search(text))
    if len(text.strip()) < 4:
        return False, flags, "too-short"
    if len(text) > 500:
        return False, flags, "too-long"
    if any(unicodedata.category(char) == "Cc" for char in text):
        return False, flags, "control-character"
    if _MARKUP.search(text):
        return False, flags, "unresolved-markup"
    if _METADATA.search(text.strip()):
        return False, flags, "metadata"
    stack: list[str] = []
    for char in text:
        if char in _PAIRS:
            stack.append(_PAIRS[char])
        elif char in _PAIRS.values():
            if not stack or char != stack.pop():
                return False, flags, "unbalanced-delimiters"
    if stack:
        return False, flags, "unbalanced-delimiters"
    if language.split("-", 1)[0] == "ja":
        if not _JAPANESE.search(text):
            return False, flags, "non-japanese"
        if _ARCHAIC.search(text):
            return False, flags, "archaic-language"
    return True, flags, None
