from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path
from typing import Literal

import pytest

from maa_llm_wiki.models import (
    ArtifactKind,
    MachineChange,
    MachineChangeKind,
    ReleaseRecord,
    SemanticChange,
    SourceArtifact,
    SourceInventory,
)
from maa_llm_wiki.release_notes import (
    BundleDetails,
    Snapshot,
    SnapshotSource,
    build_release_notes,
    load_current_snapshot,
    load_previous_snapshot,
    render_release_notes,
)

COMMIT_A = "a" * 40
COMMIT_B = "b" * 40
COMMIT_C = "c" * 40
WIKI_REVISION = "d" * 40


def _release(version: str, commit: str) -> ReleaseRecord:
    return ReleaseRecord(
        version=version,
        tag=f"v{version}",
        commit=commit,
        released_at=date(2026, 1, 2),
    )


def _inventory(version: str, revision: str, paths: dict[str, str]) -> SourceInventory:
    return SourceInventory(
        source_id="maafw",
        version=version,
        revision=revision,
        artifacts=[
            SourceArtifact(
                path=path,
                kind=ArtifactKind.DOCUMENTATION,
                blob=blob,
                title=path,
                summary=f"Summary of {path}.",
            )
            for path, blob in sorted(paths.items())
        ],
    )


def _source(
    *,
    version: str,
    revision: str,
    releases: list[ReleaseRecord],
    inventory: SourceInventory | None = None,
    source_id: str = "maafw",
    name: str = "MaaFramework",
) -> SnapshotSource:
    return SnapshotSource(
        source_id=source_id,
        name=name,
        version=version,
        revision=revision,
        releases=tuple(releases),
        inventory=inventory,
    )


def _change(
    version: str,
    commit: str,
    kind: MachineChangeKind,
    symbol: str,
    *,
    change: Literal["added", "removed", "modified"] = "added",
    path: str = "include/MaaFramework/MaaDef.h",
) -> MachineChange:
    return MachineChange(
        version=version,
        commit=commit,
        change=change,
        kind=kind,
        symbol=symbol,
        quote=f"#define {symbol} 1",
        paths=[path],
    )


def _semantic(version: str, revision: str, topic: str, description: str) -> SemanticChange:
    return SemanticChange(
        topic_id=topic,
        first_version=version,
        revision=revision,
        description=description,
        paths=["docs/en_us/1.1-QuickStarted.md"],
    )


def _previous_snapshot(*, machine_present: bool = True) -> Snapshot:
    return Snapshot(
        sources=(
            _source(
                version="5.15.0",
                revision=COMMIT_A,
                releases=[_release("5.15.0", COMMIT_A)],
                inventory=_inventory("5.15.0", COMMIT_A, {"docs/a.md": "1" * 40}),
            ),
        ),
        machine_changes=(_change("5.15.0", COMMIT_A, MachineChangeKind.ENUM_VALUE, "MaaOld"),)
        if machine_present
        else (),
        machine_source_id="maafw" if machine_present else None,
        semantic_changes=(_semantic("5.15.0", COMMIT_A, "framework.old", "Old behaviour."),),
    )


def _current_snapshot() -> Snapshot:
    return Snapshot(
        sources=(
            _source(
                version="5.16.0",
                revision=COMMIT_B,
                releases=[_release("5.15.0", COMMIT_A), _release("5.16.0", COMMIT_B)],
                inventory=_inventory(
                    "5.16.0",
                    COMMIT_B,
                    {"docs/a.md": "1" * 40, "docs/b.md": "2" * 40, "include/x.h": "3" * 40},
                ),
            ),
        ),
        machine_changes=(
            _change("5.16.0", COMMIT_B, MachineChangeKind.SCHEMA_PROPERTY, "task.mode"),
            _change("5.16.0", COMMIT_B, MachineChangeKind.ENUM_VALUE, "MaaNew"),
            _change("5.15.0", COMMIT_A, MachineChangeKind.ENUM_VALUE, "MaaOld"),
        ),
        machine_source_id="maafw",
        semantic_changes=(
            _semantic("5.15.0", COMMIT_A, "framework.old", "Old behaviour."),
            _semantic("5.16.0", COMMIT_B, "framework.new", "New behaviour."),
        ),
    )


def _render(
    *,
    previous_tag: str | None = "v0.1.0",
    previous: Snapshot | None = None,
    bundle: BundleDetails | None = None,
) -> str:
    return render_release_notes(
        version="v0.2.0",
        previous_tag=previous_tag,
        current=_current_snapshot(),
        previous=_previous_snapshot() if previous is None and previous_tag else previous,
        wiki_revision=WIKI_REVISION,
        bundle=bundle,
    )


def test_render_with_new_releases_machine_and_curated_sections() -> None:
    body = _render(
        bundle=BundleDetails(
            name="maa-llm-wiki-catalog-v0.2.0.zip",
            sha256="e" * 64,
            size_bytes=1_500_000,
            file_count=1278,
        )
    )

    assert body.startswith("# Catalog snapshot v0.2.0\n")
    assert ("Catalog data: MaaFramework `5.16.0`. Wiki revision `" + WIKI_REVISION + "`.") in body
    assert "## Upstream snapshot" in body
    assert "| MaaFramework | 5.16.0 | `" + COMMIT_B + "` |" in body
    assert "## New upstream releases since v0.1.0" in body
    assert f"- MaaFramework 5.16.0 `{COMMIT_B[:12]}` (2026-01-02)" in body
    assert "## Machine-extracted changes" in body
    assert "- `MaaFramework 5.16.0` — 2 records: enum-value 1, schema-property 1" in body
    assert "  - enum-value added `MaaNew` — `include/MaaFramework/MaaDef.h`" in body
    assert "  - schema-property added `task.mode` — `include/MaaFramework/MaaDef.h`" in body
    assert "MaaOld" not in body  # only records for the new release are listed
    assert "## Curated behaviour changes" in body
    assert "- `framework.new`: New behaviour." in body
    assert "framework.old" not in body
    assert "## Indexed material moved" in body
    assert "| MaaFramework | 2 | 0 | 0 |" in body  # b.md + include/x.h added, a.md unchanged
    assert "## Verification" in body
    assert "sha256sum -c SHA256SUMS" in body
    assert "## Assets" in body
    assert "sha256 `" + "e" * 64 + "`, 1500000 bytes, 1278 files" in body
    assert "`maa-llm-wiki-catalog-latest.zip` (byte-identical copy)" in body
    assert "## Documentation" in body
    assert (
        "Full changelog: https://github.com/Windsland52/MaaLLMWiki/compare/v0.1.0...v0.2.0" in body
    )


def test_render_packaging_snapshot_without_new_releases() -> None:
    current = _current_snapshot()
    previous = Snapshot(
        sources=(
            _source(
                version="5.15.0",
                revision=COMMIT_A,
                releases=[_release("5.15.0", COMMIT_A), _release("5.16.0", COMMIT_B)],
                inventory=_inventory("5.16.0", COMMIT_B, {"docs/a.md": "1" * 40}),
            ),
        ),
        machine_changes=(),
        machine_source_id=None,
        semantic_changes=(),
    )
    body = render_release_notes(
        version="v0.2.0",
        previous_tag="v0.1.0",
        current=current,
        previous=previous,
        wiki_revision=WIKI_REVISION,
    )

    assert "No new upstream releases; this snapshot records packaging or metadata changes." in body
    assert "The machine-extracted change catalog first appears in this snapshot;" in body
    assert "lists 3 records (0 unclassified)" in body
    assert "## Curated behaviour changes" not in body


def test_render_no_new_machine_records_points_at_unclassified() -> None:
    current = _current_snapshot()
    previous = _previous_snapshot()
    current = Snapshot(
        sources=current.sources,
        machine_changes=(
            _change("5.15.0", COMMIT_A, MachineChangeKind.UNCLASSIFIED, "unclassified"),
        ),
        machine_source_id="maafw",
        semantic_changes=(),
    )
    body = render_release_notes(
        version="v0.2.0",
        previous_tag="v0.1.0",
        current=current,
        previous=previous,
        wiki_revision=WIKI_REVISION,
    )

    assert "No machine-extracted records for the new releases;" in body
    assert "lists 1 records (1 unclassified)" in body
    assert "## Curated behaviour changes" not in body


def test_render_initial_snapshot() -> None:
    body = render_release_notes(
        version="v0.1.0",
        previous_tag=None,
        current=_current_snapshot(),
        previous=None,
        wiki_revision=WIKI_REVISION,
    )

    assert "Initial catalog snapshot." in body
    assert "## New upstream releases since" not in body
    assert "## Machine-extracted changes" not in body
    assert "## Curated behaviour changes" not in body
    assert "## Indexed material moved" not in body
    assert "## Upstream snapshot" in body
    assert "## Verification" in body
    assert "## Documentation" in body
    assert "https://github.com/Windsland52/MaaLLMWiki/commits/v0.1.0" in body


def test_render_caps_machine_examples_and_curated_entries() -> None:
    kinds = list(MachineChangeKind)
    releases = [
        _release("5.15.0", COMMIT_A),
        _release("5.16.0", COMMIT_B),
        _release("5.17.0", COMMIT_C),
    ]
    source = _source(
        version="5.17.0",
        revision=COMMIT_C,
        releases=releases,
        inventory=_inventory("5.17.0", COMMIT_C, {"docs/a.md": "1" * 40}),
    )
    records = tuple(
        _change(
            "5.16.0" if index < len(kinds) else "5.17.0",
            COMMIT_B if index < len(kinds) else COMMIT_C,
            kinds[index % len(kinds)],
            f"MaaSymbol{index:02d}",
        )
        for index in range(2 * len(kinds))
    )
    semantic = tuple(
        _semantic("5.16.0", COMMIT_B, f"framework.topic{index:02d}", f"Change {index}.")
        for index in range(12)
    )
    current = Snapshot(
        sources=(source,),
        machine_changes=records,
        machine_source_id="maafw",
        semantic_changes=semantic,
    )

    body = render_release_notes(
        version="v0.2.0",
        previous_tag="v0.1.0",
        current=current,
        previous=_previous_snapshot(),
        wiki_revision=WIKI_REVISION,
    )

    assert body.count("— 10 records:") == 2
    example_lines = [line for line in body.splitlines() if line.startswith("  - ")]
    assert len(example_lines) == 15
    assert "Example records capped at 15." in body
    curated = [line for line in body.splitlines() if line.startswith("- `framework.topic")]
    assert len(curated) == 10
    assert "(2 more entries omitted)" in body


def test_render_is_deterministic() -> None:
    assert _render() == _render()


def test_render_rejects_malformed_version() -> None:
    with pytest.raises(ValueError, match="version must look like vX.Y.Z"):
        render_release_notes(
            version="0.2.0",
            previous_tag=None,
            current=_current_snapshot(),
            previous=None,
            wiki_revision=WIKI_REVISION,
        )


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _write_snapshot_state(
    root: Path, *, version: str, commit_hint: str, extra_release: bool
) -> None:
    sources = root / "sources" / "maa-framework"
    (sources / "inventories").mkdir(parents=True, exist_ok=True)
    (root / "sources" / "repositories.yaml").write_text(
        "repositories:\n"
        "- id: maafw\n"
        "  name: MaaFramework\n"
        "  url: https://github.com/MaaXYZ/MaaFramework\n"
        "  role: authoritative\n"
        "  enabled: true\n"
        f"  default_revision: {commit_hint}\n",
        encoding="utf-8",
    )
    releases = [("5.15.0", COMMIT_A)]
    if extra_release:
        releases.append((version, commit_hint))
    release_lines = ["source_id: maafw", "releases:"]
    for release_version, commit in releases:
        release_lines.extend(
            [
                f"- version: {release_version}",
                f"  tag: v{release_version}",
                f"  commit: {commit}",
                "  released_at: '2026-01-02'",
            ]
        )
    (sources / "releases.yaml").write_text("\n".join(release_lines) + "\n", encoding="utf-8")
    (sources / "inventory.yaml").write_text(
        "source_id: maafw\n"
        f"version: {version}\n"
        f"revision: {commit_hint}\n"
        "artifacts:\n"
        "- path: docs/a.md\n"
        "  kind: documentation\n"
        "  title: A\n"
        "  summary: A doc.\n",
        encoding="utf-8",
    )
    machine_lines = ["source_id: maafw", "changes:"]
    if extra_release:
        machine_lines.extend(
            [
                f"- version: {version}",
                f"  commit: {commit_hint}",
                "  change: added",
                "  kind: enum-value",
                "  symbol: MaaNew",
                "  quote: '#define MaaNew 1'",
                "  paths:",
                "  - include/MaaFramework/MaaDef.h",
            ]
        )
    if not extra_release:
        machine_lines = ["source_id: maafw", "changes: []"]
    (sources / "machine-changes.yaml").write_text("\n".join(machine_lines) + "\n", encoding="utf-8")
    semantic_lines = ["source_id: maafw", "changes:"]
    if extra_release:
        semantic_lines.extend(
            [
                "  - topic_id: framework.new",
                f"    first_version: {version}",
                f"    revision: {commit_hint}",
                "    description: New behaviour.",
                "    paths:",
                "    - docs/a.md",
            ]
        )
    if not extra_release:
        semantic_lines = ["source_id: maafw", "changes: []"]
    (sources / "semantic-changes.yaml").write_text(
        "\n".join(semantic_lines) + "\n", encoding="utf-8"
    )


@pytest.fixture()
def catalog_git_repo(tmp_path: Path) -> Path:
    repository = tmp_path / "catalog"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "catalog@example.com")
    _git(repository, "config", "user.name", "Catalog Test")
    _git(repository, "config", "commit.gpgsign", "false")
    _write_snapshot_state(repository, version="5.15.0", commit_hint=COMMIT_A, extra_release=False)
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "-m", "snapshot one")
    _git(repository, "tag", "v0.1.0")

    _write_snapshot_state(repository, version="5.16.0", commit_hint=COMMIT_B, extra_release=True)
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "-m", "snapshot two")
    _git(repository, "tag", "v0.2.0")
    return repository


def test_load_previous_snapshot_reads_the_tagged_git_objects(catalog_git_repo: Path) -> None:
    snapshot = load_previous_snapshot(catalog_git_repo, "v0.1.0")

    assert [source.version for source in snapshot.sources] == ["5.15.0"]
    assert [release.version for release in snapshot.sources[0].releases] == ["5.15.0"]
    assert snapshot.machine_source_id == "maafw"
    assert snapshot.machine_changes == ()
    assert snapshot.sources[0].inventory is not None
    assert snapshot.sources[0].inventory.version == "5.15.0"


def test_load_current_snapshot_reads_the_working_tree(catalog_git_repo: Path) -> None:
    snapshot = load_current_snapshot(catalog_git_repo)

    assert [source.version for source in snapshot.sources] == ["5.16.0"]
    assert [release.version for release in snapshot.sources[0].releases] == ["5.15.0", "5.16.0"]
    assert len(snapshot.machine_changes) == 1
    assert snapshot.machine_changes[0].symbol == "MaaNew"


def test_load_previous_snapshot_rejects_unknown_tag(catalog_git_repo: Path) -> None:
    with pytest.raises(ValueError, match="unknown previous tag: v9.9.9"):
        load_previous_snapshot(catalog_git_repo, "v9.9.9")


def test_build_release_notes_against_the_temp_git_repo(catalog_git_repo: Path) -> None:
    body = build_release_notes(
        root=catalog_git_repo,
        version="v0.2.0",
        previous_tag="v0.1.0",
    )

    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=catalog_git_repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    assert f"Wiki revision `{revision}`" in body
    assert "## New upstream releases since v0.1.0" in body
    assert f"- MaaFramework 5.16.0 `{COMMIT_B[:12]}` (2026-01-02)" in body
    assert "- `MaaFramework 5.16.0` — 1 records: enum-value 1" in body
    assert "- `framework.new`: New behaviour." in body
    assert "| MaaFramework | 0 | 0 | 0 |" in body
