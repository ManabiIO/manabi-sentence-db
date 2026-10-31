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

The implementation provides Wikimedia, Tatoeba, RealPersonaChat, JMultiWOZ,
STAIR, JEC Basic Sentence, Kyoto Wikipedia pairs, and curated SCP-JP adapters for the enabled sources
below. The high-priority additions farther down are researched options, not
currently enabled ingestion jobs.

| Source | Intended use | Rights and acquisition |
| --- | --- | --- |
| Japanese Wikipedia | Large contemporary expository corpus | CC BY-SA 4.0 for covered text; current-revision Wikimedia exports; preserve page/revision/history links and exceptions. |
| Japanese Wikivoyage | Travel and practical prose; small enough for a complete development build | CC BY-SA 4.0 for covered text; same export machinery. |
| Japanese Wikinews | Archived journalistic prose | Current Japanese footer offers CC BY 4.0 for post-2005-09-25 text; historical versions and pre-cutoff text require the separate treatment below. The project is closed. |
| Tatoeba Japanese | Sentence-first material with optional direct translation links | CC BY 2.0 **France** by default; some CC0 sentences. Weekly detailed TSV exports preserve sentence IDs and current-owner usernames. Audio is a separate rights decision. |
| [RealPersonaChat](https://github.com/nu-dialogue/real-persona-chat) | Contemporary conversation; upstream release has 13,583 human dialogues and 408,619 utterances before filtering | CC BY-SA 4.0; commit-pinned JSON, dialogue text only. Profiles, model conversations, and masked utterances are excluded. |

| [JMultiWOZ](https://github.com/nu-dialogue/jmultiwoz) | Human task-oriented role-play; 4,246 dialogues and 61,186 turns in the inspected archive | CC BY-SA 4.0; pinned human turns only; no goals, worker IDs, backend database or model output. |
| [STAIR Captions](https://github.com/STAIR-Lab-CIT/STAIR-captions) | Short descriptive Japanese; 616,435 public captions in the inspected v1.2 train/validation files | CC BY 4.0 for captions; no images or tokenized duplicates; visual-context dependence retained. |
| [JEC Basic Sentence Data](https://alaginrc.nict.go.jp/jecbs/index.htm) | 5,304 Japanese sentence patterns aligned row by row with English and Chinese translations | CC BY 3.0; hash-pinned Kyoto University v1.3 ZIP, workbook, and README; unresolved `X`/quotation placeholders excluded, numeric ranges retained; Kyoto University Japanese and NICT translation attribution are separate. Translation method and individual sentence authorship are not specified. |
| [NICT Kyoto Wikipedia corpus](https://alaginrc.nict.go.jp/WikiCorpus/index_E.html) | Japanese Wikipedia sentences aligned to English translations | CC BY-SA 3.0; hash-pinned v2.01 archive; import final checked translations only, preserve article/page/history links, and exclude source-flagged typo, incomplete, classical, quotation, and reference material. |
| [Japanese Wikibooks](https://ja.wikibooks.org/) | Textbook explanations and other nonfiction prose | CC BY-SA 4.0 for covered text; revision/history attribution and conservative third-party quotation exclusions. |

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
The adapter itself preserves publisher units, including unpunctuated ones;
processor 5 splits multi-sentence units with exact original-unit context and
preserves whole-unit translations separately. The reuse guide explicitly
identifies `@change`, `archaic`, and `vulgar`; the other exact labels were also
observed in the pinned Japanese export used for implementation verification.

## High-priority additions

ALT and ASDC have reviewed adapters; their admitted subsets and qualification
status are described below. The other candidates still need reviewed adapters
and fixtures. Prioritize human-translated Wikipedia pairs before expanding
unpaired encyclopedia prose; the implemented Kyoto adapter is described below.

| Candidate | Upstream scale and character | License / implementation decision |
| --- | --- | --- |
| [NICT ALT Parallel Corpus](https://www2.nict.go.jp/astrec-att/member/mutiyama/ALT/) (adapter enabled) | 20,106 aligned sentences from 1,893 English Wikinews articles, 13 languages including Japanese | CC BY 4.0 parallel ZIP only. Same page's treebank/annotation downloads are NC and excluded. Japanese is translated; translation method remains unknown. |
| [Accommodation Search Dialog Corpus](https://github.com/megagonlabs/asdc) (adapter enabled) | 210 main dialogues; additional crowdwritten vanilla and supplemental material | Corpus/annotations/docs CC BY 4.0; code Apache 2.0. Only main dialogue text is admitted, with booking summaries excluded; correction fields require separate review. |
| [Global Voices Japanese](https://jp.globalvoices.org/) | Translated reporting across many countries and topics | Only the opt-in, hash-pinned 65906 editorial subset is enabled below. Wider acquisition still needs per-work rights/attribution review; no blanket crawl. |
| [MDN Japanese documentation](https://github.com/mdn/translated-content) | Substantial technical prose with source files in Git | CC BY-SA 2.5 or later for documentation; pin commit, skip code, retain document/contributor credit. |
| [Japanese Wikiversity](https://ja.wikiversity.org/wiki/Wikiversity:著作権) | Educational prose; natural reuse of the Wikimedia adapter | General Wikimedia CC BY-SA 4.0 framework, subject to local/imported exceptions. Tag register and exclude classical-language exercises/quotations. Wikibooks is already enabled. |

### Global Voices acquisition evidence — 2026-10-31

The [Japanese site](https://jp.globalvoices.org/) states CC BY 3.0. Its
[republishing guidelines](https://globalvoices.org/about/global-voices-attribution-policy/)
permit commercial adaptation of covered editorial material, require original
article links and author credit, and retain exceptions. Media rights are separate.
The [AI policy](https://globalvoices.org/about/global-voices-policy-on-ai/) rejects
automatically generated writing and translations while allowing reference tools.
This is publisher workflow evidence, not proof of native-speaker review for every
sentence. Preserve individual author and translator credit and translation
direction; never label translated Japanese as Japanese original writing.

Bounded primary checks found a usable WordPress metadata endpoint,
`https://jp.globalvoices.org/wp-json/wp/v2/posts`, reporting 2,903 posts. That is
a discovery count, not an admitted article or sentence count. The
[robots policy](https://jp.globalvoices.org/robots.txt) specifies a ten-second
crawl delay; acquisition must use one worker, persistent snapshots, explicit
opt-in refreshes and at least that spacing, including retries. Do not request
disallowed paths or fetch embedded media.

A subsequent bounded pilot captured the four most recent Japanese article pages
listed below, one discovery response, and the publisher policy/robots responses.
Every request used one worker with at least ten seconds between attempts; no
media or linked original articles were fetched. These are acquisition and rights
findings, not admitted article or sentence counts.

| Japanese article | Publisher bylines | Original / Japanese publication dates | Admission finding |
| --- | --- | --- | --- |
| [65749: ロシアの朝鮮人の困難な歩みを振り返る](https://jp.globalvoices.org/2026/10/26/65749/) | Daria Dergacheva, writer (English); Mitsuo Sugano, translator (Japanese); Miyu Yamamoto, proofreader | 2024-06-24 / 2026-10-26 | Candidate editorial prose; the recent translation date does not make the reporting current. Caption blocks include fair-use and separately licensed media notices. |
| [65906: 太平洋で緊張が高まるなか、日本の若者が平和運動の新しいかたちを模索](https://jp.globalvoices.org/2026/10/23/65906/) | Jo Carter, writer (English) and translator (Japanese) | 2026-09-25 / 2026-10-23 | Candidate editorial prose; six direct quote blocks, a translation-tabs block and additional quotations inside ordinary paragraphs require exclusions. The same writer/translator name does not establish Japanese-original text. |
| [65764: 2026年8月27日、ネパール土石流災害翌日の記者の記録](https://jp.globalvoices.org/2026/10/15/65764/) | Nepali Times, writer (English); Miyu Yamamoto, translator (Japanese); introduction credits Suman Nepali | 2026-08-31 / 2026-10-15 | Exclude pending independent rights evidence: the introduction expressly describes edited republication under a content-sharing agreement with Nepali Times. This is not evidence of a downstream commercial/adaptation grant from that partner. |
| [65886: 沖縄の米軍基地が阻む、琉球先住民族の認知と権利の訴え](https://jp.globalvoices.org/2026/10/09/65886/) | Jo Carter, writer (English) and translator (Japanese) | 2026-08-10 / 2026-10-09 | Candidate editorial prose; includes external quoted text and its Japanese translation in separate blockquotes, plus inline quotations and captions. |

All four explicitly label Japanese as a translation and name English as the
writer's language. Preserve both article-level dates, the original article URL,
and every credited contributor/role. The API's single numeric `author` field is
insufficient: the rendered Japanese pages supply translator and proofreading
credits, and the partner introduction supplies an additional original writer.
Publisher AI policy and a proofreading byline do not certify native-speaker
review or the translation method for each sentence. Keep those claims unknown;
retain the observed translation direction separately.

The precise remaining admission work is a reviewed, hash-pinned inventory of
eligible editorial paragraphs for each selected work. A generic `entry p`
selector would include photo captions, partner text and quotations; discarding
only `blockquote` misses quotes within otherwise ordinary paragraphs. Withhold
entire affected paragraphs, promotional/translator notes and credit modules,
and reserve context gaps across every omitted block. Fail closed on changed
body text, bylines, dates, original links, exceptions or unfamiliar body markup.
The general footer license cannot override a per-work exception.

#### Single-work importer: 65906

The follow-up captured the
[English original](https://globalvoices.org/2026/09/25/young-japanese-find-new-outlets-for-peace-activism-amid-rising-tensions-in-the-pacific/)
in one bounded request, without media. Both versions carry article-level and
footer CC BY 3.0 links. The original credits Jo Carter and contains no observed
partner-republication or alternate text-license notice. Its photo captions say
“used with permission”; those captions and all media remain excluded. The
original also reproduces Japanese source quotations with English translations;
those quotations do not make the Japanese narrative original writing or create
article-level sentence alignment.

The opt-in [source configuration](../sources/globalvoices-65906-ja.yaml) covers
only this work. The
[reviewed inventory](../src/manabi_sentence_db/globalvoices_65906.json) commits
metadata and hashes, never article bodies. It retains direct body-block ordinals
**2, 3, 4, 7, 9, 11, 16, 21, 25, 35, 38** (zero-based), totaling **11 narrative
paragraphs / 1,232 characters** before sentence filtering. Every one of the other
30 blocks has a pinned text/markup hash, an exclusion reason and a context break:
six quote blocks, translated-quote tabs, captions, headings, promotional text,
inline quotations and dependent introductions to omitted quotations. Retained
paragraph 11 contains reporter narration and indirect paraphrase; it excludes
the following direct speaker quotation.

The Japanese publication/modified timestamp is `2026-10-23T06:25:15+0000`;
the English original was published `2026-09-25T06:52:28+0000` and modified
`2026-10-01T11:55:56+0000`. Exact publisher timestamps, date labels, both URLs
and Jo Carter's separate writer (English) / translator (Japanese) credits remain
in the inventory and record attribution/tags. Japanese `published_at` refers to
translation publication. Authorship and language origin remain `unknown`; tags
record observed translation direction and unknown translation method. No
English text, translations, human certification or native-review flag is emitted.

Acquisition requires explicit single-source selection and a canonical persistent
article cache outside snapshots/builds. `--source all` skips the work in every
mode. Cached response hashes/sizes are checked without HTTP; misses use one
cache lock, primary robots checks, a 1.5 MB response bound, a 30-second timeout,
at most three attempts and at least ten seconds between all attempts across
hosts and retries. Redirects are rejected and linked assets are never fetched.
Both raw pages, metadata, body blocks, all omissions and license markup are
revalidated at acquisition/reuse and build. Even changed wrapper text requires
explicit re-review; a footer license cannot override a newly inserted exception.

Each retained paragraph is a separate publisher unit. Character ranges refer to
decoded text of **all** direct body blocks joined with two newlines; omitted
text is never emitted, and each omitted block reserves a context ordinal.
`source_text_hash` hashes this same complete decoded block stream, including
omitted material only in the digest. No native-review metadata is emitted.
Sentence splitting retains exact paragraph fragments and never joins prose
across those gaps. Attribution preserves title, both contributor roles, article
links, license and a selection/markup-removal/segmentation modification notice.
Synthetic regressions cover partner/quote/media insertion, missing credits,
date/direction/license/body/markup drift, omissions, cache-only reuse and retry
spacing. A tiny offline build from the captured pages retained **25 occurrences /
25 within-source distinct Japanese sentences**, with **30 context breaks** and
**zero translations**; normalized SQLite integrity, foreign keys and provenance
round-trip checks passed. These are source-only counts, not serving-corpus novelty.
`--refresh` is rejected for this immutable page pin.
These checks establish a bounded importer, not blanket site permission,
novelty against the serving corpus, native qualification or production activation.
The separate Nepali Times article 65764 remains excluded.

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

The enabled [Multi-Relational Multi-Party Chat Corpus configuration](../sources/mrmp-ja.yaml)
pins publisher revision `e6e39cb896df88781c7a2e0451226a527c5f1e2e`.
The publisher's [README and license](https://github.com/nu-dialogue/multi-relational-multi-party-chat-corpus/tree/e6e39cb896df88781c7a2e0451226a527c5f1e2e)
grant CC BY-SA 4.0 and report 960 dialogues / 100,680 utterances. The pinned Git
tree independently contains 477 first-time and 483 family-included dialogue
files totaling 20,447,851 bytes. These are upstream inventory counts, not an
admitted-sentence or novel-text count. The older Hugging Face loader declares
BY-ND for a different tag; the adapter never substitutes that tag or a mirror's
license metadata for this reviewed primary revision.

Before decoding any dialogue, the adapter checks the exact publisher README and
LICENSE SHA-256 values inside the ZIP. Only dialogue turns are exported; profiles,
personality/demographic attributes, relationship fields, participant identifiers
and evaluations are not corpus metadata. Retained authored text is never rewritten.
Turns containing ASCII or fullwidth at-sign address markers are withheld whole,
before segmentation and original-unit context creation. Pseudonyms such as
`@たまねぎ` otherwise make a food-word query match an address to another person.
The reviewed archive has 20,524 turns containing `@` and 12 containing `＠`,
including trailing and inline addresses. This is a conservative source-specific
quality gate; the raw snapshot is retained, and no handle is stripped to create
an invented sentence. Original file identity, Git revision,
raw member hash, turn IDs and immutable citations remain available. Masked and
addressed turns and missing source units reserve context gaps. Short utterances may depend on
surrounding dialogue; human collection is not a project quality review.

The full pinned snapshot and an assistant-only sample show ordinary contemporary
chat alongside short, context-dependent fragments. Human collection is not native
quality certification; occurrence review state remains unreviewed. Compressed
normalization, novelty against the serving corpus, and serving-size qualification
remain required before a corpus addition. No serving import is implied by
enabling its source manifest. Processor source fingerprints identify the changed
extraction; existing builds require a new output to apply it.

The enabled [Accommodation Search Dialog Corpus (ASDC) main
configuration](../sources/asdc-main-ja.yaml) contains Japanese customer/operator
role-play about finding accommodation. It pins Megagon Labs revision
`f37d6575c73602adcb8ae3687520726793baa672`. Its
[README](https://github.com/megagonlabs/asdc/blob/f37d6575c73602adcb8ae3687520726793baa672/README.md)
explicitly licenses corpus text, annotations and documentation under CC BY 4.0;
programs have a separate Apache license. The
[collection documentation](https://github.com/megagonlabs/asdc/blob/f37d6575c73602adcb8ae3687520726793baa672/docs/dialog/collection.md)
describes typed Slack role-play by 35 customers and two operators, all native
Japanese speakers. This supports human original-Japanese dialogue provenance,
without establishing sentence-level review or error-free learner examples.

Only `data/main/dialog/json/001.json` through `210.json` are decoded. Archive
root, exact inventory, member bounds and four publisher-evidence hashes are
checked before turn decoding. Utterance identities, original turn ranges, role
tags, source-member hashes and immutable citations survive; missing turn numbers
and filtered units reserve context gaps. Scenario requirements, timestamps,
pseudonym identifiers and all SCUD descriptions, original/supplemental/vanilla
material are excluded. Project sentence segmentation uses the original published
utterance text, without interpreting `text_sbs` against another string.

The adapter excludes whole operator booking-summary checklists before sentence
segmentation, reserving a context gap so their text cannot enter `source_unit`.
The pinned 4,270-turn snapshot has 210 such turns: 209 consist entirely of
middle-dot bullet lines; dialogue 033 has one exact publisher closing preamble
before its bullets. Each has 6–14 bullet lines and at least two explicit booking
slots (`日付は`, `人数は`, `行先は`, etc.). The narrow filter requires this
structure and operator role; it preserves ordinary middle-dot prose, customer
lists, short lists and unmatched preambles. No single-line checklist was found,
so these are not excluded. Text is never rewritten. The processor source
fingerprint identifies this changed extraction; existing builds require a new
output to apply it.

The publisher documents NFKC/tab transformations and typo edits. The optional
`text_fixed` field requires further schema qualification; the adapter fails
closed if it appears rather than silently selecting a corrected or uncorrected
version. A complete scan of all 210 pinned dialogues (4,270 turns) found no
`text_fixed` fields, so adding correction-field support is not a prerequisite
for this snapshot. A different snapshot containing those fields still requires
separate schema qualification.

After the 210 operator summaries are excluded, an in-memory run of the canonical
admission gates retains 8,622 occurrences and 5,039 within-source distinct texts.
These are source-only counts, not novelty against the serving corpus. An
assistant-only sample found practical travel requests and polite service language,
alongside short replies that require dialogue context. It establishes neither
native quality review nor serving approval.

The 2026-10-31 offline compressed-build and normalized-SQLite qualification
reproduced all 210 works, 8,622 occurrences and 5,039 distinct texts, with no
translations. All 210 summary context breaks survive canonical admission. SQLite
integrity and foreign-key checks pass. The normalized ZIP is 1,628,504 bytes and
SQLite is 13,508,608 bytes; these are source-only artifacts, not native serving
index growth. Build identity is `build_cb31a897449c8945e037cc14df97e670`; normalized
ZIP SHA-256 is `d84c72e1a0aa6d63d2c4e887df9604ee41dbbfc05b016e4d6b4ef4daf037fa0a`.
This reused the pinned local snapshot under the producer lock, with no downloads,
native jobs or serving activation.

A subsequent bounded native compilation against the frozen active v9 runtime
retained all 5,039 distinct texts in a 16,695,296-byte compact index. Against the
read-only current corpus of 1,848,842 texts, 4,916 are novel and 123 shared. This
is a small standalone index, not measured merged-corpus growth. Native index
validation, 5,933 citation checks and 48 internal missing-ordinal context checks
passed; all work rights, origin and transformation fields match the normalized
input. Vocabulary-estimated JLPT levels are N1 785, N2 1,298, N3 1,800, N4 820,
N5 295 and unknown 41. An assistant inspected 62 ranked results across eight
queries with two sentences of dialogue context per side. Practical travel/service
examples predominate, with some awkward role-play language and source numeric
shorthand. A broad `食べる` query also matches an analyzed `食べ` component in
`食べ歩き`. The full-word query policy is asymmetric: a query for `食べ歩く`
must retain the whole compound rather than admit bare eating, bare walking or
separated eating/walking clauses. Native regressions cover these cases; a broad
base-verb match alone does not establish a compound-query defect. No source text
was rewritten, current corpus changed or serving activation performed.
Merged growth and final combined-corpus review remain required. Occurrences remain
unreviewed. A configured adapter is not an activated corpus.

The [Japanese Movie Recommendation Dialogue dataset](https://github.com/ku-nlp/JMRD)
offers roughly 5,000 human dialogues under CC BY-SA 4.0, but includes external
movie reviews, synopses, and other knowledge fields. Review the provenance and
credit of those fields before admitting them; a dialogue-only extraction is the
starting point, not wholesale flattening of the repository.

### Parallel corpora

The enabled [Kyoto Wikipedia configuration](../sources/wikipedia-kyoto-ja.yaml)
pins NICT Kyoto corpus v2.01. It selects original Japanese and only the final
checked `<e type="check" ver="1">` English translation; primary and revised
translation stages are retained as upstream evidence but not imported as
parallel examples. Preserve article metadata and the required NICT/Wikipedia
attribution specified on its
[license section](https://alaginrc.nict.go.jp/WikiCorpus/index_E.html).
Version 2.01 is a hash-pinned 74,096,805-byte archive. Historical subject
matter does not itself mean archaic language, but quoted historical passages
need filtering. KFTT is a derivative of this material, not an additional
independent corpus to count twice. The adapter preserves article-level
Wikipedia page/history references and source copyright notices, and excludes
reference/quote sections and source-flagged incomplete, classical, or typo
examples. Sentence IDs retain upstream ordinal gaps after filtering.

The original release has 443,849 sentence units in 14,111 article XML files;
the publisher's approximate 500,000-pair figure also covers translated headings.
The README describes Japanese-native primary translators, English-native revision
against the Japanese, and Japanese-native technical checking. It prohibits use
of machine translation systems. These translations therefore have
`generation.kind: human`; they are not machine translations with human post-editing.
No generic machine-translation native-review field is added: this source does
not supply that kind of annotation. The publisher's process description is
evidence about translation workflow, not a human quality rating assigned by this
project. Source dump dates are not article publication dates, and headings never
become sentence examples.

The first complete default build processed all 14,111 articles and admitted
288,201 sentence-pair occurrences from 14,094 works: 282,624 distinct Japanese
texts and 288,201 final English translations. The normalized ZIP is 125,447,542
bytes. This is compressed interchange size, not serving SQLite/index size.
Excluded spans include incomplete prose, quotations/title quotes, source-noted
defects/classical material, references and shared/Wikipedia quality failures.
These are deterministic admission counts, not human usefulness ratings.

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

[TALPCo](https://github.com/matbahasa/TALPCo) is enabled as `talpco-ja`, a CC BY 4.0
Japanese-first teaching corpus. The pinned publisher commit
`eb4746249830e2c0a8b192a464a74616da3e0453` supplies 1,372 raw Japanese rows
(80,569 bytes) and 1,372 original British English rows (62,051 bytes), before
ordinary content-quality filtering. Exact sizes and SHA-256 values are in the
source configuration. Acquisition downloads only these two files; audio,
annotations, tokenized variants, other languages and the US adaptation are excluded.
Both complete files are verified before any document is yielded, and malformed,
empty, duplicate, missing or mismatched IDs fail closed. Rows join by explicit
publisher sentence ID, not by coincidentally matching line positions.

The [publisher paper, section 2](https://www.anlp.jp/proceedings/annual_meeting/2018/pdf_dir/C3-5.pdf)
establishes Japanese-to-English human translation: a Japanese undergraduate
prepared the English, subsequently checked by a native British English speaker.
This supports human translation metadata and a source-level workflow description;
it does not establish per-record native review or a project quality certification.
Japanese authorship remains unknown. Each row is a separate example-sentence work,
with publisher ID, pinned revision, independent CC BY 4.0 attribution and no
neighboring dialogue links. Deliberate Japanese bunsetsu spaces remain intact;
the usual NFC and edge-whitespace normalization is disclosed. Publisher pairs
remain whole, so splitting never falsely attaches a full English translation to
a Japanese fragment. No full-source qualification, measured marginal growth or
serving activation is implied by the adapter or upstream row count.

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
| [SNOW T15](https://www.jnlp.org/GengoHouse/snow/t15) / [T23](https://www.jnlp.org/GengoHouse/snow/t23) | Indexed publisher pages specify CC BY 4.0 and manual Japanese simplification. Defer acquisition until the corrected primary XLSX links and inherited Tanaka/Tatoeba attribution are verified; direct pages still failed on recheck. English is inherited, not established as wholly human-translated. The simplified Japanese is the main potential addition; measure overlap rather than counting all source rows as novel. |
| [FLORES+](https://huggingface.co/datasets/openlanguagedata/flores_plus) | Eligible CC BY-SA 4.0 but lower priority: 2,009 public sentences per language, designed as an evaluation benchmark. Keep benchmark provenance/split labels; do not silently fold it into an unlabeled training corpus. |
| [JSICK](https://github.com/verypluming/JSICK) | Defer pending rights-chain verification: publisher README says BY 4.0 but the repository LICENSE is BY-SA 4.0, and the original SICK sentence rights require separate verification. A translation repository license does not resolve its underlying English-source rights. Stress-test permutations/deleted particles are also unsuitable as blanket learner examples. |
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



## Additional enabled sources 2026-10-23

### JMultiWOZ

Publisher: Nagoya University's dialogue research group. The
[pinned license statement](https://github.com/nu-dialogue/jmultiwoz/blob/a78dd334b907e12318b76bb23d0a9ed1498b8d15/README.md#license)
covers the dataset under CC BY-SA 4.0. The
[publisher data guide](https://github.com/nu-dialogue/jmultiwoz/blob/a78dd334b907e12318b76bb23d0a9ed1498b8d15/dataset/README.md)
and [paper](https://aclanthology.org/2024.lrec-main.835/) distinguish human
Wizard-of-Oz turns from generated benchmark outputs. Only
`JMultiWOZ_1.0/dialogues.json` is read, one dialogue at a time. `SYSTEM` is a human
wizard role. Worker identifiers, goals, belief states, backend databases, and
model outputs are excluded. Credit all four named authors in the manifest.
Source links point to the exact publisher archive; native dialogue/turn IDs
identify the contained unit without inventing a web page for it.

The 11,016,438-byte pinned archive has SHA-256
`283dea36f5abeea8f016fea2bd4df4dfba67a40f89c4600e47ed701c57ea2bc2`.
A complete streaming inspection read 4,246 dialogues and 61,186 original turns.
Those counts precede splitting and filtering. Role-play data can be repetitive,
context-dependent, and contain outdated facility facts; it is not travel advice.

### STAIR Captions v1.2

The [publisher license](https://github.com/STAIR-Lab-CIT/STAIR-captions/blob/6ac656e65d80cbe2c914d93626a1d5454e35a5d6/README.md#license)
grants CC BY 4.0 for the caption dataset. The
[publisher project page](https://stair-lab-cit.github.io/STAIR-captions-web/)
describes original Japanese image captions and distinguishes its public subset
from larger research totals. The adapter reads only the non-tokenized train and
validation JSON members. It omits images, image URLs/metadata, and tokenized
copies. Each caption is a separate work with its native caption ID; captions of
the same image are not falsely represented as consecutive conversational context.
Image IDs and `context:image-not-included` tags remain available to consumers.
Credit Yoshikawa, Shigeto, and Takeuchi with the publisher URL and license link.

The 57,913,104-byte pinned archive has SHA-256
`8d47b7971d2883bffcba92e2ab44918e70e22c434d80dfffc01670c1654a7735`.
A complete streaming inspection read 616,435 caption records with unique IDs.
They are descriptive text, not evidence of a verified event or a guarantee of
standalone meaning. Shared image subjects and repeated wording require
relevance-aware duplicate handling in the consumer.

### Japanese Wikibooks

The current [Japanese copyright policy](https://ja.wikibooks.org/wiki/Wikibooks:著作権)
explicitly identifies CC BY-SA 4.0 and discourages external copyrighted quotations.
Covered main-namespace textbook prose is admitted through the existing Wikimedia
adapter. It omits tables, code, media, marked quotations and recognized rights
problems; revision/history links preserve contributor attribution. Use official
API samples or dated exports with the existing identified client, one-request-per-
second behavior, and retry policy. No generic website crawler is added.
Authorship and original-language status remain unknown. Historical writing and
unmarked third-party quotations are not solved by the site's general license;
the conservative extractor and quality gates remain bounded safeguards.

Contemporary original fiction requires per-work exception and authorship review.
Apart from the single reviewed SCP-JP work below, SCP/Backrooms/Hoshizora site-wide
imports remain deferred; their entire sites and Massif's underlying Narou novels
are not blanket reusable sources.

### One curated contemporary Japanese narrative: 適性

The [SCP-JP Tale 『適性』](https://scp-jp.wikidot.com/aptitude) credits terukami
and gives a creation year of 2023; that year is not represented as a confirmed
publication date. Its credit module and page footer explicitly identify CC BY-SA 3.0.
The [publisher licensing guide](https://scp-jp.wikidot.com/licensing-guide)
requires individual title, author, source, and license attribution. This source
is a one-work allowlist, not permission to crawl SCP-JP generally. The reviewed
text is a short fictional café recruitment conversation followed by a telephone
conversation. It contains no media in the narrative body. Linked words retain
only their displayed text; linked pages are never fetched or imported.

The source pins page revision 10, timestamp `2026-05-15T14:14:29Z`, and SHA-256
`1878a3f7438818c7279a0d7e608db48dbc0301f979878b077904228032cf3de4` of the
extracted paragraph texts joined with two newlines. Acquisition preserves the
complete raw HTML and its independent SHA-256. Both acquisition and every offline
build revalidate title, credit, license, revision/timestamp, `jp` and `tale` tags,
the reviewed body boundary, inline-only markup, and body hash. Drift fails closed
until a maintainer reviews and updates the pin. Navigation, ratings, credit
modules, comments, scripts, and media are not sentence material.

The HTML extraction preserves paragraph order and authored `<br>` line breaks;
HTML source whitespace is collapsed. Reviewed `span.ruby > span.rt` annotations
produce base text rather than concatenating a pronunciation onto its word.
`publisher-ruby-base-text-v1` records that transformation. The existing reviewed
body pin still covers complete inline text including readings, so changing only
a reading still fails the pin check. The derived `source_text_hash` separately
covers the extracted base-text paragraphs. Ambiguous ruby layouts fail closed.
Paragraph ranges refer to codepoints in the
extracted body, not raw HTML bytes. The existing splitter retains multi-sentence
paragraphs as original source units, with exact fragment offsets. Scene separators
remain units for quality rejection rather than being silently joined. This is a
small genre sample and does not establish narrative vocabulary coverage. Human
authorship remains `unknown`; original-Japanese status is supported specifically
by the publisher's `jp` and `tale` classification and its
[FAQ definition of Tale-JP originals](https://scp-jp.wikidot.com/faq-jp), not by an inferred author's
nationality. All extracted/adapted text retains CC BY-SA 3.0 and a modification
notice. No external media or translations are included.


### Three additional curated contemporary Tales

Reviewed on 2026-10-24, each of these original Japanese Tales credits
**aisurakuto (2019)** in its own publisher credit module, with CC BY-SA 3.0. The
creation year is not a confirmed publication date. Human authorship remains unknown.
The original-Japanese evidence is the individual `jp` and `tale` tags, interpreted
using the publisher FAQ cited above. These are fictional narrative/dialogue,
including references to the shared fictional SCP universe; none is a collection
of externally quoted texts. No linked page, image, script, rating, credit module,
footer or comment is imported as prose.

| Work | Pinned revision | Revision timestamp (UTC) | Reviewed inline body SHA-256, including ruby readings |
|---|---|---|---|
| [カモと商人](https://scp-jp.wikidot.com/a-duck-and-a-merchant) | 8 | 2026-09-25T05:15:53Z | `4e85ec9b7e8cef50f8ec2c587bed7600f4c45a5ff8bf3fb801f714ac2ca2103d` |
| [証明写真](https://scp-jp.wikidot.com/id-photo) | 5 | 2022-01-28T13:48:52Z | `ab519e18e659d5f54700886392ac5f99f15e4833b90ef2de3c721eafafb70474` |
| [定点観測](https://scp-jp.wikidot.com/fixed-point-observation) | 9 | 2022-07-23T16:37:43Z | `eea86d516075c45ebcb7d7dcea825848a27f5f09d576356a50d885894ca00319` |

The reviewed boundary selects direct `p` children of `page-content`, validates
inline-only content, and skips spacing-only paragraphs. Nested modules are never
traversed. The body hash covers all selected nonblank paragraphs, joined by two
newlines. The source ID fixes the page URL and boundary profile in code; source
configuration cannot repurpose the adapter for an arbitrary page. The exact title,
credit (including the publisher's copyright prefix), license link, revision,
timestamp, tags and body hash are revalidated during acquisition and every build.
The three snapshots yield 124 nonblank paragraphs and 462 admitted sentence
occurrences after ordinary short-fragment rejection; this remains a small genre
supplement, not evidence of broad narrative coverage.

The inspected candidate `before-date` is excluded from this expansion because of
explicit sexual content. `the-kitten-couldn-t-get-down` and `last-holiday` remain
deferred because the inspected pages did not provide the required individual
credit module. These exclusions are not a site-wide rights determination.


### One additional curated Tale: 髭を剃ったあとは気分がいい。

Reviewed the complete work and its body boundary on **2026-10-30**. The publisher
[page](https://scp-jp.wikidot.com/feeling-good-after-shaving) credits
**©︎aisurakuto (2020)** and links CC BY-SA 3.0 in its individual credit module.
The [licensing guide](https://scp-jp.wikidot.com/licensing-guide) permits commercial
reuse and adaptations under its attribution and ShareAlike terms, subject to its
exceptions. This work's reviewed prose contains no identified imported quotation
collection or narrative media, and no separate restriction was identified for it.
The exact title, author, source and license remain attached with an extraction
and sentence-splitting modification notice. The creation year is not a confirmed
publication date. Publisher `jp` / `tale` tags and the FAQ support the
`original_japanese` classification; human authorship remains `unknown`.

The source `scp-jp-shaving-ja` pins revision **12**, revision timestamp
`2026-09-24T23:08:35Z`, and reviewed inline body SHA-256
`62006a02867311fa3c1cf12d15860ce62d38c75b57e8906da61d5d5fa4ebc57b`.
The 2026-10-30 verification returned the same revision and complete body as the
prior discovery cache. The only raw HTML difference was the request timestamp in
the publisher's script; the new 55,694-byte HTML SHA-256 is
`c7800bdceff2c6d809d83fc58bac9baf4ff6360b00c72e4c5173e5caf4114512`.
This request-specific HTML value does not replace the semantic body/revision pin;
immutable snapshots independently hash the exact raw bytes actually captured.

The direct `page-content` boundary contains 65 `p` children, of which 57 are
nonblank prose units (6,501 codepoints before inter-paragraph separators).
All prose markup is `p` and authored `br`; there is no ruby or inline link in
this work. The reviewed omitted siblings are credit/rating modules, clearing
and empty layout divs, and an empty `hr` at the change of narrator. The scene
boundary reserves a context gap before paragraph 38; prose from the two scenes
is not presented as adjacent context. All 57 prose units are retained for ordinary
splitting/filtering. No nested narrative prose was silently skipped. Title,
credit, license, body/revision and fixed-URL checks remain strict, with an explicit
scene-layout pin added for this work.

This is psychological horror about a shaving product that severs unwanted
relationships, followed by dependence on the product and its sales cycle. It
includes contemporary domestic actions and sales conversation, emotional distress,
supernatural imagery and short fragments. There is no identified explicit sexual
passage or graphic injury, but the absence of heuristic content flags does not
make it child-suitable. No sentence was rewritten or corrected. Whole-work
admission review is not a native-speaker sentence-quality review: all admitted
occurrences remain `unreviewed`, with no invented reviewer or translation data.

A network-forbidden offline build with processor 5 and compressed JSONL shards
produced **1 work, 291 occurrences, 286 distinct exact Japanese texts, and no
translations**. Of 295 candidate fragments, four were rejected as too short:
`宗教。`, `髭。`, `泡。`, and `俺だ。`. Forty-two original units were split, retaining
exact source-unit context and offsets. Snapshot/build hashes, normalized ZIP CRC
and member hashes, normalized database validation, SQLite integrity and foreign
keys all passed. This is one additional work by an existing author; it adds no
author diversity and these counts do not measure novelty against existing sources
or marginal vocabulary coverage. Further works remain subject to their own rights,
complete-text and boundary reviews.


### Publisher context barriers

`publisher-context-barriers-v1` preserves missing ordinals when a complete
publisher unit is withheld before splitting (for example masked text,
machine-generated text, malformed or oversized units). Later units must not
be renumbered as if they were adjacent to earlier retained text. No text or
metadata from the withheld unit is serialized as the barrier.

Curated narrative extraction also reserves a gap at a publisher `<hr>` scene
boundary, preserving the body text and its character offsets. Consecutive rules
form one boundary; leading/trailing rules do not invent an empty scene. Optional
`scene_breaks` pins list the zero-based nonblank paragraph positions following
these rules and fail closed on drift. The reviewed shaving work has a boundary
before paragraph 38; カモと商人 has boundaries before paragraphs 4, 9 and 59.
These are extraction boundaries, not sentences or translated source units.

This changes future derived builds. Existing snapshots remain reusable, and
existing artifacts retain their own processor fingerprint and ordinal layout.
A source-specific rebuild/refresh is required to adopt the corrected boundaries;
do not edit released occurrence metadata in place.

### NICT ALT parallel Japanese (20191206)

`alt-parallel-ja` imports only the CC BY 4.0 parallel-text ZIP, never the
separate CC BY-NC-SA Japanese/English treebanks. Japanese is explicitly tagged
as translated from English; translation method and authorship remain unknown.
The paired English is original English Wikinews text, with its CC BY 2.5 license,
article URL and history attribution retained. No native review is claimed.

The pinned 21,105,607-byte archive contains 20,106 paired rows and 1,893 URL-map
articles, of which 1,888 have rows. Preserve all split suffixes exactly. Five
Japanese fields are empty, one Japanese ID is duplicated (the corresponding
English second row instead has a different ID), and one ID has a trailing hyphen.
Exclude both duplicate-ID rows and the malformed-ID row rather than repairing
or inventing alignment. Missing/excluded rows reserve context gaps. Quotation
spans and incomplete prose are conservatively excluded. Corpus release dates
are never interpreted as publication dates. Initial offline qualification admitted
14,772 occurrences in 1,883 documents before content-flag exclusions and the
subsequent reviewed-pair policy.

The 2026-10-31 offline rebuild with text processor v9 and eight exact
reviewed-pair exclusions retains **14,696 occurrences, 14,693 distinct Japanese
texts, 14,696 paired English records and 1,882 works**. Its normalized ZIP has
SHA-256 `699278e599948b3870a7ed68ca1c242876fd1d62eda9458c978e63fb72a21148`.
All eight withheld identities are absent. The latest exact exclusion,
`SNT.253499.10122`, conflicts on a period's end year (2001 versus 2011).
Comparison with the prior build confirms this is the only removed pair and
that surviving text is unchanged. Its neighbors remain unlinked; the source
has 2,154 gaps between surviving occurrences, preserving missing context.

The numeric diagnostic v2 pass inspected six remaining disagreement signals
before that exclusion. The other five signals involve omitted numerals or
numbers written as words and do not establish a mistranslation. These are
assistant-only findings, and source text is never repaired. The rebuild also
annotates 351 violence mentions, including all four disturbing snippet classes
found in the result review. Public annotations are retained; the private serving
pipeline excludes flagged occurrences and prevents context from crossing them.
Rights and translation direction remain independently licensed and labeled;
no human/native review or generation evidence is inferred. This qualifies the
source build, not a serving activation or accuracy certification of all pairs.


### YJ Captions: pinned caption-only adapter

The [publisher README](https://github.com/yahoojapan/YJCaptions/blob/2f2d6de87ce90b7ff1fd318efef17b1ce0e127db/README.md)
licenses captions under CC BY 4.0. The accompanying
[paper](https://aclanthology.org/P16-1168.pdf) establishes human Japanese creation
and cleaning; its machine caption-generation experiments are separate from the
released annotations. `yj-captions-ja` reads only `yjcaptions26k_clean.json` from
the pinned 4,257,429-byte ZIP (SHA-256
`e2978ac2770f571a012d280ffe9c69f3612be9c104d3cd5cf7116249a4006503`).

No images, image URLs, image-license fields, or inferred translations enter the
corpus. Each complete caption is its own work with caption/image identity,
source-row hash, publisher revision and attribution; captions sharing an image
are independent examples. Rejected incomplete captions have separate acquisition
counters. Synthetic tests cover ingestion and compressed normalized export;
full source admission, overlap, serving predicate checks, representative review
and size measurements remain required before activation. The publisher count
is not a measured corpus increase.

For the opt-in Global Voices source, raw HTML is local rights evidence, not a public snapshot asset: it still includes withheld third-party quotations and caption text. The adapter is absent from the raw snapshot workflow and `snapshot-pack` rejects its pages. Public corpus exports contain only the reviewed eligible Japanese paragraphs.
