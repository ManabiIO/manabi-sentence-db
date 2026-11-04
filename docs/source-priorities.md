# Source priorities and admission policy — 2026-11-04

Current completion and exact resume evidence live in [corpus-progress.md](corpus-progress.md).
The dated investigations below preserve their original findings; they are not
instructions to repeat completed acquisitions or qualification.

Accept licenses allowing commercial redistribution **and modification**. Exclude
all NC and ND variants, machine-generated Japanese, historical Japanese, and
unlicensed third-party quotations. A dataset repository's license is not evidence
that independently copyrighted contents can be redistributed. Unknown authorship
and language origin must remain unknown; translations do not become Japanese originals.

## Enabled adapters

Wikipedia, Kyoto Wikipedia pairs, Wikivoyage, Wikibooks, archived Japanese
Wikinews, Tatoeba, RealPersonaChat, MRMP multi-party chat, JMultiWOZ, STAIR Captions, YJ Captions, JEC Basic
Sentence Data, NICT ALT parallel news text, ASDC main accommodation dialogues, TALPCo teaching examples,
JMRD review-grounded authored dialogue, MASSIVE human-localized Japanese requests,
one opt-in Global Voices translated-news work (`globalvoices-65906-ja`),
the license-separated Storybooks Japan Japanese narrative subsets,
and individually curated SCP-JP Tales
『適性』『カモと商人』『証明写真』『定点観測』『髭を剃ったあとは気分がいい。』.
Wikimedia and Tatoeba provenance does not establish blanket human authorship or
original Japanese. Their releases preserve that uncertainty. Machine generation
metadata explicitly excludes an item from the Japanese corpus. Heuristic era and
content checks remain incomplete, and all imported occurrences remain unreviewed.

RealPersonaChat is pinned to commit `28d0b6b3865b29cabc26c230a2db37cdf315e937`.
Its [publisher README](https://github.com/nu-dialogue/real-persona-chat#ライセンス)
confirms CC BY-SA 4.0, 408,619 human utterances, privacy filtering, and the separate
location of model experiments. The adapter reads only `real_persona_chat/dialogues`.
It excludes profiles, evaluations, model-generated dialogues and masked utterances.
There are two duplicate internal dialogue IDs; filename identity preserves all works
without fabricating provenance links. The adapter has a regression for this upstream defect.

## Enabled parallel data

The [NICT Kyoto Wikipedia corpus](https://alaginrc.nict.go.jp/WikiCorpus/index_E.html)
is now enabled as `wikipedia-kyoto-ja`. The pinned v2.01 archive provides
Japanese Wikipedia sentences with NICT English translations; only the final
checked translation is imported. This adds explicit Japanese-English alignment
and translation attribution, but overlaps the Japanese Wikipedia corpus.
Article history, translator IDs, and the publisher's CC BY-SA 3.0 notice are
preserved. Source-flagged errors, classical or incomplete examples, quotes,
and reference sections are excluded. Counts should distinguish admitted
pairs from source rows and from text overlap with Wikipedia.

## Next structured datasets

| Candidate | Publisher evidence / license | Admission notes |
|---|---|---|
| STAIR Captions (enabled) | [Publisher](https://github.com/STAIR-Lab-CIT/STAIR-captions), CC BY 4.0 | README rechecked; Japanese image captions. Images require separate rights. |
| Japanese Visual Genome VQA | [Publisher](https://github.com/yahoojapan/ja-vg-vqa), reported CC BY 4.0 | Verify downloadable text license; many answers are fragments. |
| YJ Captions (adapter enabled) | [Pinned publisher](https://github.com/yahoojapan/YJCaptions/blob/2f2d6de87ce90b7ff1fd318efef17b1ce0e127db/README.md), verified CC BY 4.0 | Human original Japanese caption text only; complete-caption gate and separate works; no English alignment inferred from image IDs. Full admission, overlap and serving growth remain to be measured. |
| Yahoo VFD (adapter ready; full qualification pending) | [Pinned publisher](https://github.com/yahoojapan/VFD-Dataset/tree/5cb774f44d8fa64e288cbb9b8e96c7aa5959ad62), CC BY 4.0 | Conservative punctuated spoken pairs; no images/non-verbal actions. See the November 4 review below; no published/serving output claimed. |
| JMRD (enabled and source supplement published) | [Pinned publisher](https://github.com/ku-nlp/JMRD/tree/a20b0a89b4cf6ce1db320039f6e27df10604bf4c), CC BY-SA 4.0 | Review-grounded authored dialogue only; excludes external plots/biographies, copied prose and questionnaires. Five exact problematic utterances are withheld whole. See [current admission evidence](sources.md#high-priority-additions). |
| MASSIVE Japanese (enabled and source supplement published) | [Publisher](https://github.com/alexa/massive), CC BY 4.0 with SLURP credit | Independent publisher judgments gate human-localized Japanese requests. No English prompts are exported as translations; entities can differ. See [source policy](sources.md#massive-japanese-practical-requests). |
| JMultiWOZ (enabled) | [Publisher](https://github.com/nu-dialogue/jmultiwoz), verified CC BY-SA 4.0 | Human role-play, preserve speaker/turn context without profiles. |
| Multi-Party Chat / MRMP (enabled) | [Pinned publisher](https://github.com/nu-dialogue/multi-relational-multi-party-chat-corpus/tree/e6e39cb896df88781c7a2e0451226a527c5f1e2e), verified CC BY-SA 4.0 | Human conversation; only dialogue turns, exact README/LICENSE pins, no profiles/evaluations. |
| ASDC main (enabled) | [Pinned publisher](https://github.com/megagonlabs/asdc/tree/f37d6575c73602adcb8ae3687520726793baa672), verified corpus CC BY 4.0 | 210 main human role-play dialogues; no SCUD descriptions, supplemental or vanilla material. |
| JGLUE questions | [Publisher](https://github.com/yahoojapan/JGLUE), reported CC BY-SA 4.0 | Audit component and underlying passage rights separately. |
| JaQuAD | [Publisher](https://github.com/SkelterLabsInc/JaQuAD), reported CC BY-SA 3.0 | Questions versus reused Wikipedia passages. |

Except the rows explicitly marked enabled, these remain candidates. Dated
publisher-notice checks do not qualify a particular release, its underlying
third-party text or its sentence quality. Other undated rows retain the supplied
shortlist's unverified claims. Do not enable downloads until the specific release
and underlying content rights are reviewed.

### JMRD and VFD primary-evidence follow-up — 2026-11-02

JMRD's current README lists 4,575 training, 200 validation and 300 test dialogues;
these are published split counts, not measured usable/novel sentences. The
[construction paper](https://aclanthology.org/2022.dialdoc-1.9.pdf), sections
3.1–3.2, distinguishes crowdwritten reviews from Wikipedia-derived plots and
person descriptions. Its reviews are **not described as scraped Yahoo reviews**;
Yahoo Movies supplies genre classifications. Recommenders see the knowledge and
are instructed to use it; seekers do not have that interface. A future adapter
must separate utterances from `knowledge`, `checked_knowledge` and questionnaires,
preserve turn gaps, and review copied knowledge/attribution rather than assuming
that excluding the knowledge fields resolves every reused passage. No JMRD
archive, native analysis or serving import was produced in this follow-up.

VFD's [publisher format](https://github.com/yahoojapan/VFD-Dataset#annotation-format)
and [paper](https://aclanthology.org/2020.emnlp-main.267/) distinguish utterances,
verbal replies and non-verbal responses grounded in images and gaze. Non-verbal
action descriptions are not interchangeable with spoken examples. Keep image
rights separate and require a text-only usefulness sample before investing in an
adapter; an open license alone does not establish independent sentence quality.
This November 2 check did not download or admit VFD. The November 4 follow-up
below supersedes its acquisition status.

### VFD text-only follow-up — 2026-11-04

The pinned publisher commit is `5cb774f44d8fa64e288cbb9b8e96c7aa5959ad62`.
Its **6,576,449-byte ZIP** contains README, preparation code and a
**34,569,789-byte TSV**, with no images. SHA-256:
`d8f90ac159383813da5a79ead1883548356cc97f33fef0cd11a2cc0e737b17d3`.
The TSV's Git blob matches publisher metadata. It has **314,895 rows**; 6,102
verbal responses are empty/dummy. These are raw rows, not admitted sentences or
novel text. The actual header is `gf_id`, despite `gfid` in the README.

The [construction paper §3.2](https://aclanthology.org/2020.emnlp-main.267.pdf)
establishes that crowdworkers authored Japanese utterances and verbal responses.
An assistant-only development review read both spoken fields in all 96
deterministically sampled rows. Everyday requests, sports, travel and household
language are promising; terse replies, missing punctuation and image references
are common. This is not a population quality estimate or native review.

The `yahoo-vfd-ja` adapter selects only terminally punctuated spoken units and
then uses the shared text/content gates. It preserves the exact two-turn pair,
omitted-turn gaps, original text and row citations; separate candidate responses
are never joined across TSV rows. Non-verbal actions, image paths, images and
publisher code are excluded. `context:image-not-included` remains explicit.
Punctuation is only a conservative admission proxy. **Full source build, fresh
retained-output review, exact novelty and serving-size qualification are pending;
no public source archive or search activation is claimed.** Reuse the pinned
compressed acquisition rather than downloading again.

## Fiction and longer writing

Five original SCP-JP Tales are admitted with per-work credit, CC BY-SA 3.0, and
revision/body-hash pins; see the [individual review notes](sources.md#three-additional-curated-contemporary-tales).
Further original SCP-JP Tales and Backrooms JP require per-work exception checks,
separating translated international fiction from original Japanese. Preserve mixed
BY-SA versions. Hoshizora's API license filters can identify individual BY/BY-SA/PD
works but it is a small supplement. Rosebleu's exact publisher release is now
identified below; it remains disabled pending format, notice and content gates.

### Rosebleu publisher evidence — 2026-11-04

The shortlist's “Roseblue” link resolves to
[`open_contents_datasets/Rosebleu`](https://gitlab.com/open_contents_datasets/Rosebleu),
commit `b8a169893c87611c7c1c76d78acd1cbe3273a146`. The pinned
[README](https://gitlab.com/open_contents_datasets/Rosebleu/-/blob/b8a169893c87611c7c1c76d78acd1cbe3273a146/README.md)
identifies the former brand representative as the supplier and ten titles whose
rights had not been transferred. It records redistribution permission without
commercial/noncommercial restrictions and applies Apache 2.0; it also expressly
permits uses compliant with that license beyond model fine-tuning. The pinned
[LICENSE](https://gitlab.com/open_contents_datasets/Rosebleu/-/blob/b8a169893c87611c7c1c76d78acd1cbe3273a146/LICENSE)
retains `Copyright (c)Rosebleu` and an Apache 2.0 notice. README bytes/SHA-256:
3,457 / `ce2f0360de003bd1baa0ba36a074ceae37b4b9567d260c7c78dd7dc908128739`;
LICENSE: 546 / `c8b5278bf3346156a20333e20a165f219022f76e9fa0e95f60a06c7b6a0c95c1`.

This is a plausible substantial modern narrative/dialogue supplement, not an
enabled source or an admitted sentence count. Before acquisition/admission:

- Review Apache license/notice retention at the public and private interchange
  boundaries; both currently allow only reviewed CC-family text licenses.
- Complete the chapter inventory using the pinned commit. A bounded first-title
  metadata page contains 100 entries with a second page outstanding; it is not a
  full inventory. JSONL and TSV duplicate the same material; import one form.
- The README identifies adult-scene filename groups, but the converted filename
  conventions need a complete audit. Withhold whole identified adult scenes,
  unknown groups and graphic passages; filenames alone do not certify safety.
- Preserve each chapter's ordered utterances, omission gaps and speaker evidence;
  review variable/control markup, quotations and sentence quality. Do not infer
  publication dates, original-language status or native review from folder names.

Only the small pinned README, LICENSE and one metadata page were acquired during
this check. No scenario text, archive, adapter, native analysis or serving import
was produced. Preserve/reuse that evidence rather than repeating the source search.

Wikibooks, government public-information pages, Japanese Stack Overflow, and Fandom
are additional candidates, with per-site/per-post license dates and third-party
exclusions. KAKEN and J-ResearchCorpus need original document rights checks; a mirror
label does not resolve older report exceptions. J-STAGE requires per-article screening.

## Translations and holds

StoryWeaver story text (reported BY 4.0) is separate from NC-ND readalong/video editions.
Global Voices and MDN Japanese should be classified by original versus translated
work. Common Voice is on hold pending redistribution-policy review. Open2ch remains on hold
because poster rights are unresolved. Aozora is deferred for the contemporary cut.

MultiLS-Japanese is also deferred from corpus expansion. Its
[primary dataset card](https://huggingface.co/datasets/naist-nlp/multils-japanese)
labels CC BY-SA 4.0 but gates files behind account-information sharing and says
the annotation is intentionally kept off the open web to avoid benchmark
contamination. The [publisher repository](https://github.com/naist-nlp/multils-japanese)
confirms that distribution choice. No gate was accepted or dataset downloaded.
It is a small evaluation resource rather than a high-yield expansion source.

The [news-chat corpus](https://github.com/fukanarita/newschat-with-impression)
has an MIT repository notice and crowd dialogue, but its own example explicitly
incorporates tweets and verbatim third-party newspaper quotations. Do not admit
all utterances under the repository license; first isolate authored turns and
preserve gaps, as with the reviewed JMRD policy. No acquisition or adapter is
enabled by this inspection.

Exclude Livedoor (ND), KokoroChat/Japanese Daily Dialogue/NUCC (NC/ND), restricted
BCCWJ material, MARC-ja without current source rights, Common Crawl-derived text
without underlying permissions, synthetic corpora, and copyrighted scripts copied
into otherwise open wikis. Do not report raw published unit counts as distinct,
usable sentences; report admitted occurrences, unique texts, origin, and exclusions.



### October 23 implementation update

JMultiWOZ and STAIR v1.2 now have bounded, commit/hash-pinned adapters and offline
regressions; Wikibooks uses the existing conservative Wikimedia prose adapter.
See the [exact admitted subsets and primary evidence](sources.md#additional-enabled-sources-2026-10-23).
Source counts are separate from admitted fragments, deduplicated texts, vocabulary
coverage, and independence from visual/dialogue context. Beyond the one reviewed
Tale, narrative candidates remain subject to per-work rights and original-language checks; no Narou or
unverified fiction has been imported merely to increase sentence totals.


### Caption expansion follow-up

YJ Captions is pinned to publisher commit `2f2d6de87ce90b7ff1fd318efef17b1ce0e127db`.
Its [paper](https://aclanthology.org/P16-1168.pdf), sections 3–3.1, describes
human Japanese descriptions and a subsequent cleaning task. Its published
131,740-caption count is not an admitted or novel-sentence count. The adapter
checks the archive checksum, accepts only `yjcaptions26k_clean.json`, streams
annotations, rejects incomplete captions, and never follows image URLs. Each
caption is a separate work so other descriptions of the same picture cannot
be mistaken for preceding/following context. English COCO captions are independent
descriptions, not sentence translations. Preserve image-dependency flags and
apply the serving predicate filter before activation. Measure deduplicated overlap
with STAIR and existing text, actual result quality, and compressed/index growth
before selecting how much to publish.

SNOW T15/T23 remain candidates. Archived publisher pages and download handlers
now establish the exact live January 7, 2020 corrected XLSX URLs; see the
[acquisition and rights-chain review](sources.md#snow-simplified-japanese-acquisition-recheck-2026-10-31).
The publisher grants CC BY 4.0 and describes manual Japanese simplification, but
inherited Tanaka/Tatoeba attribution and third-party origins require separate
handling. A bounded T23 prefix also contains malformed or meaning-changing
rewrites. Keep admission on hold pending source-specific provenance, quality and
exact-overlap review. Do not label inherited English as human-translated merely
because the Japanese was simplified by people.


### Parallel-text quality diagnostics

ALT's method-unknown Japanese/English pairs can contain source numeric or wording
errors. Parallel provenance and open licensing do not certify translation accuracy.
`audit-parallel-numbers` now prepares a text-free count report and an optional
bounded compressed review packet from existing builds. Numeric differences are
review signals only; magnitude/date/identifier notation is skipped conservatively.
The diagnostic rejects or corrects no pair automatically. A separate assistant
review now withholds eight exact ALT pairs with conflicting quantities/years or
unrelated content. Their paired-text hashes and article URLs are pinned in
`alt_reviewed_exclusions.json`; changed text fails closed for fresh review.
Publisher ordinals retain gaps, and no side is rewritten or certified correct.
This does not turn the remaining pairs into reviewed translations. See the
operations guide.


### Storybooks Japan narrative supplement

The two pinned sources admit only 29 explicitly CC BY 3.0/4.0 works from a
40-story Japanese catalog; eleven NC works, illustrations and audio are excluded.
Per-work translator/original-work credits, primary page units and omission gaps
survive. Japanese translation origin is explicit, while method/native review
remain unknown. See the [source decision](sources.md#storybooks-japan-narrative--2026-11-03).
These smaller narrative additions complement the large Wikipedia expansion;
they are not a ceiling on later corpus growth or already active serving content.
