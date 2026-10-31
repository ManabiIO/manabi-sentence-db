import pytest

from manabi_sentence_db.text import (
    assess_sentence,
    is_complete_sentence,
    sentence_spans,
    split_sentences,
)


def test_halfwidth_japanese_stops_preserve_offsets_and_quotation_protection():
    text = "電車で駅に着いた｡ 明日は家で休む｡"
    assert split_sentences(text) == ["電車で駅に着いた｡", "明日は家で休む｡"]
    assert [text[a:b] for a, b in sentence_spans(text)] == split_sentences(text)
    assert is_complete_sentence("明日は家で休む｡")
    assert split_sentences("彼は「今日は晴れ｡明日は雨｡」と言った｡帰宅した｡") == [
        "彼は「今日は晴れ｡明日は雨｡」と言った｡", "帰宅した｡",
    ]
    assert split_sentences("説明（これは例｡）を読んだ｡終わった｡") == [
        "説明（これは例｡）を読んだ｡", "終わった｡",
    ]
    assert assess_sentence("書状を受け取り候｡")[2] == "archaic-language"


def test_japanese_punctuation_closers_and_reporting_clause():
    assert split_sentences("今日は晴れだ。明日は雨です！「本当？」と聞いた。") == [
        "今日は晴れだ。", "明日は雨です！", "「本当？」と聞いた。",
    ]
    assert split_sentences("「明日は晴れです。」次の話を始めた。") == [
        "「明日は晴れです。」", "次の話を始めた。",
    ]


@pytest.mark.parametrize("space", ["", " ", "\t", "\u3000", "\u00a0", "\u2009"])
def test_reporting_clause_whitespace_preserves_exact_source_spans(space):
    first = f"𠮷田さんは「明日は晴れです。」{space}と言った。"
    second = "「雨ですか？」次の話を始めた。"
    text = (first + second) * 40
    expected = [part for _ in range(40) for part in (first, "「雨ですか？」", "次の話を始めた。")]
    assert [text[start:end] for start, end in sentence_spans(text)] == expected


def test_reporting_clause_does_not_skip_bom_or_line_boundaries():
    text = "「晴れです。」\ufeffと言った。\n「雨です。」\t\nと書いた。"
    assert [text[start:end] for start, end in sentence_spans(text)] == [
        "「晴れです。」", "\ufeffと言った。", "「雨です。」", "と書いた。",
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


@pytest.mark.parametrize("text", [
    "この地域は温暖な気候。",
    "回復の兆候。",
    "その家で暮らす居候。",
    "空を見てふと思い出した。",
    "走ってふらついてしまった。",
    "パンは焼けふくらんだ。",
    "ゐろはさんと公園を歩いた。",
    "店名はヱビスです。",
    "看板にはゑんやと書かれている。",
    "ヰノウエさんに手紙を書いた。",
    "最低時給への不満が高まっている。",
    "安定供給への備えが必要です。",
    "水分補給への配慮をお願いします。",
    "本人の意思ひとつで決められる。",
    "教訓を格言ふうに書いてみた。",
    "冗談を名言ふうに言ってみた。",
    "試合でボールをけり返した。",
    "箱をけり飛ばした。",
])
def test_modern_words_and_names_are_not_rejected_as_archaic(text):
    assert assess_sentence(text) == (True, [], None)


@pytest.mark.parametrize("text", [
    "昔のことを思ひ出した。",
    "その人はかく言ふ。",
    "山の上になりけり。",
    "書状を受け取り候。",
    "「承知いたし候。」",
    "これを読み給へ。",
    "花を与え給ふ。",
    "給へと願った。",
    "『給へ。』",
    "思ひ出の道を歩いた。",
    "言ふことなし。",
    "【思ひ出の道。】",
    "彼は“言ふことなし。”と書いた。",
])
def test_specific_historical_constructions_remain_excluded(text):
    assert assess_sentence(text)[2] == "archaic-language"


@pytest.mark.parametrize("text", ["物思ひに沈んだ。", "片思ひの歌を読んだ。"])
def test_ambiguous_compound_spellings_are_not_a_source_era_verdict(text):
    # A tokenizer-free substring rule cannot distinguish compound boundaries
    # reliably. Prefer a false negative here to rejecting 意思 + ひとつ.
    assert assess_sentence(text) == (True, [], None)


def test_flags_are_annotations_instead_of_blanket_rejection():
    accepted, flags, reason = assess_sentence("新聞には殺人事件についての記事が載っていた。")
    assert accepted and flags == ["violence"] and reason is None
    assert assess_sentence("自殺予防について話し合った。")[1] == ["self-harm"]
    assert assess_sentence("性行為に関する説明が書かれていた。")[1] == ["sexual-content"]


@pytest.mark.parametrize("text", [
    "学校の体育館で撃たれた。",
    "学校襲撃時の様子を伝えた。",
    "家庭内暴力について相談した。",
    "児童虐待の相談窓口を案内した。",
    "身体的虐待を受けた。",
    "彼は顔を殴られた。",
    "男が通行人を殴った。",
    "船は魚雷に撃たれた。",
    "船が機雷に撃たれた。",
    "クリッチフィールドは更に、子供達に、食べ物を食べ、飲み続けたうえで、自分達の吐物を食べるように強いた。",
    "嘔吐物を飲むよう強要された。",
])
def test_reviewed_assault_abuse_and_forced_ingestion_receive_violence_flag(text):
    assert assess_sentence(text) == (True, ["violence"], None)


@pytest.mark.parametrize("text", [
    "射撃競技で優勝した。",
    "射撃場で標的を撃った。",
    "落雷に撃たれる方が確率は高い。",
    "雷に撃たれた木が倒れた。",
    "稲妻に撃たれたことがある。",
    "メモを殴り書きしてから出かけた。",
    "電話番号を殴り書いた。",
    "患者の嘔吐物を検査した。",
    "吐物を取り除いて気道を確保した。",
    "吐瀉物を片付けるように指示された。",
    "吐物を食べることがある。",
    "嘔吐物を飲み込まないように注意した。",
    "吐物を食べることがある。彼は帰宅を強いた。",
    "圧力を強いたが、吐物を食べることはなかった。",
])
def test_sport_shooting_and_vomiting_without_ingestion_coercion_are_unflagged(text):
    assert assess_sentence(text) == (True, [], None)


def test_lightning_exception_does_not_hide_a_separate_shooting_mention():
    assert assess_sentence("雷に撃たれた兵士が、その後に銃で撃たれた。") == (True, ["violence"], None)


def test_whole_unit_flags_are_independent_of_sentence_admission():
    from manabi_sentence_db.text import content_flags

    text = "学校襲撃についての長い説明。" * 60
    assert content_flags(text) == ["violence"]
    accepted, flags, reason = assess_sentence(text)
    assert not accepted and reason == "too-long" and flags == content_flags(text)


@pytest.mark.parametrize("text", [
    "コックバンドを装着する。",
    "コックリングが販売されている。",
    "近隣にはソープランド街がある。",
    "性風俗店について調査した。",
    "デリヘルの広告が掲載された。",
])
def test_reviewed_explicit_sexual_terms_receive_existing_content_flag(text):
    accepted, flags, reason = assess_sentence(text)
    assert accepted and flags == ["sexual-content"] and reason is None


@pytest.mark.parametrize("text", [
    "農村の風俗について調べた。",
    "コックがバンドの演奏を聞いた。",
    "陰茎の構造について説明した。",
])
def test_cultural_customs_cooking_and_anatomy_alone_do_not_trigger_new_flags(text):
    assert assess_sentence(text) == (True, [], None)


def test_sentence_sources_can_have_unpunctuated_utterances():
    assert assess_sentence("どうもありがとう")[0]
    assert assess_sentence("あ。")[2] == "too-short"
    assert assess_sentence("あ" * 501)[2] == "too-long"
    assert assess_sentence("正常\x00ではない。")[2] == "control-character"


def test_classical_construction_in_modern_warning_is_style_evidence():
    from manabi_sentence_db.text import style_tags

    text = "芝生に入るべからず。"
    assert assess_sentence(text) == (True, [], None)
    assert style_tags(text) == ["style:classical-construction"]
    assert style_tags("普通の現代日本語です。") == []
    assert style_tags(text, "en") == []


@pytest.mark.parametrize("label", ["Zou!", "Yahoo!", "Zou！"])
def test_punctuated_latin_name_keeps_following_japanese_particle(label):
    text = f"地域バス{label}のチケットを買います。次は電車です。"
    assert split_sentences(text) == [f"地域バス{label}のチケットを買います。", "次は電車です。"]
    assert split_sentences("いいね!また会おう。") == ["いいね!", "また会おう。"]
    assert split_sentences("OK! 次は電車です。") == ["OK!", "次は電車です。"]
    assert split_sentences("OK!\nの続きではない。") == ["OK!", "の続きではない。"]
