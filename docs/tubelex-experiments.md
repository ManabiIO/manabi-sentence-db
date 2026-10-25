# TUBELEX experiments and current tool research

Evaluated on October 24, 2026. Real captions remain in a private compressed
snapshot outside Git. No transcript excerpts, model weights or transcript-derived
indexes are distributed by this report.

## Inputs and method

Seven videos were selected from the pinned Japanese TUBELEX list, one each from
education, how-to, people/blogs, news, science/technology, gaming and entertainment:
`a2JH3bLpSTc`, `3s1thHo4gQw`, `2g-BGUPWq2U`, `9djOQ_cGSUg`, `0G1CpZnNpE4`,
`3kcaZDfrvWw`, `bfr6IYoL62k`.

They produced 33 caption streams and 12,888 normalized characters. Two tracks
had no terminal punctuation and mostly/exclusively zero cue gaps. Earlier logic
retained just 8.2% and 0% of their text. The independent-coverage implementation
indexes every normalized character, regardless of sentence predictions.

The layout/search study used 177 deterministic queries: common Japanese literals,
seeded source substrings of 1/2/3/4/8/16 characters, and negative probes. Explicit
cross-sentence probes were excluded. Every layout returned the same full reference
records, including order and limits. These are not representative learner logs.

Measurements used macOS ARM64 and Python 3.13.5. Query timings use warm OS caches,
one reader, and paired/interleaved repetitions. They establish neither full-corpus
scaling nor production/HTTP latency. Do not extrapolate storage from this small
sample, whose SQLite page and metadata overhead is substantial.

## Layout results

All figures below are physical sizes of the complete private SQLite artifact,
including compressed text and alignment/index data. Public reference exports are
separate. Source text is stored as Zstandard chunks.

| Chunk characters | Relational short postings | FTS-compressed short postings |
|---:|---:|---:|
| 1,024 | 460 KiB | 284 KiB |
| 2,048 | 372 KiB | 268 KiB |
| 4,096 | 336 KiB | 256 KiB |
| 8,192 | 332 KiB | 256 KiB |

Retained 4,096-character chunks with a 499-character overlap, sufficient for every
allowed query up to 500 characters. The larger chunk did not save space with the
compressed postings in this sample and raises the decode bound.

Short-query postings formerly occupied 143,360 bytes of the 344,064-byte artifact.
A contentless, position-free FTS5 index of encoded unigrams/bigrams reduced the
complete artifact to 262,144 bytes: **23.8% smaller**. The original UTF-8 trigram
candidate index remains position-free. Every candidate still undergoes literal
verification against private compressed text.

Profiling also found per-hit JSON Schema validation dominated materialization.
Reference construction now uses a narrow checked factory; full schema validation
remains at export/verification. Repeated playback envelopes are skipped before
hydration, and already-decoded candidate text is reused.

Schema v4 also moves weak source-text eligibility assessment entirely into the
build. Fixed 256-character tiles with 128 characters of surrounding context yield
packed eligibility bits. This keeps model segmentation from changing lexical
recall and removes repeated regex/delimiter scans from common-query retrieval.
All 75 tiles in this sample were eligible. Deep verification recomputes the bitmap
and stream lengths using bounded buffers, and rejects altered bits or padding.
The final sample artifact is **266,240 bytes (260 KiB)** including this metadata;
the 256 KiB layout table predates the stream-length field.

## Reader and recent SQLite experiments

The final schema-v4 comparison used 177 queries and five paired repetitions:

| Reader | Median query | p95 of per-query medians |
|---|---:|---:|
| Frozen implementation, new connection | 1.123 ms | 60.02 ms |
| Refined stdlib reader, new connection | 0.724 ms | 8.11 ms |
| Refined stdlib reader, reused connection prototype | 0.226 ms | 7.46 ms |
| Refined APSW reader, new connection | 0.488 ms | 11.30 ms |
| Refined APSW reader, reused connection prototype | 0.209 ms | 11.05 ms |

The stdlib linked SQLite 3.47.1. The newer comparison used
[APSW 3.54.1.0](https://rogerbinns.github.io/apsw/about.html), released in October
2026, carrying [SQLite 3.54.1](https://www.sqlite.org/chronology.html), released
October 16. All results were identical. APSW improved some medians but had worse
tails here, so it was not added as an application dependency. The standard reader
now has an explicit reusable `TubelexReader` API with deterministic cleanup.
The prototype table rechecked metadata per lookup; it is not a claim that its
exact timings describe every future serving integration.

The implemented `TubelexReader` API was then measured separately against the
one-shot helper, again with identical full results for all 177 queries over five
paired repetitions. Median query latency was 0.784 ms one-shot and 0.206 ms reused;
p95 was 8.35 ms and 8.43 ms respectively. The class validates its metadata once
on open and explicitly closes cursors and the connection.

A prior intermediate implementation assessed larger fixed source windows during
retrieval and regressed to 22.12 ms p95 one-shot. It was replaced by the offline
bitmap design above; those intermediate timings do not describe the final code.

## Recent sentence-boundary candidates

Recent releases and primary model cards were checked before downloading pinned
weights. All inference was local. Only character offsets were retained from model
outputs; no punctuation or generated text was inserted into the indexed source.

| Candidate | Release/update checked | Weight size | Inference over 12,888 characters | Held-out publisher-boundary proxy F1 |
|---|---|---:|---:|---:|
| [SaT 3L SM](https://huggingface.co/segment-any-text/sat-3l-sm), original ONNX | 2024 weights; wtpsplit 2.2.2 released Sep 25, 2026 | 428 MB | 25.82 s | 0.429 at published SM threshold 0.25 |
| [Hayamimi Japanese 4-class](https://huggingface.co/oboroge0/hayamimi-punct-ja-4class), int8 | Sep 16, 2026 | 37 MB | 0.34 s | 0.446 |
| [AstroNier Japanese character model](https://huggingface.co/AstroNier/japanese-punctuation-onnx), int8 | Sep 27, 2026 | 92 MB | 9.04 s | 0.552 |
| [Horizon punctuation small](https://huggingface.co/Horizon-Labs/punctuation-restoration-small), int8 | Oct 9, 2026 | 268 MB | 3.66 s | 0.465 |

Sizes use decimal MB. Inference excludes loading and used two CPU threads. Model
tokenizers/windowing differ: SaT used its 512-token, stride-64 inference; the
punctuation models used 400-token/character windows with 64-token/character
overlap. These are end-to-end tested configurations, not equal-compute architecture
comparisons. SaT's process peaked around 2.26 GB RSS; the Japanese character model
around 295 MB. Models are optional offline build tools and are not loaded by query
readers or downloaded to browsers.

The boundary proxy used 139 adjacent pairs of punctuation-complete publisher
sentences, each sentence at most 120 characters. Terminal punctuation was removed.
One how-to video supplied 47 calibration windows; the remaining 92 windows came
from different videos. Thresholds for the new punctuation candidates were selected
on calibration only. The SaT table reports the independently chosen upstream SM
default; its calibration-winning 0.025 threshold scored 0.358 on the held-out proxy.

**These figures are not human sentence-boundary accuracy.** Publisher punctuation
can itself omit true boundaries, adjacent windows are correlated, and genre shift
was substantial. An initial full-stream proxy was rejected because missing
publisher boundaries were incorrectly counted as model false positives. Even the
corrected proxy remains weak. Model cards' own FLEURS/FLORES/ASR scores are not
directly comparable to these captions.

The smallest model missed many boundaries and sometimes left long passages.
The character model was the most promising newer Japanese candidate on this
proxy; it was added as an optional local backend, preserving explicit punctuation.
No model became the automatic default. Source-preserving adapter parity was
checked across all 33 streams, and its complete build passed deep verification
with all 12,888 characters indexed.

### Reproducible model identities

- SaT: `segment-any-text/sat-3l-sm`, revision
  `137da054051ad9f1eac42025f758db4ac9f22535`.
- XLM-R tokenizer: `facebookAI/xlm-roberta-base`, revision
  `e73636d4f797dec63c3081bb6ed5c7b0bb3f2089`.
- Hayamimi: revision `226c5d4a461ed368264881fc3e6637cbeb68055e`.
- AstroNier: revision `89f8d70475328ff9b3e992696604845abd3257db`.
- Horizon: revision `ee31fdfc5304f876ea3b0dd72d30eda7e940b2b1`.

The isolated test environment used wtpsplit 2.2.2, ONNX Runtime 1.31.0,
transformers 4.57.6 and tokenizers 0.22.2. Runtime and weight/vocabulary identities
are recorded in model-backed build manifests. The wrapper specifies the threshold
explicitly: wtpsplit otherwise derives its default from the local directory name,
so renaming identical weights can change segmentation.

### Follow-up: September quantized SaT export

The September 18, 2026
[weight-only quantized SaT export](https://huggingface.co/jiangzhuo9357/sat-3l-sm-onnx)
was downloaded at revision `7698b9e41fef7a1e24638b9aaff2108ce1020657` and its
241,945,842-byte model verified against SHA-256
`1132546a16fa1aa9da218602049c6e7aeba0ec5b76409131446f40ebda2be99f`.
The published upstream config and existing pinned XLM-R tokenizer were reused.

It is **not a drop-in wtpsplit 2.2.2 model**: that wrapper hardcodes an fp16
attention mask, while this export expects fp32. A task-local experimental session
adapter fixed the mask type without changing installed dependencies or weights.
This compatibility shim is not part of the production builder.

In fresh, separate processes on the same 33 streams, both using two CPU threads,
batch size 8, stride 64 and threshold 0.25:

| SaT export | Weight bytes | Inference | Peak process RSS | Held-out proxy F1 |
|---|---:|---:|---:|---:|
| Published upstream ONNX | 427,756,189 | 17.46 s | 2.15 GB | 0.429 |
| September weight-only int8 | 241,945,842 | 19.71 s | 1.66 GB | 0.430 |

These are single-pass local measurements, excluding loading. The recent export
saved about 43% of weight storage and 23% of peak process memory, but did not
improve inference speed in this run. The tiny proxy-score change is not evidence
of better sentence detection. Splits matched on 30 of 33 streams, with three
internal boundary differences overall. No new backend or automatic default was added.
This follow-up also illustrates why newer exports need runtime and offset checks,
rather than adopting their model-card numbers directly.

The export author's [September benchmark](https://github.com/kizuna-ai-lab/sokuji/blob/main/docs/superpowers/notes/2026-09-14-asr-punctuation-benchmark.md)
reports much higher Japanese boundary F1 on different, partly handwritten inputs.
Its small per-language boundary counts, ASR-oriented reference construction and
browser runtimes make that a useful lead, not a directly comparable result for
these YouTube captions. The report also documents end-of-input boundary bias,
supporting the current adapter's right-context overlap and refusal to split at
an artificial window edge.

## Additional recent tools and the scale decision

Primary upstream sources were rechecked on October 24, 2026:

| Tool | Recent change verified | Fit for this pipeline |
|---|---|---|
| [wtpsplit 2.2.2](https://github.com/segment-any-text/wtpsplit/releases/tag/2.2.2) | Sep 25: `torch.compile` / optional NVIDIA AITune | Optional build-time acceleration for PyTorch/GPU setups; not measured here and not an ONNX optimization. |
| [wtpsplit 2.2.0](https://github.com/segment-any-text/wtpsplit/releases/tag/2.2.0) | Feb 26: length-constrained Viterbi/greedy splitting | Enforces character budgets, not true sentence boundaries or seconds. Supplying `max_length` ignores the usual probability threshold; do not silently enable it. |
| [yt-dlp 2026.10.21](https://github.com/yt-dlp/yt-dlp/releases/tag/2026.10.21) | Oct 21: updated YouTube extraction | Keep acquisition tools current and record the actual version. Snapshot reuse avoids extractor churn in rebuilds; no new acquisition was needed for these experiments. |
| [Qwen3-ForcedAligner-0.6B](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B) | Jan 29 release; June 26 native Transformers support in Qwen3-ASR | Supports Japanese text/audio alignment, but requires audio and substantial processing. Researched only; excluded from bulk builds. |
| [Silero VAD 6.2.3](https://github.com/snakers4/silero-vad/releases/tag/v6.2.3) | Sep 23; preceding 6.2.2 added offline ONNX sequence inference | Detects speech activity from audio, not grammatical sentences. Its VAD code is MIT; do not confuse it with separately licensed Silero speech products. No audio/VAD stage added. |
| [WhisperX 3.8.6](https://github.com/m-bain/whisperX/releases/tag/v3.8.6) | May 25 stable release; June 26 prerelease also inspected | Has a Japanese aligner, but also requires audio. Its [alignment code](https://github.com/m-bain/whisperX/blob/main/whisperx/alignment.py) can interpolate or fall back to original timestamps; outputs need confidence/provenance checks. Not installed or benchmarked here. |
| [BudouX](https://github.com/google/budoux) | Repository active Oct 23 | Predicts phrase boundaries for line wrapping; unsuitable as a sentence detector despite recent activity. |

**Do not force-align 100,000 videos.** The chosen bulk path uses existing manual
caption timestamps, source-preserving text segmentation and cue-envelope playback.
It neither downloads audio nor runs ASR. Optional sentence models process text
once during a build; the cheap punctuation/pause fallback remains the default.
A sentence starting inside a cue may produce a clip with neighboring words.
Accepting that honest imprecision avoids the acquisition, storage and compute
cost of corpus-wide audio alignment. No bulk alignment implementation was added.

The 30-second bound is a preferred playback-window duration, not a claimed
mid-sentence pause threshold. Search streams separate at caption gaps of at
least five seconds. Display gaps are not acoustic silence measurements.

The Qwen aligner identity checked was
`c7cbfc2048c462b0d63a45797104fc9db3ad62b7`; no weights/audio were downloaded.

## Earlier schema-v5 verification and reproduction evidence

The actual CLI built and deeply verified schema-v5 sidecars from the saved
snapshot for both the default policy and optional Japanese character model.
The default took 0.17 seconds; the Astro-backed build took 3.09 seconds at the
experiment's calibration-selected threshold 0.35. Those build times include
loading and indexing, but only unpunctuated remainders need model inference;
they are not comparable to the earlier whole-stream model timings. Both builds
retained all 12,888 characters, and 177 probes produced identical video sets.
Clip envelopes can differ; full-record parity is not asserted between models.
The complete offline suite passed 375 tests; Ruff, source/schema configuration
validation and tracked diff whitespace checks passed.

Private reproduction evidence is outside Git in
`~/.codex/experiments/tubelex-review-20261024-717bb2wd/`: revised model-window
reports, experiment scripts, verified default/model sidecars and reader timings.
The recent-tool comparison and pinned weight restoration recipe remain in
`~/.codex/experiments/tubelex-recency-20261024-7y4k69o4/`. The frozen comparator
and prior model identities remain in
`~/.codex/experiments/tubelex-comparison-20261024-dpo9_cdw/`. The original compressed
caption snapshot remains in `tubelex-refinement-20261024-6n3wansg/`. Reports contain
measurements/offsets, not transcript text. Disposable weights/caches can be moved
to Trash after recording their pinned restoration recipe.

## Follow-up correctness review

Six new regression cases first reproduced these problems and then passed after
the fixes:

- Returning speakers were joined across another speaker's intervening turn,
  creating searchable phrases nobody spoke consecutively. A speaker/region
  change now closes the previous turn, including when that voice returns later.
- Newlines and `<br>` could concatenate Latin words into a new word. Wrapped
  Latin letters/digits now retain a separating space, including accented and
  fullwidth Latin text and cue boundaries. Japanese wraps remain contiguous.
  Added spaces retain cue provenance; scrolling repeats retain both timing
  envelopes. This intentionally favors separate words when the layout is ambiguous.
- The optional character model previously committed predictions with no left
  context at interior window starts. Windows now divide ownership at the center
  of the overlap, providing 32 characters on both sides. A long synthetic probe
  also confirms that each intended boundary is owned exactly once.

Additional checks reject caption URLs for a different video and orphaned trigram
postings during deep verification. The acquisition cache policy changed to
`manual-ja-v3`. Private index schema v5 / processor v5 require rebuilding older
sidecars, reusing their existing compressed snapshots without network access.
Pause locations are computed lazily and reused across unpunctuated spans.

The actual Japanese model's raw segmentation changed in four of 33 source
streams. All 12,888 source characters survived unchanged; production builds also
preserved explicit publisher punctuation. Selected changed windows were inspected
privately. The 139-pair publisher-boundary proxy was unchanged (held-out F1 0.552),
but its pairs fit one model window, so it cannot validate seam quality. No human
accuracy improvement is claimed. The optional model remains opt-in.

With schema-v5 artifacts, 177 probes still returned identical **video sets** for
default versus model builds. The final five-repeat reader check measured 0.647 ms
median / 7.62 ms p95 one-shot, and 0.174 ms median / 7.15 ms p95 with the reusable
reader. All full results were equal between reader modes. These are separate warm
local runs, not proof of a speedup over the schema-v4 timing table or full-scale
performance. Default/model artifacts were respectively 266,240 and 262,144 bytes.

## Remaining qualification

Human review of a small Japanese boundary/playback sample is still needed to
judge clip quality; corpus-wide audio alignment is not a prerequisite or planned
build stage. Full-corpus, production HTTP and cold-I/O measurements, plus the
private Django/native-backend integration, remain separate work. The Linux and
small concurrency studies below qualify only their stated fixtures. The experiments
justify the measured local layout/reader refinements and opt-in model support;
they do not establish linguistic superiority over Massif.

## Synthetic scale, cancellation, recovery and Linux follow-up

No new YouTube material or audio was acquired. Deterministic Japanese fixtures
were generated directly into compressed private snapshots, with 16 cues per
synthetic video. The larger case had **10,000 videos, 160,000 cues/references and
7,826,147 normalized characters**. Its source JSON occupied 29,483,961 UTF-8 bytes
before compression and 6,152,369 bytes in the compressed snapshot. This is repetitive
synthetic text, not a representative estimate for 100,000 actual videos.

The initial build took 53.69 seconds and deep verification 36.94 seconds, with
about 85 MB peak macOS process RSS. The initial SQLite artifact was 42,532,864 bytes;
its compressed sentence payload was only 3,245,980 bytes. Alignment, sentence-unit
tables, candidate postings and unused pages accounted for the rest. “Index size”
therefore includes much more than sentence text, which remains compressed.

The scale fixture deliberately included shared query grams without the full
literal, a rare match in the final video, and a frequent string crossing explicit
sentence boundaries. Seven query classes were compared in five interleaved
repetitions against the saved pre-change reader, with full result-record parity:

| Probe | Before median | Refined median |
|---|---:|---:|
| Common two-character match, top 250 | 18.14 ms | 18.26 ms |
| One-character match, top 250 | 6.17 ms | 6.23 ms |
| Longer positive match, top 250 | 6.47 ms | 7.01 ms |
| Rare match in last video | 1.77 ms | 1.77 ms |
| Absent grams | 0.14 ms | 0.12 ms |
| Present grams, absent full literal | 73.79 ms | 74.99 ms |
| Cross-sentence negative | 1,337.86 ms | 322.88 ms |

The improvement comes from reading stored quote-aware boundaries once per
candidate chunk and rejecting crossing spans before per-hit reference hydration.
Ordinary positive lookups are broadly unchanged in this run. The default one-second
query budget separately bounds cooperative work in Python and SQLite; it raises an
explicit `QueryBudgetExceeded`, returning no partial results. A one-millisecond
probe stopped after about 1.25 ms. Deterministic tests also interrupt SQLite work,
confirm handler removal, prove reader reuse, and expire a query after it already
materialized a result. A budget error must not be presented as an empty match set.

### Compaction

The larger artifact contained 2,256 free 4 KiB pages after FTS merges and dropping
the temporary deduplication table. A disposable-copy `VACUUM` reduced it from
42,532,864 to **30,322,688 bytes (28.7% smaller)** in 0.50 seconds, with zero free
pages and identical query results. The builder now compacts before its final
completion metadata/checksums. A fresh production-path build of the 1,000-video
fixture passed deep verification and shrank from 4,124,672 to 3,084,288 bytes,
also with zero free pages and identical complete query records. Compaction uses
temporary disk space; it does not inflate sentence payloads into plaintext.
Separate Zstandard transport copies of the larger whole indexes were 9,667,721
bytes before compaction and 4,474,459 bytes after. These archive sizes differ
from both the live SQLite size and its embedded compressed sentence payload.

### Concurrent readers

The compacted larger artifact was tested with seven queries twice per worker,
including the expensive negative probes, with a one-second budget:

| Mode | Completed | Explicit budget errors | Whole mode wall time |
|---|---:|---:|---:|
| One thread | 14/14 | 0 | 0.86 s |
| Four threads | 48/56 | 8 | 5.20 s |
| Four processes | 56/56 | 0 | 1.29 s |

Every completed response matched the expected full-record digest. Four-thread
contention increased ordinary common-query median latency to 356 ms; separate
processes measured 23 ms for the same query. All eight thread-mode budget errors
were the cross-sentence negative probe, not partial successes. Worker startup is
included in whole-mode wall time, not individual query timers. These small local
tests favor bounded process workers for a future serving integration; they are
not an HTTP load test, capacity forecast or claim of production readiness.

### Linux and recovery

An existing Linux aarch64 image was run in a separate container with a read-only
repository, no network, two CPU limits and 2 GiB memory limit. It used Python
3.13.8 and SQLite 3.40.1, compared with host Python 3.13.5 / SQLite 3.47.1.
All seven synthetic probe digests and seven real-sample probe digests matched
the host. It read the macOS-built indexes and rebuilt the real compressed snapshot
offline, deeply verifying all 33 streams and 12,888 characters with identical
citation records. This checks format portability across those versions, not every
Linux architecture or ONNX backend.

The complete suite passed **406 tests on both macOS and Linux**. Ruff, all twelve
source/schema configurations, and tracked diff whitespace checks passed. New tests
cover malformed snapshot inventories, skipped-video entries, JSON encoding,
caption URL types/ports/video IDs, index identity metadata, cancellation and
compaction. An injected mid-build interruption left an unusable incomplete index;
a subsequent fresh-output build succeeded offline from the same snapshot and
left the base CC asset unchanged.

Reproduction scripts, the frozen baseline, source identities and measurement
reports are outside Git in `~/.codex/experiments/tubelex-scale-20261024-4t8s8zga/`.
Disposable synthetic databases may be regenerated and moved to Trash after the
essential scripts/reports are retained. Loose synthetic snapshots/databases were
moved to Trash; checksum-verified compressed index copies, source snapshots and
a restoration helper remain with the reports. The 1,000-video initial “common” probe
used `です`, which does not occur in that fixture; the larger study corrected it
to the present literal `ます` and supplies the comparison table above.

## Packed metadata, boundary-aware candidates and reusable model inference

That iteration used private **schema v6**. It replaced the relational punctuation
boundary table with canonical per-chunk bitmaps (at most 512 bytes) and stores
display-unit kinds as small integers. Original caption verification payloads,
cue timing and citation records retain their meaning. The index schema and
candidate-generation policy now enter the logical build identity.

On the same 10,000-video / 160,000-cue synthetic fixture:

| Layout | Live SQLite bytes |
|---|---:|
| Compacted schema v5 | 30,322,688 |
| Packed metadata, prior candidate policy | 21,196,800 |
| Packed metadata, boundary-aware candidate policy | **21,143,552** |

That is **30.3% smaller** than the already compacted baseline. The compressed
sentence payload remains 3,245,980 bytes; these are whole live-index sizes, not
compressed transport sizes. The normal builder produced and deeply verified the
final artifact, retaining all 7,826,147 characters and 160,000 references. It took
68.45 seconds to build and 41.45 seconds to verify in this run. Host load varied
substantially across runs, so those times are not a controlled ingestion-speed
comparison or a forecast for real 100,000-video corpora.

### Avoiding impossible candidate grams

Bitmaps reduced per-candidate boundary checking, but a stronger improvement was
to exclude cross-boundary grams at build time. Short-query terms come from inside
hard sentence spans only. Trigram input separates those spans with a control
character disallowed in queries; this affects only the private candidate index,
never original text or exported references. Soft timing/model boundaries remain
searchable. Quoted punctuation uses full-stream context, including quotes opening
before a storage chunk.

Seven query classes were compared over seven interleaved repetitions with full
record parity. The final candidate-policy comparison recorded these **process CPU
medians**, alongside wall times in the private report:

| Probe | Packed, prior candidate policy | Boundary-aware candidates |
|---|---:|---:|
| Common two-character match, top 250 | 16.54 ms | 19.37 ms |
| One-character match, top 250 | 6.19 ms | 5.94 ms |
| Longer positive match, top 250 | 6.19 ms | 5.53 ms |
| Rare match in last video | 1.64 ms | 1.83 ms |
| Absent grams | 0.085 ms | 0.069 ms |
| Present grams, absent literal | 82.50 ms | 79.12 ms |
| Cross-sentence negative | 134.23 ms | **0.127 ms** |

The last probe became an absent-term lookup, with 0.129 ms median wall time.
Regression tests confirm it no longer decompresses candidate text. This is a win
for that deliberately impossible phrase; other present-gram/absent-literal queries
still scan compressed candidates, and not every query improved. The earlier
schema-v5 reader used about 327 ms CPU for the same cross-sentence probe in the
separate packed-layout comparison. CPU time is reported here because competing
host work produced large wall-time variation; neither is a production HTTP SLA.
All larger-fixture probe digests also matched the original reader after a fresh
production-path build, not just an experimental database conversion.

### Reusing inference after interruptions and across index iterations

`build-tubelex --boundary-cache PRIVATE_DIRECTORY` optionally caches model boundary
offsets, with no transcript text in entries. Keys bind normalized text, processor,
model/vocabulary identity, threshold, window policy and runtime profile. Offset
checksums, strict ordering, source coverage and bounded compressed reads detect
corruption. Entries are installed atomically; paths/counters stay out of logical
build identity and public artifacts. Input/output/model directories cannot serve
as the cache, and the default non-model build rejects this option.

Two controlled pairs on the seven-video real sample followed import/kernel priming:

| Pair | Cold model inference: wall / CPU | Cached offsets: wall / CPU |
|---|---:|---:|
| 1 | 6.09 s / 7.04 s | 0.612 s / 0.332 s |
| 2 | 7.29 s / 7.22 s | 0.337 s / 0.331 s |

All four builds produced identical citation assets and build IDs. Each cold pass
recorded ten misses; each warm pass recorded ten hits. The same completed cache
was then reused after the candidate-index policy changed, with ten hits and no
inference misses in both final model builds. Local model loading and identity
checks still run. These small-sample timings are not a full-corpus throughput claim.

All 177 real-sample probes returned identical full default records between schema
v5 and v6, identical full records between cached/uncached model builds, and identical
video sets between default/model builds. The original 12,888 characters survived
unchanged. An injected second-video inference failure reused the completed first
entry on restart. Another test reused identical text across different videos while
preserving each video's original timing. Corrupt, oversized or mismatched cache
entries fail explicitly rather than silently changing predictions.

This provides reusable **inference**, not SQLite transaction checkpointing or a
new multi-shard serving layer. Acquisition batches still use their existing
offset/limit and compressed input cache. Completed model work can be shared
across sequential batches; index construction restarts into fresh directories.

### Final compatibility and reproduction checks

The complete suite passes **429 tests on macOS and Linux aarch64**. The networkless,
read-only-repository Linux container uses SQLite 3.40.1; host SQLite is 3.47.1.
The final packed/candidate-policy artifact and real sample produce identical probe
records on both platforms, and Linux can rebuild/deeply verify the real sample
offline. Tests cover bitmap corruption/padding, integer unit kinds, chunk-overlap
boundaries, quote context predating a chunk, absent cross-boundary grams, inference
reuse/cancellation, and private cache path separation. Ruff, configuration/schema
validation and diff whitespace checks also pass.

Evidence is outside Git at
`~/.codex/experiments/tubelex-packed-20261024-fafat0rz/`: baseline code, paired CPU
and wall-time reports, normal-build verification, model-cache studies and Linux
checks. Disposable synthetic snapshots and duplicate indexes were moved to
Trash after preserving the final compressed artifact bundle and reproduction notes.
The 8,551,721-byte private evidence bundle includes the index, compressed reference
export, both manifests and synthetic base identity asset. It was restored into a
fresh directory, deeply verified and searched before the disposable restored files
were also moved to Trash. This bundle size is not the live index size.
No additional YouTube download, ASR or audio alignment was used.

## Clip inventory, cue identifiers and Unicode audit

A subsequent correctness review found that probing only source-origin starts
omitted some suggested clips: a cue can begin in one sentence and contain the
start of another sentence with a distinct playback envelope. The exporter now
merges display-unit and origin starts, probes each distinct offset and retains
playback-ID deduplication. This inventories suggested clips, not every possible
envelope for a query crossing uncertain boundaries.

Rebuilding the same seven cached videos produced:

| Boundary mode | Previous clips | Corrected clips | Added | Removed / changed shared records |
|---|---:|---:|---:|---:|
| Default punctuation/pause | 394 | **410** | 16 | 0 / 0 |
| Optional Japanese model | 314 | **335** | 21 | 0 / 0 |

All **177 retrieval probes remained unchanged** in full default records; the two
cached model builds also agreed in full records. Default/model video sets remained
equal. Both live sample indexes stayed at 229,376 bytes, with all 12,888 normalized
characters and 33 streams retained. These are clip-inventory gains, not measured
improvements in linguistic sentence accuracy or query recall.

The extra export probes have a build cost. One paired run on 1,000 synthetic
videos, each with 16 sentence-dense cues, isolated the inventory change while
using the current parser for both builders:

| Export policy | Wall time | Process CPU | References | Live index bytes |
|---|---:|---:|---:|---:|
| Origin starts only | 6.39 s | 5.56 s | 16,000 | 2,170,880 |
| Unit and origin starts | 7.22 s | 6.42 s | 16,000 | 2,170,880 |

The corrected variant used about **15% more CPU** in that run. Its reference
asset was byte-identical: multiple sentences within each synthetic cue shared
the same playback envelope. The real sample above demonstrates the case where
the additional probes recover distinct clips. This single paired build is not
a throughput forecast, and the inventory fix does not add query-time work.

### Source IDs, WebVTT blocks and input errors

Author-written cue identifiers can contain arbitrary strings. SQLite alignment
now stores source ordinals (`cue-1`, `cue-2`, etc.); the original IDs remain in the
compressed VTT input. Deep verification checks ordinal syntax. The seven real
tracks had no author-annotated identifiers, so this is preventive hardening,
not a measured storage reduction in that sample.

WebVTT parsing also distinguishes block keywords from cue-ID prefixes. A cue
named `NOTEBOOK` is not a `NOTE` comment, and IDs such as `STYLE-12`, `REGION-12`
and `WEBVTT-12` are retained. Header syntax and its separating blank line are
validated; repeated author IDs still receive distinct source ordinals. Synthetic
fixtures exercise these cases against the
[WebVTT specification](https://www.w3.org/TR/webvtt1/) and
[MDN format documentation](https://developer.mozilla.org/en-US/docs/Web/API/WebVTT_API/Web_Video_Text_Tracks_Format).
No such keyword-prefix IDs or inline timestamp tags occurred in the real sample;
these parser tests do not establish word-level timing precision.

Query validation now rejects nonstrings, control/surrogate characters and
oversized input with `DataError`. Limits require actual integers in 1..250;
booleans and floats are rejected before opening a one-shot reader. An independent
authored Unicode oracle checks every 1..8-codepoint substring against explicit
sentence membership, covering quoted punctuation, decomposed accents, emoji,
supplementary Japanese characters, fullwidth Latin, literal FTS syntax and case.

### Rebuild identity and reusable predictions

That audit retained **schema v6**, while its processor was
`tubelex-ja-independent-coverage-v6` and reference policy is
`unit-and-origin-starts-v2`. Rebuild older sidecars before activation. Original
compressed snapshots remain usable; the index and reference manifests bind the
new processor and export policy.

Prediction keys now bind a separate boundary-input version, retaining the prior
v5 profile: cue-ID representation and inventory enumeration do not change model
input. All ten earlier cached predictions were reused, with zero inference
misses, by each model build in this audit. No new audio, transcript acquisition,
ASR or forced alignment was needed.

The complete suite now passes **456 tests on macOS and Linux aarch64**. Ruff,
all 12 source/schema configurations and diff whitespace checks pass. A networkless
Linux run deeply verified both current real-sample builds and matched all 177
probe records and full citation exports against macOS. A fresh default Linux
rebuild also matched every probe, the citation export and build identity. This
checks portability with SQLite 3.40.1 versus host 3.47.1; it does not qualify
full-corpus scale or HTTP latency.

Private evidence is outside Git at
`~/.codex/experiments/tubelex-citation-audit-20261024-ol_1iv4d/`, including frozen
baseline sources, inventory differences, paired build costs, current real builds
and reproduction checks. Earlier large synthetic measurements above used the
previous processor/export policy; their frozen evidence is historical and needs
an offline rebuild before current activation.

## Mixed punctuation, new videos, resumable shards and compact literal filtering

The current implementation is **private schema v7 / processor v7**. It adds
selective refinement inside publisher spans, resumable immutable collections,
blinded review tooling, a decoded-work budget and a compact fourgram Bloom filter.
Earlier measurements above remain historical rather than current-activation
artifacts. Existing caption snapshots and matching boundary predictions remain
reusable offline.

### Sentence selection and a separate new-video check

An authored regression with three complete sentences in three cues, one-second
gaps and punctuation only at the end formerly produced one unit and zero model
calls. A final full stop no longer disables all refinement. Conservative finite
endings at internal cue boundaries identify possible missing punctuation; the
timing-only path additionally requires the configured pause. The optional model
also considers publisher spans longer than 120 characters. Quote/bracket/word
guards and minimum fragment lengths constrain refinement. Original publisher
ends stay hard; inferred internal ends stay soft, so prediction errors cannot
remove literal coverage. Punctuation-only mode retains publisher spans.

Caption-only acquisition with an isolated **yt-dlp 2026.10.21** environment selected
14 additional videos, two per category across seven categories. Thirteen manual
Japanese tracks were acquired and one candidate was skipped. No audio, ASR or
automatic translations were downloaded. With the original seven, the sample now
contains **20 videos and 36,203 normalized characters**. Selection within each
category used the pinned list's order, not random video sampling.

Review packets sample windows independently of the segmenter and contain no
predictions. Labels were supplied by an assistant from text before per-case model
predictions were inspected. Scoring uses the original full stream, not cropped
window inference. These are **assistant text-only annotations**, not independent
human or audio-verified sentence truth.

The original seven-video review used 28 windows: 24 scored, four abstained, with
97 certain and six uncertain internal boundaries. Refinement changed model F1
from 0.891 to 0.901, increasing recall but lowering precision from 0.943 to 0.915.
The timing-only score was unchanged. This tradeoff prevents claiming a universal
quality improvement from the model.

The thirteen new videos were kept separate from policy/threshold selection. One
random 200-character core per video yielded twelve scored windows, one abstention,
59 certain and five uncertain internal boundaries. The model threshold remained
the previously chosen **0.35**; it was not tuned on these labels:

| Profile | Correct / extra / missed boundaries | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| Legacy timing-only | 18 / 0 / 41 | 1.000 | 0.305 | 0.468 |
| Refined timing-only | 19 / 0 / 40 | 1.000 | 0.322 | 0.487 |
| Legacy model policy | 50 / 2 / 9 | 0.962 | 0.847 | 0.901 |
| Refined model policy | **58 / 2 / 1** | 0.967 | 0.983 | 0.975 |

This is a small text-boundary check with explicit abstentions, not a general
Japanese subtitle accuracy estimate. Some windows contain no internal sentence
boundary. Audio-dependent conversational fragments were abstained rather than
given invented certainty. Model labels can still reflect systematic reviewer
bias. These numbers say nothing about factual reliability or whether an uploader
manually authored the track.

Across the full twenty-video export, the default profile produced 1,360 citations,
904 tagged `context-window`; the model profile produced 1,087, with 93 context
windows. That is **66.5% versus 8.6%** of these inventories. Counts are suggested
playback envelopes, not independent sentences or query-weighted quality rates.
The local Japanese character model with a prediction cache is the recommended
tested profile for sentence-focused builds; it remains explicitly opt-in.

### Cached text inference and shard-level resume

A cold/warm pair on all twenty videos used a fresh prediction cache. Both builds
had identical logical build IDs and reference assets:

| Run | Wall / process CPU | Cache hits / misses |
|---|---:|---:|
| Cold | 20.09 s / 32.87 s | 0 / 109 |
| Warm | 1.27 s / 1.14 s | 109 / 0 |

This pair used processor v7 before the Bloom layout update and included model
loading/build work. Concurrent host work affected wall time; CPU includes the
model's two threads. It is not a forecast for 100,000 videos. The final schema-v7
model build reused all 109 entries with zero inference misses.

`build-tubelex-batch` freezes an explicit plan of disjoint completed snapshots.
Each shard is built in a new staging directory, deeply verified, closed and
renamed into place. Interrupt/restart tests confirm that a completed first shard
is reused byte-for-byte after the next shard fails. An incomplete collection has
no completion manifest and cannot be served. Changing the base, source plan,
processing implementation, parameters, model bytes or applicable model runtimes
requires a fresh destination. Existing complete shards are verified on resume;
this has an offline verification cost, not a new acquisition cost.

The combined reader uses deterministic first matches, a bounded connection LRU,
and one shared deadline/decode budget across shards. Tests expire work after
earlier results exist and confirm that no partial success is returned. It also
checks base identity, closed-reader reuse errors, duplicate-video rejection,
immutable-plan conflicts, malformed options, corrupted receipts and bounded
filter caching. Resume also normalizes omitted versus explicit defaults, and
snapshot-directory versus manifest-file arguments, so equivalent CLI/API calls
reuse the same plan. This is not an appendable serving database or a ranking engine.

### Real-backed scale baseline

The scale study repeated the **twenty actual caption shapes** under fictional IDs.
The largest fixture had 10,000 videos, **18,101,145 characters**, 679,964 suggested
citations and ten 1,000-video shards. These are replicas, not 10,000 independently
acquired videos; their vocabulary is less diverse than a real corpus.

Before adding the Bloom filter, its verified schema-v6 build occupied
**118,902,784 live SQLite bytes**, including compressed verification text,
candidate postings and alignment metadata. Building took 608.09 s wall / 524.48 s
CPU; a separate deep verification took 238.69 s wall. These measurements used
the earlier batch path with redundant post-build verification and varying host
load; they are not current ingestion-throughput forecasts.

A fresh final schema-v7 production build of the first 1,000 replicas completed
in 51.37 s wall / 44.71 s CPU and deeply verified 68,000 citations. It occupied
11,919,360 bytes with a 26,752-byte filter. The batch builder now reuses the deep
verification result when installing a new shard instead of validating it again
immediately. Existing shards are still verified before reuse.

### Fourgram dictionary experiment and compact Bloom choice

A global set of four-character fingerprints can reject literals even when all
their trigrams occur somewhere in candidate chunks. The first exact B-tree
prototype occupied 356,352 bytes for 26,745 fingerprints from the twenty videos.
It rejected both independently constructed negative probes.

To avoid judging vocabulary cost only on replicas, another experiment processed
100,000 distinct real Japanese Tatoeba sentences (1,775,786 characters) from the
existing CC release. Their **583,922 fingerprints** occupied **7,634,944 bytes**
as an exact B-tree. A six-probe Bloom filter at eight bits per fingerprint used
**583,928 payload bytes**, or **589,824 SQLite bytes**. In 20,000 independently
sampled fingerprint probes it retained 419 false candidates (**2.095%**). Those
responses still require full literal verification; they are not false sentence
results. The sentence dataset measures diverse vocabulary cost, not the eventual
YouTube vocabulary distribution.

The production builder therefore drops the temporary exact dictionary and keeps
only the Bloom filter. Each shard caps its filter at 8 MiB and the combined
reader keeps a separate 16 MiB filter cache. Deep verification reconstructs and
compares every bit from source chunks. Tests cover missing bits, fingerprint
collisions, all-fourgrams-present/full-literal-absent cases, Unicode normalization
and storage seams. This is a necessary-condition accelerator, not an exact index
or a privacy transform.

### Paired query/storage comparison

To isolate the new filter, the verified ten-shard baseline was **copied and
experimentally converted** to schema v7; source text, alignment and reference
assets remained unchanged. This experiment-only conversion is not a supported
public migration command. Its first shard has the same logical build identity
as the fresh production 1,000-video build. The entire converted collection was
deeply verified. Seven query classes, seven shuffled warm repetitions, and full
record digests were compared using the same OS-cached inputs:

| Probe | Before median CPU | Final median CPU | Decoded chunks before → final |
|---|---:|---:|---:|
| Common match, top 250 | 10.840 ms | 10.962 ms | 64 → 64 |
| One-character match, top 250 | 16.216 ms | 16.353 ms | 43 → 43 |
| Longer positive, top 250 | 28.797 ms | 21.672 ms | 250 → 250 |
| Rare match in last shard | 6.369 ms | **0.366 ms** | 1 → 1 |
| Absent trigrams | 4.336 ms | **0.050 ms** | 0 → 0 |
| Present real trigrams, absent six-character literal | 13.220 ms | **0.029 ms** | 2,000 → 0 |
| Present real trigrams, absent four-character literal | 70.751 ms | **0.048 ms** | 3,499 → 0 |

The final negative filters also skip opening rejected shards once warm; their
retained filter cache was **267,536 bytes**. Warm wall medians for the last two
probes were 0.030 and 0.049 ms. Reader-cold measurements are preserved separately;
the table excludes reader construction, OS cold-cache behavior, networking and
HTTP serialization. Common short-query CPU did not improve. These are specific
local probes, not a universal speedup or production SLA.

All complete query records match the baseline exactly. With the default
**2048 decoded-chunk budget**, the old four-character negative exhausted its
budget; the final filter returned the correct empty result without decoding.
Uncapped baseline measurements above establish the actual empty result. Queries
whose fourgrams all pass can still require verification and hit the shared
deadline/work cap; neither error is reported as an empty or partial success.
All 32 final requests across four process workers completed.

The copied final layout occupied **119,189,504 live SQLite bytes**, an increase of
286,720 bytes (**0.24%**) on this vocabulary-replicated fixture. The filters total
267,536 bytes; sentence payloads remain compressed. On twenty genuinely distinct
videos, default live indexes grew from 602,112 to **634,880 bytes** (5.4%); model
indexes grew from 614,400 to **647,168 bytes**. The replica size increase must not
be extrapolated to a more diverse full corpus. These are live database sizes,
not compressed transport/archive sizes.

For this same replica fixture, the final compressed verification BLOBs total
26,811,461 bytes. Compressing the SQLite shards independently with Zstandard
level 9 yields **7,673,368 transport bytes**; already compressed reference exports
add 22,369,997 bytes, excluding manifests. No extra transport copies were retained
for that measurement. The separate **62,859,968-byte evidence bundle** contains
three layouts (baseline, converted final, and normal production 1,000-video build),
not one dataset download. All ninety bundle members were checksum-verified by
streaming them back without plaintext caption intermediates. Replicated vocabulary
also improves transport compression, so these sizes are not full-corpus forecasts.

### Current compatibility and evidence

The complete suite passes **484 tests on macOS and Linux aarch64**. Ruff, all twelve
source/schema configurations and whitespace checks pass. On the twenty real
videos, **591 retrieval probes**, full citation exports, Bloom bytes and shard
build identities agree across host SQLite 3.47.1 and Linux SQLite 3.40.1. A fresh
networkless Linux default build of both snapshot batches also agrees. The model
artifacts were queried/verified on Linux; model inference was performed on macOS.
Final CLI builds and idempotent reruns also produce data indexes byte-identical
to those portability-checked artifacts after plan-default/path normalization.

Private evidence is outside Git at
`~/.codex/experiments/tubelex-completion-20261024-sihiwrqc/`: pinned acquisition
selection, compressed caption inputs and review labels, frozen pre-filter/final
sources, scripts, full query/storage/work reports and portability checks. Task-owned
replica snapshots and duplicate outputs can be regenerated and moved to Trash
after checksummed compressed evidence is preserved. Nothing in this experiment
publishes transcripts, their derived indexes, labels containing source text, or
the fictional-ID benchmark citations. No audio or bulk alignment was used.


## October 25 resume and review-preparation audit

The follow-up audit reproduced two collection-consistency failures: resume could
accept a valid standalone shard built with different pause settings, and a
collection receipt could point at a different valid build without matching its
declared plan. Regression tests now reproduce and reject both cases.

Collection and plan metadata are now **v2**. A shared model descriptor freezes
exact options and model identity consistently during planning and building. The
builder verifies those options, processor, snapshot and base before installation
or reuse. The reader derives each expected build identity from stored descriptors,
without requiring model assets at serving time. Strict metadata checks reject
malformed counts, duplicate snapshots and noncanonical shard paths.

After deep verification, each new shard receives a private binding record covering
the complete processing profile and four artifact checksums. Resume checks this
record, the covered files and closed SQLite state instead of reparsing the entire
citation export. These records detect accidental corruption or incompatible
mixing; they do not authenticate a producer. Explicit verification retains its
normal export checks and optional deep source/filter recomputation.

Both final CLI profiles built from the twenty cached videos and completed an
identical idempotent rerun. All data indexes remain byte-identical to the previous
schema-v7 indexes: 1,360 default citations and 1,087 model citations. An earlier
single resume pair measured 6.84 ms wall / 6.38 ms CPU for the default profile and
136.07 ms wall / 117.64 ms CPU for the model profile, including profile/hash checks.
These small-sample timings are not production SLAs. V1 collections need a fresh
batch build from cached snapshots; standalone index schema 7 and reference schema
1 are unchanged, and no new acquisition is needed.

Review preparation now reservoir-samples at most **twenty videos** by default
(configurable from 1 to 1,000), selects window offsets before hydrating their
source context, and uses indexed origin lookup. It incrementally enforces the
32 MiB decoded packet limit and rejects oversized streams before copying their
complete origin metadata. Candidate inventory is capped at 120,000 videos.

On one authored continuous 10,000-cue track, the instrumented previous/current
pair took 4.677/1.843 seconds wall and 3.927/1.409 seconds CPU: about **64% less
CPU**. Selected cases and complete source payloads agree exactly. Both runs had
about 32 MiB traced peak allocation; this is no demonstrated memory reduction or
full-corpus throughput estimate. Repreparing the actual development and held-out
packets also preserves all 28/13 cases and their complete source payloads; only
sampling metadata and packet checksums change. Existing schema-1 packets/labels
remain readable.

Standalone output/input separation now prevents output artifacts entering a
snapshot/model tree. SaT's PyTorch descriptor also binds the Torch version for
prediction-cache validity. Existing Japanese character/ONNX descriptors are
unchanged, preserving their compatible prediction-cache entries.

The current complete suite passes **505 tests on macOS and Linux aarch64**; Ruff,
all twelve source/schema configurations and whitespace checks pass. The 591
real-caption retrieval probes, full exports, filter bits and shard identities
still agree with the previous iteration and across Python 3.13.5 / SQLite 3.47.1
on macOS and Python 3.13.8 / SQLite 3.40.1 on Linux. A fresh offline Linux default
build also agrees. Model inference remains a macOS build-time check, not a claim
of testing that inference runtime in Linux. Synthetic CLI checks additionally
cover snapshotting, batch build/resume, deep verification, text-free search and
capped review preparation/scoring.

Current private reports and reproduction inputs are outside Git at
`~/.codex/experiments/tubelex-resume-audit-20261024-3xgkxd2v/`. Earlier measurements
above remain historical; the new audit does not change their sampling limitations.
No private application integration, commits or publication occurred in this audit.


## October 25: retrieval completeness and reassessment

The build architecture and `selective-mixed-punctuation-v1` policy remain selected.
The previously reported assistant text-only development/holdout comparisons are
exploratory after inspection. No new threshold, broader punctuated-span inference
or global quote ban was promoted.

Four corruption regressions first passed ordinary checksum/SQLite/FTS integrity
checks while the old deep verifier accepted missing/added short or trigram
postings. The strengthened verifier independently derives all distinct expected
term/chunk pairs from compressed source windows and compares cryptographic
count/sum/XOR bindings with FTS5 vocabularies. A further regression swaps postings
between chunks, preserving the vocabulary and counts. Unicode, combining-mark,
non-BMP, punctuation and one/two-character positive cases also pass. It stores no
second full index, source plaintext file or corpus-sized expected-term set.
No missing postings were observed in the actual 20-video sample. In five measured
paired warm rounds, full deep verification of both sample shards cost median
336.73 ms before / 472.53 ms after the completeness check. This activation/build
cost does not enter serving queries or sealed completed-shard resume.

The checked-in pipeline benchmark then measured the same two cached snapshots
under default and optional Japanese-model profiles, plus a separate authored
10,000-cue workload combined with the seven-video snapshot:

| Sample/profile | Cold prediction cache | Fresh rebuild/warm prediction cache | Completed resume | Resume after controlled interruption |
|---|---:|---:|---:|---:|
| 20 actual videos, default | 1.056 s | 1.015 s | 0.006 s | 0.684 s |
| 20 actual videos, local character model at frozen 0.35 | 15.254 s | 1.381 s | 0.100 s | 0.906 s |
| Authored 10,000-cue track + seven actual videos, default | 4.445 s | 4.363 s | 0.006 s | 0.345 s |

These are single end-to-end pairs with warm filesystem inputs, not full-corpus or
production throughput estimates. Model inference consumed 13.55 s cold and zero
calls on warm rebuild/resume; all 109 predictions were reused on rebuild. The
warm model rebuild still spent about 311 ms setting up model sessions. Default
cold file hashing / caption decompression cost about 6.8 / 3.2 ms; model completed
resume hashing / caption decompression cost about 47.2 / 0.7 ms. Full caption
integrity scanning and sealed file hashes remain in place. Phase reports include
nested inclusive and exclusive timings; exclusive phase totals equal the root
measurement exactly. Stored build-cache counters must not be interpreted as new
inference during completed resume. Database and citation-export hashes agreed
across cold, rebuild and resumed outputs in every workload.

Default cache stress used authored zero-filled Bloom byte fixtures, the real
collection cache, an 8-reader default and a 16 MiB dedicated filter budget. It
models warm byte loading/eviction only: no real caption distribution, cold disk,
SQLite-open cost or production-latency claim.

| Shards × filter bytes | Working set | Warm median | Readers opened per warm query |
|---|---:|---:|---:|
| 8 × 1 MiB | 8 MiB | 0.013 ms | 0 |
| 64 × 256 KiB | 16 MiB | 0.071 ms | 0 |
| 32 × 1 MiB | 32 MiB | 4.700 ms | 32 |
| 16 × 2 MiB | 32 MiB | 3.926 ms | 16 |
| 8 × 4 MiB | 32 MiB | 0.024 ms | 0 (all eight readers retained) |

The last case retains 32 MiB across open-reader/filter references despite the
16 MiB dedicated cache budget. Current sample filters occupy only 27,568 bytes;
this is a scale risk, not evidence of a current production problem. Cache defaults
stay unchanged, with new per-search hit/miss/eviction/open/reuse counters.

Across eight diagnostic queries, complete default reference records matched the
pre-reassessment implementation. Opt-in diverse mode increased two common-query
20-result selections from one video to 20 and 19 videos respectively. Those
single-pass calls cost 32.35/11.70 ms rather than default 1.78/0.97 ms because they
scan all shards; no ranking-quality or production claim follows. The selection
pool and per-video bookkeeping stay bounded by the result cap; shared deadlines
and decoded-chunk limits discard incomplete results. Default order stays intact.

New private review material contains 44 nonoverlapping text windows from 17 of
the previously seen videos, excluding all contexts in the 28 development and
13 earlier holdout cases. This is not a new-video holdout. Forty independently
sampled text-free playback references have a separate listening-label template.
Both templates are blank, and playback scoring rejects text-only reviewer types
or missing listening confirmation. No human/audio quality result is claimed.

Scripts, pre-change sources, phase reports, corruption red/green results and
compressed review packets remain outside Git in `tubelex-findings-dx6tmrn2`.
Only public build/search/review code, authored test fixtures and text-free
aggregate findings belong in this repository. The private Django serving format
and native dictionary/runtime were not changed.


### Follow-up: bind citations and review cases to their source

A second consistency gap remained after complete posting verification: a forged
but canonical citation URL could name a different video/time, use the wrong
boundary tag, or duplicate another exported clip while every file checksum and
count still passed. Four red regressions reproduced this. Deep verification now
reconstructs the `unit-and-origin-starts-v2` inventory using the same private
cue/unit materialization rules that readers serve, deduplicates text-free IDs in
a temporary SQLite file with a 2 MiB page cache, and compares full canonical
citation bindings. It ignores export line/key/tag order. Stream snapshot and
boundary-mode metadata must also match the advertised build. Intentionally empty
punctuation-only exports remain valid. No source text is written to the ledger,
and the main artifact remains read-only and byte-identical.

Both saved 20-video builds passed the stronger check: 1,360 default references
and 1,087 model-assisted references over 36,203 indexed characters. Five measured
paired warm rounds gave medians of 490.55→580.35 ms (default) and 447.51→529.39 ms
(model profile). This roughly 80–90 ms additional cost is offline deep verification,
not search work. These checks establish consistency with stored cue alignment,
not human listening quality or proof of upstream caption accuracy.

Fresh complete-pipeline runs with the stronger verifier retained identical index
bytes to the preceding saved builds. Default cold/rebuild/completed-resume times
were 1.166/1.120/0.006 seconds; the frozen model profile measured
15.267/1.467/0.101 seconds. Controlled interrupted attempts now have explicit
report rows (0.371/0.604 seconds default/model), followed by resumed builds of
0.757/0.958 seconds. All successful build/index/export identities matched, and
nested exclusive times still account for the root exactly. Earlier timing tables
predate this additional check. These remain single warm-filesystem sample pairs.

Review packets now reject duplicate/altered case IDs, invalid source/core offsets,
text differing from its full source stream, mismatched clipped origins and missing
source streams before inference. Re-signing the changed packet/case does not make
those inconsistencies valid. All 28 development, 13 earlier holdout and 44 fresh
saved cases remain readable. Exclusions bind to full-source text hashes so stream
renumbering cannot silently resample old contexts; unknown/edited streams in
already reviewed videos are skipped conservatively. Playback packets receive the
same canonical citation checks as artifact verification and reject duplicate IDs.
No new boundary F1 or listening labels were manufactured.

The diversity selector also matched an independent exhaustive priority oracle
across 1,000 seeded randomized/interleaved synthetic cases, including evictions;
its result/ID/per-video maps remained bounded by the cap. No selection default
changed. Benchmark regressions now preserve interrupted/failed/mismatched-artifact
reports and restore all instrumentation hooks; failed results cannot be reported
as successful identity qualification, even with Python assertions disabled.
Small reproduction evidence is in `tubelex-reference-review-9j3g_b02` outside Git.

### Follow-up: bound diverse-search deduplication end to end

The preceding pool-level bound omitted a separate shard-scanner seen-ID set.
Unlike the bounded result pool, it retained every matching clip during a diverse
scan. A 120-cue regression with a three-result cap reproduced 120 retained IDs.
The scanner now shares the pool's retained-ID set. Eviction removes a video's
last retained slot, and its next candidate has the evicted priority, which cannot
beat the monotonically improving heap cutoff. This also rejects repeated evicted
clips without retaining their IDs. The ordinary first-match path is unchanged.

A separate exhaustive oracle globally deduplicates records, assigns per-video
arrival ordinals and sorts the complete candidate list. The bounded selector
matched it in 1,000 seeded randomized cases with interleaved videos and repeated
clips, including repeats after eviction. All 42 query/limit/profile combinations
on the saved 20-video default/model samples returned identical text-free results
before and after the scanner change.

The existing authored continuous 10,000-cue track (130,000 characters) gave the
same 250 results in both implementations. Observed scanner deduplication high
water fell from 9,999 IDs to 250; peak query-time Python-traced allocations fell
from 1,762,806 to 501,544 bytes. This excludes SQLite/native memory, reader setup
and process RSS. Five serial warm rounds per version measured medians of
289.59 ms before and 279.78 ms after. This single workload supports the memory
bound and indicates no observed slowdown; it does not establish a general speed
improvement or production latency. No corpus bytes, storage format or selection
defaults changed. Reproduction code and aggregate evidence are outside Git in
`tubelex-bounded-search-0zw_120u`.

### Follow-up: reduce citation assembly and filter-copy overhead

Profiling 120 diagnostic searches on the saved real sample attributed most query
time to citation materialization, rather than Zstandard decoding. The scanner now
loads/decodes stream metadata once per visited stream, origin selection uses one
indexed SQLite statement instead of two, and an accepted display-unit envelope
does not first fetch a redundant match-only envelope. A regression reduced 800
metadata reads to one across repeated matches and multiple chunks. Query-local
state retains only the current stream's metadata and eligibility, not full text.

All 84 query/selection/limit/profile combinations matched the previous text-free
results on the two saved 20-video builds. Five alternating paired warm rounds
measured workload medians of 153.50→116.53 ms (default profile) and 126.30→78.35 ms
(model profile). Host load was variable, including one 541 ms baseline outlier;
these small-sample medians support the observed direction, not an HTTP latency or
universal speedup claim. File hashes and modification times stayed unchanged.

Reopening an immutable shard now shares an already cached filter payload. A
synthetic 64-shard, 256 KiB/filter fixture fitting the 16 MiB cache but exceeding
the eight-reader pool reduced unique retained filter payloads from 18 to 16 MiB.
Seven repeated positive-path scans loaded 112 MiB of duplicate filter bytes
before and zero afterward; component medians were 4.32→1.96 ms. SQLite candidate
work was stubbed in this component measurement, so these are not search timings.
The existing negative-cache stress still reproduces thrashing for working sets
larger than the cache; no cache capacity/admission defaults changed. Essential
reports and reproduction scripts are outside Git in `tubelex-performance-vufbcipi`.
