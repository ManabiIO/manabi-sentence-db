# Corpus expansion checkpoint — 2026-10-31

This is the current corpus-pipeline checkpoint. It supersedes earlier dated
notes describing these completed stages as running or queued. Generated source
text and evidence remain outside Git. Work is paused at Alex's request; reading
this checkpoint is not authorization to resume processing.

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
