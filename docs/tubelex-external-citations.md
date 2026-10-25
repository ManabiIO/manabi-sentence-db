# Optional Japanese YouTube citation sidecar

The public corpus release remains the redistributable CC/public-domain content
and its indexes. This repository additionally publishes **build code** for a
downstream, private TUBELEX extension. It does not publish TUBELEX transcripts,
transcript-derived search indexes, or an expanded content archive.

The extension binds an independent index to the SHA-256 of an existing downloaded
release asset. The base asset is neither unpacked nor modified. An application can
search its normal corpus index and this sidecar separately, then merge results.
The sidecar reader returns canonical `kind: reference` records; it never returns
transcript snippets. It is a working standalone build/search facility, not an
integration with the private Django application or its experimental native index.

## Why TUBELEX rather than original JTubeSpeech

[TUBELEX](https://github.com/naist-nlp/tubelex) supplies a curated Japanese video
list, video metadata and a newer, substantially changed JTubeSpeech fork. Its
README explicitly says that the full corpus text cannot be published for
copyright reasons. It supplies IDs so users can reconstruct the corpus.

We consume `corpus/videos-ja.csv`, pinned to commit
`7cb5fb36add76b83a266d1967536e1a1d3faa513` and SHA-256
`eb0e2442a4872bda280ec96e99b6d0b9f620eaf3f2f8da13511bfeca284002ba`.
No TUBELEX code is vendored. Its repository's BSD license is not treated as a
license to the videos or transcripts. This source deliberately does **not** enter
`sources/*.yaml`, `snapshot --source all`, normal builds, or public release jobs.

Only Japanese (`ja`, not `jp`) manual subtitle tracks qualify. The CSV's `auto`
field means an automatic track is also available; it does not mean the manual
track is automatic. Selection requires `sub=True` and `language=ja`, then checks
the current video's `subtitles["ja"]` metadata. `automatic_captions` is never used.
Tracks with `tlang`, `kind=asr`, a non-Japanese source language, or explicit
automatic/translation flags are rejected. This excludes automatic translations
as well as ASR. An uploader's manually translated Japanese captions cannot
reliably be distinguished from Japanese originals, so original-audio language
and human authorship are not asserted.
When the caption URL supplies a `v` parameter, it must match the selected video.
The acquisition cache policy is `manual-ja-v3`; older completed snapshots remain
offline build inputs, while the new acquisition policy uses separate cache keys.

## Acquisition is separate and opt-in

Start with a small selection. Install `yt-dlp` in your own environment for the
network variant; it is a metadata extractor, not a production serving dependency.
The exact available version depends on your environment. It is invoked with
`--ignore-config`, no media download, no playlists and no retries. No login,
cookie, proxy or access-control workaround is configured by this pipeline.

```sh
mise run snapshot-tubelex -- \
  --output data/private/tubelex-snapshot-001 \
  --cache data/private/tubelex-cache \
  --max-videos 10
```

The command downloads the pinned video list, inspects each selected video's
metadata, and fetches only one validated manual Japanese VTT track. It waits at
least five seconds between video metadata requests, spaces metadata extractor
requests, fetches captions serially, and stops on acquisition/access failures.
It downloads no audio, video, translated tracks, or generated transcripts.
Explicitly removed/private videos are recorded and skipped. Rate limits, bot
challenges and unknown failures stop acquisition. A durable per-video cache and
negative-result ledger allow restarting with a fresh snapshot destination. Cache
keys bind video ID and eligibility policy, so selecting another list or shard
does not download completed videos again. Use `--offset N` to choose a later
slice; `--max-videos` limits attempts, not successful acquisitions. One writer
per cache is supported. Completed entries are atomically installed; interrupted
staging files are never mistaken for completed entries.

For already acquired TUBELEX captions, use a local list and a flat directory
containing `<videoid>.info.json` (yt-dlp subtitle metadata) and
`<videoid>.ja.vtt`. Supplying **both** makes snapshotting fully offline:

```sh
mise run snapshot-tubelex -- \
  --videos-csv /path/to/videos-ja.csv \
  --captions-dir /path/to/rehydrated-ja \
  --output data/private/tubelex-snapshot-001 \
  --cache data/private/tubelex-cache \
  --max-videos 10
```

A bare VTT is not sufficient to establish track provenance. The local metadata
and VTT must describe the same downloaded track; the importer verifies video ID
and metadata eligibility, but cannot prove a supplied VTT's origin. The original
TUBELEX scraper's plain VTT directory alone therefore needs corresponding
metadata before import. A supplied CSV is recorded by its checksum, with no
claim that it is the pinned upstream list.

Snapshots and reusable cache entries contain **compressed** private caption JSON.
The pipeline never writes plaintext caption intermediates. Snapshot manifests
list checksums and skipped videos, but contain no captions or signed download
URLs. The output directory is new and private; caching avoids reacquisition
across processing revisions. Use a new cache location to refresh upstream data.
This also refreshes cached removed/private or unavailable-manual-track states.
Caption payloads retain acquisition time, safe track metadata, extractor version
when supplied by yt-dlp, and a metadata checksum. Signed URLs are not persisted.
An interrupted snapshot has no completed manifest; completed cache entries can
be reused with a fresh snapshot destination.

TUBELEX's reconstruction code is not permission from YouTube or video owners.
[YouTube's terms](https://www.youtube.com/static?template=terms) restrict automated
access, and the official [captions download API](https://developers.google.com/youtube/v3/docs/captions/download)
requires authorization and permission to edit the video. Use acquisition only
where you have the necessary permission; the local import/build path does not
depend on public YouTube scraping being available. Neither citations nor keeping
an index private by themselves settle permission to acquire or process content.

## Build beside an existing release

```sh
mise run build-tubelex -- \
  --snapshot data/private/tubelex-snapshot-001 \
  --base-artifact dist/downloaded/wikipedia-ja.ja.normalized.zip \
  --private-output data/private/tubelex-index-001 \
  --references-output build/tubelex-references-001

mise run verify-tubelex -- \
  --private-build data/private/tubelex-index-001 \
  --references build/tubelex-references-001 \
  --base-artifact dist/downloaded/wikipedia-ja.ja.normalized.zip \
  --deep

mise run search-tubelex -- \
  --index data/private/tubelex-index-001/citations.private.sqlite3 \
  --base-artifact dist/downloaded/wikipedia-ja.ja.normalized.zip \
  --query '図書館' --limit 250
```

Paths are examples: pass the actual asset you downloaded, whether ZIP, Zstandard
or SQLite. The base file's checksum, snapshot identity, processor version, model
identity and boundary options bind the sidecar. This is an asset-level binding;
a release with multiple assets should use one agreed immutable identity asset.

Use fresh output directories outside the snapshot and model/tokenizer input trees.
Standalone and batch builds reject overlapping input/output locations, so build
artifacts cannot become new model inputs or alter cached snapshot identity.

`verify-tubelex` is an offline transfer/activation check. It verifies both artifact
roles, their matching build identities, the database and export checksums, closed
SQLite state, database inventory, and each exported citation's URL/timing identity.
`--deep` also checks bounded decoded chunks, overlapping text, contiguous source
origin coverage, display-unit ranges, fixed-window eligibility bitmaps and
orphaned index records. It independently derives every expected distinct
(term, chunk) posting from bounded caption text and compares count plus SHA-256
sum/XOR bindings with both FTS vocabularies. Missing, extra and reassigned postings
are rejected even after file checksums are recomputed and FTS integrity passes.
The comparison streams the vocabularies once and retains only one chunk's term
set. It does not assess linguistic or playback quality. Validate once when activating
a build; serving code should not hash a large base artifact on every query.

`data/private/tubelex-index-001/` contains a SQLite index and private manifest.
Verification text is stored as overlapping 4096-character Zstandard chunks,
independent of sentence predictions. A 499-character overlap guarantees that
every allowed literal query (up to 500 characters) fits in at least one chunk.
The working candidate index uses contentless FTS5 trigrams **without positions**
(`detail=none`, `columnsize=0`) and a second position-free FTS5 index of encoded
single/bigrams. Delta-compressed postings replace the former relational short-term
B-tree. The short-term encoding is reversible and private, not a rights workaround.
Every candidate is verified against bounded decompression before a result is
returned. Matching is literal, case-sensitive and NFC-normalized. Explicit
punctuation boundaries prevent cross-sentence hits; uncertain pause/model
boundaries do not suppress matches. Speaker turns, regions, ambiguous overlaps and
context gaps of at least five seconds separate searchable streams. There is no
JMdict expansion. Multiple hits sharing a playback range are deduplicated.
Text eligibility is computed offline on fixed 256-character source tiles with
128 characters of context on either side. Queries read packed bits for the tiles
they touch; no text classifier or boundary model runs during retrieval. These
deliberately weak rules can exclude nearby clean text and are not a safety rating.
They are independent of predicted sentence boundaries. Deep verification
recomputes the bits, including padding, from a bounded two-chunk buffer.
The current private format is **schema v7 / processor v7**, with reference policy
`unit-and-origin-starts-v2` and boundary policy `selective-mixed-punctuation-v1`.
The processor refines sparsely punctuated publisher spans; schema v7 adds a
compact private literal Bloom filter. These identities enter the build identity. Rebuild
older sidecars before activation; existing compressed snapshots and compatible
model-prediction caches can be reused offline without another acquisition.
Batch collection/plan metadata now use **format v2**. Earlier v1 collections
need a fresh batch build from their existing snapshots. Standalone schema-v7
indexes and canonical reference records keep their formats.
The measured sample
results and current tool research are in [the experiment notes](tubelex-experiments.md).
Synthetic scale/concurrency tests and Linux compatibility checks are described in
the experiment notes. They do not qualify full-corpus size or production HTTP latency.

Serving code can reuse a connection per thread/worker:

```python
from pathlib import Path
from manabi_sentence_db.tubelex_index import TubelexReader

with TubelexReader(Path("data/private/index/citations.private.sqlite3"), timeout_ms=1000) as reader:
    references = reader.search("食べました", limit=250)
```

Verify the build before activation. Keep the reader on its owning thread, close
it on shutdown, and close/reopen it when activating a new immutable build.
`search_tubelex_index` remains a convenience function for a single lookup. Query
code reuses decoded candidate text and skips repeated playback envelopes before
hydration. Full JSON Schema validation happens during export/verification; the
query's fixed reference factory checks its narrow input contract.

Before searching candidates for literals of four or more characters, the reader
checks a global per-shard Bloom filter of four-character fingerprints. A missing
gram proves absence without decompressing captions. A positive Bloom response
only retains candidates; the normal substring and boundary verification still
decide every match. Fingerprint collisions and Bloom false positives therefore
cannot create false search results. This derived vocabulary remains private;
hashing it does not establish redistribution rights.

The builder uses a temporary disk-backed fingerprint dictionary, then replaces it
with eight bits per distinct fingerprint and six bit probes. Each shard's filter
is capped at 8 MiB; saturation increases candidate work, not false matches or
false negatives. Private stats report byte count and set-bit count. `--deep`
reconstructs the complete filter from the compressed source chunks and compares
its bits exactly. The temporary dictionary is dropped before final compaction.

Queries must be Unicode strings containing 1..500 NFC-normalized characters,
without control characters or surrogate code points. Raw input is capped at
2000 characters before normalization. Result limits must be integers from 1 to
250; booleans, floats and strings are rejected. Invalid requests raise `DataError`;
the one-shot reader validates them before opening the database.

Each query has a cooperative wall-clock budget, default **1000 ms**. Both Python
candidate traversal and SQLite's progress handler enforce it. Expiration raises
`QueryBudgetExceeded` (a `DataError`); results already accumulated are discarded.
It never turns an unfinished search into an empty or partial successful response.
The reader remains usable after interruption. Serving integrations should expose
this as an explicit retry/narrow-query error rather than “no matches.” Slow I/O
or scheduling can delay a cooperative deadline; it is not a hard real-time bound.
The budget covers searching, not reader startup or optional base-file hashing.
Python readers and the CLI accept 1..60000 ms (`--timeout-ms`); a longer budget
can be useful for explicit offline audits.

There is also a **2048 decoded-chunk budget**, configurable with
`--max-decoded-chunks` or `TubelexReader(..., max_decoded_chunks=N)`. It bounds
verification work even when many candidate grams exist. The cap is shared across
all shards in a collection. Exceeding it raises `QueryWorkLimitExceeded`, a
`QueryBudgetExceeded` subclass, and discards partial results. A caller must not
turn this into an empty successful response. Allowed values are 1..1000000;
larger explicit budgets are useful for offline benchmarking. This is an upper
bound on chunks decoded sequentially, not a promise that every query touches
only a handful of sentences or that all permitted work completes in real time.
`last_search_stats` reports text-free work counters; CLI `--stats` prints them on
stderr. Keep these diagnostics private rather than exposing corpus oracles.

Each bounded candidate chunk carries a canonical punctuation bitmap of at most
512 bytes. The reader checks its interior bits before hydrating cross-sentence
matches; negative literals do not decode an unused bitmap. This avoids fetching
a list of boundary rows from SQLite. Punctuation inside quotes remains searchable,
including when the opening quote predates the current storage chunk.
The candidate indexes also omit one/two-character grams that cross a hard
boundary. Their trigram input inserts an unsearchable control separator at those
boundaries; the original verification text and exported records never receive
that separator. This prevents many impossible phrases from becoming candidates
at all. Shared grams can still occur elsewhere in a chunk, so literal verification
and bitmap checks remain necessary. Uncertain model/pause boundaries do not break
gram generation. The candidate policy enters the logical build identity.
Deep verification checks bitmap size, canonical encoding, padding and agreement
with the stored punctuation units using a bounded rolling window. As before,
this is structural consistency checking, not independent linguistic annotation.

For the future Django integration, prefer bounded **process workers**, each with
its own reader. A small four-worker test completed all requests with processes;
four Python threads contended heavily and hit budgets on the broadest negative
queries. This is measured guidance, not a new serving pool or private-app integration.

Completed builds run SQLite `VACUUM` before final checksums and completion
metadata. This reclaims temporary-table and FTS-merge space while keeping sentence
payloads compressed. Budget temporary disk space for a second database-sized copy
during compaction. No changes to the base CC release are needed.

`build/tubelex-references-001/` contains only `references.jsonl.zst` and a checksum
manifest. Records have video ID, generic title, YouTube attribution link, timing,
boundary-method tag and snapshot provenance. The export probes both display-unit
and source-origin starts, deduplicating identical playback ranges. This includes
sentences beginning inside a cue that starts in the preceding sentence. It
inventories suggested clips; a query spanning uncertain boundaries can produce
an additional envelope dynamically from the private alignment map. Records contain
no text, snippets, translations, character offsets, transcript hashes, vocabulary
or postings. No
transcript redistribution license is attached. The normal `package` command
does not consume this sidecar or its private index. Publishing the scripts does
not require publishing either of these generated directories.

## Caption lines, sentence boundaries and timing

Caption lines wrap for presentation and can divide a sentence. Conversely one
cue can contain several sentences. [Subtitle style guidance](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements)
also imposes display duration and line-length constraints, so a cue gap is an
imperfect proxy for a speech pause, rather than an acoustic measurement.

The default `--boundary-mode hybrid --pause-ms 800`:

1. Strips VTT markup and ruby readings while retaining the Japanese base text.
   Removes exact overlapping repeated display cues; genuinely repeated phrases
   at later times remain separate. Only complete repeated display lines are
   removed for scrolling captions; arbitrary character overlap is not guessed.
   Newlines and `<br>` wrap Japanese text contiguously. A wrap between Latin
   letters/digits becomes one space, including across cues, so `good` followed
   by `morning` cannot create the nonexistent literal `goodmorning`. Accented
   and fullwidth Latin letters are covered. This conservative heuristic can
   separate a word the author split mid-word; that ambiguity cannot be resolved
   reliably from caption layout alone. Spaces across cues retain both envelopes.
2. Retains voice/region metadata and source cue ordinals (`cue-1`, `cue-2`, etc.).
   Author-written cue IDs remain only in the compressed original VTT, avoiding
   arbitrary caption-like strings in the uncompressed alignment metadata.
   WebVTT metadata blocks follow their exact syntax: a cue named `NOTEBOOK`, for
   example, is not silently discarded as a `NOTE` comment. Distinct speakers
   and ambiguous overlapping cues are not concatenated. Scrolling deduplication
   preserves the timing coverage of repeated display lines.
   A returning speaker starts a new stream after another speaker/region's turn,
   even when the gap is short. Independent turns do not form a new searchable phrase.
   NFC normalization also crosses cue boundaries. If a base kana and its dakuten
   occupy different cues, the composed character retains both source ranges.
3. Splits at Japanese terminal punctuation using the existing quote-aware
   segmenter. In unpunctuated spans, gaps of at least 800ms propose soft display
   boundaries (`pause-inferred`); remaining spans are `unsegmented`. These are
   **utterance candidates**, not proven grammatical sentences. Short gaps never
   remove searchable text or prevent matching a continuing phrase.
   A final full stop no longer disables all earlier refinement. For punctuated
   spans, an internal cue boundary after a conservative finite ending such as
   `ます` or `です` identifies a possible missing sentence boundary. Timing-only
   splitting additionally requires the configured pause. With a local model,
   these spans, and publisher spans longer than 120 characters, receive model
   proposals. Interior splits inside quotes, brackets and Latin words are
   suppressed; short fragments are merged. Original terminal boundaries remain
   hard, while every added model/pause boundary remains soft for literal search.
   Punctuation-only mode retains the original publisher spans without refinement.
4. Indexes the full normalized stream even when it exceeds 30 seconds or 500
   characters. A match uses a containing display unit if reasonably bounded;
   otherwise a small surrounding caption window is marked `context-window`.
   Fixed source windows receive weak text-quality and sexual-content checks
   during the build; retrieval consults their stored eligibility bits. Partial
   context is allowed to have unmatched quotation marks. These checks
   are neither a safety guarantee nor a human quality rating.
5. Maps the result span back to overlapping original cue ranges. The playback range
   is the earliest start and latest end of those cues, with millisecond metadata.
   Two sentences inside one cue have the same range; there is no fabricated
   proportional word timing. Embed URLs use `start=floor(start_ms/1000)` and
   `end=ceil(end_ms/1000)`; **end is absolute from video start**, not duration.
   If a single cue itself lasts over 30 seconds, its truthful envelope is retained
   with `timing:wide-cue-envelope`; no word-level offset inside it is invented.

800ms is a configurable heuristic, not a validated Japanese linguistic threshold.
Use `--boundary-mode punctuation` for higher-precision punctuation-backed results
only, or compare thresholds on a manually inspected sample. Caption authors can
leave no gaps even when speakers pause; timing alone cannot recover that signal.

The 30-second bound above limits a preferred **playback clip**, not a threshold
for a mid-sentence pause. A five-second caption gap already separates searchable
streams. Caption display gaps are not measured audio silence. The default build
does not download audio, transcribe it or force-align 100,000 videos. Playback
uses existing caption timing, accepting that a cue envelope can include words
outside the inferred sentence. This cost/precision choice is deliberate.

For continuous unpunctuated tracks, optionally install
[wtpsplit/SaT](https://github.com/segment-any-text/wtpsplit) in your build environment.
SaT is a multilingual punctuation-agnostic sentence segmenter. Provide **local**
model and tokenizer directories with `--sat-model` and `--sat-tokenizer`; build
sets Hugging Face offline flags and does not download weights. Model/tokenizer
bytes and installed package version enter the build identity. The adapter checks
that concatenating all predicted segments reproduces the input exactly, so a
model cannot introduce punctuation, rewrite a caption or shift source offsets.
Existing explicit sentence boundaries are preserved. Prediction runs on
unpunctuated remainders and selected sparsely punctuated spans, marking inferred
prefix units `boundary:model` while retaining the publisher's final boundary. Short display gaps do
not force model boundaries. Predictions change clip selection; they never control
which caption text enters the substring index.
`--sat-threshold` defaults explicitly to 0.25 (the published SM default), avoiding
wtpsplit's directory-name-dependent default. Base/non-SM weights may need another
threshold. A local `model_optimized.onnx` selects CPU ONNX; otherwise the adapter
uses PyTorch. Backend and dependency versions enter the build identity. We tested
wtpsplit 2.2.2 with ONNX Runtime 1.31.0 and transformers 4.57.6 in an isolated
environment. Model inference is optional build-time work, not query-time work.
Model-backed quality still needs Japanese subtitle sample review. Offline tests
exercise the segmentation/offset contract with a deterministic stand-in; no model
weights are downloaded or model accuracy claimed by the test suite.

### Recent Japanese character model alternative

The optional four-label character profile supports the September 27, 2026
[AstroNier Japanese punctuation model](https://huggingface.co/AstroNier/japanese-punctuation-onnx).
It uses 92 MB int8 weights and a small `vocab.txt`, with Apache-2.0 licensing.
Pin revision `89f8d70475328ff9b3e992696604845abd3257db` when acquiring the files
separately. The builder reads local `punct.int8.onnx` (or `model.onnx`) and
`vocab.txt`; it does not fetch them. For example, in a build environment with
ONNX Runtime installed:

```sh
uv run --locked --with onnxruntime==1.31.0 sentence-db build-tubelex \
  --snapshot data/private/tubelex-snapshot-001 \
  --base-artifact dist/downloaded/wikipedia-ja.ja.normalized.zip \
  --private-output data/private/tubelex-index-ja-model \
  --references-output build/tubelex-references-ja-model \
  --ja-punct-model /path/to/local/japanese-punctuation-onnx \
  --ja-punct-threshold 0.35
```

0.35 reproduces the experiment; the CLI's conservative default is 0.5. Select
either the Japanese model or SaT. Only period/question predictions propose
boundaries; commas do not. Overlapping windows divide ownership near the middle
of the overlap, retaining both left and right context for interior predictions.
They never force a split at a window edge and return exact source slices without
inserting marks. The 64-character overlap supplies 32 characters of context on
each side of an ownership seam; actual transcript starts/ends have no such context.
Existing punctuation is preserved. Runtime, weight/vocabulary hashes, threshold,
window settings and CPU thread counts enter the build identity.

For sentence-focused builds, the recommended tested profile is this local
Japanese character model at **0.35**, with a reusable boundary cache. The cheap
timing-only default remains available without model dependencies, but it misses
many boundaries in continuously displayed captions. The recommendation is based
on limited assistant-reviewed text samples; it is not human/audio validation.

### Reusing model inference across rebuilds

When using either local model, optionally add:

```sh
  --boundary-cache data/private/tubelex-boundary-cache
```

The default punctuation/pause build has no model inference to cache and rejects
this option without a model. Use a dedicated private directory separate from the
snapshot, model/tokenizer inputs and both output directories. Use one writer per
cache; sequential snapshot batches can reuse the same completed entries.

Entries contain compressed boundary offsets, length and integrity/identity hashes,
not transcript strings. Their keys bind exact normalized input text, a separate
boundary-input version,
model/vocabulary bytes, threshold, window policy and runtime profile. The SaT
PyTorch profile includes the installed Torch version; older entries for that
backend incur a one-time cache miss. Japanese character/ONNX descriptors are
unchanged and their compatible entries remain reusable. Changing the
model configuration misses the cache; changing only the SQLite layout, citation
inventory or cue-ID representation can reuse it. Processors v6/v7 retain the v5
boundary-input normalization profile. Selective refinement can request additional
text slices; keys bind their exact text, so existing matching entries remain valid.
Predictions are checked to cover the original input exactly. These remain
private derived data and are not included in either corpus or reference exports.

Entries are installed atomically. An interrupted build can retain completed
inference and reuse it when rebuilding into fresh output directories. Corrupt or
oversized entries stop the build explicitly instead of silently changing output.
Private manifest counters report `boundary-cache-hits` and
`boundary-cache-misses`; cache paths/counters do not change the logical build ID
or public citation output. Reusing the cache still loads the local model and
checks its identity; it does not bypass the required local runtime/assets.

This caches inference, not a partially written SQLite transaction. The database
itself is rebuilt and verified from the existing snapshot. Snapshot acquisition
continues to have its own video offset/limit and compressed caption cache.

This is an opt-in candidate, not a claim of validated Japanese sentence accuracy.
Our publisher-punctuation proxy is small and genre-dependent. It does not measure
human judgments or audio alignment, and predictions can still split names or
clauses poorly. The model is not included in public corpus releases.

Actual word alignment would require authorized audio and a separate forced
alignment stage (for example [WhisperX](https://github.com/m-bain/whisperX)), with
substantially more acquisition/compute. This first version uses existing captions
only. [YouTube's player documentation](https://developers.google.com/youtube/player_parameters)
also notes keyframe-dependent seek imprecision, so even a good cue envelope is
not a promise of sample-accurate playback.

## Resumable snapshot batches and combined search

Acquire disjoint batches sequentially, reusing the same private acquisition cache:

```sh
mise run snapshot-tubelex -- --output data/private/captions-000 \
  --cache data/private/caption-cache --offset 0 --max-videos 1000
mise run snapshot-tubelex -- --output data/private/captions-001 \
  --cache data/private/caption-cache --offset 1000 --max-videos 1000

mise run build-tubelex-batch -- \
  --snapshot data/private/captions-000 --snapshot data/private/captions-001 \
  --base-artifact dist/downloaded/wikipedia-ja.ja.normalized.zip \
  --output data/private/citation-collection-001 \
  --ja-punct-model /path/to/local/japanese-punctuation-onnx \
  --ja-punct-threshold 0.35 --boundary-cache data/private/boundary-cache

mise run verify-tubelex-collection -- \
  --collection data/private/citation-collection-001 \
  --base-artifact dist/downloaded/wikipedia-ja.ja.normalized.zip --deep

mise run search-tubelex -- --collection data/private/citation-collection-001 \
  --query '図書館' --limit 250 --stats
```

Offsets count eligible unique CSV candidates, and limits count acquisition
attempts. Removed/private videos and missing manual tracks may reduce the
successful batch size. At five seconds between metadata requests, 100,000
uncached attempts already require at least about 5.8 days; parallel requests are
not a shortcut implemented here. Use one writer per acquisition cache, prediction
cache and collection. Downloading the captions remains separate from rebuilding.

The builder writes an immutable private plan bound to the base checksum,
snapshot identities/order, options, processing implementation, model bytes and
applicable runtime versions. Duplicate videos across snapshots are rejected.
Each shard is built in a fresh staging directory, deeply verified, closed and
renamed into place. The collection completion manifest appears only after all
planned shards are complete. Rerun the identical command after an interruption:
completed shards are verified and reused; only an unfinished shard is rebuilt.
Each installed shard has a `binding.private.json` record covering the full plan
profile and checksums of its index, both manifests and reference export. Resume
checks those bytes and closed SQLite state, without parsing the entire citation
export again. Before installing or reusing a shard, the builder also checks its
exact boundary options, model identity, processor, snapshot and base against the
plan. The reader checks each receipt's expected build identity before opening it,
using stored model descriptors without requiring model assets or inference
runtimes on the serving machine. A profile seal detects accidental mixing with
shards from another implementation/runtime profile. These checksums establish
consistency, not producer authentication: someone able to rewrite all artifacts
can also rewrite their checksums. The explicit verification command still
validates the export, and `--deep` still recomputes source coverage and filter bits.
Completed prediction offsets are reused too. Handled failed staging directories
move to Trash when possible; retained `.partial-*` directories are never complete
shards. An already completed collection can be verified/reopened idempotently.

Changing the plan requires a fresh collection destination. This is shard-level
resume, not appending to a live SQLite database or merging incompatible processor
revisions. Existing standalone sidecars are not silently adopted. Completed
collections remain usable after transfer without the original snapshot/model
paths; those paths in the private plan are build provenance, not serving inputs.
All collection payloads and manifests remain private and outside public packaging.

```python
from pathlib import Path
from manabi_sentence_db.tubelex_batch import TubelexCollectionReader

with TubelexCollectionReader(
    Path("data/private/citation-collection-001"),
    timeout_ms=1000, max_decoded_chunks=2048,
    max_open_shards=8, max_filter_bytes=16 * 1024**2,
) as reader:
    references = reader.search("食べました", limit=250)
```

The reader keeps at most eight connections by default and a separate bounded
16 MiB filter cache. Warm impossible literals can skip rejected shards without
opening their databases. Filter memory on open readers is also bounded by the
8 MiB per-shard limit; the separate cache adds at most its configured allowance.
A single deadline and decode budget cover the whole request, including later
shards; later errors discard earlier matches. Results are deterministic first
matches in snapshot order, capped at 250, rather than a relevance-ranking layer.
Use one reader per owning worker/thread, verify before activation, and close and
reopen readers when replacing a complete immutable collection.

## Independent private boundary review

```sh
mise run prepare-tubelex-review -- \
  --snapshot data/private/captions-000 --snapshot data/private/captions-001 \
  --output data/private/review.private.json.zst --per-video 4 --window-chars 200 --max-videos 20
```

This uniformly samples at most twenty videos by default, then samples text
windows within each selected video, independently of the segmenter and its
predictions. `--max-videos` accepts 1..1000; the input candidate inventory is capped
at 120,000. Counts report both available and sampled videos. Window offsets are
sampled before context and origins are hydrated, avoiding repeated full-origin
scans for every possible window. The compressed private packet includes
context, codepoint core ranges, cue timing and original normalized streams.
Scoring uses the full original stream, once per stream, rather than predicting
on cropped windows. The packet contains copyrighted text and must not be
published or copied into plaintext intermediates. It is not a content artifact.
Packet construction checks the 32 MiB decoded size incrementally; reduce the
sample size if it exceeds that limit. Oversized streams are rejected before
copying their complete origin metadata into the packet.

Supply a separate compressed JSON label file, for example:

```json
{
  "packet_sha256": "checksum-returned-by-prepare",
  "reviewer_type": "human-text-only",
  "cases": [
    {"id": "case-id-from-packet", "boundaries": [123, 175], "uncertain": [146]},
    {"id": "another-case-id", "abstain": true, "reason": "Audio needed"}
  ]
}
```

Offsets are exact Unicode codepoint positions in each case's `text`, strictly
inside its `core_start` / `core_end`; they are not bytes or times. Mark uncertain
boundary positions explicitly, or abstain with a reason. Declare the actual
review method: `human-text-only`, `human-audio-verified`, or
`assistant-text-only`. The scorer binds labels to the packet checksum and rejects
unknown/duplicate cases and invalid offsets. Uncertain points are excluded from
boundary comparisons, and abstentions remain visible in coverage counts.

```sh
mise run score-tubelex-review -- --packet data/private/review.private.json.zst \
  --labels data/private/review-labels.private.json.zst
mise run score-tubelex-review -- --packet data/private/review.private.json.zst \
  --labels data/private/review-labels.private.json.zst \
  --ja-punct-model /path/to/local/japanese-punctuation-onnx --ja-punct-threshold 0.35
```

`--legacy-punctuation-policy` supplies a pre-refinement comparison. Reports contain
aggregate/per-video precision, recall, F1 and review coverage, with no caption
strings. Freeze the policy/threshold before evaluating new videos. These scores
measure annotated text boundaries; they do not establish exact playback timing,
human accuracy, source factual reliability, or human authorship of manual tracks.

## Why the public substring index is not extended

A suffix/FM index encodes enough text structure for substantial reconstruction;
a public suffix document array is not a copyright barrier. Positional n-grams
can expose most or all of the text through overlap. Non-positional n-grams still
disclose vocabulary and candidate phrases and cannot independently verify all
arbitrary-length exact substrings. Hashing small Japanese character grams does
not help: the candidate universe is enumerable. Compression, contentless FTS and
encryption with a published key likewise do not remove the underlying material.

Therefore this extension intentionally publishes no transcript-derived index.
Users can reconstruct their own private sidecar where permitted. A service can
query a private index and return playback references, but unrestricted substring
queries and exact hit oracles can themselves permit text reconstruction. Any
public integration needs query-abuse controls, restricted result/count exposure
and a permission decision; this local reader is not evidence of a legal safe
harbor. No technical transform here guarantees a right to distribute somebody
else's transcript or a lossless representation of it.

## Validation

`mise run check` includes synthetic offline fixtures for cross-cue sentences,
unpunctuated pause boundaries, punctuation-only mode, quoted clauses, repeated
overlapping cues, timing rounding, automatic-translation rejection, cache reuse,
checksum failures, base compatibility, short and long literal searches,
sentence-boundary isolation, text-free exports and output path separation.
It never acquires real YouTube captions in CI.

An independent authored Unicode fixture compares every 1..8-codepoint substring
with explicit sentence membership. It covers quoted punctuation, NFC accents,
emoji, supplementary Japanese characters, fullwidth Latin, case sensitivity and
literal FTS punctuation. Separate regressions cover multi-sentence cues, author
cue-ID prefixes and invalid query types.

It also checks malformed manifests/metadata, budget cancellation in Python and
SQLite, reader reuse after cancellation, discarding partial results, compaction,
and restarting an interrupted build from the existing snapshot into fresh output
directories. An incomplete build has no completed manifests and cannot be opened
as a complete index. Partial task-owned directories may be moved to Trash after
inspection; rebuilding never requires acquiring the captions again.

An exploratory seven-video TUBELEX sample covered education, how-to, people/blogs,
news, science/technology, gaming and entertainment. Two tracks had no terminal
punctuation and mostly/exclusively zero cue gaps. The former per-sentence builder
retained only 8.2% and 0% of their text. These observed shapes are now represented
by original synthetic fixtures, without committing copyrighted captions. Full
indexed coverage is a separate measure from sentence-boundary quality; SaT still
requires Japanese subtitle evaluation. TUBELEX's published human evaluation also
contains synthesized speech and occasional audio/subtitle language mismatches,
so an uploader-provided track does not establish human speech or original audio
language.


## Reassessment: verification, measurements and independent review

The selective mixed-punctuation policy stays unchanged. Running inference on
every punctuated span or globally forbidding quote splits is not justified by
the small assistant-labelled evaluations. Previously inspected holdouts are
exploratory evidence; do not tune against them and then call them held out.

The deep verifier now reports `posting_verification: complete-term-document-v1`
and text-free per-index posting counts. It checks the full expected posting set,
not just the existence of each chunk's first-character posting. Existing schema-7
artifacts can be reverified without changing their storage format. Collection
plans bind the implementation hashes, so changing build code still requires a
fresh collection destination; compressed snapshots and compatible model-offset
caches remain reusable. Completed resume retains the full input-caption integrity
scan and sealed-shard hash checks. No guarantees were removed to accelerate it.

Reproduce phase measurements offline, always with a fresh private output:

```sh
mise run benchmark-tubelex-pipeline --   --snapshot /path/to/snapshot-a/manifest.json   --snapshot /path/to/snapshot-b/manifest.json   --base-artifact /path/to/downloaded-release.zip   --output /path/to/new-private-benchmark

mise run benchmark-tubelex-filter-cache -- --output /path/to/new-private-cache-benchmark
```

The pipeline runner measures file hashing, compressed caption/index decoding,
optional inference, deep shard verification and sealed-shard verification.
It compares cold prediction-cache builds, fresh warm-cache rebuilds, completed
resume and controlled interrupted resume. Nested inclusive times overlap;
exclusive times account for the end-to-end total. Stored shard build stats describe
the original build, not inference newly performed during resume. With optional
`--ja-punct-model` and `--ja-punct-threshold`, use the provisioned model runtime;
the runner downloads nothing. The default-cache runner is a synthetic byte/cache
component test, not a caption corpus or a production latency benchmark.

Collection diagnostics now include filter-cache hits/misses/evictions, reader
opens/reuses and examined shards. The dedicated filter cache remains bounded at
16 MiB by default, independently of the at-most-eight open readers. Open readers
also retain their own filter references; the cache limit is not a process-RSS cap.
The current 20-video sample fits comfortably. Synthetic working sets larger than
the budget reproduce cyclic scan thrashing; production-size workload evidence is
still needed before changing the cache layout or admission policy.

For future search integration, collections support opt-in video diversity:

```sh
mise run search-tubelex -- --collection /path/to/collection   --query 'です' --limit 250 --selection diverse --stats
```

`TubelexCollectionReader.search(..., selection="diverse")` keeps a bounded
250-record pool and favors a first result from each video before second results.
Query-stable video ordering makes selection reproducible across shard order.
It visits all retained candidates under the same shared deadline/decode budget;
expiration discards all results. Scanning more candidates can cost more than the
unchanged default `selection="first"`. The Django integration is separate; this
option is not a claim about semantic ranking or a change to public-site defaults.

Prepare new sentence-review cases without predictions:

```sh
mise run prepare-tubelex-review -- --snapshot /path/to/new-snapshot   --exclude-packet /path/to/previous-review.private.json.zst   --output /path/to/new-review.private.json.zst
```

Video-level exclusion is the default. Explicit `--exclude-scope windows` instead
selects nonoverlapping context windows in previously seen videos; these are not
a new-video holdout. Packets and scoring reports retain the exclusion scope and
evaluation role. Sentence labels remain independent of model predictions and
must declare assistant text, human text, or human audio review.

Playback quality has a separate text-free packet and scorer:

```sh
mise run prepare-tubelex-playback-review -- --references /path/to/references   --output /path/to/playback.private.json.zst --max-cases 40
mise run score-tubelex-playback-review -- --packet /path/to/playback.private.json.zst   --labels /path/to/listening-labels.private.json.zst
```

Playback labels bind the packet checksum, declare `human-audio-verified`, and
confirm `listened: true` per rated case. Rate `start` and `end` independently as
`clean`, `early`, `late` or `unclear`; rate `complete_sentence` and `useful_context`
as true/false/null, or abstain with a reason. A clean edge means no audible cut;
an early start/late end includes extra material, while a late start/early end
cuts wanted material. These counts are not sentence-boundary F1. Explicit reviewer
declarations are provenance, not proof that listening occurred. No audio download,
bulk alignment, generated transcript, storage-engine replacement or boundary-policy
expansion is part of this reassessment.
