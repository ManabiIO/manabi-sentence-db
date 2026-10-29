"""Explicit, snapshot-bound Wikimedia page selection; no text transformations."""

import re

from .serialization import DataError


def validate_selection(value: dict, snapshots: list[dict]) -> frozenset[str]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "source_id", "snapshot_id", "page_ids"
    }:
        raise DataError("Document selection requires schema_version, source_id, snapshot_id, page_ids")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise DataError("Unsupported document selection schema")
    matches = [m for m in snapshots if m["source_id"] == value["source_id"]]
    if len(matches) != 1 or matches[0]["snapshot_id"] != value["snapshot_id"]:
        raise DataError("Document selection must match one input source and snapshot")
    if matches[0]["source"]["adapter"] != "wikimedia":
        raise DataError("Document selection supports Wikimedia snapshots only")
    ids = value["page_ids"]
    if not isinstance(ids, list) or not ids or any(
        not isinstance(item, str) or re.fullmatch(r"[1-9][0-9]*", item) is None
        for item in ids
    ):
        raise DataError("Document selection requires a nonempty list of positive page-ID strings")
    if len(set(ids)) != len(ids):
        raise DataError("Duplicate document selection page ID")
    return frozenset(ids)
