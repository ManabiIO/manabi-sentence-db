# Measure vocabulary breadth

Sentence counts do not measure how much new vocabulary a source adds. This
offline report compares distinct analyzed lemmas per source and new lemmas
against a fixed baseline union. Exact normalized sentence IDs deduplicate
repeated text across sources while preserving each source's membership.

The public corpus pipeline does not contain a Japanese tokenizer. Supply an
analysis export produced by one explicitly identified tokenizer, lexicon, and
normalization configuration. Each JSONL row has exactly these fields:

```json
{"sentence_id":"s_<64 lowercase SHA-256 characters>","lemmas":["写真","撮る"]}
```

Rows are unique by sentence ID. Lemmas are nonempty NFC strings, at most 256
characters each. Repeated lemmas within a sentence are counted once. An empty
lemma list means analysis was performed and produced no lexical tokens; an
absent row means analysis is missing. Homographs are distinguished only to the
extent that the chosen analyzer distinguishes their lemma identities. Do not
mix exports from different analyzer/dictionary versions.

The private consumer's `export_sentence_vocabulary --index ... --output ...`
command produces this contract plus a `.metadata.json` sidecar. Pass that
sidecar to check its analyzer identity, exported row count, and SHA-256. Its
index/build/scorer provenance is retained in the report. Target vocabularies
must use the same lemma normalization as the exporter (including NFKC/casefold
when identified by that export), rather than unprocessed dictionary spellings.

```sh
mise run vocabulary-coverage -- \
  --archive dist/tatoeba-ja.ja.normalized.zip \
  --archive dist/jmultiwoz-ja.ja.normalized.zip \
  --analysis analysis/vocabulary.jsonl \
  --metadata analysis/vocabulary.jsonl.metadata.json \
  --analyzer 'exact-analyzer-identity-from-the-sidecar' \
  --baseline-source tatoeba-ja \
  --target-vocabulary analysis/target-lemmas.json \
  --output analysis/coverage.json
```

`--target-vocabulary` is optional. It is a JSON array of target lemmas; the
report stores its hash and distinct size. Without an explicit vocabulary
denominator, the report gives unique counts and leaves vocabulary percentages
unset. It never divides by an invented estimate of all Japanese vocabulary.

For each source, inspect:

| Field | Meaning |
| --- | --- |
| `unique_sentences` | Exact distinct text identities represented in that source |
| `analyzed_sentences`, `missing_analysis`, `analysis_coverage` | Completeness of supplied analysis; missing is unknown |
| `unique_lemmas` | Distinct lemmas in analyzed sentences |
| `novel_lemmas_vs_baseline` | Lemmas absent from the fixed union of `--baseline-source` sources |
| `target_lemmas_seen`, `target_vocabulary_coverage` | Coverage of the explicit target vocabulary, when supplied |
| `novel_target_lemmas_vs_baseline` | Target lemmas added beyond the fixed baseline union |

Report-level `baseline_target_vocabulary_coverage` and
`combined_target_vocabulary_coverage` compare the baseline with the union of
all supplied sources. That union counts overlapping candidate vocabulary once.

Every normalized member's count and digest is checked. Duplicate analysis IDs,
overlapping source snapshots, missing sentence/work links, mismatched export
metadata, malformed lemmas, and invalid text identities fail before the report
is published. Processing uses disk-backed joins instead of retaining all corpus
sentences or lemma sets in memory. Input archive and analysis digests make the
comparison repeatable.

Marginal counts overlap between candidate sources; they are not additive.
Incomplete baseline analysis inflates apparent novelty, so compare completeness
alongside novelty before selecting sources. Corpus breadth also needs register,
construction, source-context and licensed-origin variety. These measurements
do not establish naturalness, learner difficulty, or first-result quality.
