# Manabi Sentence DB

An open, attributed example-sentence corpus, beginning with contemporary Japanese.
The repository contains source configurations, schemas, a Python pipeline, and
small original test fixtures. Downloaded source text and generated corpora are
**build artifacts, not committed YAML**. A search engine or learning interface
belongs in a separate project.

The build keeps acquisition separate from processing:

1. **Snapshot** an explicitly selected upstream source. Record its exact bytes,
   hashes, source configuration, license, and retrieval time.
2. **Build** canonical YAML from that snapshot, entirely offline.
3. **Compile** validated YAML into SQLite, also offline.
4. **Package** bounded YAML ZIP archives and per-source SQLite Zstandard downloads
   with catalogs, attribution, provenance, schemas, and checksums.

Revising extraction logic never causes an upstream download. Missing or corrupt
inputs fail; they are not automatically replaced from the network.

## Quick start

Install [mise](https://mise.jdx.dev/getting-started.html), then:

```sh
mise install
mise run check
mise run demo -- --output build/demo
```

The demo uses synthetic Japanese sentences and requires no corpus download. Tool
installation may use the network. Once the environment is installed, all build,
verification, database, and packaging commands operate offline. The project uses
`uv run --locked` and the committed `uv.lock`, rather than a fresh unpinned `uvx`
environment for each command.

### One-page development snapshots

```sh
mise run snapshot -- --source wikipedia-ja --mode sample \
  --title 日本語 --output data/snapshots/wikipedia-sample

mise run build -- --snapshot data/snapshots/wikipedia-sample/manifest.json \
  --output build/wikipedia-sample

mise run build-db -- --build build/wikipedia-sample \
  --output build/wikipedia-sample.sqlite3

mise run package -- --build build/wikipedia-sample \
  --output dist/wikipedia-sample
```

`package` compiles a SQLite database for each source from the canonical YAML;
the standalone `build-db` command is useful when a consumer wants one combined
database. No search index or Japanese tokenizer is bundled into these databases.

`snapshot --source all --mode sample` acquires the configured Wikimedia examples
serially. It explicitly skips Tatoeba, which supplies language exports rather
than this page API. Every sample or limited build is labeled `sample` in the
corpus and release catalogs.

### Complete exports and optional translations

```sh
mise run snapshot -- --source wikivoyage-ja --mode full --date 2026-10-01 \
  --output data/snapshots/wikivoyage-2026-10-01

mise run snapshot -- --source tatoeba-ja --mode full --translations en \
  --output data/snapshots/tatoeba-current

mise run build -- \
  --snapshot data/snapshots/wikivoyage-2026-10-01/manifest.json \
  --snapshot data/snapshots/tatoeba-current/manifest.json \
  --output build/japanese

mise run package -- --build build/japanese --output dist/japanese
```

Choose an actually available Wikimedia export date; the example is a verified
October 2026 export. A source exports its own version/date, while `retrieved_at`
records when this project downloaded it. Tatoeba's mutable weekly exports have
no date selector: the snapshot pins their downloaded bytes. The first adapter
supports optional English translations; the schema permits any language and
multiple translations per sentence.

Use `--source all --mode full --date YYYY-MM-DD` to acquire all configured
sources, with the date applied to Wikimedia. This includes a multi-gigabyte
Wikipedia download. For development, `--max-files` limits Wikimedia export chunks
and labels the snapshot `partial`; `build --max-documents` limits processing
without any source request. A single Wikipedia chunk can still be several GB.

Repeating the same local snapshot request reuses verified existing files without
contacting upstream. `--refresh` downloads a complete candidate snapshot before
comparing its identity; it does not use conditional HTTP requests or ETags. A
changed snapshot is written to a new ID-suffixed directory, preserving the
previous one. The command prints the actual manifest path. A failed `all`
request reports which sources failed and preserves completed snapshots.

## Included sources

| Source ID | Text license | Acquisition |
| --- | --- | --- |
| `wikipedia-ja` | CC BY-SA 4.0 for covered text | Current-revision MediaWiki Content File Exports, or selected API pages |
| `wikivoyage-ja` | CC BY-SA 4.0 for covered text | Same adapter; practical full-source development input |
| `wikinews-ja` | `LicenseRef-Wikinews-JA`: historical BY 4.0 / BY 2.5 / BY 2.1 Japan notices retained | Explicit archived `pages-articles` export, or selected API pages |
| `tatoeba-ja` | CC BY 2.0 **France** | Detailed Japanese TSV, tags, optional English/direct-link TSV |

See [source research and admission decisions](docs/sources.md) for primary
licensing evidence, source-specific exceptions, and approximately thirty
researched source families. Priorities for future adapters include
RealPersonaChat, NICT Kyoto, ALT's parallel corpus, JMultiWOZ, ASDC, and Global
Voices Japanese. They are researched candidates, not enabled downloads.

Wikimedia's new export checksum manifest is the completion signal. The project
does not silently fall back to a different dump format when an export is absent.
Six legacy current/history/stub jobs are being retired; `pages-articles` is
explicitly outside that retirement, and remains the configured Wikinews archive
path. [Wikimedia export documentation](https://wikitech.wikimedia.org/wiki/MediaWiki_Content_File_Exports)
and [migration scope](https://wikitech.wikimedia.org/wiki/Legacy_content_dumps_sunset).

## Data model and output layout

Canonical YAML is a stream of bounded article/document records, grouped by
language and source. Each record carries title, original URL, page/sentence ID,
revision/history links where available, license, attribution, source categories,
and a list of sentences. Keeping document metadata once avoids repeating the
same attribution on every sentence.

YAML shards are capped at 500 documents or approximately 4 MiB by default. A
single large document can exceed the shard target, up to a 32 MiB record bound.
These are artifact buckets, not editorial categories or stable page addresses.
Identity comes from record IDs and source IDs, independent of the directory
layout. The document index maps IDs to shard paths and positions.

| Artifact | Purpose |
| --- | --- |
| `yaml/<language>/<source>/<number>.yaml` | Canonical multi-document YAML, streamed one record at a time |
| `documents.jsonl` | Lightweight document ID/title → shard/position catalog |
| `catalog.json` | Inputs, scope, processor/runtime versions, options, counts, hashes |
| `provenance/*.snapshot.json` | Exact immutable input manifests with source/license metadata |
| `licenses.json` | Licenses and notices used by included text and translations |
| `*.yaml-*.zip` | Bounded bundles with a ZIP central directory and individually extractable YAML shards |
| `*.sqlite3.zst` | Per-source SQLite database compressed with Zstandard |
| `*.sqlite3.zst.partNNNN` | Ordered pieces when a compressed database exceeds the asset budget |
| `release.json`, `SHA256SUMS` | Download inventory, ordered parts, compressed and restored hashes |

ZIP provides convenient listing and selective extraction of **shards**. A
consumer reads the external index, extracts one small shard, then selects its
document. Zstandard is used for SQLite downloads, where the whole database is
normally restored; a generic `.zst` stream is not advertised as a random-access
archive. For split SQLite downloads, concatenate the listed parts in order,
decompress once, and verify the uncompressed hash in `release.json`.

Duplicate text remains as separate occurrences with its original source and
license. Exact normalized UTF-8 text hashes let consumers group duplicates
without discarding attribution. NFC normalization and other transformations are
recorded; source text is not paraphrased by an LLM.

The [schema guide](docs/schema.md) explains stable IDs, translation provenance,
SQLite tables, and future link-only text-fragment/media selectors. The
[record schema](src/manabi_sentence_db/schemas/record.schema.json) is distributed
with releases. Unknown fields, duplicate YAML keys, aliases, invalid licenses,
contradictory identities, and modified artifacts fail validation.

## Selection and content policy

The initial corpus targets contemporary Japanese. It excludes Aozora and
classical-text corpora for now. The Wikimedia extractor keeps main-namespace
prose, excludes redirects and marked copyright/deletion problems, and removes
lists, tables, references, media, and marked quotations. Unknown inline markup
invalidates the affected sentence rather than joining words across a removed
template. It also omits sentences with Japanese corner-quoted passages, including
some title mentions, as a conservative first-version tradeoff.

Shared rules reject malformed, very short/long, obviously archaic, or non-Japanese
units. Tatoeba's correction/archaic/unnatural tags additionally influence
selection. A small transparent lexicon annotates sexual content, violence,
self-harm, and profanity. Sexual-content flags are excluded by default;
`--exclude-flag violence` adds an exclusion and `--include-sexual-content`
changes the default. Categories and upstream tags remain available for consumer
filters.

Every admitted sentence is marked **`unreviewed`**. The era and content rules are
heuristics, not guarantees of modern usage, correctness, or child suitability;
they can both miss material and reject harmless prose. Translations also require
quality review. Extraction omissions happen before shared-filter counters, so
those counters do not describe every upstream page or passage. The build report
records decisions it can count without claiming a manual review took place.

## GitHub operation and scale

PR CI runs source/schema validation, linting, and offline regression tests with
synthetic fixtures. Two independent manual Actions workflows acquire snapshots
and build releases from stored snapshots. Source acquisition never runs on a
push, pull request, or schedule.

Merge the workflow files into the repository's default branch before their
**Run workflow** controls become available. Running them requires repository
write access. [GitHub's manual workflow requirements](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)

1. Run **Snapshot sources (manual)** with the desired source and scope. Enable
   `create_draft_release` to retain the raw snapshot for the later build workflow;
   otherwise the result is a seven-day workflow artifact. Save the snapshot
   release tag and catalog SHA-256 printed in the run summary. Review and
   **publish the raw snapshot draft** before using it in the build workflow.
2. Run **Build corpus from snapshot (manual)** with that release tag and catalog
   SHA-256. Reuse these inputs when changing processing logic; this workflow
   never requests source content again.
3. Enable `create_draft_release` in the build workflow when a corpus release is
   wanted. Review the resulting draft and publish it through GitHub. With the
   option disabled, the packaged corpus remains a seven-day workflow artifact.

Raw snapshots can be packed into content-addressed transport parts and kept in
draft GitHub releases. The build workflow downloads a selected stored snapshot,
checks a pinned catalog hash, restores it, and performs all corpus processing
offline. Optional release jobs create new **draft** releases without replacing
assets. The read-only build workflow requires a published raw snapshot release;
it cannot download a private draft. Local builds can use cached raw snapshots
or bundles downloaded by a maintainer without publishing them. Maintainers can
review and publish corpus drafts through GitHub.

The workflows support small sources on ordinary hosted runners and require a
provisioned self-hosted Linux runner labeled `self-hosted`, `linux`, and
`sentence-db` for full or partial Wikipedia exports. Select `self-hosted` in
the workflow's runner input; Wikipedia API samples can use `ubuntu-24.04`.
Local commands provide the same route. There is no assumption that GitHub's
ephemeral cache can permanently store a Wikipedia snapshot. For more languages
or long-term raw retention, move the same verified bundles to object storage;
this version does not provision or require a paid storage service.

See [operations and release procedures](docs/operations.md), including current
GitHub limits, disk sizing, snapshot transport, checksums, and publication.

## License and contributions

Software is [MIT licensed](LICENSE). Imported text retains its own source license
and notices; the MIT license does not apply to those sentences. Commercial use
can still require attribution and ShareAlike compliance. See
[data licensing](DATA_LICENSES.md) and [contribution guidance](CONTRIBUTING.md).
