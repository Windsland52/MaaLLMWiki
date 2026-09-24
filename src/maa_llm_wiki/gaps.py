from __future__ import annotations

from dataclasses import dataclass
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


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _is_reviewable(artifact: SourceArtifact) -> bool:
    return artifact.kind in REVIEW_KINDS


@dataclass(frozen=True)
class ReleaseDelta:
    version: str
    revision: str
    previous_version: str
    previous_revision: str
    added: tuple[str, ...]
    removed: tuple[str, ...]
    revised: tuple[str, ...]

    @property
    def tracked_changes(self) -> int:
        return len(self.added) + len(self.removed) + len(self.revised)


@dataclass(frozen=True)
class ReviewQueue:
    reviewed_through: str | None
    entries: tuple[ReleaseDelta, ...]


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
        and (artifact.title != before[path].title or artifact.summary != before[path].summary)
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


def review_queue(root: Path) -> ReviewQueue:
    """Indexed releases newer than the newest semantic-change record whose material moved.

    Recorded titles and summaries are compared between consecutive inventories. A moved title or
    summary is a suspected trigger for a behavior change, not proof of one: the summary is the
    first paragraph of the artifact, so edits deeper inside a file stay invisible here.
    """
    releases = sorted(
        load_release_catalog(root).releases, key=lambda item: _version_key(item.version)
    )
    changes = load_semantic_changes(root).changes
    inventories = {inventory.version: inventory for inventory in load_source_inventories(root)}
    recorded = [change.first_version for change in changes]
    reviewed_through = max(recorded, key=_version_key) if recorded else None
    threshold = _version_key(reviewed_through) if reviewed_through is not None else None

    entries: list[ReleaseDelta] = []
    previous: SourceInventory | None = None
    for release in releases:
        inventory = inventories.get(release.version)
        if inventory is None:
            continue
        if previous is not None:
            delta = _delta(previous, inventory)
            if delta.tracked_changes and (
                threshold is None or _version_key(release.version) > threshold
            ):
                entries.append(delta)
        previous = inventory
    return ReviewQueue(reviewed_through=reviewed_through, entries=tuple(entries))


def _bullet(label: str, paths: tuple[str, ...]) -> list[str]:
    if not paths:
        return []
    listed = ", ".join(f"`{path}`" for path in paths[:_LISTED_PATHS])
    if len(paths) > _LISTED_PATHS:
        listed += f", and {len(paths) - _LISTED_PATHS} more"
    return [f"  - {label}: {listed}"]


def render_review_queue(root: Path) -> str:
    """Render the semantic-review issue body, or an empty string when nothing needs review."""
    queue = review_queue(root)
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
        "recorded titles and summaries come from the first paragraph of each artifact, so edits",
        "deeper inside a file are not detected here.",
        "",
    ]
    for entry in reversed(queue.entries):
        lines.append(
            f"- **{entry.version}** `{entry.revision[:12]}` "
            f"(previous `{entry.previous_version}` `{entry.previous_revision[:12]}`)"
        )
        lines.extend(_bullet("added", entry.added))
        lines.extend(_bullet("removed", entry.removed))
        lines.extend(_bullet("revised", entry.revised))
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
