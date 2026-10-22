"""Small, strict serialization primitives shared by offline build stages."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml


class DataError(ValueError):
    """Invalid or inconsistent input; safe to display to a CLI user."""


class StrictLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise DataError("YAML aliases and merge keys are not supported")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise DataError("YAML mapping keys must be strings")
            if key == "<<" or key in result:
                raise DataError(f"Duplicate or merged YAML mapping key: {key}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


# YAML 1.1's `no`/`on`/dates must not change language codes or revision dates.
StrictLoader.yaml_implicit_resolvers = {
    key: [
        (tag, pattern)
        for tag, pattern in values
        if tag not in {"tag:yaml.org,2002:bool", "tag:yaml.org,2002:timestamp"}
    ]
    for key, values in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
StrictLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$"), list("tf")
)


def load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return yaml.load(handle, Loader=StrictLoader)


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode(
                "utf-8"
            )
            + b"\n"
        )


def read_json(path: Path) -> Any:
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise DataError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    with path.open(encoding="utf-8") as handle:
        return json.load(
            handle,
            object_pairs_hook=unique_pairs,
            parse_constant=lambda s: (_ for _ in ()).throw(DataError(s)),
        )


def safe_relative(root: Path, name: str) -> Path:
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or ":" in name
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
    ):
        raise DataError("Invalid artifact path")
    relative = Path(name)
    if relative.is_absolute() or any(part in {"", "..", "."} for part in name.split("/")):
        raise DataError(f"Unsafe artifact path: {name}")
    destination = (root / relative).resolve()
    if not destination.is_relative_to(root.resolve()):
        raise DataError(f"Artifact escapes its directory: {name}")
    return destination


def require_new_directory(path: Path) -> None:
    if path.exists():
        raise DataError(f"Output already exists: {path}. Choose a new output directory.")
    path.parent.mkdir(parents=True, exist_ok=True)


def atomic_replace_file(staged: Path, destination: Path) -> None:
    """Replace a complete artifact only after validation, never a live SQLite WAL."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged, destination)
