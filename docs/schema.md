# Corpus schema, identities, and consumers

Schema version 1 is a language-neutral content/provenance format. The initial
adapters select Japanese source text and optionally Tatoeba English translations.
It does not encode Japanese grammar-matching rules or a search engine's index.

The machine-readable contracts are
[`record.schema.json`](../src/manabi_sentence_db/schemas/record.schema.json) and
[`source.schema.json`](../src/manabi_sentence_db/schemas/source.schema.json).
Validation also checks cross-record identities, snapshot/source bindings,
license URLs/notices, exact text hashes, index positions, and output counts.

## Canonical YAML

A shard is a YAML stream, with `---` separating records. Each `document` record
contains shared provenance followed by its sentences. This keeps article-level
metadata once while bounding the number of files and the memory required to
load one record. Shards can be reorganized without changing logical identities.

This abbreviated example illustrates the structure; generated records contain
the actual IDs, hashes, and required fields:

```yaml
schema_version: 1
kind: document
id: doc_<stable-document-hash>
source_id: wikipedia-ja
snapshot_id: <immutable-input-hash>
native_id: '123'
language: ja
title: <original page title>
url: https://ja.wikipedia.org/?curid=123
license:
  id: CC-BY-SA-4.0
  url: https://creativecommons.org/licenses/by-sa/4.0/
attribution:
  text: <project and contributor credit>
  url: <page contributor-history URL>
revision:
  id: '456'
  timestamp: '2026-10-01T00:00:00Z'
  url: <permanent revision URL>
  history_url: <contributor-history URL>
tags: []
transformations:
  - wikitext-prose-extraction
  - sentence-segmentation
  - conservative-quotation-exclusion
  - NFC
  - edge-whitespace-trim
sentences:
  - id: sent_<stable-occurrence-hash>
    ordinal: 0
    text: <extracted original sentence>
    text_sha256: <SHA-256 of exact normalized UTF-8 text>
    tags: []
    content_flags: []
    review_state: unreviewed
    translations: []
```

Use strings for source IDs and upstream revision IDs. Language tags use a
lowercase two/three-letter primary subtag and optional BCP-47-shaped subtags,
such as `ja`, `en`, or `zh-Hant`. Use `ja`, not `jp`. The shape check is not a
complete language registry. Source-specific adapters decide how to segment or
assess each language; the generic schema does not promise equal extraction
quality for every language.

Source categories and editorial tags are retained as strings, with no inferred
JLPT level or native-speaker label. Content flags are limited heuristic
annotations. A missing flag is not a negative classification. Every generated
sentence currently has `review_state: unreviewed`.

## Translations and generation provenance

Each translation contains its own `language`, `text`, `text_sha256`, `id`,
`source_url`, `license`, and `attribution`. Optional `native_id` preserves the
translation's source key. There can be several translations in the same target
language. Translation text does not inherit the source sentence's license or
author automatically.

Optional `generation` describes how the text was produced:

```yaml
generation:
  kind: machine
  tool: example-translation-service
  model: provider/model-version
  version: <optional tool or pipeline version>
```

`kind: machine` requires a nonempty `tool`; `model` can preserve a provider's
standard model identifier. `kind: human` may include an `agent` credit when
known. When the generation method is unknown, omit `generation`. The pipeline
does not invent one based on a username, a source reputation, or a language-pair
link. The same optional structure is available for a source sentence if a future
source explicitly identifies generated text.

`alignment` is separate: `direct-link`, `human`, `machine`, or `unknown`. A
machine-aligned pair is not necessarily machine-translated. Tatoeba imports only
direct links, with `alignment: direct-link`, and leaves generation absent. These
links do not establish translation direction. No LLM calls or automatic
translations run in this version.

## Future external references

The alternate `kind: reference` schema intentionally has **no copied sentence
text**, sentence array, or asserted redistribution license. It carries source
identity, title, URL, attribution, language, and a locator. It shares the
document/snapshot identity model so a future reviewed citation adapter can be
added without pretending that a reference is freely licensed corpus text.

Supported locator shapes are:

```yaml
locator:
  type: text-fragment
  url: https://example.org/article#:~:text=selected%20text
```

```yaml
locator:
  type: media
  start_seconds: 42
  end_seconds: 49.5
```

Keep the ordinary canonical page/video URL in the record's `url`. A text-fragment
URL stores the browser selector separately; that URL can itself contain an
excerpt, so later citation admission still needs a rights policy. A media end
is an absolute time from the beginning, must follow the start, and is not a clip
duration. Times must be finite. The future application can convert selectors to
player-specific URLs. Browser support and a changing source page can affect
whether a selector resolves. [Text fragments](https://developer.mozilla.org/en-US/docs/Web/URI/Reference/Fragment/Text_fragments)
and [YouTube player parameters](https://developers.google.com/youtube/player_parameters).

This is schema/database support for later work. No external-citation crawler,
YouTube downloader, transcription, or player UI is implemented.

## Identity and duplicate text

Document IDs hash `(source_id, native_document_id)`. For sentence-first sources,
sentence IDs include the upstream sentence ID. For prose documents, sentence IDs
include the exact normalized text hash and its occurrence number within the
document. Inserting an unrelated earlier sentence therefore does not renumber
all later sentence IDs. Editing prose changes that sentence's identity; editing
an upstream sentence with its own stable ID retains the ID but changes its text
hash. Always identify an exact release with its build/snapshot ID too.

Identical repeated sentences in one article remain distinct occurrences. The
same text in two sources also remains distinct, with both sources' licensing
and attribution. `text_sha256` is an exact normalized-text comparison key, not a
claim that two similar sentences or translations mean the same thing.

Document and sentence IDs use a type prefix plus the first 128 bits of a SHA-256
over an unambiguous canonical JSON tuple. Raw input files, exact text hashes,
artifact hashes, and full snapshot identities use full SHA-256. Duplicate IDs
fail validation rather than overwriting an earlier row.

## SQLite

SQLite is compiled from validated YAML, with foreign keys, `STRICT` tables,
identity constraints, and an integrity check before the staged file becomes
visible. It uses a standalone DELETE-journal database; no WAL sidecars are
needed. Output paths must be new, so a failed rebuild preserves existing files.

| Table | Contents |
| --- | --- |
| `metadata` | Build catalog and SQLite runtime version |
| `sources` | Source IDs, languages, and complete configuration JSON |
| `snapshots` | Exact input manifests, bound to sources |
| `licenses` | License ID, URL, and preserved notice |
| `documents` | Article/title/source/revision/attribution metadata |
| `sentences` | Text, order, language, hash, review state, generation, tags/flags |
| `translations` | Translated text with independent attribution/license/generation/alignment |
| `sentence_tags` | Relational tag lookup |
| `sentence_content_flags` | Relational content-flag lookup |
| `external_references` | Future locator records without corpus text |

For example, display sentences with their required source credit:

```sql
SELECT s.id, s.text, d.title, d.url, d.attribution_text,
       d.attribution_url, l.id AS license_id, l.url AS license_url, l.notice
FROM sentences AS s
JOIN documents AS d ON d.id = s.document_id
JOIN licenses AS l ON l.id = d.license_id
WHERE s.language = 'ja'
ORDER BY d.id, s.ordinal
LIMIT 20;
```

Get optional translations by joining `translations.sentence_id = sentences.id`
and their own `license_id` to `licenses`. Do not display source credit as if it
were the translator's credit. Indexes support identities, document order,
language/text hashes, tags, flags, and translation relationships. Full-text
ranking, morphological tokenization, embeddings, and search hosting remain the
responsibility of a separate project.

## Reproducibility and integrity

Snapshots preserve byte hashes, requests, source configurations, upstream dates,
and retrieval timestamps. The build recipe includes the input snapshot IDs,
processor code fingerprint, Python/SQLite/dependency versions, and selection/
sharding options. Git revision and dirty-worktree status are recorded separately.
Build time is provenance, not an input to stable corpus identity.

The catalog hashes every shard, document index, license inventory, and preserved
snapshot manifest. Canonical validation checks counts, unique identities,
source/snapshot/license bindings, and the ordered document index. The pipeline
uses disk-backed uniqueness tracking to avoid retaining the whole corpus in RAM.
While writing shards and the document index, the builder separately hashes the
intended serialized bytes. It verifies closed temporary files against those
expectations, publishes them atomically, and verifies the complete artifact
catalog before publishing the build directory. Packaging validates the canonical
records and their ordered index again before producing release assets.

ZIP dates, permissions, and member order are fixed. SQLite binary identity is
qualified by runtime version; canonical YAML/text hashes are the primary content
comparison across environments. SHA-256 pins detect changed inputs or corruption;
they are not publisher signatures. Consumers should obtain their initial release
or catalog hash through a trusted channel.



## Original publisher units

Processor 5 adds optional sentence/occurrence `source_unit` metadata without
changing existing required fields. It retains a bounded original NFC utterance
or sentence record, exact codepoint offsets and original-unit translations when
one source record yields several sentences. Fragment-level translations remain
empty unless genuine aligned provenance is supplied by a future adapter.
See [the complete field contract](normalized-format.md#publisher-unit-segmentation).
