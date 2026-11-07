from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile

import yaml

from .bindings import BINDING_SPECS, sync_binding_history
from .bundle import build_catalog_bundle, bundle_sha256, verify_catalog_bundle
from .inventory import artifact_changed, sync_maafw_history, write_yaml
from .models import (
    ArtifactKind,
    MachineChange,
    MachineChangeCatalog,
    SourceArtifact,
    SourceInventory,
    UpstreamCommit,
    UpstreamCommitCatalog,
)
from .release_notes import build_release_notes
from .schemas import generate_schemas
from .validation import (
    load_repository_catalog,
    load_source_inventories,
    validate_repository,
)


def _error_boundary(action: Callable[[], int]) -> Callable[[], int]:
    """Turn expected failures into one actionable line instead of a traceback."""

    def run() -> int:
        try:
            return action()
        except (OSError, RuntimeError, ValueError, BadZipFile) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1

    return run


def _root_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser


@_error_boundary
def main() -> int:
    args = _root_parser("Validate MaaLLMWiki content and source metadata").parse_args()
    errors = validate_repository(args.root.resolve())
    if errors:
        for error in errors:
            print(error)
        return 1
    print("MaaLLMWiki validation passed")
    return 0


@_error_boundary
def generate_schemas_main() -> int:
    args = _root_parser("Generate MaaLLMWiki metadata schemas").parse_args()
    generate_schemas(args.root.resolve())
    return 0


@_error_boundary
def sync_maafw_history_main() -> int:
    parser = _root_parser("Index all stable releases for a MaaFramework major version")
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--major", type=int, default=5)
    parser.add_argument(
        "--prune",
        action="store_true",
        help=(
            "allow the upstream tag list to shrink the registered release/prerelease registry "
            "(do NOT pass from automation)"
        ),
    )
    args = parser.parse_args()
    releases, prereleases = sync_maafw_history(
        root=args.root.resolve(),
        repository=args.repository.resolve(),
        major=args.major,
        prune=args.prune,
    )
    print(
        f"Indexed {len(releases)} MaaFramework {args.major}.x releases "
        f"and {len(prereleases)} prereleases"
    )
    return 0


def _parse_binding_repository(value: str) -> tuple[str, Path]:
    source_id, separator, raw_path = value.partition("=")
    if not separator or not source_id or not raw_path:
        raise ValueError(f"invalid --repository value, expected SOURCE_ID=PATH: {value!r}")
    return source_id, Path(raw_path)


def _binding_repositories(
    *,
    explicit: list[str],
    go_repository: Path | None,
    rust_repository: Path | None,
) -> dict[str, Path]:
    repositories: dict[str, Path] = {}
    for value in explicit:
        source_id, path = _parse_binding_repository(value)
        if source_id not in BINDING_SPECS:
            raise ValueError(f"unsupported binding source: {source_id}")
        if source_id in repositories:
            raise ValueError(f"duplicate --repository entry for binding source: {source_id}")
        repositories[source_id] = path.resolve()
    legacy = {
        "maa-framework-go": go_repository,
        "maa-framework-rs": rust_repository,
    }
    for source_id, path in legacy.items():
        if path is not None and source_id not in repositories:
            repositories[source_id] = path.resolve()
    if not repositories:
        raise ValueError("no binding repositories given")
    return repositories


@_error_boundary
def sync_bindings_history_main() -> int:
    parser = _root_parser("Index all stable releases for registered binding sources")
    parser.add_argument(
        "--repository",
        action="append",
        default=None,
        metavar="SOURCE_ID=PATH",
        help=(
            "binding source id and clone path, repeat once per source "
            "(e.g. maa-framework-go=../maa-framework-go)"
        ),
    )
    parser.add_argument(
        "--go-repository",
        type=Path,
        help="legacy alias for --repository maa-framework-go=PATH (optional)",
    )
    parser.add_argument(
        "--rust-repository",
        type=Path,
        help="legacy alias for --repository maa-framework-rs=PATH (optional)",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help=(
            "allow the upstream tag list to shrink the registered release/prerelease registry "
            "(do NOT pass from automation)"
        ),
    )
    args = parser.parse_args()
    repositories = _binding_repositories(
        explicit=args.repository if args.repository is not None else [],
        go_repository=args.go_repository,
        rust_repository=args.rust_repository,
    )
    for source_id in BINDING_SPECS:
        repository = repositories.get(source_id)
        if repository is None:
            continue
        releases, prereleases = sync_binding_history(
            root=args.root.resolve(),
            repository=repository,
            source_id=source_id,
            prune=args.prune,
        )
        print(
            f"Indexed {len(releases)} stable {BINDING_SPECS[source_id].display_name} releases "
            f"and {len(prereleases)} prereleases"
        )
    return 0


@_error_boundary
def build_bundle_main() -> int:
    parser = _root_parser("Build a versioned MaaLLMWiki catalog snapshot")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument(
        "--version",
        "--catalog-version",
        dest="catalog_version",
        default=None,
        help=(
            "snapshot tag recorded in catalog-manifest.json as catalog_version "
            "(for example v0.2.0; --catalog-version is kept as an alias)"
        ),
    )
    args = parser.parse_args()
    manifest = build_catalog_bundle(
        root=args.root.resolve(),
        output=args.output.resolve(),
        allow_dirty=args.allow_dirty,
        version=args.catalog_version,
    )
    print(f"Built catalog bundle for {manifest.wiki_revision} with {len(manifest.files)} files")
    return 0


@_error_boundary
def verify_bundle_main() -> int:
    parser = _root_parser("Verify a versioned MaaLLMWiki catalog bundle")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--expect-revision")
    parser.add_argument("--expect-version")
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    manifest = verify_catalog_bundle(
        bundle=bundle,
        expect_revision=args.expect_revision,
        expect_version=args.expect_version,
    )
    version = manifest.catalog_version or "unversioned"
    print(
        f"Verified catalog bundle: {version} {manifest.wiki_revision} "
        f"({len(manifest.files)} files) sha256={bundle_sha256(bundle)}"
    )
    return 0


_DIFF_KINDS = tuple(kind.value for kind in ArtifactKind)


@dataclass(frozen=True)
class _DiffEntry:
    path: str
    kind: str
    title: str
    summary: str
    blob: str | None
    previous_title: str | None = None
    previous_summary: str | None = None
    previous_blob: str | None = None


@dataclass(frozen=True)
class _InventoryDiff:
    added: tuple[_DiffEntry, ...]
    removed: tuple[_DiffEntry, ...]
    changed: tuple[_DiffEntry, ...]


def _diff_entry(artifact: SourceArtifact) -> _DiffEntry:
    return _DiffEntry(
        path=artifact.path,
        kind=artifact.kind.value,
        title=artifact.title,
        summary=artifact.summary,
        blob=artifact.blob,
    )


def _diff_inventories(before: SourceInventory, after: SourceInventory) -> _InventoryDiff:
    old = {artifact.path: artifact for artifact in before.artifacts}
    new = {artifact.path: artifact for artifact in after.artifacts}
    added = tuple(_diff_entry(new[path]) for path in sorted(set(new) - set(old)))
    removed = tuple(_diff_entry(old[path]) for path in sorted(set(old) - set(new)))
    changed: list[_DiffEntry] = []
    for path in sorted(set(new) & set(old)):
        previous = old[path]
        entry = new[path]
        if not artifact_changed(previous, entry):
            continue
        changed.append(
            _DiffEntry(
                path=entry.path,
                kind=entry.kind.value,
                title=entry.title,
                summary=entry.summary,
                blob=entry.blob,
                previous_title=previous.title,
                previous_summary=previous.summary,
                previous_blob=previous.blob,
            )
        )
    return _InventoryDiff(added=added, removed=removed, changed=tuple(changed))


def _json_entry(entry: _DiffEntry) -> dict[str, str | None]:
    return {
        "path": entry.path,
        "kind": entry.kind,
        "title": entry.title,
        "summary": entry.summary,
        "blob": entry.blob,
        "previous_title": entry.previous_title,
        "previous_summary": entry.previous_summary,
        "previous_blob": entry.previous_blob,
    }


def _diff_json(
    source_id: str,
    before: SourceInventory,
    after: SourceInventory,
    diff: _InventoryDiff,
) -> str:
    by_kind: dict[str, dict[str, int]] = {}
    for kind in _DIFF_KINDS:
        counts = {
            "added": sum(1 for entry in diff.added if entry.kind == kind),
            "removed": sum(1 for entry in diff.removed if entry.kind == kind),
            "changed": sum(1 for entry in diff.changed if entry.kind == kind),
        }
        if any(counts.values()):
            by_kind[kind] = counts
    payload: dict[str, object] = {
        "source": source_id,
        "from": {"version": before.version, "revision": before.revision},
        "to": {"version": after.version, "revision": after.revision},
        "counts": {
            "added": len(diff.added),
            "removed": len(diff.removed),
            "changed": len(diff.changed),
        },
        "by_kind": by_kind,
        "added": [_json_entry(entry) for entry in diff.added],
        "removed": [_json_entry(entry) for entry in diff.removed],
        "changed": [_json_entry(entry) for entry in diff.changed],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _diff_line(entry: _DiffEntry) -> str:
    line = f"- `{entry.path}` — {entry.title}"
    if entry.previous_title is not None and entry.previous_title != entry.title:
        line += f" (was: {entry.previous_title})"
    if entry.previous_title is not None and entry.previous_blob != entry.blob:
        previous = (entry.previous_blob or "no blob")[:12]
        current = (entry.blob or "no blob")[:12]
        line += f" [`{previous}` -> `{current}`]"
    return line


def _diff_markdown(
    source_id: str,
    before: SourceInventory,
    after: SourceInventory,
    diff: _InventoryDiff,
) -> str:
    lines = [
        f"# Catalog diff: {source_id} {before.version} -> {after.version}",
        "",
        f"- From: `{before.version}` at `{before.revision}`",
        f"- To: `{after.version}` at `{after.revision}`",
        "",
        f"Totals: {len(diff.added)} added, {len(diff.removed)} removed, "
        f"{len(diff.changed)} changed.",
        "",
    ]
    sections = (
        ("Added", diff.added),
        ("Removed", diff.removed),
        ("Changed", diff.changed),
    )
    if not any(entries for _, entries in sections):
        lines.append("No artifact changes.")
        return "\n".join(lines) + "\n"
    for heading, entries in sections:
        if not entries:
            continue
        lines.extend([f"## {heading} ({len(entries)})", ""])
        for kind in _DIFF_KINDS:
            grouped = [entry for entry in entries if entry.kind == kind]
            if not grouped:
                continue
            lines.extend([f"### {kind}", "", *(_diff_line(entry) for entry in grouped), ""])
    return "\n".join(lines).rstrip() + "\n"


@_error_boundary
def diff_main() -> int:
    parser = _root_parser("Diff the indexed inventories of two releases for one source")
    parser.add_argument("--from", dest="from_version", required=True)
    parser.add_argument("--to", dest="to_version", required=True)
    parser.add_argument("--source", default="maafw")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()
    root = args.root.resolve()
    known_sources = {repository.id for repository in load_repository_catalog(root).repositories}
    if args.source not in known_sources:
        raise ValueError(f"unknown source: {args.source}")
    inventories = {
        inventory.version: inventory for inventory in load_source_inventories(root, args.source)
    }
    for version in (args.from_version, args.to_version):
        if version not in inventories:
            raise ValueError(f"unknown {args.source} release: {version}")
    before = inventories[args.from_version]
    after = inventories[args.to_version]
    diff = _diff_inventories(before, after)
    if args.format == "json":
        print(_diff_json(args.source, before, after, diff))
    else:
        print(_diff_markdown(args.source, before, after, diff), end="")
    return 0


_MACHINE_CHANGES_PATH = "sources/maa-framework/machine-changes.yaml"
_UPSTREAM_COMMITS_PATH = "sources/maa-framework/upstream-commits.yaml"
# Comparison key and the (version, label) pair used to summarise a difference.
_RecordKey = tuple[object, ...]


def _version_sort_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) if part.isdigit() else -1 for part in version.split("."))


def _machine_change_key(change: MachineChange) -> _RecordKey:
    return (
        change.version,
        change.kind.value,
        change.commit,
        change.change,
        change.symbol,
        change.quote,
        change.previous_quote,
        tuple(change.paths),
    )


def _upstream_commit_key(commit: UpstreamCommit) -> _RecordKey:
    return (
        commit.version,
        "commit",
        commit.commit,
        commit.subject,
        commit.pull_request,
        commit.path_count,
        tuple(commit.paths),
    )


def _load_committed(path: Path, label: str) -> object:
    if not path.is_file():
        raise ValueError(f"committed {label} is missing: {path}")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError(f"committed {label} is not valid YAML: {error}") from error


def _report_difference(
    label: str, relative: str, fresh: Counter[_RecordKey], committed: Counter[_RecordKey]
) -> bool:
    """Print whether the fresh records match the committed ones; True when they match."""
    added = fresh - committed
    missing = committed - fresh
    total = sum(fresh.values())
    if not added and not missing:
        print(f"{label} matches {relative} ({total} record(s))")
        return True
    print(
        f"{label} differs from {relative}: {sum(added.values())} new, "
        f"{sum(missing.values())} missing, {total} extracted total"
    )
    for heading, keys in (("new", added), ("missing", missing)):
        if not keys:
            continue
        counts: Counter[tuple[str, str]] = Counter()
        for key in keys.elements():
            counts[(str(key[0]), str(key[1]))] += 1
        print(f"  {heading}:")
        for (version, kind), count in sorted(
            counts.items(), key=lambda item: (_version_sort_key(item[0][0]), item[0][1])
        ):
            print(f"    {version} {kind}: {count}")
    return False


def _build_machine_changes(*, root: Path, repository: Path) -> MachineChangeCatalog:
    """Extractor hook kept separate so tests can stub the sync-side implementation."""
    from .extract import build_machine_changes

    return build_machine_changes(root=root, repository=repository)


def _build_upstream_commits(*, root: Path, repository: Path) -> UpstreamCommitCatalog:
    """Commit-index hook kept separate so tests can stub the sync-side implementation."""
    from .commits import build_upstream_commits

    return build_upstream_commits(root=root, repository=repository)


@_error_boundary
def extract_changes_main() -> int:
    parser = _root_parser(
        "Extract the machine-change catalog and the upstream commit index from a MaaFramework clone"
    )
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare with the committed YAML instead of writing it (release gate)",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    repository = args.repository.resolve()
    changes = _build_machine_changes(root=root, repository=repository)
    commits = _build_upstream_commits(root=root, repository=repository)
    changes_path = root / _MACHINE_CHANGES_PATH
    commits_path = root / _UPSTREAM_COMMITS_PATH
    if not args.check:
        changes_path.parent.mkdir(parents=True, exist_ok=True)
        write_yaml(changes_path, changes.model_dump(mode="json", exclude_none=True))
        write_yaml(commits_path, commits.model_dump(mode="json", exclude_none=True))
        print(f"Wrote {_MACHINE_CHANGES_PATH} with {len(changes.changes)} machine change(s)")
        print(f"Wrote {_UPSTREAM_COMMITS_PATH} with {len(commits.commits)} upstream commit(s)")
        return 0
    committed_changes = MachineChangeCatalog.model_validate(
        _load_committed(changes_path, "machine change catalog")
    )
    committed_commits = UpstreamCommitCatalog.model_validate(
        _load_committed(commits_path, "upstream commit index")
    )
    changes_match = _report_difference(
        "Machine change catalog",
        _MACHINE_CHANGES_PATH,
        Counter(_machine_change_key(change) for change in changes.changes),
        Counter(_machine_change_key(change) for change in committed_changes.changes),
    )
    commits_match = _report_difference(
        "Upstream commit index",
        _UPSTREAM_COMMITS_PATH,
        Counter(_upstream_commit_key(commit) for commit in commits.commits),
        Counter(_upstream_commit_key(commit) for commit in committed_commits.commits),
    )
    return 0 if changes_match and commits_match else 1


@_error_boundary
def release_notes_main() -> int:
    parser = _root_parser("Render a substantive release body from the catalog snapshot")
    parser.add_argument("--version", required=True)
    parser.add_argument("--previous")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = build_release_notes(
        root=args.root.resolve(),
        version=args.version,
        previous_tag=args.previous,
        bundle=args.bundle.resolve() if args.bundle is not None else None,
    )
    if args.output is None:
        print(text, end="")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8", newline="\n")
    return 0
