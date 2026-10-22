# Contributing

Run `mise run check` and the offline demo before opening a pull request. Keep
changes focused and include synthetic regression cases for extraction, identity,
provenance, or packaging behavior that could corrupt a corpus. Do not commit raw
source downloads, generated YAML/SQLite, credentials, or copied copyrighted test
passages. The ignored `data/`, `build/`, and `dist/` directories are intentional.

## Adding a source

Start with a source review in `docs/sources.md`: publisher and exact subset,
commercial redistribution and adaptation terms, attribution requirements,
third-party exceptions, upstream versions, scale, and acquisition route. Prefer
official bulk exports. New scraping requires an explicit rate/robots/access
policy; adding a URL to the catalog does not authorize a generic crawler.

Then add a small `sources/<id>.yaml` configuration, a streaming adapter, and
original fixtures. Sources use language tags such as `ja` (not `jp`) and stable
native document/sentence IDs. Preserve original text, source links, author/history
credit, per-source licenses, and known translation-generation provenance. Leave
unknown provenance absent. Do not infer human or native authorship from a username
or infer machine translation from machine alignment.

Unknown license IDs, NC licenses, ND transformations, fabricated source URLs,
piracy, and sources primarily consisting of adults-only material are excluded.
Mainstream reference/news sources can contain sensitive passages; retain honest
unreviewed status and explicit selection rules rather than claiming universal
suitability. Modern Japanese is the first scope; historical subject matter alone
does not make the prose archaic.

## Pipeline contracts

Acquisition is opt-in. Offline stages must not call a downloader when inputs are
missing. Use temporary files/directories, verify before publication, and preserve
existing snapshots. Keep input fingerprints distinct from processor/runtime
fingerprints. Changes to output semantics need a processor-version review; an
incompatible public schema change requires a schema version change.

Strict schemas reject unknown fields. YAML mappings reject duplicate/non-string
keys, aliases, and merge keys. Preserve IDs independently of artifact filenames;
retain duplicate occurrences with their own attribution. Keep memory bounded by
one source document/shard and disk-backed joins/indexes.

## Releases

PR CI performs offline checks only. Manual workflows can acquire snapshots and
create new draft releases. Review source scopes, counts, checksums, licenses,
filter options, and samples before publishing a corpus. A `sample` label must not
be changed to `full`; rerun a complete build from complete snapshots instead.
See `docs/operations.md` for the concrete commands and storage constraints.
