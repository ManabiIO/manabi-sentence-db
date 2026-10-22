from manabi_sentence_db.text import assess_sentence, is_complete_sentence, split_sentences


def test_japanese_punctuation_closers_and_reporting_clause():
    assert split_sentences("今日は晴れだ。明日は雨です！「本当？」と聞いた。") == [
        "今日は晴れだ。", "明日は雨です！", "「本当？」と聞いた。",
    ]
    assert split_sentences("「明日は晴れです。」次の話を始めた。") == [
        "「明日は晴れです。」", "次の話を始めた。",
    ]


def test_paragraph_fragments_are_never_joined():
    assert split_sentences("ひとつの断片\n\n別の文章です。") == ["ひとつの断片", "別の文章です。"]
    assert not is_complete_sentence("ひとつの断片")
    assert is_complete_sentence("「別の文章です。」")


def test_nested_quotation_does_not_end_the_enclosing_sentence():
    assert split_sentences("彼は「明日は晴れ。今日は雨。」と言った。帰宅した。") == [
        "彼は「明日は晴れ。今日は雨。」と言った。", "帰宅した。",
    ]
    assert split_sentences("説明（詳しくは後述。ここでは省略。）を読んだ。") == [
        "説明（詳しくは後述。ここでは省略。）を読んだ。",
    ]
    assert assess_sentence("「閉じていない文章です。")[2] == "unbalanced-delimiters"


def test_generic_decimal_handling():
    assert split_sentences("The value is 3.14. It is approximate!", "en") == [
        "The value is 3.14.", "It is approximate!",
    ]
    assert assess_sentence("It’s a nice day.", "en")[0]


def test_quality_rejects_unknown_templates_and_archaic_language():
    assert assess_sentence("今日は\ufffcに行きます。")[2] == "unresolved-markup"
    assert assess_sentence("これを思ひ出した。")[2] == "archaic-language"
    assert assess_sentence("昨日のことを思い出した。")[0]
    assert assess_sentence("This is only English.")[2] == "non-japanese"


def test_flags_are_annotations_instead_of_blanket_rejection():
    accepted, flags, reason = assess_sentence("新聞には殺人事件についての記事が載っていた。")
    assert accepted and flags == ["violence"] and reason is None
    assert assess_sentence("自殺予防について話し合った。")[1] == ["self-harm"]
    assert assess_sentence("性行為に関する説明が書かれていた。")[1] == ["sexual-content"]


def test_sentence_sources_can_have_unpunctuated_utterances():
    assert assess_sentence("どうもありがとう")[0]
    assert assess_sentence("あ。")[2] == "too-short"
    assert assess_sentence("あ" * 501)[2] == "too-long"
    assert assess_sentence("正常\x00ではない。")[2] == "control-character"
