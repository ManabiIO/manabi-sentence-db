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
