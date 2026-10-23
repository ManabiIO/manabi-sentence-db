# Reproducible normalized downloads

Normalized JSONL ZIPs are reusable inputs for sentence indexing. Re-exporting
unchanged records and provenance should not change the archive checksum merely
because the export ran later or a checkout has different file permissions.

Every member now uses the same fixed ZIP timestamp (1980-01-01), creator system,
and regular-file mode. This includes the manifest, catalog, licenses and source
snapshot manifests, not just the five JSONL tables. Source files are copied in
bounded chunks rather than loaded whole. Source-specific provenance selection is
unchanged.

The timestamps and attribution **inside** catalog/provenance JSON are preserved
byte-for-byte. This change does not replace retrieval/publication dates, normalize
sentence text again, or change sentence IDs, counts, rights, or SQLite schemas.
Actual input changes still change the archive checksum.

Reproducibility assumes identical input bytes and ordering with the same
Python/zlib compression runtime; different codec versions are not promised to
produce identical compressed bytes. Previously published artifacts remain valid
and must not be overwritten in place. The fixed exporter produces new checksums
when next used through the ordinary versioned release process.

Focused transport checks:

```sh
uv run --locked pytest -q tests/test_normalized_archive.py
```

These synthetic checks exercise changing clocks/file metadata, all-member
integrity, streaming a multi-chunk table, source selection, Unicode paths,
changed-content identity, and relational SQLite read-back. Run `mise run check`
and the offline demo for the complete pipeline gate. The separate normalized
admission work in PR #2 is intentionally not duplicated here.
