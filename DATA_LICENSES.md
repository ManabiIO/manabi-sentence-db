# Data licenses and attribution

This repository builds a **collection of separately licensed sources**. It does
not grant one new permissive license over all imported text. The repository's
MIT license covers its software and original documentation. Original synthetic
fixture sentences are also available under CC0 1.0.

The initial source grants are:

| Source | Recorded license and evidence |
| --- | --- |
| Wikipedia / Wikivoyage / Wikibooks covered text | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); [Wikimedia Terms of Use](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use) |
| Tatoeba sentence text | [CC BY 2.0 France](https://creativecommons.org/licenses/by/2.0/fr/); [publisher reuse guide](https://en.wiki.tatoeba.org/articles/show/using-the-tatoeba-corpus) |
| Japanese Wikinews archive | `LicenseRef-Wikinews-JA`, preserving [BY 4.0](https://creativecommons.org/licenses/by/4.0/), [BY 2.5](https://creativecommons.org/licenses/by/2.5/), and [BY 2.1 Japan](https://creativecommons.org/licenses/by/2.1/jp/) notices; [Japanese historical policy](https://ja.wikinews.org/wiki/ウィキニュース:ウィキニュースについて) |

`LicenseRef-Wikinews-JA` is a project identifier for historical requirements,
not a new license. Its full required notice travels in every imported document,
source configuration, SQLite license table, and generated license inventory.
The latest page revision does not identify the creation date of every sentence
or contribution. This archive does not incorrectly assign the English edition's
early public-domain rule to Japanese text.

Redistributed records retain source and revision URLs, contributor/history
attribution, precise license URLs and notices, and transformation descriptions.
Translations carry their own source URL, attribution, and license. The current
Tatoeba export names a current owner; the data does not falsely identify that
person as the sole author or prove native-speaker/human-translation status.

Consumers should retain this information in downloads and make the relevant
credit, license links, and modification notice available alongside displayed
examples. When adapting ShareAlike content, follow its applicable ShareAlike
requirements. Merely placing an entry in a database does not erase those terms.
The [Wikimedia reuse terms](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use)
and each Creative Commons license explain the actual obligations.

Source-level licenses do not cover every possible third-party quotation, image,
or contribution included under an exception. This pipeline is text-only and
conservatively excludes marked quotations, media, and recognized rights-problem
templates. That is a bounded extraction policy, not a claim to resolve the
copyright history of every sentence. Rights corrections should identify the
source, document/sentence ID, snapshot, and affected release so maintainers can
exclude the record and publish a corrected dataset. Old downloaded copies are
not silently rewritten.

NC and unreviewed license identifiers fail admission. ND material is outside the
initial transformation/translation pipeline. Adding a new license requires a
source review, an explicit allowlist entry, and tests; a dataset card or an
open-source scraping script alone is insufficient evidence. See the
[source review](docs/sources.md) for decisions and deferred sources.

## RealPersonaChat

The pinned human dialogue corpus is CC BY-SA 4.0. Credit Sanae Yamashita,
Koji Inoue, Ao Guo, Shota Mochizuki, Tatsuya Kawahara, and Ryuichiro Higashinaka,
*RealPersonaChat* (2023), with the [publisher link](https://github.com/nu-dialogue/real-persona-chat)
and [license](https://creativecommons.org/licenses/by-sa/4.0/).
Each work retains its immutable dialogue URL and source text hash. Extraction,
normalization, and filtering are recorded as transformations. Participant profiles,
evaluations, masked personal information, and separately published model conversations
are excluded. Japanese text remains under its original content license; MIT covers
this repository's software only.



## JMultiWOZ and STAIR Captions

JMultiWOZ human turns are CC BY-SA 4.0. Credit Atsumoto Ohashi, Ryu Hirai,
Shinya Iizuka, and Ryuichiro Higashinaka, *JMultiWOZ* (2024), with the
[publisher URL](https://github.com/nu-dialogue/jmultiwoz) and
[license](https://creativecommons.org/licenses/by-sa/4.0/). Human wizard turns
are distinct from the excluded generated-model experiments.

STAIR caption text is CC BY 4.0. Credit Yuya Yoshikawa, Yutaro Shigeto,
and Akikazu Takeuchi, *STAIR Captions* (2017), version 1.2, with the
[publisher URL](https://github.com/STAIR-Lab-CIT/STAIR-captions) and
[license](https://creativecommons.org/licenses/by/4.0/). This grant is not an
image license. Images are neither downloaded nor redistributed by the adapter.

Each source manifest pins its reviewed release and license evidence. Sentence
segmentation and normalization are explicit transformations. When a publisher
unit is split, any translations retain their separate rights and attribution
inside `source_unit.translations`; they do not become sentence-aligned translations.

## JEC Basic Sentence Data

The Japanese, English, and Chinese components are each available under
[CC BY 3.0](https://creativecommons.org/licenses/by/3.0/). The Japanese component
is attributed to Kyoto University Kurohashi–Kawahara Laboratory; Kyoto University
describes it as case-frame-derived sentences that were human corrected, without
identifying individual sentence authors. The aligned English and Chinese
translations are attributed separately to NICT Master Project Multilingual
Translation Laboratory. The primary source does not identify their translation
method, so records do not label them human or machine translated. The source
row is the alignment unit; row order is not asserted to provide discourse
context. The adapter excludes unresolved `X` and quotation placeholders while
retaining numeric ranges such as `2～3`. It pins the v1.3 archive, workbook,
and README hashes. See the [source page](https://alaginrc.nict.go.jp/jecbs/index.htm)
and the [Kyoto University data description](https://nlp.ist.i.kyoto-u.ac.jp/index.php?%E6%97%A5%E8%8B%B1%E4%B8%AD%E5%9F%BA%E6%9C%AC%E6%96%87%E3%83%87%E3%83%BC%E3%82%BF).


## Curated SCP-JP narrative

The single reviewed work [『適性』](https://scp-jp.wikidot.com/aptitude),
by terukami (2023), is [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/).
Its title, author, source URL, revision 10 / timestamp, license link, and
modification notice accompany the extracted sentences. The adapter excludes all
site navigation, rating and credit modules, comments, scripts, and media. It
preserves paragraph context and records extraction and segmentation changes.
The [publisher licensing guide](https://scp-jp.wikidot.com/licensing-guide)
explains attribution and ShareAlike obligations. This admission applies only to
the pinned work; it does not admit other SCP-JP pages, translations, or images.
