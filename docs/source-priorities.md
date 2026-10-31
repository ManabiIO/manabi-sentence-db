# Source priorities and admission policy — 2026-10-24

Accept licenses allowing commercial redistribution **and modification**. Exclude
all NC and ND variants, machine-generated Japanese, historical Japanese, and
unlicensed third-party quotations. A dataset repository's license is not evidence
that independently copyrighted contents can be redistributed. Unknown authorship
and language origin must remain unknown; translations do not become Japanese originals.

## Enabled adapters

Wikipedia, Kyoto Wikipedia pairs, Wikivoyage, Wikibooks, archived Japanese
Wikinews, Tatoeba, RealPersonaChat, MRMP multi-party chat, JMultiWOZ, STAIR Captions, YJ Captions, JEC Basic
Sentence Data, NICT ALT parallel news text, ASDC main accommodation dialogues,
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
| Yahoo VFD | [Publisher](https://github.com/yahoojapan/VFD-Dataset), reported CC BY 4.0 | Human imagined responses; keep modality/context flags. |
| JMRD | [Publisher](https://github.com/ku-nlp/JMRD), reported CC BY-SA 4.0 | Conversation, not copyrighted movie scripts. |
| JMultiWOZ (enabled) | [Publisher](https://github.com/nu-dialogue/jmultiwoz), verified CC BY-SA 4.0 | Human role-play, preserve speaker/turn context without profiles. |
| Multi-Party Chat / MRMP (enabled) | [Pinned publisher](https://github.com/nu-dialogue/multi-relational-multi-party-chat-corpus/tree/e6e39cb896df88781c7a2e0451226a527c5f1e2e), verified CC BY-SA 4.0 | Human conversation; only dialogue turns, exact README/LICENSE pins, no profiles/evaluations. |
| ASDC main (enabled) | [Pinned publisher](https://github.com/megagonlabs/asdc/tree/f37d6575c73602adcb8ae3687520726793baa672), verified corpus CC BY 4.0 | 210 main human role-play dialogues; no SCUD descriptions, supplemental or vanilla material. |
| JGLUE questions | [Publisher](https://github.com/yahoojapan/JGLUE), reported CC BY-SA 4.0 | Audit component and underlying passage rights separately. |
| JaQuAD | [Publisher](https://github.com/SkelterLabsInc/JaQuAD), reported CC BY-SA 3.0 | Questions versus reused Wikipedia passages. |

Except the rows explicitly marked enabled, these are candidate claims supplied in the research
shortlist, not newly verified admission grants. Do not enable downloads until the
specific release and underlying content rights are reviewed.

## Fiction and longer writing

Five original SCP-JP Tales are admitted with per-work credit, CC BY-SA 3.0, and
revision/body-hash pins; see the [individual review notes](sources.md#three-additional-curated-contemporary-tales).
Further original SCP-JP Tales and Backrooms JP require per-work exception checks,
separating translated international fiction from original Japanese. Preserve mixed
BY-SA versions. Hoshizora's API license filters can identify individual BY/BY-SA/PD
works but it is a small supplement. Rosebleu requires an exact identified release
and verified license before admission; the supplied shortlist did not identify it.

Wikibooks, government public-information pages, Japanese Stack Overflow, and Fandom
are additional candidates, with per-site/per-post license dates and third-party
exclusions. KAKEN and J-ResearchCorpus need original document rights checks; a mirror
label does not resolve older report exceptions. J-STAGE requires per-article screening.

## Translations and holds

StoryWeaver story text (reported BY 4.0) is separate from NC-ND readalong/video editions.
Global Voices and MDN Japanese should be classified by original versus translated
work. Common Voice is on hold pending redistribution-policy review. Open2ch remains on hold
because poster rights are unresolved. Aozora is deferred for the contemporary cut.

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

SNOW T15/T23 remain candidates: the indexed primary pages specify CC BY 4.0 and
manual Japanese simplification, but live landing-page downloads were unavailable
on recheck. Verify the corrected XLSX download links and upstream Tanaka/Tatoeba
attribution before enabling an adapter. Human simplification does not prove that
all inherited English translations are human-created; leave their generation
unknown unless more specific evidence is available.
