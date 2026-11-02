# Corpus expansion checkpoint — 2026-11-02

This is the current corpus-pipeline checkpoint. It supersedes earlier dated
notes describing these completed stages as running or queued. Generated source
text and evidence remain outside Git. Alex resumed work on 2026-11-02.

## Current pass: Wikipedia admission v6

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

Resumable native analysis is now running against this exact ZIP after a 32→64
record check proved that the first 32 were reused. The cache keeps sentence
records individually Zstandard-compressed; it is offline analysis evidence,
not a second serving engine. Serving remains compact SQLite v11. Postings,
actual queries, combined deduplication and the complete serving-size budget
remain gates. No new corpus/runtime has been activated. Use the private resume
index below for the exact running job before launching anything. The completed
v5 input below is historical reusable evidence; no raw dump was reacquired.

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

When resumed, the next work is remaining Wikipedia quality review, targeted
admission improvements with controls, native qualification of the resulting
selection, and one combined serving candidate. No newly prepared source above
has been activated.
