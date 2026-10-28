# Normalized corpus interchange (v2)

The CLI builds JSONL by default; `--format yaml` retains the same validated document
schema for inspection and hand authoring. The Python build API defaults to YAML for
compatibility with v0.1 callers. Source manifests remain YAML. Imported data stays
outside Git.

Every release also contains `<source>.<language>.normalized.zip`. Prefer this format
for new consumers. It contains UTF-8 JSONL tables:

- `sentences`: unique exact NFC text, language, SHA-256, stable content identity.
- `works`: documents, original URLs, independent license/attribution, revision,
  snapshot identity, optional actual publication date and authorship/origin.
- `occurrences`: source identity, sentence/work foreign keys, original ordinal,
  review/content flags, source range where available, previous/next admitted occurrence.
- `translations`: independent provenance, license, optional human/machine generation,
  sentence and occurrence foreign keys. Alignment does not establish authorship.
- `references`: text-free future external citations; never treated as licensed text.

`manifest.json` identifies version 2, build, scope, table counts, and SHA-256 of each
JSONL member. The ZIP also carries original snapshot manifests, licenses, and the
build catalog. ZIP members can be streamed individually; no full archive extraction
is necessary. Each source archive must remain below GitHub's 2 GiB asset limit;
packaging rejects oversized archives. Splitting normalized tables into multiple
release assets is still a future large-Wikipedia requirement.

A sentence ID is `s_` plus SHA-256 of the compact sorted-key UTF-8 JSON array
`[language, text]`. Deduplication never chooses a winning license: every occurrence
and its original work remains. Cross-source consumers deduplicate by this ID and
retain all source records. Separate snapshots of the same source must not be combined.

A revision timestamp is not a publication date. Missing dates/origins remain unknown.
RealPersonaChat records human/original-Japanese/dialogue explicitly. Its upstream
`dialogue_id` contains two collisions in the reviewed release; immutable file names
are the authoritative native IDs. We omit profiles, speaker attributes, evaluations,
LLM conversations, and utterances containing masked personal data. Utterance offsets
refer to the original dialogue turn numbers. Neighbor pointers refer to admitted
units, which can skip excluded turns; they are not proof of original adjacency.
For Wikimedia, extraction also omits material before canonical ordinals are
assigned, so even consecutive ordinals do not establish adjacency in the source.
Consumers must not present these pointers alone as uninterrupted original context.

Wikimedia processor `wikimedia-prose-v3` rejects whole pages exceeding 1,000,000
Unicode characters before calling the wikitext parser. This fixed limit bounds
parser input and subsequent whole-page prose/sentence lists; pages are never
truncated into misleading excerpts. Build source and aggregate statistics report
`wikimedia_pages_seen` (eligible pages reaching extraction) and
`rejected:page-text-limit`. These are extraction exclusions, not acquisition
sampling: snapshot completeness still describes the saved upstream inputs, not
retention of every article. XML decoding still holds one complete page before
this check; saved API JSON responses are loaded as a whole. The limit therefore
bounds wikitext parsing, not all input-decoder memory or adversarial parser CPU.

Default JSONL release builds compile normalized **v2 SQLite** with `sentences`,
`works`, `occurrences`, `translations`, and `external_references`. `metadata_json`
columns retain complete provenance and optional fields. `PRAGMA user_version` is 2;
the release database inventory also records `schema_version: 2`. Use
`mise run build-normalized-db -- --archive ...normalized.zip --output corpus.sqlite`
to compile it independently. Packaging compresses it with Zstandard and verifies
restored bytes against the original identity.

The original v1 `build-db` command and YAML-mode release output remain supported
for existing document-oriented consumers. It contains occurrences in the historically named `sentences` table;
new applications should consume normalized v2 instead of treating those IDs as
unique-text identity. A serving application may compile JSONL into its own SQLite
posting index and compressed payload store without changing this interchange model.

## Publisher-unit segmentation

Processor version **5**, text processor `ja-conservative-v5`, introduces
`publisher-unit-segmentation-v1` for Tatoeba, RealPersonaChat, JMultiWOZ and STAIR.
Wikimedia prose continues to use the conservative extraction segmenter. A quoted
reporting clause remains one sentence; punctuation inside an unfinished quotation
or parenthesis does not force an invalid fragment.

A publisher unit with multiple sentences yields separate sentence/occurrence
records. Each occurrence gains optional `source_unit` metadata:

| Key | Contract |
| --- | --- |
| `id` | Stable original-unit identity, `unit_` plus 32 hexadecimal characters |
| `text`, `text_sha256` | Original NFC unit, including internal whitespace/newlines, and exact UTF-8 hash |
| `start`, `end` | Half-open Unicode **codepoint** offsets selecting this exact sentence from `text` |
| `segment_index`, `segment_count` | Zero-based index and count before sentence-quality exclusions |
| `translations` | Complete independently attributed translations of the original unit |

An original unit is limited to 20,000 codepoints and 256 candidate segments.
Its independently licensed translations are limited to 256 entries and 20,000
codepoints per translated text; transport record-size bounds still apply.
Oversized original texts or segment counts are counted as rejected; invalid
translation metadata fails validation. Whole-unit masked information, excluded
content, unresolved markup, invalid control bytes and broken delimiters cannot
leak back through embedded context. Original `source_range` and native identity
remain separate; a dialogue utterance range still refers to the original turn.
Fragment native IDs suffix the original ID with exact character offsets. Existing
single-sentence native IDs remain unchanged. Ordinals order the expanded units;
source ranges, not consecutive ordinals, establish original positions.

Do not display unit translations as if they translated just one fragment. Split
fragments have empty sentence-level `translations`; their original-unit translations
remain under `source_unit.translations` and therefore do not appear as false
sentence-aligned rows in `translations.jsonl`. Each such translation uses the
same complete translation contract (ID, text/hash, language, source URL, license,
attribution and optional generation/alignment). License inventories include both
translation scopes.

This is an additive occurrence metadata extension; normalized interchange remains
v2. `metadata_json` carries it without a relational table change. The legacy v1
SQLite export adds a `sentence_context` table with `source_range_json` and
`source_unit_json`, keeping existing sentence columns intact. Original-unit
translations remain in that JSON with their licenses recorded in the license table.

**Rebuild required:** rebuild retained snapshots with processor 5, then rebuild
the private serving index. Old releases are not silently reinterpreted. The
shorter text changes normalized sentence IDs for split units, so do not combine
old and rebuilt snapshots of the same source. Consumers should show the source
unit as explicitly labeled context, retain its attribution, and compute sentence
difficulty/highlighting/copy text only from the selected fragment.


### Release transport parts

`package` applies `--part-bytes` (default 1 GiB) to normalized ZIP transport as
well as compressed SQLite transport. A normalized ZIP at or below the budget
keeps its existing filename and `normalized-jsonl-zip` asset kind. Larger ZIPs
become deterministic `.normalized.zip.part0000`, `.part0001`, … byte slices,
with asset kind `normalized-jsonl-zip-part`. These slices are not independent
ZIPs. The standalone normalized exporter still produces an ordinary ZIP.

The additive `release.json.normalized_archives` inventory records each logical
ZIP's `source_id`, `language`, original `path`, complete `size` and `sha256`,
and ordered `parts` filenames. Every part also has a size and SHA-256 in
`assets` and an entry in `SHA256SUMS`. Verify these identities, concatenate the
parts in manifest order to the original filename, then verify the complete ZIP
size and SHA-256 before passing it to an existing normalized importer. Do not
extract individual parts or assume lexical filename order. Package read-back
checks the concatenated identity with bounded memory and no restored ZIP.

Existing normalized importers accept a complete ZIP, not a release manifest or
individual transport part. Clients that download only assets of kind
`normalized-jsonl-zip` must add the assembly step to consume larger releases.
Small releases remain directly importable, and package verification still
accepts older releases without the additive inventory. Splitting uses the
already completed ZIP after SQLite generation; it does not reduce the disk
space required to build the normalized ZIP. Splitting works backwards, truncating
each completed tail before copying the next, so temporary duplication is bounded
by one part instead of nearly a second full ZIP. Split assets require the complete
archive inventory; the legacy exception only applies to unsplit releases.
GitHub's total asset-count limit still
applies and is checked before publication.
