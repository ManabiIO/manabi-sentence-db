# Corpus sources and admission decisions

Reviewed against primary publisher documentation on **2026-10-22 (UTC)**. Counts and
download sizes below describe upstream material at review time, before sentence
extraction and filtering. They are not claims about the size of a Manabi release.
Builds retain duplicate occurrences and their provenance, with content hashes for
downstream deduplication. The implemented adapter list belongs in the project
README; this document also records researched candidates for later work. An
admission decision records the publisher's stated terms and a bounded extraction
policy; it does not guarantee rights in every contribution or third-party quote.

## Admission policy

The redistributable corpus requires an explicit grant permitting **commercial
redistribution and the transformations used by this project**. A free download,
public API, research paper, open-source scraper, or permissively licensed model
does not establish a license to republish the underlying text. We exclude NC
material. We also defer ND material from the transformation and translation
pipeline, although ND alone does not prohibit commercial distribution of an
unchanged work.

Keep source licenses with source records and release artifacts. The software
license does not relicense imported sentences. In particular, CC BY-SA text keeps
its attribution, modification notice, and applicable share-alike obligations.
Translations can have additional copyright and their own provenance. A collection
containing several sources must not erase those differences with a single
permissive label.

For each admitted source, record its publisher, canonical URL, precise license
version and jurisdiction where relevant, policy/evidence URLs, attribution
instructions, exceptions, and review date. Each snapshot then records the actual
input URLs, upstream version, retrieval time, byte counts, and SHA-256 hashes.
Each derived build identifies those snapshots and the extraction/filter versions.

## Enabled source catalog

The implementation provides Wikimedia, Tatoeba, and RealPersonaChat adapters for
the five sources below. The high-priority additions farther down are researched
options, not currently enabled ingestion jobs.

| Source | Intended use | Rights and acquisition |
| --- | --- | --- |
| Japanese Wikipedia | Large contemporary expository corpus | CC BY-SA 4.0 for covered text; current-revision Wikimedia exports; preserve page/revision/history links and exceptions. |
| Japanese Wikivoyage | Travel and practical prose; small enough for a complete development build | CC BY-SA 4.0 for covered text; same export machinery. |
| Japanese Wikinews | Archived journalistic prose | Current Japanese footer offers CC BY 4.0 for post-2005-09-25 text; historical versions and pre-cutoff text require the separate treatment below. The project is closed. |
| Tatoeba Japanese | Sentence-first material with optional direct translation links | CC BY 2.0 **France** by default; some CC0 sentences. Weekly detailed TSV exports preserve sentence IDs and current-owner usernames. Audio is a separate rights decision. |
| [RealPersonaChat](https://github.com/nu-dialogue/real-persona-chat) | Contemporary conversation; upstream release has 13,583 human dialogues and 408,619 utterances before filtering | CC BY-SA 4.0; commit-pinned JSON, dialogue text only. Profiles, model conversations, and masked utterances are excluded. |

### Wikipedia and Wikivoyage

The [Wikimedia Terms of Use](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use)
allow commercial reuse of appropriately licensed text. They explain attribution
through a page URL/history or equivalent author credit, preservation of extra
notices for imported text, and marking modifications. Follow the project-specific
exceptions; third-party material used under a legal exception is not automatically
covered by the page's general license. The
[Japanese Wikipedia copyright policy](https://ja.wikipedia.org/wiki/Wikipedia:著作権)
adds local guidance.

Start with main-namespace prose and skip redirects, templates, tables, code, image
captions, citation/reference bodies, and marked quotations. Keep document title,
page ID, revision ID and timestamp, permanent revision URL, contributor-history
URL, and useful categories. Do not call the last editor the sole author. Article
categories are descriptive source metadata, not verified content-safety labels.

The default Wikimedia adapter uses
[MediaWiki Content File Exports](https://wikitech.wikimedia.org/wiki/MediaWiki_Content_File_Exports),
which publish compressed XML chunks under:

```text
https://dumps.wikimedia.org/other/mediawiki_content_current/{wiki_id}/{YYYY-MM-DD}/xml/bzip2/
```

The `SHA256SUMS` file indicates a complete export. The
[legacy dump sunset notice](https://wikitech.wikimedia.org/wiki/Legacy_content_dumps_sunset)
announces staged unavailability from 2026-10-26 and discontinuation in January
2027 for six specified legacy jobs: current-page, complete-history, and history
stub XML variants. **The notice explicitly excludes `pages-articles.xml.bz2`
from those changes.** The separate legacy articles adapter therefore remains a
supported acquisition route, including the archival Japanese Wikinews import.
Store the selected manifest and verified blobs independently of upstream
retention. A single-page API snapshot is a useful development input, explicitly
marked as a sample; it is not evidence that a complete dump was processed.

### Wikinews is an archive with historical licensing

The [Japanese main page](https://ja.wikinews.org/wiki/メインページ) reports that all
Wikinews editions closed on 2026-05-04. Do not present this source as an ongoing
news feed or schedule recurring refreshes by default. At review time, the new
Japanese Wikinews export directory existed without completed checksums, while a
legacy October 2026 dump was available. An explicit archival/legacy import is
appropriate; silent fallback between unrelated snapshot systems is not.

Do **not** copy English Wikinews licensing dates into the Japanese configuration.
The [Japanese about page](https://ja.wikinews.org/wiki/ウィキニュース:ウィキニュースについて)
describes CC BY 2.5 or later and notes that material posted before
**2005-09-24 22:15 UTC** used **CC BY 2.1 Japan**. Its current footer offers
post-2005-09-25 text under CC BY 4.0. The
[global license-upgrade discussion](https://meta.wikimedia.org/wiki/Requests_for_comment/Update_standard_license_for_Wikinews)
and [deployment task T384614](https://phabricator.wikimedia.org/T384614) document the
2025 change to the default license. English Wikinews has its own different
transition dates and an early public-domain period; that is not a Japanese rule.

A latest-revision timestamp is not a page-creation timestamp and cannot identify
the license of every earlier contribution. This implementation uses the project
identifier `LicenseRef-Wikinews-JA` with a required notice preserving the BY 4.0,
BY 2.5, and BY 2.1 Japan license links and attribution requirements. Validation
requires that notice to remain attached. This identifier describes the historical
license bundle; it is not a new license or a claim that every contribution was
originally offered under all three licenses. Current page/revision and history
links remain necessary. Imported third-party exceptions still require exclusion;
retaining the bundle does not override them.

### Tatoeba

Use the publisher's [corpus reuse guide](https://en.wiki.tatoeba.org/articles/show/using-the-tatoeba-corpus),
[FAQ](https://en.wiki.tatoeba.org/articles/show/faq), and
[Japanese export index](https://downloads.tatoeba.org/exports/per_language/jpn/).
The default sentence license is
[CC BY 2.0 France](https://creativecommons.org/licenses/by/2.0/fr/), not the
unported 2.0 license. Preserve each sentence's contributor and canonical sentence
URL, and credit Tatoeba. CC0-only exports exist but the Japanese subset was tiny
at review time; it is not a substitute for the main Japanese corpus.

The adapter keeps the exported username as **current owner**, without asserting
sole authorship. For unowned/deleted-owner entries, it credits Tatoeba contributors
and links the sentence history rather than inventing an author. Unknown
translation-generation methods remain absent.

Useful input files include:

```text
https://downloads.tatoeba.org/exports/per_language/jpn/jpn_sentences_detailed.tsv.bz2
https://downloads.tatoeba.org/exports/per_language/jpn/jpn_tags.tsv.bz2
```

The detailed file is about 4.5 MB compressed in the reviewed weekly export and
contains ID, language, text, contributor, and creation/modification timestamps.
Language-pair link exports are available in the same directory. These URLs are
mutable: lock downloaded bytes and related export dates/checksums rather than
treating the URL as a version. Reuse stored inputs until a maintainer explicitly
requests a new snapshot.

Import **direct** translation links only. The FAQ explains that transitive/grey
links can drift in meaning. A link does not establish which sentence was original,
and a username does not prove human authorship or native-speaker status. Leave
translation method unknown when it is not supplied. Preserve the translation's
own ID, URL, author, and license. Machine alignment and machine translation are
different facts.

Upstream tags and ratings help identify correction requests, unnatural wording,
archaic language, and sensitive content. They are incomplete annotations, not a
guarantee of suitability. Audio has separate contributor-selected licenses,
including NC cases; do not inherit the text license for audio.

The implemented builder conservatively rejects `@change` and its space-separated
variants, `archaic`, `old-fashioned`, `unnatural`, and `possibly unnatural` for
this source. It interprets `vulgar` as a profanity flag and `sexual` as a sexual
content flag; the default content policy excludes sexual-content entries. Raw
tags remain attached to admitted records, and rejection reasons are counted.
The adapter itself preserves publisher sentence units, including unpunctuated
ones, and does not silently rewrite their content. The reuse guide explicitly
identifies `@change`, `archaic`, and `vulgar`; the other exact labels were also
observed in the pinned Japanese export used for implementation verification.

## High-priority additions

These sources have useful primary licensing evidence but need their own reviewed
adapters and fixtures before being enabled. Prioritize varied contemporary
conversation and well-attributed parallel data over another copy of Wikipedia.

| Candidate | Upstream scale and character | License / implementation decision |
| --- | --- | --- |
| [NICT Kyoto Wikipedia corpus](https://alaginrc.nict.go.jp/WikiCorpus/index_E.html) | Approximately 500,000 Japanese–English pairs in 14,111 article XML files | CC BY-SA 3.0; human translations with stages and required NICT attribution. Prefer original XML over flattened KFTT copies. |
| [NICT ALT Parallel Corpus](https://www2.nict.go.jp/astrec-att/member/mutiyama/ALT/) | 20,106 aligned sentences from 1,893 English Wikinews articles, 13 languages including Japanese | CC BY 4.0 parallel ZIP only. Same page's treebank/annotation downloads are NC and excluded. |
| [JMultiWOZ](https://github.com/nu-dialogue/jmultiwoz) | 4,246 human role-play travel dialogues spanning six domains | CC BY-SA 4.0; versioned ZIP and JSON; retain dialogue/turn IDs. |
| [Accommodation Search Dialog Corpus](https://github.com/megagonlabs/asdc) | 210 main dialogues; additional crowdwritten vanilla and supplemental material | Corpus/annotations/docs CC BY 4.0; code Apache 2.0. Admit only selected text fields and record the subset. |
| [Global Voices Japanese](https://jp.globalvoices.org/) | Ongoing translated reporting across many countries and topics | CC BY 3.0 for covered editorial content; per-post author/translator and exceptions. Needs a bounded, polite snapshot crawler or verified export. |
| [JEC basic sentences](https://alaginrc.nict.go.jp/jecbs/index.htm) | 5,304 revised basic Japanese sentences with English and Chinese translations | CC BY 3.0; filter placeholder templates; record Kyoto/NICT credits and exact spreadsheet version. |
| [MDN Japanese documentation](https://github.com/mdn/translated-content) | Substantial technical prose with source files in Git | CC BY-SA 2.5 or later for documentation; pin commit, skip code, retain document/contributor credit. |
| [Japanese Wikibooks](https://ja.wikibooks.org/wiki/Wikibooks:著作権) / [Wikiversity](https://ja.wikiversity.org/wiki/Wikiversity:著作権) | Educational prose; natural reuse of the Wikimedia adapter | General Wikimedia CC BY-SA 4.0 framework, subject to local/imported exceptions. Tag register and exclude classical-language exercises/quotations. |

### Conversational corpora

The enabled [RealPersonaChat configuration](../sources/realpersonachat-ja.yaml)
pins the archive revision. The adapter reads one JSON file per dialogue at
`real_persona_chat/dialogues/*.json`; `utterances` contains local IDs and text.
The publisher's release masks personal information and omits problematic
dialogues; this pipeline omits the remaining masked utterances. The separate
interlocutor profiles, personality measurements, and
demographic tables are unnecessary for a sentence database. Do not accidentally
include `llm_dialogue_system/`, which contains generated experimental dialogue.
Respect the publisher's requests against re-identification and impersonation.

JMultiWOZ's [dataset documentation](https://github.com/nu-dialogue/jmultiwoz/blob/master/dataset/README.md)
describes its dialogue structure. The dataset consists of human role-play; model
inference outputs in the repository are separate material. ASDC's README
distinguishes main, supplemental, correctness-labeled, and vanilla subsets. Some
fields are standalone reformulations or intentionally incorrect annotations.
Do not flatten every string into a natural sentence or count every field as a
distinct example.

The [Multi-Relational Multi-Party Chat Corpus](https://github.com/nu-dialogue/multi-relational-multi-party-chat-corpus)
is a further CC BY-SA 4.0 option: its current public tables total 960 dialogues
and 100,680 utterances. It follows a similar JSON layout and contains additional
participant metadata that should remain outside sentence outputs.

The [Japanese Movie Recommendation Dialogue dataset](https://github.com/ku-nlp/JMRD)
offers roughly 5,000 human dialogues under CC BY-SA 4.0, but includes external
movie reviews, synopses, and other knowledge fields. Review the provenance and
credit of those fields before admitting them; a dialogue-only extraction is the
starting point, not wholesale flattening of the repository.

### Parallel corpora

The NICT Kyoto corpus records original Japanese, primary translation, revised
translation, and final checked translation. Prefer the final
`<e type="check" ver="1">` variant and record human provenance. Preserve article
metadata and the required NICT/Wikipedia attribution specified on its
[license section](https://alaginrc.nict.go.jp/WikiCorpus/index_E.html).
Version 2.01 is a roughly 74 MB archive. Historical subject matter does not itself
mean archaic language, but quoted historical passages need filtering. KFTT is a
derivative of this material, not an additional independent corpus to count twice.

For ALT, use `ALT-Parallel-Corpus-20191206.zip` and preserve the supplied
[article URL map](https://www2.nict.go.jp/astrec-att/member/mutiyama/ALT/ALT-Parallel-Corpus-20191206/URL.txt)
and [README](https://www2.nict.go.jp/astrec-att/member/mutiyama/ALT/ALT-Parallel-Corpus-20191206/README.txt).
Credit NICT translations and the underlying English Wikinews articles. The
separate `Japanese-ALT-20210218.zip` and English/Khmer/Myanmar annotations on the
same site are **CC BY-NC-SA 4.0**; they are not covered by the parallel corpus's
BY license.

JEC contains placeholders such as `X` and `～`, and is partly a pattern resource.
Filter incomplete templates and retain its explicit Kyoto University authorship
for Japanese and NICT authorship for translations. The NICT page provides v1.2;
the [Kyoto publisher page](https://nlp.ist.i.kyoto-u.ac.jp/?日英中基本文データ)
announces a later English-correction release. Pin and document the chosen version.

[TALPCo](https://github.com/matbahasa/TALPCo) is a smaller CC BY 4.0 Japanese-first
teaching corpus with several Asian-language translations. Its TSV sentence IDs
are convenient for provenance and alignment. It is useful after the larger
sources, especially for language coverage. Associated audio links require their
own review; third-party audio adaptations can have different conditions.

### Web prose and public-sector text

Global Voices' [attribution policy](https://globalvoices.org/about/global-voices-attribution-policy/)
links to CC BY 3.0 and requires author credit, the original URL, and a change
notice. Japanese articles can name both an original author and a translator.
Preserve both. Skip third-party media, quotations, and republished material with
different terms. No stable public bulk endpoint was verified in this review, so
this is a future snapshot adapter, not permission for an unbounded crawl.

MDN's [content licensing policy](https://developer.mozilla.org/en-US/docs/MDN/Writing_guidelines/Attrib_copyright_license)
covers documentation under CC BY-SA 2.5 or later, with title/link, Mozilla
Contributors credit, and modification notices. Code samples have separate
licenses. The Japanese `files/ja/` content in `mdn/translated-content` allows a
commit-pinned snapshot without scraping thousands of pages. Mark it as technical
register and extract prose only.

Selected government writing is another substantial option. For example, the
[Digital Agency policy](https://www.digital.go.jp/copyright-policy) applies
[Public Data License 1.0](https://www.digital.go.jp/resources/open_data/public_data_license_v1.0),
which expressly allows use under CC BY 4.0. Build a **site and path allowlist**
with attribution and third-party exceptions. A `.go.jp` domain does not by itself
license everything on it. Prefer structured text/HTML over PDF extraction where
available, and keep administrative/technical register labels.

## Deferred or excluded sources

| Source | Decision and primary evidence |
| --- | --- |
| [JParaCrawl](https://www.kecl.ntt.co.jp/icl/lirg/jparacrawl/) | Exclude the standard download: publisher terms prohibit commercial use and direct commercial users to a separate license. Its large size does not make it open for this project. |
| [Business Scene Dialogue](https://github.com/tsuruoka-lab/BSD) | Exclude: CC BY-NC-SA. Do not confuse its useful conversational format with eligible rights. |
| [TED](https://www.ted.com/about/our-organization/our-policies-terms/ted-talks-usage-policy) and derived TED/IWSLT text | Exclude from the open corpus: the standard TED grant is NC-ND. A research derivative does not remove those conditions. |
| [BCCWJ](https://clrd.ninjal.ac.jp/bccwj/dvd-index.html) | Exclude: access requires the institute's agreement and redistribution is prohibited. Public search access is not a corpus license. |
| [National Diet proceedings API](https://kokkai.ndl.go.jp/api.html) | Exclude as a blanket source: API terms explain that individual speakers retain copyright in their speeches. Public availability is not an unrestricted redistribution grant. |
| [livedoor news corpus](https://www.rondhuit.com/download.html) | Defer from this transformation pipeline: publisher describes Attribution–NoDerivatives article licenses and per-category notices. ND differs from NC, but does not support arbitrary published adaptations. |
| [Common Crawl](https://commoncrawl.org/terms-of-use), OSCAR, mC4, generic web crawls | Exclude as blanket sources: underlying sites retain their own rights. Admit only independently verified eligible origins with preserved provenance. |
| [Massif](https://massif.la/about) / its Narou novel corpus | Search-product comparison only. Massif's open-source software does not grant reuse rights to the underlying novels. Future external citations are a separate feature. |
| [JESC](https://nlp.stanford.edu/projects/jesc/index.html) / OpenSubtitles | Defer: the JESC page's actual license link is BY-SA 4.0, but the subtitle sources' redistribution provenance needs review. Do not rely on mirrors claiming BY 4.0. |
| [Common Voice Japanese 27.0](https://mozilladatacollective.com/datasets/cmu5xbhnf00fmnq07z9p3aa70) | Defer the current distribution route: the official page labels CC0 but also expressly forbids re-hosting/re-sharing the dataset. Resolve that condition or identify an independently reusable text source before ingestion. No transcription is required, but license metadata alone is insufficient. |
| [JSUT](https://sites.google.com/site/shinnosuketakamichi/publication/jsut) | Defer bulk import: text has mixed source licenses described in the archive; audio has separate use/redistribution restrictions. A future text-only subset needs file-level license review. |
| [Aozora Bunko](https://www.aozora.gr.jp/guide/kijyunn.html) | Defer for the first contemporary-language corpus. Rights vary by work; public-domain works can be reused, while some in-copyright works have limited permission. Modern kana/kanji formatting alone does not establish contemporary vocabulary/style. |
| Wikisource, Wikiquote, Wiktionary quotations | Defer generic extraction. A Wikimedia footer does not automatically license every quoted or transcribed third-party work, and much material is historical or not complete natural sentences. |
| [SNOW T15/T23](https://www.jnlp.org/GengoHouse/snow/t15) | Promising easy-Japanese simplification pairs; defer until the current primary license and original-text attribution can be captured. The primary site was unavailable during review. Do not substitute a mirror's CC tag for this verification or confuse them with differently restricted SNOW resources. |
| [FLORES+](https://huggingface.co/datasets/openlanguagedata/flores_plus) | Eligible CC BY-SA 4.0 but lower priority: 2,009 public sentences per language, designed as an evaluation benchmark. Keep benchmark provenance/split labels; do not silently fold it into an unlabeled training corpus. |
| [OPUS](https://opus.nlpl.eu/) as a whole | Not one licensable source. Review each component and its original sources. Human text mined into an automatic alignment must not be relabeled as machine-translated text. |

## Quality and content filtering

Licensing, linguistic quality, and content suitability are separate properties.
An encyclopedia sentence about sexual health differs from explicit sexual
material; a news report quoting hateful language differs from advocacy. Useful
metadata includes source register, upstream tags, extraction quality, and a
versioned screening result. Never represent an absent tag as a human judgment
that a sentence is safe for all audiences.

The initial conservative policy should reject broken extraction, placeholders,
obvious non-Japanese fragments, marked archaic passages, and detected explicit
adult material from the default learner-facing collection. Preserve rejection
counts and rule identifiers so policy changes can be evaluated without fetching
upstream again. Broader violence, hate/discrimination, medical, and similar
labels should identify their method and confidence; simple keyword rules have
both false positives and false negatives. Do not rewrite questionable sentences
silently to make them pass a filter.

For contemporary Japanese, source selection does more reliable work than a
claimed perfect archaic-language detector. Modern prose can discuss old events;
old orthography can be normalized without becoming modern prose. Preserve original
text where admitted, document normalization, and make uncertainty explicit.

## Adding a source

An adapter proposal should supply:

1. Publisher-owned rights evidence covering commercial redistribution and intended
   processing, including the exact files/subsets and all relevant exceptions.
2. A bounded acquisition method with a stable version or captured content hashes,
   an identified client, conservative request behavior, and a development sample.
3. A mapping from source IDs, titles, authors, revisions, links, licenses, and
   translation metadata to corpus records without invented provenance.
4. Source-specific extraction/filter rules and a small synthetic or properly
   attributed fixture that exercises the difficult cases.
5. Output attribution and modification notices, plus counts that distinguish raw
   records, accepted sentences, translations, and duplicate occurrences.

Keep original occurrences distinct when attribution or license provenance differs.
Normalized-text hashes can support duplicate grouping without discarding source
credits. Export partitions should make it possible to consume a single source or
license family without downloading the entire corpus.
