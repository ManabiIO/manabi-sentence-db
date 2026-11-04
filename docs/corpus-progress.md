# Corpus expansion checkpoint — 2026-11-04

This is the current pipeline checkpoint and supersedes historical running/queued
statements below. Generated corpus text and detailed evidence stay outside Git.

## Latest: 1,783,000 further Wikipedia and 429,846 VFD occurrences published

Both reviewed source supplements are public. **All 59 uploaded source/metadata
asset sizes and SHA-256 digests matched**, and both unauthenticated manifests
were checked. The October 24 full base remains GitHub's designated latest.
These are source occurrences, not globally novel or already searchable additions.

| Release | Retained works/pairs | Occurrences | Compressed source bytes |
|---|---:|---:|---:|
| [Further Wikipedia prose](https://github.com/ManabiIO/manabi-sentence-db/releases/tag/corpus-wikipedia-further-2026-11-04) | 120,616 | 1,783,000 | 427,337,970 / 16 ZIPs |
| [VFD visual-dialogue text](https://github.com/ManabiIO/manabi-sentence-db/releases/tag/corpus-vfd-2026-11-04) | 277,242 | 429,846 | 85,333,252 / 35 ZIPs |

Wikipedia reuses the cached snapshot and body-free metadata. Its 127,197 selected
page IDs exclude all 170,976 earlier IDs before quotas. V10 canonical refinement
withholds 163 demonstrated wording/structural remnants and one empty work. A
replacement example exposed unreliable wording in the captured watermill article;
that **whole work (117 occurrences)** is additionally withheld from the release.
All 280 removals and the current 264-example review were inspected by an assistant.
The last selection reused fifteen compressed ZIPs and replaced only the affected
bucket, independently comparing every retained normalized record against its
parent. It took 201.68 seconds / 749,068,288 peak cgroup bytes, without repeating
a full extraction, native analysis or the prior full verifier.

The verified v10 canonical build remains `build_4a17eecef2f9239fc5ee48c8ed84dbb7`,
catalog SHA-256 `7cf016b3cc36c60fcb55fb3cb3ffcebc6ba80c0ec2e8a54d2721cd65786ceff0`.
It still describes the original full verified build; each published ZIP's bound
whole-work selection identifies the selected release subset. Use the released
selection for import, rather than reintroducing the omitted article. The public
manifest SHA-256 is `9cf9f8d5bf8741341db5f24516eb0a55a6c5a5a38f463470766f48cd880307b7`.
No retained wording, identifiers, license, attribution, revision or ordinal gap
was changed. This conservative work omission includes valid sentences; it is not
a general ban on historical or scientific prose.

VFD reuses its single pinned publisher archive. `vfd-example-quality-v1` removes
one exact typing-error utterance and five occurrences of one adult-context
utterance, dropping four now-empty pairs. Every retained record was independently
compared against its parent, with separate pair boundaries and omitted-turn gaps.
All 96 current examples and all six removals were inspected: 94 prior examples
matched exactly and both replacements were read. The manifest SHA-256 is
`d0851cb7cbe24ba7cc19ecbaedd0e847da1a19eaf94d6a362533ef13eb8d971e`.
Text is CC BY 4.0, with original Japanese crowd authorship established by the
paper. Images, paths, gaze annotations, action labels and publisher code are
excluded; `context:image-not-included` remains. There are no translations.

**Public source code `4e38a04` is qualified:** 1,430 host tests pass / one optional
native-backend-only skip, **all 1,431 main Linux tests pass**, Ruff and 26 source
configs pass. The private consumer's default acquisition now distinguishes the
latest full release from newer source-only supplements. No publication has been
repeated; exact local receipts are in the private resume index.

The bounded Wikipedia/MASSIVE native/storage pilot is also **complete, exit 0**:
**11,775 Wikipedia texts / 49,082,368 bytes** and **12,820 MASSIVE texts /
44,072,960 bytes** in the selected compact SQLite v11 format, including indexes,
metadata, projections and word links. Peak cgroup memory was 562,503,680 bytes.
Word dictionaries reduce payloads 5,622,416 → 2,231,616 and 2,821,755 → 1,091,767
bytes, plus 131,226 dictionary/manifest bytes each; held-out checks also improve.
These are measured word-payload gains, not whole-database compression ratios.
Fifty-five of 1,230 query rows were inspected, including all 15 whole-compound
matches. No sampled bare-持つ false match was observed for 持っていく. The pilot
is not a population size/quality, combined-diversity, recall or latency estimate.
Reuse its analyses, words and verification rather than repeating them.

All imported occurrences remain **unreviewed**. Assistant inspection is not
native-speaker certification or a population quality estimate; awkward, nominal,
specialist and context-dependent prose can remain. The previously published
[1,972,952-occurrence Wikipedia supplement](https://github.com/ManabiIO/manabi-sentence-db/releases/tag/corpus-wikipedia-expanded-2026-11-04)
and the three earlier supplements remain unchanged. No raw dump, private captions or
private serving/native artifacts were uploaded. Source publication does not
activate the preview. Next: exact budgeted native admission, preserving the
**8 GB serving target / 10 GB ceiling**, followed by one combined serving refresh.
Source-release storage has a separate budget. Reuse completed source, baseline,
analysis-cache and IDs-only novelty receipts; do not redo their verification.

## Qualified source-CPU and reusable-import improvements

`67d2d2a` removes a redundant prewrite schema walk while preserving complete
validation of every written child record before publication. Corrupted written
tags, licenses and source IDs still fail closed; original inputs remain unchanged.
`d157c74` adds pinned `jsonschema-rs` 0.59.0 for compatible JSON values, preserving
Python validation and diagnostics for other inputs. Rust-only probes differed on
URL whitespace and tuple coercion; the guard prevents those fast acceptances.
Differential regressions cover over 3,000 mutations of source manifests, nested
translations/source units and both reference locators. Actual backend/dependency
versions enter build identity; legacy frozen environments without the native
package retain Python behavior.

**1,373 full tests pass on both macOS and Linux**, Ruff passes, and 25 source
configs validate. Linux explicitly used the native backend under the producer
lock (90.55-second suite). An 80-work / 1,280-sentence full-refinement comparison
used 0.169–0.201 CPU seconds with Python versus 0.064–0.073 with guarded Rust,
with every record identical. These are tiny-fixture gains, not an extrapolated
full-corpus speedup. The completed v9 release kept its original frozen producer;
only the new source cohort uses the qualified faster producer.

The private offline import command now supports repeatable `--reuse-analysis`
for already-qualified immutable parents. It reuses exact tokens/JLPT metadata,
reads corrected provenance/flags/positions from new source archives, keeps one
decoded sentence and bounded readers, checks parent identities before publication,
and validates the complete new logical import. Its owned analyzer cannot close
the web thread's cached analyzer. **42 import/compact-parent/runtime tests pass**.
The serving architecture remains compact SQLite v11; no new full serving artifact
or production deployment is claimed.

## Other source supplements already published

The [November 4 prose/dialogue/request supplement](https://github.com/ManabiIO/manabi-sentence-db/releases/tag/corpus-prose-dialogue-2026-11-04)
contains **562,881 occurrences / 123,984,131 compressed bytes**:

| Source | Works | Occurrences | Archive-distinct texts | Compressed bytes |
|---|---:|---:|---:|---:|
| Earlier Wikipedia v8 cohort | 26,695 | 437,881 | 434,474 | 101,502,099 |
| Refined JMRD dialogue | 5,075 | 111,378 | 59,116 | 18,956,495 |
| MASSIVE Japanese requests | 13,598 | 13,622 | 12,820 | 3,525,537 |

Do not sum archive-distinct counts as globally novel text. Wikipedia/JMRD retain
CC BY-SA 4.0. MASSIVE retains CC BY 4.0 with SLURP credit, explicit human-localized
origin and independent publisher judgment gates. English prompts can contain
different entities and are not exported as translations. All 96 MASSIVE examples
were read; no worker identities, raw judgments or other locales were published.
The two November 3 supplements and October 24 full base remain unchanged.

Reuse all preserved native analyses, corrected metadata and baseline receipts.
The completed prior 493,606-text import binds pre-refinement payloads; use its
cached analyses with corrected occurrences rather than serving it unchanged or
repeating the verified 2,038,328-text baseline. Exact native eligibility and final
combined serving size still require their normal gates. Source-priority research
now pins Rosebleu's publisher grant/Apache notice but does not enable it: adult
scene boundaries, complete archive inventory, notice support and text quality
remain open. No scenario text was acquired. See [source priorities](source-priorities.md).

## Previous pass: two completed source batches; compressed quality refinement queued

Public main `5669f51` adds Wikipedia admission **v8**; `c0737d6` adds
`jmrd-example-quality-v1` and the reusable **`refine-jmrd`** command. The full
**1,305-test suite**, Ruff and **24 source configurations** pass. A subsequent
focused 45-test pass also verifies JMRD refinement through normalized SQLite,
including its exact parent catalog. No serving architecture or native runtime
changed.

The completed new Wikipedia cohort selected **27,829 new page IDs**, producing
**26,695 works / 437,889 occurrences / 434,482 distinct texts within the archive**.
Its original v7 normalized ZIP is **101,337,270 bytes**. The complete 132-example
assistant packet was read (12 distinct-text hash examples per metadata topic).
V8 adds narrow orphan-example and missing-unit-table rules, plus four exact
hash omissions: three demonstrated wording errors and an unflagged graphic
passage. Ordinary units statements, medical prose, nominal forms, science and
history retain controls. This inspection is not a population quality estimate or
native-speaker certification. **Do not publish this unrefined v7 archive.**

The corrected JMRD v2 batch completed **5,075 works / 111,388 occurrences /
59,126 distinct texts**, in an **18,954,886-byte** normalized ZIP before refinement.
Primary paper §3.1 establishes first-party crowdwritten reviews; review-grounded
dialogue is retained, while external plots/biographies and raw knowledge fields
remain excluded. The same pinned 8,797,366-byte download is reused, with no new
acquisition. All 96 hash-selected review sentence texts were read. Five exact
problematic utterances will be withheld whole, including sibling segments, by
`jmrd-example-quality-v1`; colloquial language is not broadly banned. Occurrences
remain `unreviewed`. **Source publication awaits compressed refinement.**

One frozen worker is still performing **one compressed non-serving native import
of JMRD plus the completed Wikipedia batch**, reusing exact analyses from both
verified parents. Its four-sentence native fixture passed. Full novelty/counts,
peak memory and import completion must come from its final stage receipt; partial
logs are not completion. It then releases the native process and builds the
unchanged larger Wikipedia selection: **190,000-page quota**, excluding both
previous cohorts before quotas, body-free reusable metadata and 8,000-work ZIP
buckets. Quotas are not admitted sentence counts. This frozen source job still
uses **v7** and must receive v8 compressed refinement before publication/promotion.
Do not relaunch it or repeat completed native work because source quality changes.

A separate frozen **compressed-only refinement worker is dispatched and waiting
on the same Linux producer lock**. It first runs a tiny Linux fixture, then
refines the completed Wikipedia and JMRD canonical builds. It checks every
retained record/field against the parent, preserves ordinal gaps and rights,
checks normalized member counts/hashes independently, and writes completion
receipts last. It performs no raw extraction, new downloads, native calls,
serving index build or activation. The first capsule failed strict ZIP preflight
before obtaining the lock; its fresh replacement passed packaging preflight and
is waiting. Do not relaunch either capsule. Exact recipes, parent hashes,
container identities and stage paths are in the private resume checkpoint.

Both producers remain **one worker / 0.25 CPU / 1 GiB**, serialized through the
actual Linux producer lock. No new serving dataset is active; no production
change. Reuse the verified 2,038,328-text baseline and qualified MRMP/YJ native
analyses. Source archives and serving storage have separate budgets: retain the
**8 GB serving target / 10 GB ceiling**. The larger new cohort requires a fresh
review packet and source-only refinement before publication, then deduplicated
admission/novelty and a measured serving-size decision before any one combined
serving rebuild.

## Earlier pass: substantially larger Wikipedia cohorts dispatched

Following Alex's request for dramatic, sensible growth, public main `c7f439a`
adds a reusable body-free Wikipedia metadata index, exclusion of previous page
IDs **before** topic quotas, and single-pass whole-work normalized ZIP buckets.
Its full **1,256-test suite**, Ruff, 23 source configurations and main CI passed.
Two further input-mutation regressions now bring the passing local suite to
**1,258 tests**: changes during metadata indexing or after checksum verification
cannot publish completion/selection manifests.
Existing segmentation, rights and Wikipedia quality v7 gates remain in force.

The current 27,829-new-page cohort is still extracting from cached inputs. A
larger successor is **dispatched and waiting on the same Linux producer lock**:
15,000 pages per topic plus 40,000 general, a combined **190,000-page quota**,
with both prior cohorts excluded first. Actual new page and sentence counts
will be lower than the quotas and must be read from its completion receipts.
No native analysis or serving activation is claimed for these running jobs.

The larger worker first runs a tiny Linux index → disjoint selection → compressed
bucket fixture; failure prevents full processing. It then creates the reusable
metadata index, selects a new cohort, extracts compressed canonical records,
exports 8,000-work ZIP buckets in one pass, and prepares a topic-stratified
assistant review packet. Completion manifests are published last. Each worker
is limited to one worker / 0.25 CPU / 1 GiB; processing is serialized, with no new
download or concurrent full serving rebuild. The private resume index binds
exact container, recipe, code and input hashes; do not dispatch duplicates.

Large source archives and a downstream serving database have separate budgets.
Source publication retains every eligible occurrence and its attribution;
deduplicated native/quality qualification and the existing 8 GB target / 10 GB
serving ceiling remain subsequent gates. Reuse the already verified baseline
and exact-text analyses instead of repeating their verification.

## Earlier pass: conversation/caption growth published; Wikipedia started

The separate [conversation and caption supplement](https://github.com/ManabiIO/manabi-sentence-db/releases/tag/corpus-dialogue-captions-2026-11-03)
is public. Three normalized-v2 ZIPs total **49,847,146 compressed bytes** and
contain **206,061 source sentence occurrences**:

| Archive | Works | Occurrences | Distinct texts within archive |
|---|---:|---:|---:|
| MRMP conversation | 960 | 77,425 | 64,551 |
| YJ complete captions, bucket 0 | 80,000 | 80,004 | 77,084 |
| YJ complete captions, bucket 1 | 48,632 | 48,632 | 47,299 |

Do not sum distinct-text counts across buckets or sources as novel sentences.
MRMP uses CC BY-SA 4.0; YJ uses CC BY 4.0. No translations, images, image URLs,
audio, participant profiles or evaluations are included. All seven uploaded asset
sizes and SHA-256 digests matched; the manifest was also downloaded without
authentication. The full base and earlier supplement remain unchanged.

Whole-caption selection compared **every original occurrence ID** with native
admission, requiring all fragments of each retained caption to pass. It retained
128,632 complete works / 128,636 occurrences, with two exact assistant-reviewed
wording/typo cases withheld whole. Original source text is never repaired.
`qualification.json` records the selection policy and counts; the two buckets
keep each normalized manifest below 4 MiB. Imported occurrences remain unreviewed;
predicate checks and assistant inspection are not native-speaker certification.

The final compressed offline consumer import is qualified: **184,036 novel
eligible texts** relative to the already verified 2,038,328-text candidate.
All **187,268** input native analyses were reused; no new native calls or serving
indexes were required for this final pass. Its **553,922,560 bytes** are an
intermediate import, not the increase in final serving size. The previous full
candidate verification remains valid and must not be repeated. Public source
publication does not activate the private search preview.

The next Wikipedia cohort is **running**, using cached 2026-10-01 inputs,
routing v2 and quality v7, with up to 34,000 selected pages before excluding the
previous cohort. Page quotas are not sentence counts or quality approval.
Native/quality qualification and final combined serving-size measurement follow.
One worker / 0.25 CPU holds the Linux producer lock; no new snapshot is downloaded.
The private resume index binds the exact container, frozen recipe and receipts.

## Earlier pass: Wikipedia/pairs and seven source additions published

The [November 3 supplemental release](https://github.com/ManabiIO/manabi-sentence-db/releases/tag/corpus-additions-2026-11-03)
is public. Its seven normalized-v2 ZIPs total **181,031,342 compressed bytes** and
contain **505,768 sentence occurrences**, before cross-source deduplication and
consumer quality/content admission. It supplements the October 24 full base;
that base remains GitHub's latest full-corpus release for existing consumers.

| Archive group | Works | Occurrences | Distinct texts within archive | Translations |
|---|---:|---:|---:|---:|
| Kyoto Wikipedia, final checked pairs | 14,094 | 288,201 | 282,624 | 288,201 |
| Modern Wikipedia sample, quality v7 | 11,489 | 187,313 | 185,937 | 0 |
| ASDC and TALPCo | 1,582 | 9,994 | 6,409 | 1,372 |
| ALT parallel news | 1,882 | 14,696 | 14,693 | 14,696 |
| JEC basic examples | 4,733 | 4,733 | 4,733 | 9,466 |
| Global Voices reviewed article | 1 | 25 | 25 | 0 |
| Storybooks CC BY subsets | 29 | 806 | 800 | 0 |

Do not sum distinct-text counts as global novel Japanese texts. Every archive
embeds work/occurrence/translation rights, snapshot identity and extraction
metadata. `additions.json` records exact byte/member hashes and build IDs;
`SHA256SUMS` covers every download. All ten uploaded asset sizes and GitHub SHA-256
digests matched staging, and an unauthenticated manifest download was verified.
Completed canonical qualification was reused; no native/serving artifact, private
caption text, image, audio or mixed-license raw research snapshot was published.
This source publication does not activate the private search preview.

Docker was subsequently reopened with Alex's explicit “Go”. The completed
conversation/caption batch and running Wikipedia cohort above supersede earlier
prepared-job statuses. No second full serving database is being built. Reuse the
qualified imports and Storybooks native analyses in the next substantial serving
batch; do not repeat completed combined verification or duplicate running jobs.

## Earlier pass: v7 applied; combined candidate verified

Admission v7 refinement **completed**. It checked every v6 occurrence, removed
exactly the two demonstrated condition/reference fragments, and verified all
retained fields. Canonical result: **11,502 works / 187,435 occurrences**, build
`build_950cab3200041bfd04e49738d1e47059`.

The current new-work transport has **11,489 works / 187,313 occurrences /
185,937 distinct texts**: **43,650,322 bytes**, SHA-256
`085d727938a93bd0dfa142170b3847dbae09cc56167cb301d29cfa135cf3d3c0`.
There are 779 parent-shared texts and 185,158 absent from the parent before
warning eligibility/final admission. These supersede the v6 input counts below.

Consumer compilation completed as an explicitly offline compressed import,
**515,584,000 bytes**, SHA-256
`16d3f4f2b2e1f44d599f47b4f9239e2195b8fc71a079db0b6c65bf1081b7d4cc`.
All 185,937 exact-text native analyses were reused with zero new sentence
analyses, record-dictionary training calls or per-source search-index builds.
Full logical-record verification passed. This intermediate is deliberately
unserveable; actual postings are verified in the final combined candidate.

The downstream combined compact SQLite v11 candidate **completed full
verification** with the qualified Wikipedia, corrected ALT/Global Voices and
ASDC/TALPCo inputs. It contains **2,038,328 distinct texts from 19 sources** and
occupies **7,367,065,600 bytes including indexes and metadata**, below the 8 GB
target / 10 GB ceiling. All logical records, expected/actual postings and ranks
were checked. Reuse this verification; do not repeat extraction or native
analysis for unchanged inputs. The private resume index binds the exact
terminal job, producer/runtime identities and complete receipt.

The combined import selected 13,072 added works and 1,882 ALT replacements;
these are work counts, not novel text counts. Its caption-policy preflight fix
preserves the parent's identity for verified non-caption additions and rejects
mismatched caption imports. All 330 compatibility tests passed before the build.

**Not yet active in the private preview.** The canonical additions were published
in the supplemental release above. Ranked-query review found dictionary-boundary
false positives and competing causative/name interpretations; request-side fixes
subsequently passed 375 tests and actual-candidate integration checks. Source quality still varies: specialist prose, directory
fragments and publisher typos are not resolved by integrity verification.
Assistant-only development checks are not human/native-speaker certification.
The October 24 base remains the latest full-corpus download; the November 3
supplement adds the qualified canonical assets and refinement lineage. Do not
distribute private serving artifacts as public source data.

Storybooks Japan's canonical v2 supplement is also qualified: **29 works / 806
occurrences / 800 distinct texts**, with licenses separated into CC BY 3.0 and
4.0 subsets. Eleven NC works and six exact malformed pages are excluded. Its
compressed consumer import has **788 novel eligible texts** relative to the
combined candidate. Retain its reusable native analyses for the next worthwhile
source batch; a full serving rebuild just for this small supplement is deferred.

## Earlier completed pass: Wikipedia admission v6

[PR #54](https://github.com/ManabiIO/manabi-sentence-db/pull/54) is merged at
`c528c363a4f81f8a11c20cf5f9a17eeaf1878be2`. All 1,191 tests, Ruff and PR CI
passed. It tightens demonstrated formula/list remnants and the existing
multi-term specialist screen, with retention controls for valid parenthetical
copulas, simple scientific prose, named relations and inline lists.

An assistant-only development review inspected 274 distinct prepared examples.
It separates nominal prose, context dependence and specialist detail; it is not
a human/native review, an untouched holdout or a population quality estimate.
The whole v5 input comparison removes 285 of 187,722 occurrences: 281 dependent
fragments and four specialist-density cases. Every draft removal was inspected;
the final 66 additional removals are exact bare-copula remnants. Broader nominal,
context and specialist admission questions remain. Do not apply the caption
predicate wholesale to Wikipedia.

The v6 compressed refinement **completed**: 11,502 works / 187,437 occurrences.
Every retained record was compared exactly with its expected parent record,
including text, identifiers, rights, translations and original ordinal gaps.
The new-work export contains **11,489 works / 187,315 occurrences / 185,939 distinct
texts**. These are incoming texts, not necessarily novel eligible additions.

- Canonical build: `build_36f0353495a0eafa791094b59d0b8b78`.
- New-work ZIP: **43,646,049 bytes**, SHA-256
  `ab10e808b3702e089e833f675468903d97a33a1c281ec56623bd1195678c2a13`.
- Frozen implementation: `64a001c8c4fcef2039b50fd1208edd5aea51dde6`.

Native analysis **completed** for all **185,939** distinct input texts, with
sentence records individually Zstandard-compressed in a **284,975,104-byte**
offline cache. It reused 779 exact texts from the pinned active parent and
72 compatible prior-pilot analyses. There are therefore **185,160 incoming texts
absent from that parent**, before warning eligibility and final admission.
This replaces the historical v5 novelty counts below for the current input.

The compact SQLite v11 Wikipedia import index **completed**, at **681,820,160
bytes including indexes and metadata**. It reused all 185,939 analyses and the
pinned serving parent's record dictionaries, with zero repeated native sentence
analyses or record-dictionary training calls. Full record, rights, membership,
ranked/literal-posting and projection verification passed, alongside four exact
phrase controls and **141,285 missing/ineligible-context-neighbor checks**.
These are standalone-addition size/integrity results, not the combined serving
size or a semantic quality certification. Eighteen real queries were captured;
their review found remaining parser ambiguities and nominal/dense prose.

Use the private resume index below for exact artifact/report identities and
query-correction evidence. Reuse completed verification rather than rebuilding
this index to establish the same facts. Combined deduplication, final admission,
ranked quality and the full serving-size budget remain gates. No new corpus or
runtime has been activated. The offline analysis cache is not a second serving
engine. The v5 input below is historical evidence; no raw dump was reacquired.

A further 75-example assistant development inspection identified two residual
whole fragments: `の下に考える。` and `（例えば 参照）。`. Admission v7 in
[PR #57](https://github.com/ManabiIO/manabi-sentence-db/pull/57) rejects these
shapes with controls for complete named conditions, references and quotations.
All 1,203 tests and Ruff passed. The frozen v6 artifacts above retain their
original policy: apply one-way v7 refinement before final admission, reusing
compatible exact-text analyses. Consumer-index qualification on the v6 input
does not certify that the newer admission policy has already been applied.

## Wikipedia: reuse the completed inputs

| Stage | Completed result | Still required |
|---|---|---|
| Cached acquisition | Japanese Wikipedia 2026-10-01 full snapshot already downloaded | No new acquisition for this expansion |
| Balanced metadata selection | 1,520,837 pages scanned; 12,000 selected | No repeat metadata scan |
| Extraction, text v10 / Wikipedia quality v4 | 11,505 works; 187,790 occurrences | Superseded by the completed v5 refinement below |
| Compressed canonical refinement, quality v5 | 11,504 works; 187,722 occurrences; 68 further fragments and one empty work removed | Quality review of remaining examples |
| New-work normalized export | 11,491 previously absent works; 187,600 occurrences; 43,666,975-byte ZIP | Native qualification and final serving-size measurement |
| Exact text comparison with the pinned serving parent | 186,050 distinct incoming texts; 793 shared; 185,257 absent from parent | This is not final admission approval |
| Existing content-warning eligibility applied | 184,573 novel eligible texts; 792 shared eligible texts | Readability, context and specialist-density decisions remain |

The selection used metadata policy v1. Future sampling uses v2, which corrects
school/computing-language allocation. The frozen v1 allowlist remains valid; do
not rescan merely to change its label. Metadata topics are not quality ratings.

Reusable identity bindings:

- Snapshot ID: `568d86489a4548dd848d6e703bb14e3948d612d79e6b5bbaf65512a1c7f721c0`.
- Selection file SHA-256: `fa5d743c12400e64657adabc5e0527eab49fa542558e8bb430c76a47a857c16c`.
- Refined canonical build: `build_0f6836959fb7d1e43903a60fba657371`.
- New-work ZIP SHA-256: `c3e4821905a12f5d0ef70e94455cf4c7aa2866ab81dbfe6480691d6acaaa67ff`.
- Refinement producer: `4a37bc6d3de6c63c0211e98fb0c71bcef197354b`.
- Subsequent normalized-SQLite lineage fix: `49f680f95cc1cf62c1d91a094a1cde7183347e48`
  ([PR #52](https://github.com/ManabiIO/manabi-sentence-db/pull/52));
  1,157 public tests, Ruff, 21 source configurations and main CI passed.

The completed archive predates PR #52's additive normalized-manifest provenance
inventory. It retains both catalogs and is supported. That metadata-only fix is
not a reason to redo Wikipedia acquisition, selection or extraction. If a new
release needs the newer exporter, re-export the verified canonical build.

## Other prepared additions

- ASDC and TALPCo: full source/native qualification completed, including seven
  indexed TALPCo phrase controls and all 1,372 independent-context checks.
  ASDC adds 4,916 novel eligible texts; TALPCo adds 778 and provides human English
  translations for 593 shared eligible texts. Counts across sources must not be
  summed without cross-source deduplication. These sources are not active yet.
- Corrected ALT and one reviewed Global Voices work: qualified compressed import
  input exists. Reuse its exact native analyses; do not repeat source acquisition.
- SNOW: corrected download locations and publisher evidence are documented in
  [sources.md](sources.md#snow-simplified-japanese-acquisition-recheck-2026-10-31).
  No full workbook acquisition or admission. Rewrite quality and inherited
  attribution remain gates; English generation remains unknown.

## Resume without repeating completed verification

On the development Mac, the sibling integration checkout's
`docs/sentence-corpus-progress.md` is the authoritative local resume index. It
records absolute artifact locations, hashes of completion reports, frozen
commands, terminal job status, the exact serving-parent identity, superseded
failed runs and the next uncompleted checks. Its historical evaluation document
contains the longer audit trail. Those private integration details are not
part of this public corpus repository.

Reuse evidence when its input, output and producer identities still match.
Perform lightweight identity/hash checks when consuming an artifact; repeat
expensive verification only for changed inputs/code, corruption, missing
evidence, or an uncovered requirement. A successful extraction or checksum does
not establish learner quality, human review, retrieval correctness or serving
size. Preserve those remaining gates.

V7 admission, compatible native reuse, combined full verification, query
qualification and both supplemental source publications are complete. Next work
is larger-Wikipedia qualification and a size-budgeted combined serving refresh.
No new preview activation has occurred. Do not repeat completed verification.
