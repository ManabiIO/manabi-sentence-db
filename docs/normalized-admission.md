# Rights at the normalized interchange boundary

The normalized v2 SQLite compiler independently enforces the reviewed license
allowlist for every work and translation. Valid ZIP checksums are evidence of
byte integrity, not permission to redistribute. NC, ND, unreviewed identifiers,
license/URL mismatches, missing attribution, and lost historical Wikinews notices
are rejected before a database is published. Importing a normalized archive must
not bypass the rights checks applied to canonical documents.

The compiler also checks strict JSON, unique ZIP members, bounded records,
manifest kind/version, table counts and hashes, exact NFC sentence identity, and
translation-to-occurrence consistency. A translation's two foreign keys must
refer to the same sentence; independently existing IDs are not enough. Failed
imports close the staging database and leave no output. Existing destinations
are never overwritten. The interchange and SQLite schema remain version 2.

Rights metadata and transformation notices are retained verbatim in each work's
or translation's `metadata_json`; deduplicating sentence text does not assign a
new license or erase any originating work. These are metadata safeguards, not
proof that a publisher owns every embedded passage or a legal clearance service.

## Applying the fiction-source research

The existing [source priorities](source-priorities.md) remain the source shortlist.
Before enabling fiction acquisition, apply these specific admission constraints:

- [Backrooms JP's licensing guide](https://japan-backrooms-wiki.wikidot.com/licensing-guide)
  describes BY-SA 3.0 with potentially incorporated BY-SA 4.0 material and
  separately restricted exceptions. Preserve the applicable version and credit
  for the extracted text, not just the site's footer. Do not infer that every
  image, embedded item, or third-party passage has the text's license.
- [SCP-JP's licensing guide](https://scp-jp.wikidot.com/licensing-guide) likewise
  distinguishes BY-SA 3.0/4.0 and specific exceptions. Original Japanese tales
  and translated works need distinct origin metadata and their actual credits.
- [Creative Commons' BY-SA 3.0 deed](https://creativecommons.org/licenses/by-sa/3.0/)
  permits commercial sharing and adaptation subject to attribution, ShareAlike,
  and other terms. Commercial permission does not mean notice-free reuse.

For a future adapter, snapshot the article, credits, revision/history location,
and licensing evidence together. Admit only portions whose rights can be
represented faithfully. The current single-license work model cannot describe
arbitrary mixed-license spans: split independently attributable units only when
their boundaries and rights are known, or hold the work for review. Never flatten
a 4.0 component into a blanket 3.0 label. Keep separately copyrighted material,
NC/ND material, profiles and unlicensed quotations out of corpus text.

This change does not enable a crawler, acquire fiction, or claim that existing
source snapshots have been newly cleared. Per-source exception review remains a
prerequisite for any new adapter. Rights, authorship/origin, content suitability,
and example-sentence quality are separate decisions.

## Focused regression command

```sh
uv run --locked pytest -q tests/test_normalized_admission.py
```

The fixtures are original synthetic test data, not newly admitted corpus content.
