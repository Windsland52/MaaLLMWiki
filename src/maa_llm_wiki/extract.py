"""Deterministic extraction of structured machine-change facts from upstream git diffs.

Nothing in this module rewrites upstream text: quotes are verbatim added/removed lines,
trimmed to 300 characters. The extractor only looks at indexed paths (the union of the two
inventories' artifacts) and emits one `unclassified` record when a release pair changed
indexed material but matched none of the structured rules.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, cast
from urllib.parse import quote

from .models import (
    MachineChange,
    MachineChangeCatalog,
    MachineChangeKind,
    ReleaseRecord,
    SourceInventory,
)
from .validation import load_release_catalog, load_source_inventories

QUOTE_LIMIT = 300
UNCLASSIFIED_PATH_LIMIT = 20
UNCLASSIFIED_SYMBOL = "unclassified"

ChangeType = Literal["added", "removed", "modified"]

_ENUM_VALUE_PATTERN = re.compile(r"\b(?P<symbol>Maa[A-Za-z0-9_]+)\s*=\s*-?\d+")
_PUBLIC_FUNCTION_PATTERN = re.compile(r"\b(?P<symbol>Maa[A-Za-z0-9_]+)\s*\(")
_CALLBACK_MESSAGE_PATTERN = re.compile(r"#define\s+(?P<symbol>MaaMsg_\w+)")
_DOCUMENTATION_VERSION_PATTERN = re.compile(
    r"^\|\s*\d{4}-\d{1,2}-\d{1,2}\s*\|\s*(?P<symbol>v[\d.]+)\s*\|"
)
_PYTHON_DEFINITION_PATTERN = re.compile(r"^\s*(?:def|class)\s+(?P<symbol>[A-Za-z]\w*)")
_NODEJS_DEFINITION_PATTERN = re.compile(
    r"^export\s+(?:declare\s+)?(?:class|function|interface|type|const)\s+(?P<symbol>\w+)"
)
_NODEJS_MEMBER_PATTERN = re.compile(r"^\s+(?:readonly\s+)?(?P<symbol>[A-Za-z]\w*)\??\s*:")


@dataclass(frozen=True)
class ExtractedRecord:
    version: str
    commit: str
    change: ChangeType
    kind: MachineChangeKind
    symbol: str
    quote: str
    paths: tuple[str, ...]


def _git_text(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def _git_texts(
    repository: Path, requests: list[tuple[str, str]]
) -> dict[tuple[str, str], str | None]:
    """Read many `revision:path` blobs through one `git cat-file --batch` process."""
    if not requests:
        return {}
    payload = "".join(f"{revision}:{path}\n" for revision, path in requests).encode("utf-8")
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", "cat-file", "--batch"],
        cwd=repository,
        check=True,
        capture_output=True,
        input=payload,
    )
    data = result.stdout
    contents: dict[tuple[str, str], str | None] = {}
    position = 0
    for key in requests:
        end = data.index(b"\n", position)
        header = data[position:end].decode("utf-8", "replace")
        position = end + 1
        fields = header.split(" ")
        if len(fields) == 2 and fields[1] == "missing":
            contents[key] = None
            continue
        size = int(fields[2])
        contents[key] = data[position : position + size].decode("utf-8", "replace")
        position += size + 1
    return contents


def _strip_diff_path(value: str) -> str:
    path = value.strip()
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return path


def _parse_diff(diff_text: str) -> tuple[list[tuple[str, ChangeType, str]], set[str]]:
    """Return (path, change, verbatim content) lines plus every changed path in the diff."""
    lines: list[tuple[str, ChangeType, str]] = []
    changed_paths: set[str] = set()
    old_path: str | None = None
    new_path: str | None = None
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            old_path = new_path = None
            payload = raw[len("diff --git ") :]
            if payload.startswith("a/") and " b/" in payload:
                old_path = payload[2:].split(" b/", 1)[0]
                new_path = payload.split(" b/", 1)[1]
            elif payload.startswith("a/"):
                old_path = payload[2:]
            if new_path is not None:
                changed_paths.add(new_path)
            continue
        if raw.startswith("--- "):
            old_path = _strip_diff_path(raw[4:])
            continue
        if raw.startswith("+++ "):
            new_path = _strip_diff_path(raw[4:])
            candidate = new_path if new_path != "/dev/null" else old_path
            if candidate is not None and candidate != "/dev/null":
                changed_paths.add(candidate)
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            path = new_path if new_path not in (None, "/dev/null") else old_path
            if path is not None and path != "/dev/null":
                lines.append((path, "added", raw[1:]))
            continue
        if raw.startswith("-") and not raw.startswith("---"):
            path = old_path if old_path not in (None, "/dev/null") else new_path
            if path is not None and path != "/dev/null":
                lines.append((path, "removed", raw[1:]))
            continue
    return lines, changed_paths


def _normalise_quote(text: str) -> str:
    return text.strip()[:QUOTE_LIMIT]


def _is_header_path(path: str) -> bool:
    return path.startswith("include/") and path.endswith((".h", ".hpp"))


def _is_schema_path(path: str) -> bool:
    return path.startswith("tools/") and path.endswith(".schema.json")


def _is_documentation_version_path(path: str) -> bool:
    return (
        path.startswith("docs/")
        and path.endswith(".md")
        and PurePosixPath(path).name.startswith("3.3-")
    )


_SQUASH_TRAILING = " \t,;|"


def _squash(quote: str) -> str:
    """Collapse formatting so a moved line or a changed trailing separator is ignored."""
    return re.sub(r"\s+", " ", quote).strip().rstrip(_SQUASH_TRAILING)


def _kind(value: str) -> MachineChangeKind:
    return MachineChangeKind(value)


def _text_line_hits(path: str, line: str) -> list[tuple[MachineChangeKind, str]]:
    """Structured facts contributed by one added/removed line."""
    hits: list[tuple[MachineChangeKind, str]] = []

    def add(kind: str, symbol: str) -> None:
        candidate = (_kind(kind), symbol)
        if candidate not in hits:
            hits.append(candidate)

    if _is_header_path(path):
        for match in _ENUM_VALUE_PATTERN.finditer(line):
            add("enum-value", match["symbol"])
        if "MAA_CALL" in line:
            for match in _PUBLIC_FUNCTION_PATTERN.finditer(line):
                add("public-function", match["symbol"])
        callback = _CALLBACK_MESSAGE_PATTERN.search(line)
        if callback is not None:
            add("callback-message", callback["symbol"])
    elif _is_documentation_version_path(path):
        table_row = _DOCUMENTATION_VERSION_PATTERN.match(line)
        if table_row is not None:
            add("documentation-version", table_row["symbol"])
    elif path.startswith("source/binding/Python/maa/") and path.endswith(".py"):
        definition = _PYTHON_DEFINITION_PATTERN.match(line)
        if definition is not None:
            add("binding-api", definition["symbol"])
    elif path.startswith("source/binding/NodeJS/src/apis/") and path.endswith(".d.ts"):
        definition = _NODEJS_DEFINITION_PATTERN.match(line)
        if definition is not None:
            add("binding-api", definition["symbol"])
        member = _NODEJS_MEMBER_PATTERN.match(line)
        if member is not None:
            add("binding-api", member["symbol"])
    return hits


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _dotted_path(parent: str, name: str) -> str:
    return f"{parent}.{name}" if parent else name


def _as_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    mapping = cast("dict[object, object]", value)
    return {str(key): item for key, item in mapping.items()}


def _as_list(value: object) -> list[object] | None:
    if not isinstance(value, list):
        return None
    return cast("list[object]", value)


def _required_name(canonical: str) -> str:
    """Recover the plain property name from its canonical JSON representation."""
    try:
        value = json.loads(canonical)
    except json.JSONDecodeError:
        return canonical
    return value if isinstance(value, str) else canonical


def _canonical_set(values: list[object] | None) -> set[str]:
    if values is None:
        return set()
    return {_canonical_json(item) for item in values}


def _schema_nodes(schema: object) -> dict[str, dict[str, object]]:
    """Map dotted property path -> schema node; "" maps the document root."""
    nodes: dict[str, dict[str, object]] = {}

    def walk(node: object, prefix: str) -> None:
        mapping = _as_dict(node)
        if mapping is not None:
            if prefix not in nodes:
                nodes[prefix] = mapping
            properties = _as_dict(mapping.get("properties"))
            if properties is not None:
                for name, child in properties.items():
                    walk(child, _dotted_path(prefix, name))
            for key, child in mapping.items():
                if key == "properties":
                    continue
                walk(child, _dotted_path(prefix, key))
        else:
            items = _as_list(node)
            if items is not None:
                for child in items:
                    walk(child, prefix)

    walk(schema, "")
    return nodes


def _structural_schema_records(
    previous_schema: object | None,
    current_schema: object | None,
    *,
    version: str,
    commit: str,
    path: str,
) -> list[ExtractedRecord]:
    if previous_schema is None or current_schema is None:
        schema = current_schema if previous_schema is None else previous_schema
        change: ChangeType = "added" if previous_schema is None else "removed"
        properties = _as_dict(_schema_nodes(schema).get("", {}).get("properties"))
        if properties is None:
            return []
        return [
            ExtractedRecord(
                version=version,
                commit=commit,
                change=change,
                kind=_kind("schema-property"),
                symbol=str(name),
                quote=_normalise_quote(_canonical_json(properties[name])),
                paths=(path,),
            )
            for name in sorted(properties)
        ]

    previous_nodes = _schema_nodes(previous_schema)
    current_nodes = _schema_nodes(current_schema)
    records: list[ExtractedRecord] = []

    def record(kind: str, symbol: str, change: ChangeType, quote_text: str) -> None:
        records.append(
            ExtractedRecord(
                version=version,
                commit=commit,
                change=change,
                kind=_kind(kind),
                symbol=symbol,
                quote=_normalise_quote(quote_text),
                paths=(path,),
            )
        )

    for parent in sorted(set(previous_nodes) & set(current_nodes)):
        previous_node = previous_nodes[parent]
        current_node = current_nodes[parent]
        previous_properties = _as_dict(previous_node.get("properties")) or {}
        current_properties = _as_dict(current_node.get("properties")) or {}
        for name in sorted(current_properties.keys() - previous_properties.keys()):
            record(
                "schema-property",
                _dotted_path(parent, name),
                "added",
                _canonical_json(current_properties[name]),
            )
        for name in sorted(previous_properties.keys() - current_properties.keys()):
            record(
                "schema-property",
                _dotted_path(parent, name),
                "removed",
                _canonical_json(previous_properties[name]),
            )

        previous_required = _as_list(previous_node.get("required"))
        current_required = _as_list(current_node.get("required"))
        previous_required_values = _canonical_set(previous_required)
        current_required_values = _canonical_set(current_required)
        for item in sorted(current_required_values - previous_required_values):
            symbol = _dotted_path(parent, _required_name(item))
            record("schema-required", symbol, "added", item)
        for item in sorted(previous_required_values - current_required_values):
            symbol = _dotted_path(parent, _required_name(item))
            record("schema-required", symbol, "removed", item)

        previous_enum = _as_list(previous_node.get("enum"))
        current_enum = _as_list(current_node.get("enum"))
        previous_enum_values = _canonical_set(previous_enum)
        current_enum_values = _canonical_set(current_enum)
        for item in sorted(current_enum_values - previous_enum_values):
            symbol = f"{parent} = {item}" if parent else item
            record("schema-enum", symbol, "added", item)
        for item in sorted(previous_enum_values - current_enum_values):
            symbol = f"{parent} = {item}" if parent else item
            record("schema-enum", symbol, "removed", item)

        if "default" in previous_node and "default" in current_node:
            previous_default = _canonical_json(previous_node["default"])
            current_default = _canonical_json(current_node["default"])
            if previous_default != current_default:
                record("schema-default", parent, "modified", current_default)
    return records


def _schema_records_for_pair(
    previous_release: ReleaseRecord,
    release: ReleaseRecord,
    previous_inventory: SourceInventory,
    current_inventory: SourceInventory,
    schema_texts: dict[tuple[str, str], str | None],
) -> list[ExtractedRecord]:
    schema_paths = sorted(
        {
            artifact.path
            for artifact in (*previous_inventory.artifacts, *current_inventory.artifacts)
            if _is_schema_path(artifact.path)
        }
    )
    records: list[ExtractedRecord] = []
    for path in schema_paths:
        previous_text = schema_texts.get((previous_release.commit, path))
        current_text = schema_texts.get((release.commit, path))
        if previous_text == current_text:
            continue
        previous_schema = json.loads(previous_text) if previous_text is not None else None
        current_schema = json.loads(current_text) if current_text is not None else None
        if previous_schema == current_schema:
            continue
        records.extend(
            _structural_schema_records(
                previous_schema,
                current_schema,
                version=release.version,
                commit=release.commit,
                path=path,
            )
        )
    return records


def _schema_requests(
    releases: list[ReleaseRecord],
    inventories: dict[str, SourceInventory],
) -> list[tuple[str, str]]:
    requests: list[tuple[str, str]] = []
    for release in releases:
        inventory = inventories.get(release.version)
        if inventory is None:
            continue
        for artifact in inventory.artifacts:
            if _is_schema_path(artifact.path):
                requests.append((release.commit, artifact.path))
    return sorted(set(requests))


def _drop_reformatting_pairs(records: list[ExtractedRecord]) -> list[ExtractedRecord]:
    """Remove added/removed records that only differ by whitespace or a trailing separator."""
    added = {
        (record.paths[0], record.kind.value, record.symbol): record
        for record in records
        if record.change == "added"
    }
    removed = {
        (record.paths[0], record.kind.value, record.symbol): record
        for record in records
        if record.change == "removed"
    }
    dropped: set[int] = set()
    for key, added_record in added.items():
        removed_record = removed.get(key)
        if removed_record is None:
            continue
        if _squash(added_record.quote) == _squash(removed_record.quote):
            dropped.add(id(added_record))
            dropped.add(id(removed_record))
    return [record for record in records if id(record) not in dropped]


def _pair_records(
    previous_release: ReleaseRecord,
    release: ReleaseRecord,
    previous_inventory: SourceInventory,
    current_inventory: SourceInventory,
    diff_text: str,
    schema_texts: dict[tuple[str, str], str | None],
) -> list[ExtractedRecord]:
    indexed_paths = {
        artifact.path for artifact in (*previous_inventory.artifacts, *current_inventory.artifacts)
    }
    diff_lines, changed_paths = _parse_diff(diff_text)
    changed_indexed = {path for path in changed_paths if path in indexed_paths}

    deduplicated: dict[tuple[str, str, str, str, str], ExtractedRecord] = {}
    for path, change, text in diff_lines:
        if path not in indexed_paths:
            continue
        quote_text = _normalise_quote(text)
        if not quote_text:
            continue
        for kind, symbol in _text_line_hits(path, text):
            key = (kind.value, symbol, change, quote_text, path)
            deduplicated[key] = ExtractedRecord(
                version=release.version,
                commit=release.commit,
                change=change,
                kind=kind,
                symbol=symbol,
                quote=quote_text,
                paths=(path,),
            )
    records = _drop_reformatting_pairs(list(deduplicated.values()))
    records.extend(
        _schema_records_for_pair(
            previous_release,
            release,
            previous_inventory,
            current_inventory,
            schema_texts,
        )
    )
    if not records and changed_indexed:
        changed = sorted(changed_indexed)
        records.append(
            ExtractedRecord(
                version=release.version,
                commit=release.commit,
                change="modified",
                kind=_kind("unclassified"),
                symbol=UNCLASSIFIED_SYMBOL,
                quote=f"{len(changed)} indexed files changed without a structured change",
                paths=tuple(changed[:UNCLASSIFIED_PATH_LIMIT]),
            )
        )
    return records


def _record_sort_key(record: ExtractedRecord) -> tuple[str, str, str, str, str, tuple[str, ...]]:
    return (
        record.version,
        record.kind.value,
        record.symbol,
        record.change,
        record.quote,
        record.paths,
    )


def _to_machine_change(record: ExtractedRecord) -> MachineChange:
    return MachineChange(
        version=record.version,
        commit=record.commit,
        change=record.change,
        kind=record.kind,
        symbol=record.symbol,
        quote=record.quote,
        paths=list(record.paths),
    )


def build_machine_changes(root: Path, repository: Path) -> MachineChangeCatalog:
    """Extract deterministic machine-change records for every consecutive release pair."""
    releases = load_release_catalog(root).releases
    inventories = {inventory.version: inventory for inventory in load_source_inventories(root)}
    schema_texts = _git_texts(repository, _schema_requests(releases, inventories))

    records: list[ExtractedRecord] = []
    for previous_release, release in zip(releases, releases[1:], strict=False):
        previous_inventory = inventories.get(previous_release.version)
        current_inventory = inventories.get(release.version)
        if previous_inventory is None or current_inventory is None:
            continue
        indexed_paths = {
            artifact.path
            for artifact in (*previous_inventory.artifacts, *current_inventory.artifacts)
        }
        diff_text = _git_text(
            repository,
            "diff",
            "--no-color",
            "--no-ext-diff",
            "--unified=0",
            previous_release.commit,
            release.commit,
            "--",
            *sorted(indexed_paths),
        )
        records.extend(
            _pair_records(
                previous_release,
                release,
                previous_inventory,
                current_inventory,
                diff_text,
                schema_texts,
            )
        )
    records.sort(key=_record_sort_key)
    return MachineChangeCatalog(
        source_id="maafw",
        changes=[_to_machine_change(record) for record in records],
    )


def _version_sort_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def render_machine_changes_page(catalog: MachineChangeCatalog, repository_url: str) -> str:
    """Render the deterministic machine-change registry page."""
    base_url = repository_url.rstrip("/")
    versions = sorted(
        {change.version for change in catalog.changes},
        key=_version_sort_key,
    )
    by_version: dict[str, list[MachineChange]] = {version: [] for version in versions}
    for change in catalog.changes:
        by_version[change.version].append(change)

    kind_counts: dict[str, int] = {}
    for change in catalog.changes:
        kind_counts[change.kind.value] = kind_counts.get(change.kind.value, 0) + 1

    lines = [
        "<!-- Generated by maa-wiki-sync-maafw. Do not edit manually. -->",
        "# Machine changes",
        "",
        "Structured change facts extracted deterministically from upstream diffs between "
        "consecutive registered releases. Quotes are verbatim added/removed lines trimmed to "
        "300 characters; `unclassified` entries mark releases whose indexed material changed "
        "without producing a structured record.",
        "",
        "Source of truth: `sources/maa-framework/machine-changes.yaml` "
        f"({len(catalog.changes)} records over {len(versions)} releases).",
        "",
        "| Kind | Records |",
        "| --- | --- |",
    ]
    for kind in sorted(kind_counts):
        lines.append(f"| `{kind}` | {kind_counts[kind]} |")
    lines.append("")

    for version in versions:
        group = by_version[version]
        lines.extend([f"## {version}", "", f"Revision: `{group[0].commit}`", ""])
        for change in group:
            links = ", ".join(
                f"[`{path}`]({base_url}/blob/{change.commit}/{quote(path, safe='/')})"
                for path in change.paths
            )
            label = f" `{change.symbol}`" if change.symbol else ""
            lines.append(
                f"- `{change.kind.value}`{label} ({change.change}): {change.quote} — {links}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
