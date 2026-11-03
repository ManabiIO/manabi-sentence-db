# Corpus expansion checkpoint — 2026-11-02

This is the current corpus-pipeline checkpoint. It supersedes earlier dated
notes describing these completed stages as running or queued. Generated source
text and evidence remain outside Git. Alex resumed work on 2026-11-02.

## Current pass: v7 applied; combined serving candidate in progress

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

One combined compact SQLite v11 candidate is now building with the qualified
Wikipedia, corrected ALT/Global Voices and ASDC/TALPCo inputs. It selects 13,072
added works and 1,882 ALT replacements; these are work counts, not novel text
counts. The first preflight stopped on a caption-policy hash mismatch without
creating a candidate. The corrected consumer verifies actual imported works
are outside every caption scope, preserves the parent's caption-policy identity,
and still rejects mismatched caption imports. All 330 relevant consumer tests
passed. No source acquisition or native import was repeated.

The combined build uses one worker / 0.25 CPU, with an **8 GB target and 10 GB
ceiling for content, indexes and metadata together**. Content remains compressed.
Its final size, deduplicated growth, full posting/context/rights verification and
ranked-result quality are not yet established. No new corpus/runtime is active.
Use the private resume index below for the exact running job and pinned evidence.

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

V7 admission and compatible native reuse are complete. Next work is completing
the one combined serving candidate, its final integrity/size verification and
ranked query/quality review before atomic local activation. No newly prepared
source above has been activated.
