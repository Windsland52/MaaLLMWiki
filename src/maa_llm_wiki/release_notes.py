"""Render a substantive release body from the committed catalog and git snapshot tags.

The release body answers four questions: what this snapshot contains, which upstream releases moved,
which machine-extracted/curated facts are new, and how to verify the bundle. The previous snapshot
is read from git objects (``git show <tag>:<path>``) because only the current tree is on disk.
Everything is deterministic: no timestamps, no ordering leaks from filesystem enumeration.
"""

from __future__ import annotations

import json
import re
import subprocess
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

from .bundle import bundle_sha256
from .gaps import artifact_changed
from .models import (
    MachineChange,
    MachineChangeCatalog,
    MachineChangeKind,
    ReleaseCatalog,
    ReleaseRecord,
    SemanticChange,
    SemanticChangeCatalog,
    SourceInventory,
)
from .validation import load_repository_catalog

_REPOSITORY_URL = "https://github.com/Windsland52/MaaLLMWiki"
_VERSION_PATTERN = re.compile(r"^v\d+\.\d+\.\d+$")
_MACHINE_RECORD_EXAMPLES = 15
_CURATED_ENTRIES = 10


@dataclass(frozen=True)
class SnapshotSource:
    source_id: str
    name: str
    version: str
    revision: str
    releases: tuple[ReleaseRecord, ...]
    inventory: SourceInventory | None


@dataclass(frozen=True)
class Snapshot:
    sources: tuple[SnapshotSource, ...]
    machine_changes: tuple[MachineChange, ...]
    machine_source_id: str | None
    semantic_changes: tuple[SemanticChange, ...]


@dataclass(frozen=True)
class BundleDetails:
    name: str
    sha256: str
    size_bytes: int
    file_count: int


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _require_version(version: str) -> str:
    if _VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError(f"version must look like vX.Y.Z: {version!r}")
    return version


def _source_directory(root: Path, source_id: str) -> str:
    for candidate in (source_id, "maa-framework"):
        if (root / "sources" / candidate / "inventory.yaml").is_file():
            return candidate
    return source_id


def _load_yaml(text: str) -> object:
    return yaml.safe_load(text)


def _build_snapshot(root: Path, read: Callable[[str], str | None]) -> Snapshot:
    sources: list[SnapshotSource] = []
    for repository in load_repository_catalog(root).repositories:
        directory = _source_directory(root, repository.id)
        releases_text = read(f"sources/{directory}/releases.yaml")
        if releases_text is None:
            continue
        releases = ReleaseCatalog.model_validate(_load_yaml(releases_text))
        inventory_text = read(f"sources/{directory}/inventory.yaml")
        inventory = (
            SourceInventory.model_validate(_load_yaml(inventory_text))
            if inventory_text is not None
            else None
        )
        latest = inventory.version if inventory is not None else releases.releases[-1].version
        revision = inventory.revision if inventory is not None else releases.releases[-1].commit
        sources.append(
            SnapshotSource(
                source_id=repository.id,
                name=repository.name,
                version=latest,
                revision=revision,
                releases=tuple(releases.releases),
                inventory=inventory,
            )
        )
    machine_text = read("sources/maa-framework/machine-changes.yaml")
    machine = (
        MachineChangeCatalog.model_validate(_load_yaml(machine_text))
        if machine_text is not None
        else None
    )
    semantic_text = read("sources/maa-framework/semantic-changes.yaml")
    semantic = (
        SemanticChangeCatalog.model_validate(_load_yaml(semantic_text))
        if semantic_text is not None
        else None
    )
    return Snapshot(
        sources=tuple(sources),
        machine_changes=tuple(machine.changes) if machine is not None else (),
        machine_source_id=machine.source_id if machine is not None else None,
        semantic_changes=tuple(semantic.changes) if semantic is not None else (),
    )


def load_current_snapshot(root: Path) -> Snapshot:
    def read(relative: str) -> str | None:
        path = root / relative
        return path.read_text(encoding="utf-8") if path.is_file() else None

    return _build_snapshot(root, read)


def _git_show(root: Path, tag: str, relative: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "-c", "core.quotepath=false", "show", f"{tag}:{relative}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout if result.returncode == 0 else None


def _verify_tag(root: Path, tag: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "--quiet", f"{tag}^{{commit}}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise ValueError(f"unknown previous tag: {tag}")


def load_previous_snapshot(root: Path, tag: str) -> Snapshot:
    _require_version(tag)
    _verify_tag(root, tag)
    return _build_snapshot(root, lambda relative: _git_show(root, tag, relative))


def _wiki_revision(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _bundle_details(path: Path) -> BundleDetails:
    with zipfile.ZipFile(path) as archive:
        payload: object = json.loads(archive.read("catalog-manifest.json"))
    if not isinstance(payload, dict):
        raise ValueError(f"bundle manifest is not a JSON object: {path}")
    manifest = cast(dict[str, object], payload)
    files = manifest.get("files")
    file_count = len(cast(list[object], files)) if isinstance(files, list) else 0
    return BundleDetails(
        name=path.name,
        sha256=bundle_sha256(path),
        size_bytes=path.stat().st_size,
        file_count=file_count,
    )


def _new_releases(
    current: Snapshot, previous: Snapshot
) -> list[tuple[SnapshotSource, ReleaseRecord]]:
    previous_versions = {
        source.source_id: {release.version for release in source.releases}
        for source in previous.sources
    }
    fresh: list[tuple[SnapshotSource, ReleaseRecord]] = []
    for source in current.sources:
        known = previous_versions.get(source.source_id, set())
        fresh.extend(
            (source, release) for release in source.releases if release.version not in known
        )
    return fresh


def _machine_kind_key(kind: MachineChangeKind) -> int:
    return list(MachineChangeKind).index(kind)


def _group_machine_records(
    records: tuple[MachineChange, ...], version: str, commit: str
) -> dict[MachineChangeKind, list[MachineChange]]:
    grouped: dict[MachineChangeKind, list[MachineChange]] = {}
    for record in records:
        if record.version != version or record.commit != commit:
            continue
        grouped.setdefault(record.kind, []).append(record)
    for kind_records in grouped.values():
        kind_records.sort(key=lambda record: (record.symbol, record.change, record.quote))
    return grouped


def _machine_section(
    current: Snapshot, previous: Snapshot, new_releases: list[tuple[SnapshotSource, ReleaseRecord]]
) -> list[str]:
    lines = ["## Machine-extracted changes", ""]
    machine_source_id = current.machine_source_id
    total = len(current.machine_changes)
    unclassified = sum(
        1 for record in current.machine_changes if record.kind is MachineChangeKind.UNCLASSIFIED
    )
    if machine_source_id is None:
        lines.append("No machine-extracted change catalog is committed in this snapshot.")
        return lines
    fresh_machine = [
        (source, release)
        for source, release in new_releases
        if source.source_id == machine_source_id
    ]
    if not fresh_machine:
        if previous.machine_source_id is None:
            lines.append(
                "The machine-extracted change catalog first appears in this snapshot; "
                f"`generated/maa-framework/machine-changes.md` lists {total} records "
                f"({unclassified} unclassified)."
            )
        elif new_releases:
            lines.append(
                "The new releases are bindings, not MaaFramework framework releases, so the "
                "machine-extracted catalog has no new records; "
                f"`generated/maa-framework/machine-changes.md` lists {total} records "
                f"({unclassified} unclassified)."
            )
        else:
            lines.append(
                "No new upstream releases, so no new machine-extracted records; "
                f"`generated/maa-framework/machine-changes.md` lists {total} records "
                f"({unclassified} unclassified)."
            )
        return lines
    displays: list[str] = []
    examples: list[str] = []
    found_any = False
    for source, release in fresh_machine:
        grouped = _group_machine_records(current.machine_changes, release.version, release.commit)
        if not grouped:
            continue
        found_any = True
        counts = ", ".join(
            f"{kind.value} {len(grouped[kind])}" for kind in sorted(grouped, key=_machine_kind_key)
        )
        record_count = sum(len(kind_records) for kind_records in grouped.values())
        displays.append(f"- `{source.name} {release.version}` — {record_count} records: {counts}")
        for kind in sorted(grouped, key=_machine_kind_key):
            if len(examples) >= _MACHINE_RECORD_EXAMPLES:
                break
            example = grouped[kind][0]
            examples.append(
                f"  - {kind.value} {example.change} `{example.symbol}` — `{example.paths[0]}`"
            )
    if not found_any:
        lines.append(
            "No machine-extracted records for the new releases; "
            f"`generated/maa-framework/machine-changes.md` lists {total} records "
            f"({unclassified} unclassified)."
        )
        return lines
    lines.extend(displays)
    lines.extend(examples)
    if len(examples) >= _MACHINE_RECORD_EXAMPLES:
        lines.append(f"Example records capped at {_MACHINE_RECORD_EXAMPLES}.")
    return lines


def _curated_section(
    current: Snapshot, new_releases: list[tuple[SnapshotSource, ReleaseRecord]]
) -> list[str]:
    new_versions = {
        release.version
        for source, release in new_releases
        if source.source_id == current.machine_source_id
    }
    entries = [
        change for change in current.semantic_changes if change.first_version in new_versions
    ]
    if not entries:
        return []
    entries.sort(key=lambda change: (_version_key(change.first_version), change.topic_id))
    lines = ["## Curated behaviour changes", ""]
    for change in entries[:_CURATED_ENTRIES]:
        lines.append(f"- `{change.topic_id}`: {change.description}")
    if len(entries) > _CURATED_ENTRIES:
        lines.append(f"- ({len(entries) - _CURATED_ENTRIES} more entries omitted)")
    return lines


_CATALOG_ROOTS = ("generated", "sources", "schemas")
_CATALOG_FILE_CAP = 20


def _git_text(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "-c", "core.quotepath=false", *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise ValueError(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")
    return result.stdout


def _catalog_files_section(root: Path, previous_tag: str | None) -> list[str]:
    """Count the catalog's own files that moved since the previous snapshot.

    The upstream sections describe what the *indexed material* did; a packaging or navigation
    change moves the catalog itself and would otherwise show up as "nothing changed".
    """
    heading = "## Catalog files changed"
    if previous_tag is None:
        tracked = _git_text(root, "ls-files", "--", *_CATALOG_ROOTS).splitlines()
        if not tracked:
            return []
        return [
            heading,
            "",
            f"Initial snapshot: {len(tracked)} catalog files published for the first time.",
        ]

    output = _git_text(
        root, "diff", "--name-status", f"{previous_tag}..HEAD", "--", *_CATALOG_ROOTS
    )
    added: list[str] = []
    removed: list[str] = []
    changed: list[str] = []
    for line in output.splitlines():
        if "\t" not in line:
            continue
        status, path = line.split("\t", 1)[0], line.split("\t")[-1]
        if status.startswith("A"):
            added.append(path)
        elif status.startswith("D"):
            removed.append(path)
        else:
            changed.append(path)
    if not (added or removed or changed):
        return [heading, "", "No catalog files changed since the previous snapshot."]

    counts = {"added": added, "removed": removed, "changed": changed}
    summary = (
        f"{len(added)} added, {len(removed)} removed, {len(changed)} changed "
        f"since `{previous_tag}`."
    )
    lines = [
        heading,
        "",
        summary,
        "",
        "| Area | added | removed | changed |",
        "| --- | --- | --- | --- |",
    ]
    for area in _CATALOG_ROOTS:
        prefix = f"{area}/"
        lines.append(
            f"| `{prefix}` | {sum(1 for x in added if x.startswith(prefix))} | "
            f"{sum(1 for x in removed if x.startswith(prefix))} | "
            f"{sum(1 for x in changed if x.startswith(prefix))} |"
        )
    lines.append("")
    listed = 0
    for label, paths in counts.items():
        for path in sorted(paths):
            if listed >= _CATALOG_FILE_CAP:
                break
            lines.append(f"- {label}: `{path}`")
            listed += 1
        if listed >= _CATALOG_FILE_CAP:
            break
    remaining = len(added) + len(removed) + len(changed) - listed
    if remaining > 0:
        lines.append(f"- ... and {remaining} more files")
    return lines


def _moved_section(current: Snapshot, previous: Snapshot) -> list[str]:
    previous_inventories = {
        source.source_id: source.inventory
        for source in previous.sources
        if source.inventory is not None
    }
    rows: list[str] = []
    for source in current.sources:
        before = previous_inventories.get(source.source_id)
        after = source.inventory
        if before is None or after is None:
            continue
        old = {artifact.path: artifact for artifact in before.artifacts}
        new = {artifact.path: artifact for artifact in after.artifacts}
        added = len(set(new) - set(old))
        removed = len(set(old) - set(new))
        changed = sum(1 for path in set(old) & set(new) if artifact_changed(old[path], new[path]))
        rows.append(f"| {source.name} | {added} | {removed} | {changed} |")
    if not rows:
        return []
    lines = [
        "## Indexed material moved",
        "",
        "| Source | added | removed | content changed |",
        "| --- | --- | --- | --- |",
        *rows,
    ]
    for source in current.sources:
        if source.source_id not in previous_inventories:
            lines.append("")
            lines.append(
                f"`{source.name}` is new in this snapshot, so there is no previous inventory to "
                "compare against."
            )
    return lines


def _upstream_section(current: Snapshot) -> list[str]:
    lines = [
        "## Upstream snapshot",
        "",
        "| Source | Version | Revision |",
        "| --- | --- | --- |",
    ]
    lines.extend(
        f"| {source.name} | {source.version} | `{source.revision}` |" for source in current.sources
    )
    return lines


def _new_releases_section(
    previous_tag: str | None, new_releases: list[tuple[SnapshotSource, ReleaseRecord]]
) -> list[str]:
    heading = f"## New upstream releases since {previous_tag}"
    lines = [heading, ""]
    if not new_releases:
        lines.append(
            "No new upstream releases; this snapshot records packaging or metadata changes."
        )
        return lines
    for source, release in new_releases:
        lines.append(
            f"- {source.name} {release.version} `{release.commit[:12]}` "
            f"({release.released_at.isoformat()})"
        )
    return lines


def _verification_section(version: str) -> list[str]:
    archive = f"maa-llm-wiki-catalog-{version}.zip"
    return [
        "## Verification",
        "",
        "```bash",
        "sha256sum -c SHA256SUMS",
        f"gh attestation verify {archive} --repo Windsland52/MaaLLMWiki",
        f"python verify_bundle.py --bundle {archive} --expect-version {version} "
        "--checksums SHA256SUMS",
        "```",
    ]


def _assets_section(version: str, bundle: BundleDetails | None) -> list[str]:
    lines = ["## Assets", ""]
    archive = f"maa-llm-wiki-catalog-{version}.zip"
    if bundle is None:
        lines.append(f"- `{archive}`")
    else:
        lines.append(
            f"- `{archive}` — sha256 `{bundle.sha256}`, {bundle.size_bytes} bytes, "
            f"{bundle.file_count} files"
        )
    lines.extend(
        [
            "- `maa-llm-wiki-catalog-latest.zip` (byte-identical copy)",
            "- `SHA256SUMS`, `verify_bundle.py`",
        ]
    )
    return lines


def _documentation_section(version: str, previous_tag: str | None) -> list[str]:
    lines = [
        "## Documentation",
        "",
        "- Start here: `generated/maa-framework/index.md` (versions) and "
        "`generated/maa-framework/machine-symbols.md` (symbol -> version)",
        "- Consumer contract and guarantees: `CATALOG-CONTRACT.md`",
        "- The zip is self-describing: `START-HERE.md`, the READMEs, the contract, the operations "
        "guide and the licence files are inside it",
        "- Known gaps: §8 of the contract",
        "- Extracted change facts: `generated/maa-framework/machine-changes.md`",
        "- Curated behaviour history: `generated/maa-framework/behaviour-changes.md`",
    ]
    if previous_tag is None:
        lines.append(f"- Full changelog: {_REPOSITORY_URL}/commits/{version}")
    else:
        lines.append(f"- Full changelog: {_REPOSITORY_URL}/compare/{previous_tag}...{version}")
    return lines


def render_release_notes(
    *,
    version: str,
    previous_tag: str | None,
    current: Snapshot,
    previous: Snapshot | None,
    wiki_revision: str,
    bundle: BundleDetails | None = None,
    root: Path | None = None,
) -> str:
    """Render the release body for ``version``; deterministic for identical inputs."""
    _require_version(version)
    catalog_line = ", ".join(f"{source.name} `{source.version}`" for source in current.sources)
    lines = [
        f"# Catalog snapshot {version}",
        "",
        f"Catalog data: {catalog_line}. Wiki revision `{wiki_revision}`.",
        "",
    ]
    if previous is None:
        lines.extend(["Initial catalog snapshot.", ""])
        lines.extend(_upstream_section(current))
        lines.append("")
        catalog_files = _catalog_files_section(root, None) if root is not None else []
        if catalog_files:
            lines.extend(catalog_files)
            lines.append("")
        lines.extend(_verification_section(version))
        lines.append("")
        lines.extend(_assets_section(version, bundle))
        lines.append("")
        lines.extend(_documentation_section(version, None))
        return "\n".join(lines).rstrip() + "\n"

    assert previous_tag is not None
    new_releases = _new_releases(current, previous)
    lines.extend(_upstream_section(current))
    lines.append("")
    lines.extend(_new_releases_section(previous_tag, new_releases))
    lines.append("")
    lines.extend(_machine_section(current, previous, new_releases))
    lines.append("")
    curated = _curated_section(current, new_releases)
    if curated:
        lines.extend(curated)
        lines.append("")
    moved = _moved_section(current, previous)
    if moved:
        lines.extend(moved)
        lines.append("")
    catalog_files = _catalog_files_section(root, previous_tag) if root is not None else []
    if catalog_files:
        lines.extend(catalog_files)
        lines.append("")
    lines.extend(_verification_section(version))
    lines.append("")
    lines.extend(_assets_section(version, bundle))
    lines.append("")
    lines.extend(_documentation_section(version, previous_tag))
    return "\n".join(lines).rstrip() + "\n"


def build_release_notes(
    *,
    root: Path,
    version: str,
    previous_tag: str | None,
    bundle: Path | None = None,
) -> str:
    """Load the current/previous snapshots and render the release body."""
    _require_version(version)
    current = load_current_snapshot(root)
    previous = load_previous_snapshot(root, previous_tag) if previous_tag is not None else None
    details = _bundle_details(bundle) if bundle is not None else None
    return render_release_notes(
        version=version,
        previous_tag=previous_tag,
        current=current,
        previous=previous,
        wiki_revision=_wiki_revision(root),
        bundle=details,
        root=root,
    )
