# Snapshots, offline builds, and releases

## Balanced Wikimedia expansion from cached inputs

Select a reproducible mixture before expensive extraction or linguistic indexing:

```sh
mise run select-wikimedia -- \
  --snapshot data/snapshots/wikipedia-full-20261001/manifest.json \
  --output data/wiki-selection --per-topic 1000 --general 2000 --progress
mise run build -- \
  --snapshot data/snapshots/wikipedia-full-20261001/manifest.json \
  --document-selection data/wiki-selection/selection.json \
  --output data/wiki-build --format jsonl --shard-compression zstd --progress
```

The selector verifies the cached snapshot and streams its content once, retaining
at most the requested metadata in memory. It makes no network requests and does
not create a plaintext corpus. XML holds one decoded page at a time; saved API
responses are decoded as whole JSON files, as in the regular adapter. The same
1,000,000-character page limit applies before category routing. Ten topic quotas
plus a general quota have a combined ceiling of 50,000 pages. Existing output
directories and symlink paths are refused; the output parent must already exist.

`wikimedia-balanced-metadata-v1` routes biographies, named organizations and
creative works to the general mixture instead of allowing incidental categories
to dominate practical topics. It keeps separate science and history allocations;
subject alone does not prove difficult, archaic or poor Japanese. Lists and
disambiguation pages are excluded. All routing remains a heuristic, including
category extraction from wikitext. The report includes bounded title/category
evidence, counts, the exact implementation hash, seed and selection digest.
Counts describe input page units, not an independently deduplicated article census.
Repeated retained IDs do not consume quota; conflicting retained metadata fails.

The smallest snapshot/seed/page-ID hashes win within each topic, independently
of input order. Raising quotas with the same seed retains earlier selected IDs.
Changing `--seed` creates another sample. Topics with insufficient pages remain
underfilled; quotas are not silently reassigned. Default limits select at most
12,000 pages, not 12,000 quality-approved works. The allowlist is bound to exactly
one snapshot and is written last. An interrupted scan leaves no completed
selection and must be retried in a fresh directory, using the same cached inputs.

Run the normal extractor, license checks and sentence-quality gates afterward;
metadata selection grants no human-review state or rights and does not activate
serving data. Inspect retained and rejected examples and measure final compressed
artifact growth before adding the selected works to an application. A serving
budget may require a smaller or staged addition. Corpus processing jobs on Alex's
development machine remain capped at 0.25 CPU and one worker; do not overlap a
second heavy scan with an existing corpus refresh or increase its quota.

The repository stores code, schemas, reviewed source configuration, and original test fixtures. Downloaded source archives, generated YAML, SQLite databases, and release packages stay outside Git. `data/`, `build/`, and `dist/` are ignored.

## The boundary between acquisition and processing

`snapshot` is the only command that requests upstream content. It creates an immutable manifest recording the entire source configuration, acquisition time, upstream date, request scope, original URLs, byte lengths, and SHA-256 hashes. The snapshot identity depends on the requested inputs and their bytes, not the local directory or acquisition clock.

`build`, `build-db`, `package`, `verify-snapshot`, `snapshot-pack`, and `snapshot-unpack` operate on local files. They never fetch missing source data. A processing change therefore needs a new build directory, not another Wikipedia download. Tool/dependency installation by `mise` or `uv` is separate from source acquisition; after installation, `uv run --offline --locked …` can enforce offline dependency resolution too.

```sh
mise install
mise run check

# A few current pages, with the exact returned revision IDs retained.
mise run snapshot -- --source wikivoyage-ja --mode sample \
  --output data/snapshots/voyage-sample

# These stages do not visit Wikivoyage.
mise run build -- --snapshot data/snapshots/voyage-sample/manifest.json \
  --output build/voyage-v1
mise run package -- --build build/voyage-v1 --output dist/voyage-v1
```

The snapshot command prints the actual manifest path on stdout; progress and skipped-source messages use stderr. Retain that path. A repeated identical snapshot request verifies the existing local bytes and returns immediately without contacting the source. A changed source configuration or request requires a different output directory or `--refresh`.

`--refresh` downloads a complete candidate snapshot before comparing its identity with the existing one. It does not use conditional requests, ETags, or a lightweight upstream change probe. If the source bytes and request are unchanged, it returns the existing snapshot after that download. If changed, it writes an ID-suffixed sibling directory and preserves the old snapshot. Use an ordinary repeated request or restore a saved bundle when no source update is wanted. Builds and packages likewise use new output directories; they do not silently replace a published artifact.

### Full and partial snapshots

```sh
# Download the specific available monthly export; there is no implicit latest fallback.
mise run snapshot -- --source wikivoyage-ja --mode full --date 2026-10-01 \
  --output data/snapshots/voyage-2026-10-01

# Explicitly selected chunks still use the production dump parser.
mise run snapshot -- --source wikipedia-ja --mode full --date 2026-10-01 \
  --max-files 1 --output data/snapshots/wikipedia-first-chunk

# Tatoeba's language exports are current files, identified by their captured hashes.
mise run snapshot -- --source tatoeba-ja --mode full --translations en \
  --output data/snapshots/tatoeba-ja-en
```

`--max-files` limits compressed export chunks, not pages or bytes. A single Japanese Wikipedia chunk can exceed 2 GiB. Its resulting snapshot is labeled `partial`; it must not be described as the full source. For a lightweight check, prefer `--mode sample --title 東京` or the offline `mise run demo`. Full Tatoeba language exports have no one-page equivalent: Tatoeba rejects sample mode, and `--source all --mode sample` explicitly skips it. `--source all --mode full --date …` acquires each configured source serially; the date applies to Wikimedia, while Tatoeba retains its current export hashes.

`build --max-documents N` limits processing after a snapshot exists. It does not make acquisition cheaper, and the build catalog labels the result as a sample. For production, omit both acquisition and processing limits.

### Wikimedia's 2026 export migration

The primary bulk adapter uses [MediaWiki Content File Exports](https://wikitech.wikimedia.org/wiki/MediaWiki_Content_File_Exports):

```text
https://dumps.wikimedia.org/other/mediawiki_content_current/{wiki_id}/{YYYY-MM-DD}/xml/bzip2/SHA256SUMS
```

The checksum manifest is published only when the complete export is available. We verify its SHA-256 for every selected compressed XML file. Do not infer readiness from the presence of some data files. Beginning with November 2026, exports are expected roughly 7–10 days after the month starts to allow suppression processing. [Official migration notice](https://wikitech.wikimedia.org/wiki/Legacy_content_dumps_sunset)

Six legacy Wikimedia current/history dump jobs are being retired in January 2027, with staged interruptions beginning October 26, 2026. The official sunset notice explicitly excludes `pages-articles.xml.bz2` from that retirement. Japanese Wikinews currently has an empty new-export directory but an available October 2026 legacy article dump. Its reviewed source configuration therefore explicitly selects the continuing `legacy-articles` export: the adapter verifies the dated `articlesdump` job is complete, checks its upstream SHA-1 and size, and records a new SHA-256. It does not silently switch formats, dates, mirrors, or license assumptions. If the archive becomes unavailable, restore an already preserved snapshot or provide a new reviewed acquisition configuration.

Downloads use an identifying project User-Agent, serial requests, at least one second between request starts, bounded retry/backoff, and atomic files. Interrupted file transfers restart into a fresh temporary file and must pass the same expected checksum. API samples use `maxlag=5` and handle MediaWiki's HTTP-200 `maxlag` errors. A long `Retry-After` stops the request with an instruction to retry later rather than ignoring the server's requested pause. Set `SENTENCE_DB_USER_AGENT` locally or the `SENTENCE_DB_USER_AGENT` repository variable to add an operator contact. [API access policy](https://www.mediawiki.org/wiki/Wikimedia_APIs/Access_policy) · [Maxlag documentation](https://www.mediawiki.org/wiki/Manual:Maxlag_parameter)

## Raw snapshot storage

The manifest is a reproducibility record; it cannot replace the input bytes. Keep raw snapshots on durable local storage or preserve their transport bundles. Upstream URLs may disappear. A stored snapshot allows rebuilding a past corpus even after a source removes an old export.

```sh
mise run snapshot-pack -- --snapshot data/snapshots/voyage-2026-10-01/manifest.json \
  --output dist/raw-voyage-2026-10-01

# Copy/download every part and bundle.json into this local directory first.
mise run snapshot-unpack -- --bundle dist/raw-voyage-2026-10-01/bundle.json \
  --output data/restored/voyage-2026-10-01
```

Transport uses already-compressed source files as bytes. It splits them into content-addressed parts of at most 1 GiB by default, with an ordered part list and both per-part and whole-file SHA-256 hashes. It does not recompress BZip2 archives. Reconstruction is offline, verifies every byte, rejects unsafe paths, and publishes the restored snapshot atomically. A missing or corrupted part fails; no source redownload is attempted. Part files are transport pieces, not individually decompressible BZip2 files.

This split is necessary now: HEAD checks of the October 2026 Japanese Wikipedia current export returned three files of **2,792,196,769**, **2,596,839,373**, and **227,131,541** bytes. The first two exceed GitHub's per-asset limit. The corresponding Japanese Wikivoyage export was **8,152,108** bytes. These observations are planning examples, not hard-coded expected source sizes.

### Storage choices

| Storage | Intended use | Boundary |
| --- | --- | --- |
| Git repository | Code, schemas, source catalog, fixtures | No raw or generated corpus bytes |
| Actions cache | Disposable dependency/tool acceleration | Never the only snapshot copy |
| Actions artifacts | Seven-day workflow previews and job handoff | Temporary; not the public download contract |
| GitHub Releases | Versioned derived corpus; optional raw snapshot bundles | Each asset below 2 GiB; up to 1,000 assets |
| Local disk or object storage | Large durable raw snapshots and growing multilingual corpora | Retain manifests and verify content hashes when copying |

GitHub [documents](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases) no aggregate release-size or bandwidth quota, but its [acceptable-use policy](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies) still permits action on excessive infrastructure usage. Do not treat release storage as an unlimited backup service. For sustained large-scale or multilingual acquisition, preserve the same manifest/part contract in durable object storage rather than relying on source re-downloads. This implementation does not provision a paid storage service.

Actions cache defaults to 10 GB and can evict entries unused for seven days; larger configured allowances can incur charges. Artifacts expire and require authenticated access. Neither is a durable public corpus origin. [Cache policy](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching) · [Artifact retention/access](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts)

## GitHub Actions

The workflow files must first be merged into the repository's default branch.
GitHub then exposes **Run workflow** in the Actions tab to users with repository
write access; choose the branch to run and supply the inputs there.
[Manual workflow requirements](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)

### 1. Snapshot sources (manual)

Run `snapshot.yml` only when new upstream bytes are wanted. Select one source or `all`, sample/full scope, an explicit Wikimedia export date for full acquisition, and optional English translations. It serializes acquisition across workflow runs and uses the same CLI as a local machine.

The workflow exports a flat bundle containing `<source-id>.bundle.json`, content-addressed raw parts, and `snapshot-catalog.json`. The job summary prints the catalog's SHA-256. With `create_draft_release` enabled, a separate job creates a new draft prerelease named `snapshot-<run-id>-<attempt>` and uploads these assets. Existing releases/assets are never overwritten. Without that option, the result is only the seven-day workflow artifact.

Enable `create_draft_release` when planning to use the build workflow: that workflow accepts a stored release tag and catalog SHA-256, not a workflow artifact or run ID. Keep both values from the snapshot run summary. A new manual snapshot run explicitly acquires upstream bytes again; a fresh hosted runner does not recover the previous run's local snapshot cache. Reuse the stored release through the build workflow for repeated offline builds.

Review and publish the raw snapshot draft before using it with the build workflow. That workflow has a read-only token; GitHub restricts draft-release access, so an unpublished draft is not a supported input. Publishing raw snapshots publicly is an explicit maintainer decision; review the preserved source configuration, licenses, notices, and intended scope first. Local builds can instead use cached snapshots or bundles downloaded by a maintainer without publishing raw content. Processed corpus releases carry the extracted text's attribution and license information separately. [Draft-release visibility](https://docs.github.com/en/rest/releases/releases#list-releases)

If one source fails during `all` acquisition, successfully completed sources are still packed and uploaded as a seven-day artifact. The catalog marks the requested selection as incomplete, the workflow fails visibly, and no release draft is created. Inspect the error and retry only the failed source instead of downloading the successful sources again.

### 2. Build corpus from snapshot (manual)

Run `build-corpus.yml` with the **published** snapshot release tag and the exact catalog SHA-256 from step 1. This pins the input inventory rather than trusting a mutable tag alone. An inaccessible or draft tag stops with instructions to review and publish the raw snapshot release. The workflow downloads and checks the catalog, checks each bundle digest, restores the hashed raw bytes, then runs the offline YAML and packaging stages. It never contacts Wikipedia, Wikivoyage, Wikinews, or Tatoeba.

Enable `create_draft_release` to produce a draft `corpus-<run-id>-<attempt>` release. Review its counts, sample/full scope, licenses, and artifacts, then publish the draft through GitHub when ready. Source acquisition and processed corpus publication are independent manual actions; there are no scheduled downloads and a pull request cannot trigger either publication workflow.

With `create_draft_release` disabled, the packaged corpus is retained only as the `sentence-corpus` workflow artifact for seven days. Neither workflow publishes a draft automatically.

Both publication jobs have `contents: write`; acquisition/build/check jobs have only `contents: read`. Actions are pinned by commit and checkout does not persist Git credentials. No cross-repository deployment or search application is included.

### Capacity and large sources

Standard public Linux runners have [14 GB of documented storage](https://docs.github.com/en/actions/reference/runners/github-hosted-runners); hosted jobs have a [six-hour execution limit](https://docs.github.com/en/actions/reference/limits). Raw archives, transport parts, canonical YAML, temporary SQLite, and packaged output may coexist. Every Japanese Wikipedia bulk snapshot is therefore blocked on a standard hosted runner, including `--max-files 1`: a single compressed chunk can already exceed 2.5 GB and expands substantially. Use API sample mode for Wikipedia development on hosted runners.

For a Wikipedia bulk run, provision a trusted Linux runner labeled `self-hosted`, `linux`, and `sentence-db` with Git, `python3`, and the GitHub CLI installed, then choose `self-hosted` for the manual workflow; or run the same commands locally. These workflows do not register runners or purchase larger runners. The current implementation processes sources serially and streams XML; it does not implement a distributed chunk-processing matrix. Check actual free space before choosing a machine. Package processing uses one source's SQLite database at a time and removes that temporary uncompressed database after compression.

The acquisition/build jobs allow 350 minutes on standard hosted runners and 1,380 minutes (23 hours) on self-hosted runners. GitHub permits self-hosted jobs to execute for up to five days, but the workflow `GITHUB_TOKEN` expires after at most 24 hours; the shorter limit leaves time for authenticated artifact handoff. These limits are operational bounds, not measured Japanese Wikipedia processing times. [Execution limits](https://docs.github.com/en/actions/reference/limits) · [Job timeout and token lifetime](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idtimeout-minutes)

## Consumer formats

YAML is the canonical validated interchange layer. Bounded shards keep individual loads manageable; document IDs and the external index locate a document without decoding the full corpus. The public package uses source/language ZIP archives with separately compressed YAML members. ZIP supports listing and extracting selected members; the external catalog identifies the relevant archive. [Python ZIP documentation](https://docs.python.org/3/library/zipfile.html)

The package step compiles each source's SQLite from those YAML shards, compresses it with Zstandard, and splits an oversized compressed stream into bounded transport parts. `release.json` lists the required order and original SQLite SHA-256. Concatenate all listed parts before decompressing. Plain `.zst` is not a ZIP-style member index; the [seekable Zstandard extension](https://github.com/facebook/zstd/blob/dev/contrib/seekable_format/zstd_seekable_compression_format.md) is not part of this format.

To produce one local SQLite database across several source snapshots:

```sh
mise run build -- --snapshot data/snapshots/voyage-2026-10-01/manifest.json \
  --snapshot data/snapshots/tatoeba-ja-en/manifest.json --output build/combined
mise run build-db -- --build build/combined --output build/combined.sqlite3
```

Record-level licensing and attribution remain attached even in a combined database. A matching text hash is useful for deduplication, but it does not erase independently licensed source occurrences or translation attribution.

## Reproducibility and refresh policy

`uv.lock` pins Python dependencies. Build metadata records the processor version/code identity, input snapshots, filtering configuration, and runtime versions. ZIP member order, dates, and permissions are fixed. Canonical record and shard hashes provide the stable content comparison; SQLite binary bytes may differ across SQLite runtime versions, so compare artifacts within the documented runtime when binary identity matters.

Refresh a source only through an explicit snapshot operation. Keep snapshots needed for published versions and do not replace a release asset in place. If content must be removed or corrected, create a new snapshot/build and release with clear replacement metadata. The source and license review in [sources.md](sources.md) remains part of that decision.



## Additional sources and boundary rebuilds (processor 5)

Acquire the reviewed sources explicitly:

```sh
mise run snapshot -- --source jmultiwoz-ja --mode full --output data/snapshots/jmultiwoz
mise run snapshot -- --source stair-captions-ja --mode full --output data/snapshots/stair
mise run snapshot -- --source wikibooks-ja --mode sample --output data/snapshots/wikibooks-sample
mise run snapshot -- --source scp-jp-aptitude-ja --mode full --output data/snapshots/scp-aptitude
```

JMultiWOZ and STAIR reject sample/date/file-limit acquisition options because
those would mislabel the pinned complete archive. Use `build --max-documents 10`
for a development sample. Complete archives are verified against their reviewed
SHA-256 and byte length. STAIR image data is never requested.

Each curated narrative source uses its complete one-work allowlist. Its live page
must still match the reviewed title, author, license, revision and body hash; changes
require a new source review before acquisition succeeds.

Builds use exactly one snapshot per source. To apply publisher-unit segmentation
to existing Tatoeba/RealPersonaChat data, rebuild their retained raw snapshots
with processor 5; no source redownload is required. Use a new output directory,
review rejection counts and source-unit context, then repackage and rebuild the
private serving index. Keep old releases available by their original build IDs;
do not mix old and rebuilt snapshots of one source in a consumer index.

See [the source-unit contract](normalized-format.md#publisher-unit-segmentation)
for translation alignment and Unicode offset details, and
[vocabulary coverage](vocabulary-coverage.md) for comparisons that measure what
new sources add beyond repeated sentence text. These operations do not publish
or replace a live corpus automatically.


The curated narrative allowlist also includes `scp-jp-duck-merchant-ja`,
`scp-jp-id-photo-ja`, `scp-jp-fixed-point-ja`, and `scp-jp-shaving-ja`; snapshot each separately with
`--mode full`. Cached raw snapshots remain immutable. The STAIR adapter accepts
the legacy `stair-captions` role as well as the current `stair-tar` role so earlier
verified snapshot manifests can be rebuilt without modifying their identities or
redownloading the pinned archive. Both roles run identical member/identity checks.


## Compressed local intermediates

Use `build --format jsonl --shard-compression zstd` for bulk work. Shard budgets
still limit the uncompressed logical input, while catalogs record the stored
compressed sizes/hashes. The reader checks a single complete standard frame,
rejects trailing data and skippable frames, and bounds the decompression window
and each canonical record. It feeds one block at a time using the
[Zstandard format's block bound](https://github.com/facebook/zstd/blob/v1.5.7/doc/zstd_compression_format.md#blocks),
so each decoder call emits at most 128 KiB; the record buffer still has its
separate 32 MiB bound. Native Zstandard validates compressed blocks and checksums.
Release ZIPs preserve `.jsonl.zst`/`.yaml.zst` member names; `documents.jsonl`
continues to locate logical document positions within those shards.

Normalized export stages five Zstandard-compressed tables and an identity-only
SQLite ledger. It streams logical JSONL bytes into the portable ZIP and verifies
their hashes during copying. This avoids a full uncompressed normalized staging
copy. The ZIP still contains ordinary JSONL members and the same provenance.
An offline 3.22 MB Wikivoyage shard comparison favored Zstandard level 3 for
short-lived tables: 0.932 MB versus gzip level 3's 1.079 MB, with median compression
times of 0.0094 s versus 0.0355 s across three trials. This is a small phase
comparison, not a whole-build benchmark; evidence is outside Git in
`wikipedia-compressed-pilot-orujb597/compression-comparison.json`.


The shard reader retains an unfinished record in a mutable buffer and scans only
new bytes plus the delimiter overlap. It compacts once per compressed input chunk,
so long documents do not trigger repeated whole-record copying/scanning. On a
seeded 2.10 MB Unicode JSONL record compressed to 1.19 MB, three alternating trials
reduced median file decode/parse time from 0.249 s to 0.0112 s with identical rows.
The input chunk size, frame/record limits and corruption checks are unchanged.
This synthetic long-record comparison is separate from full-corpus timing;
reproduction functions and results are in `compressed-reader-buffering-pjpex1i3`.
