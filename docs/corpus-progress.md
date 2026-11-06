# Corpus expansion checkpoint — 2026-11-06

This is the current pipeline checkpoint and supersedes historical running/queued
statements below. Generated corpus text and detailed evidence stay outside Git.

## Latest: v15 source review accepted; native import started

The v15 refinement completed all **16 archives / 113,772 works / 1,673,361
occurrences / 401,886,418 compressed ZIP bytes**. Its per-archive sentence sum is
**1,656,009**, not globally distinct texts or net consumer growth. Completion
receipt SHA-256: `d4393448ee8f3583df8e1ee56a5e71001a873f58e97f4ae363f1aaa70bee6b33`.
Do not repeat source acquisition, selection or completed refinement to resume.

The pass rejected **202 occurrences**: 113 dependent fragments/navigation rows,
83 malformed-punctuation occurrences, five exact reviewed-wording occurrences
and one dense specialist occurrence. All **200 sampled omission examples** were
read and their exclusions judged justified. Repeated text and the per-reason
sample cap mean this is not individual review of every rejected occurrence.

The same-seed retained review preserved **90 identical previously reviewed
text/citation records** and replaced exactly the ten flagged v14 cases. Two
assistants independently retained all ten replacements. This is explicitly
assistant-only review, not human/native-speaker certification or an estimate of
whole-corpus quality. Advanced and context-dependent grammatical prose remains
eligible. Final review packet SHA-256:
`f436b501dcd800d9a7a95058e02129ffc32adb53ab732d66c8aeaa20b2f852fd`.

The accepted source passed the downstream import's evidence preflight. Native
import has started with current-analysis/checkpoint reuse, a read-only current
corpus and an explicit **6 GB compiled-import cap**. The existing **1,694-test
public Linux** and **94-test downstream native-phase** evidence is reused for
unchanged inputs; a separate minimal-runtime compatibility check also passed.
No completed imported count, final serving size, consumer activation, new public
release or production deployment is claimed. Measure actual imported/checkpoint
storage and fresh capacity before separately admitting the combined rebuild.
The active local consumer remains **2,597,508 texts / 7,626,911,744 bytes**.

## Parallel source preparation: second Global Voices work

The explicit per-work adapter now also accepts `globalvoices-65886-ja`, with
fresh Japanese/English rights evidence and a hash-pinned 30-block inventory.
Assistant review selected **13 paragraphs**; the compressed pipeline produced
**23 sentences**, with **17 context gaps**, no translations and complete credit.
The normalized ZIP is **15,358 bytes**, SHA-256
`673e9bee1e6154b607b29079c1f13ff8837c5560078254ab8f390a5a49169cba`.
This is a prepared source supplement, not net consumer growth or a public release.

The cached snapshot/build path ran with network requests disabled. **91 focused
host tests** passed across both works, snapshot handling and transport restrictions;
source configuration validation and Ruff passed. The frozen ongoing Wikipedia
import remains unchanged. Review and source-policy details are in
[sources.md](sources.md#additional-reviewed-work-65886--2026-11-06).

## Next-source investigation: Rosebleu inventory completed

The pinned publisher inventory is complete: **1,805 JSONL chapter occurrences /
1,706 distinct Git blobs** across ten titles. A **276-row, three-chapter**
assistant-only pilot found that unmarked chapters still contain sexualized
material and quality defects missed by the current lexical gate. No chapter or
sentence is admitted. Reuse the completed inventory and compressed sample;
prioritize a specifically reviewed clean subset before bulk acquisition or Apache
license support. See [the findings and remaining license work](source-priorities.md#rosebleu-complete-inventory-and-bounded-text-pilot--2026-11-06).

## Next Wikipedia expansion: full-dump exclusions recovered

The 120,616-work normalized inventory covers only the November 4 further-source
release, not the full cached dump. Its first growth selection plus today's v15
batch consume that normalized reserve. Additional substantial growth should use
previously unselected articles from the existing October 1 raw snapshot; there
is no need to acquire another dump.

The full-dump metadata index's recorded historical path is absent, and bounded
checks of this checkout, current experiment roots, nearby project directories,
Trash and named Docker volumes did not recover it. This does not prove that no
copy exists elsewhere. Do not silently relabel a newly rebuilt index as the old
verified artifact. Keep a replacement in a durable data directory, separately
from disposable experiment output, and serialize its raw scan behind the live
native import/refresh work.

Recovered release catalogs provide the exact four disjoint prior page selections:
**12,000 + 27,829 + 131,147 + 127,197 = 298,173 page IDs**. The union passes the
existing snapshot/source selection validator against snapshot
`568d86489a4548dd848d6e703bb14e3948d612d79e6b5bbaf65512a1c7f721c0`.
This includes selected pages later rejected by source processing; it is not an
accepted-work count or a count of eligible remaining pages. Union file SHA-256:
`05c589f2d189c7729646c5d5cabbfd0db90a62b7b0754d5259f6a9a622b7725f`.

Three remote ZIP catalogs/manifests were recovered using exact HTTP ranges,
stable per-asset ETags, bounded response sizes, ZIP CRC checks and available
refinement-catalog hashes; the fourth came from the retained local release.
Only **949,785 network bytes** were read, with no sentence members and no whole
archive download or whole-archive verification. Source metadata and range receipts
are retained under `data/research/wikipedia-selection-recovery-20261106/`; the
validated union and its input hashes are under
`data/research/wikipedia-cohort-exclusions-20261001/` (generated data, not Git).

`index-wikimedia --max-index-bytes` now supports an explicit SQLite file cap.
The page allocator prevents growth beyond the cap, rounded down to whole pages;
invalid budgets fail before source hashing. Failure cannot publish a completion
manifest. **120 focused host tests** and Ruff pass, including real cap exhaustion
and unchanged selected IDs. This is not a completed replacement index or Linux
full-source qualification. Before the next guarded scan, check actual available
host/container disk space, run the bounded Linux fixture, and bind the code,
raw snapshot and recovered exclusion hashes. Then select disjoint whole-work
chunks and apply the current quality/rights gates; do not guess usable yield by
subtracting selected pages from the historical 1.52-million-page scan count.

## Earlier: v14 export complete; v15 and in-pass omission reviews qualified

The v14 successor completed all 16 archives: **113,772 works / 1,673,563
occurrences / 401,924,558 compressed ZIP bytes**. Its per-archive sentence sum is
**1,656,210**, not distinct/net growth. Two assistants inspected the fresh
100-example packet. Ten findings warrant follow-up: isolated wording/glyph/date
defects, retained citation/caption/publication labels, article scaffolding,
duplicate terminal punctuation and one concentrated specialist passage.
Other demanding or context-dependent prose remains eligible.

Policy **v15** uses seven exact-text exclusions, two narrow structural rules and
the existing distinct-term density threshold for additional biology vocabulary.
It does not rewrite source text or create broad topic/nominal-predicate bans.
The public Linux suite passed **1,694 tests**, and Ruff passed.

Refinement can now emit an attributed compressed omission sidecar during its
existing JSONL passes. Regression coverage proves unchanged corpus bytes and no
extra JSONL passes when sampling is enabled. Sidecars bind the input/output ZIPs,
policy and implementation, retain original rights, and enforce memory bounds.
See the [sidecar contract](normalized-format.md#omission-review-sidecars).

Next: apply v15 to the completed compressed v14 outputs with omission sampling,
inspect omissions and the replacement examples under the **same** survivor-review
seed, then decide native admission. Reuse earlier reviewed survivors by matching
text/citation identity. No native admission, activation or production deployment
of this larger batch has occurred; the accepted local corpus is unchanged.

## Earlier: first expansion accepted; larger compressed export completed

The first growth batch completed full validation and independent preservation
checks. The downstream local consumer now contains **2,597,508 texts**, a net
addition of **106,432**, in **7,626,911,744 bytes** including indexes/metadata.
These are consumer counts, not a new public release. Existing sentence, work,
occurrence, translation, analysis and word records were preserved. The local
preview passed HTTP search checks, and its superseded dataset was retired.
No production deployment or hosted runner was started.

The accepted consumer was reconciled with the cached Wikipedia inventory:
**113,773 additional whole articles**, organized into **12 topic-balanced
chunks**, with **1,673,639 cached-v11 occurrence candidates**. This is neither a
distinct-text count nor an admission count. The grouped export completed successfully after selecting
from each of the16 existing source archives once and applying the current v12
quality policy directly. It retains **113,773 works /1,673,619 occurrences** in
**401,931,611 compressed ZIP bytes**. The per-archive sentence-count sum is
1,656,264; global deduplication and net/eligible growth are still pending. Retained text remains in compressed ZIPs; per-stage
checksums bind source files, whole-work selections and transform code. No source
redownload, native sentence analysis or serving refresh is part of this export.

The relevant selector, refinement, review and cohort tools passed **344 focused
Linux tests** with native schema validation. The large export requires that
backend and uses the existing single-worker lease at0.25 CPU/1GiB. Fresh attributed
review packets follow export, with explicit assistant-only/unreviewed status.
Reuse completed selection/refinement receipts; do not replay the previous
successful consumer build or rerun source extraction.

## Fresh review: quality follow-ups before larger admission

The completed, hash-bound review packet contains **100 examples**, twenty each
from five routed topics. Two assistants read every example. This is development
inspection, not human/native-speaker certification or a population quality
estimate. Fifteen examples were flagged for follow-up: detached event/statistical
labels, article scaffolding, missing-formula references, specialist density and
code-heavy descriptions. Context-dependent prose and valid nominal predicates
are not automatically rejected. Metadata topics are coarse: a medical article
can route to culture through a secondary category. They are not quality labels.

Policy **v13** adds narrow whole-sentence guards for missing following relations
and reference-only promises to discuss a topic later. Inline explanations,
quoted mentions, numerical bounds and substantive prose are preserved. The
completed v12 export remains intact and **is not approved for native admission**.
Do not relabel it as v13 or repeat extraction. Next: measure the successor
policy's full omission delta against those compressed exports, inspect omissions
and fresh replacement samples, and resolve remaining fragment/density findings.
Then qualify the resumable native producer with explicit measured disk budgets.
The active local corpus remains unchanged. Focused quality/refinement validation:
**292 tests passed**, plus Ruff and whitespace checks. On the existing review
sample, v13 removes exactly the two targeted reference fragments; this is not
a full-export omission measurement.

The follow-up **v14** candidate addresses statistical rows, article naming
scaffolding, format/abbreviation labels and four uncovered specialist vocabulary
clusters. It retains the existing requirement for three distinct specialist
terms plus structural density. No article-topic bans or new exact-text exclusions
were added. In the development sample it addresses ten of the fifteen flagged
cases. The other five remain eligible on reconsideration: terse nominal narration,
a complete rounding explanation, a fictional synopsis and a route comparison
do not justify broad exclusions of names, nominal predicates or numerical prose.

Validation passed **327 focused host tests**, Ruff and **260 Linux policy tests**.
A frozen, locked, read-only scan compared all **1,656,264 per-archive sentence
records** against v12 and v14. It found **54 new exclusions: 49 dependent
fragments and five dense specialist records**. All 25 sampled omissions were
read and judged justified by an assistant. The sample remains compressed; this
is not human review or a global distinct-count measurement. Refinement is
approved; native admission still requires survivor/replacement review. The initial Linux wrapper omitted a
source-manifest fixture and failed before scanning; a fresh corrected wrapper
passed. No acquisition, extraction or native analysis is repeated.

## Current growth policy: add good licensed sentences; size target is movable

Alex clarified on2026-11-06 that good, properly licensed sentences should be
added. Historical8GB target /10GB hard-ceiling language below is superseded.
Use measured whole-artifact and temporary-space budgets, compression, compatible
caches and prompt retirement of superseded outputs to prevent runaway storage.
Do not withhold worthwhile sentences solely to meet an arbitrary file-size target.
Licensing, provenance and quality checks still govern admission. The completed
candidate fit its existing7.8GB job limit at7.627GB; no
rebuild or repeated analysis is needed. Additional clean Wikipedia cohorts should
reuse the verified metadata inventory and source bytes, with quality/cost review,
rather than treating the earlier150,000-text planning cap as a permanent limit.

## Earlier growth checkpoint: native import complete, combined refresh running

The normalized sentence-refinement tool is merged in **PR #64**, followed by
the narrow terminal-comma cutoff policy **v12 / PR #65**. Full normalized-tool
Linux suite: **1,525 passed**; host **1,524 passed / 1 expected skip**. Full v12
policy suite: **1,532 passed on both Linux and macOS**. These were local checks;
no hosted qualification or production deployment was requested.

A fresh metadata inventory of the16 existing Wikipedia release ZIPs found
120,607 novel article IDs. The mixed whole-work selection contains **6,833
articles**. Applying v11 and then v12 directly to their compressed normalized
ZIPs retains **108,855 occurrences /38,685,573 ZIP bytes**, preserving every
retained text, public ID, license, attribution, snapshot and context gap.
Per-archive sentence counts include shared IDs and cannot be summed as distinct
corpus growth. The v11 inventory counted108,242 selected distinct texts,106,899
absent from the current consumer; v12 removes one sentence before native
eligibility. Final eligible/net growth and combined artifact size remain pending.

An assistant read all110 newly sampled examples (ten per routed topic), confirmed
109 unchanged survivors, read the fresh replacement and the single v12 omission.
Two initially questioned location/topic usages were retained on reconsideration.
This is development inspection, not human/native-speaker review or a held-out
quality estimate; records remain unreviewed. Nominal/context-dependent and other
technical/historical prose can remain. No invented translations or source wording
repairs were introduced.

**Native admission and combined consumer refresh are RUNNING**, with one actual
Linux producer lease,0.25CPU /1GiB, reusable native-analysis checkpoint, unchanged
current consumer and a **7.8 GB candidate limit**. It imports the selected v12
ZIPs and refreshes one combined candidate directly, preserving existing prepared
words/codecs and attaching exact normalized transformation/archive receipts.
Native import is complete: **108,241 distinct texts /107,775 eligible texts**,
**299,413,504 compressed bytes**. It reused1,343 current analyses and4,869 cached
analyses, saving102,029 new checkpoint analyses. Word-link preparation and provenance import are
complete. The **working** candidate has **2,597,508 texts /106,432 net growth**
after pruning ineligible-only additions. Display projections and all three ranked
indexes are built; sentence and expected-posting validation is running. At
16:59 UTC it had checked 318,464 of 2,597,508 sentence records. The producer
remains live with no restart or OOM; its final report does not yet exist.
These are provisional counts pending full output validation, final size and exit0.
Observed RSS is576,764 KiB and charged peak reached the1GiB limit. The job has not OOMed, but this establishes no memory headroom claim. The
existing **2,491,076-text /7.075 GB** consumer remains active until the replacement
passes full output/native-query/HTTP validation. No larger consumer activation,
new public source release or production deployment has yet occurred.

Reuse the complete released-archive/member verification and derived metadata
inventory rather than scanning raw Wikipedia again. The first inventory's SQLite
sort exhausted128MiB tmpfs after all16 streams committed; recovery explicitly
used native scratch and reused those committed receipts. No archive scan or
baseline extraction/analysis was repeated. Current selections, source refinement
and all quality evidence remain separately bound for reproducible continuation.

## Next Wikipedia expansion: remaining cached whole articles

The verified metadata inventory contains 120,607 article IDs absent from its
original baseline. After the current 6,833-article selection, at most **113,774
unselected articles** remain. This is an opportunity count, not an accepted
sentence count. Reconcile against the newly accepted consumer before choosing
another cohort: the inventory's stored `existing` flags refer to an older corpus.

Reuse the 16 cached November 4 normalized archives and their verification
receipts. Order remaining works by the existing deterministic priority within
each topic, interleave topic queues, and split work only for resource-bounded
processing. Keep whole articles and apply current v12 refinement directly to
these released archives; cached v11 retained counts are estimates. Do not impose
another permanent article or sentence quota, or rerun the inventory's original
quota-bound construction scripts.

Fresh topic-spanning assistant review and demonstrated-failure checks precede
admission; routing topics do not establish quality. Preserve original wording,
rights, attribution, revision history and context gaps. Reuse exact-text analysis
checkpoints, measure eligible net additions and complete-artifact/scratch costs,
and choose an explicit budget before a combined refresh. This next cohort is
**not extracted, admitted or active yet**. The current producer owns the heavy
worker lease; do not start another producer while it validates.

The reusable `plan-wikipedia-cohorts` CLI/Mise task now implements this metadata
planning step. It excludes accepted/prior work IDs, rotates topics deterministically,
keeps oversized articles intact and carries all remaining work into subsequent
chunks. Inputs use read-only transactions and stat/WAL receipts; prior selection
files have SHA-256 receipts. Independent review caught and fixed an exclusion
caused by stale inventory `existing` flags: current consumer and explicit prior
IDs now determine presence. **14 focused planner/selector CLI tests passed,
including 16 subtests; Ruff passed.** These are synthetic host checks. The planner
has not run against the real inventory yet; that requires the producer and install
leases after the current job finishes. See [operations.md](operations.md#plan-further-wikipedia-cohorts-without-reacquisition).

## Bounded review sampling for larger cohorts

The previous task-local review script kept every seen `(topic, sentence_id)` even
though it selected only ten examples per topic. The reusable `TopicReviewSampler`
now retains only sample metadata, with deterministic hash priorities and minimum
citation tie-breaking independent of input order. Rejected candidates compare
against a cached cutoff. **20 focused tests passed**, including comparison with
an independent full-sort reference under reordered/duplicate input; Ruff passed.

A synthetic 40,000-row stream containing 20,000 distinct IDs produced identical
100-candidate samples with and without the old global seen set. Python allocation
peak fell from **5,654,458 to 75,243 bytes**. CPU rose from **0.515 to 0.819 seconds**
because discarded duplicates are hashed again. This trades bounded CPU work for
memory independent of stream length; it is not a full-corpus speed benchmark.
Evidence is retained in `sentence-review-sampler-memory-f0kvlhlf/report.json`.
Use the helper for the next fresh review packet; the accepted earlier review and
running producer are unchanged. Cohorts divide review/selection work, not mandatory
whole-corpus rebuilds. Group accepted additions into a combined refresh and avoid
repeated source-archive decoding for compatible selections.

The bounded sampler is now connected to `review-normalized-topics` (CLI and Mise).
Its builder binds expected ZIP hashes, streams occurrence sampling, loads only
selected full work/sentence records and writes a deterministic checksummed Zstd
packet. Sampled text identities and rights are checked; input mutation, unknown
work topics, missing/duplicate selected records and unsafe output paths fail.
The packet records algorithm/seed/input hashes and is explicitly review-pending,
not human-reviewed. **39 focused builder/sampler/CLI tests passed; Ruff passed.**
This does not replace full validation of unsampled records or untouched members.
No existing source archives were rescanned and no accepted packet was regenerated.
Use it after the next selected archives have passed current refinement.
A follow-up binds the complete frozen work-to-topic mapping by canonical digest
and count, closing a missing sampling-input receipt. **19 affected builder/CLI
tests passed**, including reordered routing and caller-mutation regressions;
Ruff passed. No real review packet has yet been generated with this builder.

## Refinement selection-lineage guard

A follow-up review found that canonical exports also contain `work_selection`,
so that field alone cannot excuse stale refinement counts. A mismatch now needs
validated normalized-selection metadata, matching build/selection digest and
actual work IDs, nonincreasing record counts, and zero selected references.
**83 focused tests passed**, including valid refinement → selection → refinement
and nine invalid lineage cases; Ruff passed. Legacy unsigned selection receipts
establish structural plausibility, not exact ancestry or authenticity. The frozen
running producer and already verified source archives are unaffected; do not
rebuild them for this tooling guard.

## Latest consumer checkpoint: 2,491,076 texts active locally

The combined downstream compact SQLite v12 artifact is validated and active in
the local search preview: **2,491,076 distinct texts / 23 sources**, including
**218,927 VFD / 58,895 JMRD / 64,537 MRMP / 12,818 MASSIVE** memberships.
Wikipedia now has **295,796** source memberships, alongside **281,293** from the
human-translated Kyoto Wikipedia dataset. Memberships overlap and must not be
summed as distinct texts. Net growth is **452,748** against the verified build
parent and **642,234** against the replaced local preview.

The complete consumer artifact is now **7,075,229,696 bytes (7.08 GB)**,
including search indexes, metadata and word links. Integer provenance references
saved **2,094,817,280 bytes / 22.844%** against the same v11 corpus; every public
ID, attribution, translation, compressed payload, posting and prepared word
stream was preserved. The artifact is below the **8 GB** target and **10 GB**
hard ceiling. Bulk text remains compressed. This storage conversion adds no
sentences and is a local activation, not a new public release or production
deployment. The full converter and canonical-record/posting validation passed;
17 offline deterministic query controls agreed exactly. Ordinary time-budgeted
queries can select different bounded results; that report is retained separately.
The old serving file was retired to host Trash after successful HTTP checks.

The new **`mise run select-normalized-works`** command selects complete works
from published normalized ZIPs without repeating raw extraction. It binds the
exact original build ID and selection digest, streams and verifies all five
logical members, retains selected context/rights and copies provenance bytes.
Bulk staging stays compressed; SQLite holds identity/ownership fields only.
Linux qualification: **1,474 passed**; macOS: **1,473 passed / 1 expected skip**.
A real lineage fixture caught and fixed copying virtual ZIP parent directories.
The next Wikipedia admission first excludes current work IDs and measures a
mixed whole-article pilot before choosing a larger batch. No new admission has
yet been activated.

Completed build verification and real Linux queries were reused for activation;
no source downloads, native analyses or full verifier were repeated. Post-switch
HTTP checks passed for twelve API cases plus home/results pages. A request-only
compound fix rejects intervening lexical verbs (`買って帰ってきた` is not a
`買ってくる` match), preserving searches for the explicit longer compound.
Some compound retrieval remains time-budget limited. Assistant review covered
57 displayed query rows and four known bad controls; it is not native-speaker
review or a population precision/recall estimate. Specialist/nominal fragments
remain in older Wikipedia/Kyoto material; JLPT is a vocabulary estimate.

Reuse the published source releases and completion receipts below. Further
Wikipedia source material is already available; the consumer deliberately
admitted a balanced whole-article subset. Before another large serving batch,
measure index/metadata costs and available headroom; do not sacrifice query
correctness or reintroduce rejected source wording just to increase counts.

## Next Wikipedia cohort: cost pilot and v11 development review complete

Whole-work selection is merged in PR #62; quality v11 is merged in PR #63.
The release inventory found **120,607 novel work IDs / 120,616 total** against
the current consumer; these are article counts, not new eligible sentences.
A deterministic pilot selected **271 complete articles**, exported 15 verified
compressed ZIPs, and built **4,941 distinct texts / 4,916 eligible texts** into
compact v12. The final artifact is **19,730,432 bytes**, including all indexes,
metadata, record dictionaries and word links. Native memory peak was
**410,607,616 bytes**, elapsed **248.4s at 0.25 CPU / 1 GiB**. It reused 66
current analyses and saved 4,875 new analyses into the existing resumable native
checkpoint. Baseline extraction/analysis/validation was not repeated.

The assistant read 48 development examples and all six v11 removals: two
orphan fragments and four dense specialist passages. Linux full suite:
**1,493 passed**; host **1,492 passed / 1 expected skip**. See `sources.md` for
citations, retained counterexamples and limitations. This is not human review or
a held-out quality estimate. The published source release and active corpus
remain unchanged. Applying v11 still precedes a growth activation. Conservative
whole-work exclusion allowlists retain **265 works / 4,547 occurrences**; that
option also withholds acceptable neighboring sentences from the six articles.

Historical planning for the currently running batch: a balanced whole-work
cohort was tentatively capped at **150,000 new eligible sentences** and a
**7.8 GB** job budget. These are batch settings, superseded as permanent
corpus limits by the current growth policy above. The pilot's roughly 4 KB
per text includes fixed overhead and is only a planning observation. It does
not predict the exact size of another cohort or authorize an oversized artifact.
Reuse the verified release bytes, review/allowlist receipts and native analysis
checkpoint. No fresh Wikipedia acquisition is needed for this next batch.

## Published sources and completed admission preparation

**Serving-admission follow-up:** current refined VFD has **218,953 distinct
Japanese texts**, of which **215,007 are absent from the verified combined
consumer baseline**. Exact novelty uses an **18,726,912-byte IDs-only ledger**;
source text remains compressed. These are pre-admission novelty counts; actual
searchable growth is recorded in the current consumer checkpoint above. No
acquisition or extraction was repeated.

Whole-work consumer pilots are complete in the selected compact SQLite v11
format, including search indexes, metadata and word links: **1,950 JMRD texts /
7,315,456 bytes**, **9,027 MRMP / 22,794,240**, **511 complete YJ captions /
3,055,616**, and **820 VFD / 3,829,760**. Peak memory was **491,458,560 bytes**.
All 11,488 earlier-source analyses were reused; 784 new VFD analyses were saved
in a resumable native-filesystem checkpoint. Each standalone pilot includes
1,019,904 fixed dictionary/schema bytes, so its total size cannot be multiplied
directly into a reliable combined-corpus estimate. These short-text pilots kept
dictionary-free word frames through the normal compression-benefit gate.

Assistant inspection read **31 of 490 recorded query rows**, including both
compound-query matches. No sampled bare-`持つ` result was observed for
`持っていく`. This is neither population accuracy/recall nor a combined-source
diversity or production-latency measurement. All source occurrences stay
**unreviewed**. Conversation still includes colloquial/context-dependent turns;
VFD retains its image-context limitations and attribution.

**Full refined VFD native admission is complete:** **218,927 eligible texts**
from 218,953 distinct inputs, with all 277,242 works / 429,846 occurrences
preserved in the compressed non-serving import. The reusable import is
1,000,984,576 bytes; its analysis-only native checkpoint is 166,559,744 bytes.
It performed 213,945 additional analyses and reused 5,008, including the pilot.
The import took 1,777.01 seconds; peak charged memory reached the configured
1 GiB ceiling. All records, relationships, memberships and stored scores passed
logical import validation. These memberships are included in the active consumer
checkpoint above.

The completed combined consumer refresh includes full refined VFD, JMRD, MRMP,
MASSIVE and a balanced **6,951-whole-article Wikipedia subset / 109,995
occurrences** from the already-analyzed published v8 cohort. Source preparation
reused **all 232,073** selected Wikipedia/JMRD/MRMP sentence analyses, with no new
native calls. Eleven existing Wikipedia works are explicit replacements: their
source, revision, license and attribution match, ten retain identical text,
and the medical article omits two dense/context-dependent sentences under the
published quality policy. Both omissions were inspected by an assistant.

The serving candidate was built directly in Docker's native volume and
atomically renamed into place, avoiding a second full artifact transfer for
activation. Its final size, growth, verification and bounded query review are
recorded above. Production is unchanged. Keep all
published sources available even when a serving batch selects a subset. The
private consumer's resume index records exact artifacts and completion receipts;
do not repeat completed source verification, baseline verification or native
analyses.

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
