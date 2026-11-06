from __future__ import annotations

import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from .models import ArtifactKind, SourceArtifact, SourceInventory
from .validation import load_release_catalog, load_semantic_changes, load_source_inventories

REVIEW_KINDS = frozenset(
    {
        ArtifactKind.DOCUMENTATION,
        ArtifactKind.SCHEMA,
        ArtifactKind.PUBLIC_API,
        ArtifactKind.BINDING_API,
    }
)
_LISTED_PATHS = 5
_CONTENT_PATHS = ("docs", "tools", "include", "source/binding")


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _is_reviewable(artifact: SourceArtifact) -> bool:
    return artifact.kind in REVIEW_KINDS


def artifact_changed(before: SourceArtifact, after: SourceArtifact) -> bool:
    """Whether recorded material changed, using the content hash whenever both sides have one.

    Inventories generated after blob ids were introduced carry the git blob SHA of each artifact,
    so a content edit is visible without a clone. Artifacts without a blob id (older inventories)
    still fall back to comparing the recorded title and summary.
    """
    if before.blob is not None and after.blob is not None:
        return before.blob != after.blob
    return before.title != after.title or before.summary != after.summary


@dataclass(frozen=True)
class ReleaseDelta:
    version: str
    revision: str
    previous_version: str
    previous_revision: str
    added: tuple[str, ...]
    removed: tuple[str, ...]
    revised: tuple[str, ...]
    content_changed: tuple[str, ...] = ()

    @property
    def tracked_changes(self) -> int:
        return len(self.added) + len(self.removed) + len(self.revised) + len(self.content_changed)


@dataclass(frozen=True)
class ReviewQueue:
    reviewed_through: str | None
    entries: tuple[ReleaseDelta, ...]


def _content_changed(
    repository: Path,
    previous_tag: str,
    current_tag: str,
    indexed_paths: set[str],
) -> tuple[str, ...]:
    """Paths with content edits between two release tags that the inventories actually index.

    This is the optional cross-check for the offline blob comparison: it can only add evidence
    (for example for inventories that predate blob ids), never remove it.
    """
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "core.quotepath=false",
            "diff",
            "--numstat",
            "--no-renames",
            f"{previous_tag}..{current_tag}",
            "--",
            *_CONTENT_PATHS,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git diff {previous_tag}..{current_tag} failed in {repository}: "
            f"{result.stderr.strip()}"
        )
    changed: set[str] = set()
    for line in result.stdout.splitlines():
        fields = line.split("\t", 2)
        if len(fields) != 3:
            continue
        path = fields[2].strip()
        if path in indexed_paths:
            changed.add(path)
    return tuple(sorted(changed))


def _delta(previous: SourceInventory, current: SourceInventory) -> ReleaseDelta:
    before = {artifact.path: artifact for artifact in previous.artifacts}
    after = {artifact.path: artifact for artifact in current.artifacts}
    added = tuple(
        path for path, artifact in after.items() if path not in before and _is_reviewable(artifact)
    )
    removed = tuple(
        path for path, artifact in before.items() if path not in after and _is_reviewable(artifact)
    )
    revised = tuple(
        path
        for path, artifact in after.items()
        if path in before
        and artifact_changed(before[path], artifact)
        and (_is_reviewable(artifact) or _is_reviewable(before[path]))
    )
    return ReleaseDelta(
        version=current.version,
        revision=current.revision,
        previous_version=previous.version,
        previous_revision=previous.revision,
        added=added,
        removed=removed,
        revised=revised,
    )


def review_queue(root: Path, repository: Path | None = None) -> ReviewQueue:
    """Indexed releases newer than the newest semantic-change record whose material moved.

    Artifact content is compared between consecutive inventories through the recorded git blob
    ids, so an edit deeper inside a file is detected without a clone. Inventories that predate
    blob ids fall back to comparing the recorded title and summary. Pass a pinned MaaFramework
    clone as ``repository`` to cross-check the diff against the release tags; the clone can only
    add evidence, never remove it.
    """
    releases = sorted(
        load_release_catalog(root).releases, key=lambda item: _version_key(item.version)
    )
    changes = load_semantic_changes(root).changes
    inventories = {inventory.version: inventory for inventory in load_source_inventories(root)}
    recorded = [change.first_version for change in changes]
    reviewed_through = max(recorded, key=_version_key) if recorded else None
    threshold = _version_key(reviewed_through) if reviewed_through is not None else None
    indexed_paths = {
        artifact.path for inventory in inventories.values() for artifact in inventory.artifacts
    }
    reviewable_paths = {
        artifact.path
        for inventory in inventories.values()
        for artifact in inventory.artifacts
        if _is_reviewable(artifact)
    }

    entries: list[ReleaseDelta] = []
    previous: SourceInventory | None = None
    previous_tag: str | None = None
    for release in releases:
        inventory = inventories.get(release.version)
        if inventory is None:
            continue
        if previous is not None:
            after_threshold = threshold is None or _version_key(release.version) > threshold
            delta = _delta(previous, inventory)
            if repository is not None and after_threshold and previous_tag is not None:
                clone_changed = _content_changed(
                    repository, previous_tag, release.tag, indexed_paths
                )
                reported = set(delta.added) | set(delta.removed) | set(delta.revised)
                extra = tuple(
                    path
                    for path in clone_changed
                    if path not in reported and path in reviewable_paths
                )
                if extra:
                    delta = replace(delta, content_changed=extra)
            if delta.tracked_changes and after_threshold:
                entries.append(delta)
        previous = inventory
        previous_tag = release.tag
    return ReviewQueue(reviewed_through=reviewed_through, entries=tuple(entries))


def _bullet(label: str, paths: tuple[str, ...]) -> list[str]:
    if not paths:
        return []
    listed = ", ".join(f"`{path}`" for path in paths[:_LISTED_PATHS])
    if len(paths) > _LISTED_PATHS:
        listed += f", and {len(paths) - _LISTED_PATHS} more"
    return [f"  - {label}: {listed}"]


def render_review_queue(root: Path, repository: Path | None = None) -> str:
    """Render the semantic-review issue body, or an empty string when nothing needs review."""
    queue = review_queue(root, repository)
    if not queue.entries:
        return ""
    since = queue.reviewed_through
    recorded = (
        f"the newest `semantic-changes.yaml` entry (`{since}`)"
        if since is not None
        else "any recorded semantic change"
    )
    lines = [
        "### MaaFramework releases awaiting semantic-change review",
        "",
        f"Recorded official material moved in {len(queue.entries)} indexed release(s) newer than",
        f"{recorded}. Each item is a suspected trigger for a behavior change, not a verified one:",
        "artifact content is compared through the git blob ids recorded in each inventory, so an",
        "edit anywhere inside a file is visible; recorded titles and summaries are the fallback",
        "for inventories that predate blob ids.",
    ]
    if repository is not None:
        lines.extend(
            [
                "The optional `git diff` cross-check against the pinned release tags can only add",
                "paths, never hide one.",
            ]
        )
    lines.append("")
    for entry in reversed(queue.entries):
        lines.append(
            f"- **{entry.version}** `{entry.revision[:12]}` "
            f"(previous `{entry.previous_version}` `{entry.previous_revision[:12]}`)"
        )
        lines.extend(_bullet("added", entry.added))
        lines.extend(_bullet("removed", entry.removed))
        lines.extend(_bullet("revised", entry.revised))
        lines.extend(_bullet("content changed (git cross-check)", entry.content_changed))
    lines.extend(
        [
            "",
            "Review each release against its pinned commit and add a `semantic-changes.yaml` entry",
            "when runtime behavior changed; a new release alone is not enough.",
            "",
            "Opened by `.github/workflows/publish-catalog.yml`.",
            "",
        ]
    )
    return "\n".join(lines)
