from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from maa_llm_wiki.gaps import render_review_queue, review_queue

COMMIT_A = "a" * 40
COMMIT_B = "b" * 40
COMMIT_C = "c" * 40

Artifact = tuple[str, str, str] | tuple[str, str, str, str]
Artifacts = list[Artifact]
Release = tuple[str, str, Artifacts]


def _write_catalog(root: Path, releases: list[Release], recorded: list[str]) -> None:
    inventory_root = root / "sources" / "maa-framework" / "inventories"
    inventory_root.mkdir(parents=True)
    release_lines = ["source_id: maafw", "releases:"]
    commits = {version: commit for version, commit, _ in releases}
    for version, commit, artifacts in releases:
        release_lines.extend(
            [
                f"- version: {version}",
                f"  tag: v{version}",
                f"  commit: {commit}",
                "  released_at: '2026-01-01'",
            ]
        )
        inventory_lines = [
            "source_id: maafw",
            f"version: {version}",
            f"revision: {commit}",
            "artifacts:",
        ]
        for artifact in sorted(artifacts):
            path, kind, summary = artifact[0], artifact[1], artifact[2]
            inventory_lines.extend([f"- path: {path}", f"  kind: {kind}"])
            if len(artifact) == 4:
                inventory_lines.append(f"  blob: '{artifact[3]}'")
            inventory_lines.extend(["  title: Title", f"  summary: {summary}"])
        (inventory_root / f"{version}.yaml").write_text(
            "\n".join(inventory_lines) + "\n", encoding="utf-8"
        )
    (root / "sources" / "maa-framework" / "releases.yaml").write_text(
        "\n".join(release_lines) + "\n", encoding="utf-8"
    )
    change_lines = ["source_id: maafw", "changes:"]
    for index, version in enumerate(recorded):
        change_lines.extend(
            [
                f"- topic_id: framework.topic-{index}",
                f"  first_version: {version}",
                f"  revision: {commits[version]}",
                "  description: Recorded behavior change.",
                "  paths:",
                "  - docs/zh_cn/a.md",
            ]
        )
    (root / "sources" / "maa-framework" / "semantic-changes.yaml").write_text(
        "\n".join(change_lines) + "\n", encoding="utf-8"
    )


def test_review_queue_lists_releases_after_the_newest_recorded_change(tmp_path: Path) -> None:
    _write_catalog(
        tmp_path,
        [
            ("1.0.0", COMMIT_A, [("docs/zh_cn/a.md", "documentation", "A.")]),
            (
                "1.1.0",
                COMMIT_B,
                [
                    ("docs/zh_cn/a.md", "documentation", "A."),
                    ("docs/zh_cn/b.md", "documentation", "B."),
                ],
            ),
            (
                "1.2.0",
                COMMIT_C,
                [
                    ("docs/zh_cn/a.md", "documentation", "A."),
                    ("docs/zh_cn/b.md", "documentation", "B."),
                    ("docs/zh_cn/mirrorc-zh.svg", "documentation-asset", "Logo."),
                ],
            ),
        ],
        recorded=["1.0.0"],
    )

    queue = review_queue(tmp_path)

    assert queue.reviewed_through == "1.0.0"
    assert [entry.version for entry in queue.entries] == ["1.1.0"]
    assert queue.entries[0].added == ("docs/zh_cn/b.md",)
    assert queue.entries[0].previous_version == "1.0.0"


def test_review_queue_skips_releases_at_or_before_the_recorded_change(tmp_path: Path) -> None:
    _write_catalog(
        tmp_path,
        [
            ("1.0.0", COMMIT_A, [("docs/zh_cn/a.md", "documentation", "A.")]),
            (
                "1.1.0",
                COMMIT_B,
                [
                    ("docs/zh_cn/a.md", "documentation", "A."),
                    ("docs/zh_cn/b.md", "documentation", "B."),
                ],
            ),
        ],
        recorded=["1.1.0"],
    )

    assert review_queue(tmp_path).entries == ()


def test_review_queue_reports_revised_summaries(tmp_path: Path) -> None:
    _write_catalog(
        tmp_path,
        [
            ("1.0.0", COMMIT_A, [("docs/zh_cn/a.md", "documentation", "Before.")]),
            ("1.1.0", COMMIT_B, [("docs/zh_cn/a.md", "documentation", "After.")]),
        ],
        recorded=["1.0.0"],
    )

    queue = review_queue(tmp_path)

    assert [entry.revised for entry in queue.entries] == [("docs/zh_cn/a.md",)]


def test_review_queue_ignores_manifest_only_releases(tmp_path: Path) -> None:
    _write_catalog(
        tmp_path,
        [
            ("1.0.0", COMMIT_A, [("package.json", "package-manifest", "Manifest.")]),
            ("1.1.0", COMMIT_B, [("package.json", "package-manifest", "Manifest v2.")]),
        ],
        recorded=["1.0.0"],
    )

    assert review_queue(tmp_path).entries == ()


def test_render_review_queue_is_empty_without_gaps(tmp_path: Path) -> None:
    _write_catalog(
        tmp_path,
        [("1.0.0", COMMIT_A, [("docs/zh_cn/a.md", "documentation", "A.")])],
        recorded=["1.0.0"],
    )

    assert render_review_queue(tmp_path) == ""


def test_render_review_queue_names_release_and_artifact(tmp_path: Path) -> None:
    _write_catalog(
        tmp_path,
        [
            ("1.0.0", COMMIT_A, [("docs/zh_cn/a.md", "documentation", "A.")]),
            (
                "1.1.0",
                COMMIT_B,
                [
                    ("docs/zh_cn/a.md", "documentation", "A."),
                    ("docs/zh_cn/b.md", "documentation", "B."),
                ],
            ),
        ],
        recorded=["1.0.0"],
    )

    report = render_review_queue(tmp_path)

    assert "**1.1.0**" in report
    assert "`docs/zh_cn/b.md`" in report
    assert "`1.0.0`" in report


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _make_upstream(tmp_path: Path) -> Path:
    repository = tmp_path / "upstream"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "catalog@example.com")
    _git(repository, "config", "user.name", "Catalog Test")
    _git(repository, "config", "commit.gpgsign", "false")
    docs = repository / "docs" / "zh_cn"
    docs.mkdir(parents=True)
    (repository / "README.md").write_text("readme one\n", encoding="utf-8")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "-m", "release one")
    _git(repository, "tag", "v1.0.0")

    (docs / "a.md").write_text("# A\n\nFirst body.\n", encoding="utf-8")
    static = repository / "docs" / "static"
    static.mkdir(parents=True)
    (static / "arch.svg").write_text("<svg/>\n", encoding="utf-8")
    (repository / "README.md").write_text("readme two\n", encoding="utf-8")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "-m", "release two")
    _git(repository, "tag", "v1.1.0")
    return repository


def _write_blobless_catalog(root: Path, recorded: list[str] | None = None) -> None:
    # These inventories predate blob ids, so only the title/summary fallback is possible; a
    # content-only edit stays invisible until the optional --repository cross-check is used.
    _write_catalog(
        root,
        [
            ("1.0.0", COMMIT_A, [("docs/zh_cn/a.md", "documentation", "Same summary.")]),
            ("1.1.0", COMMIT_B, [("docs/zh_cn/a.md", "documentation", "Same summary.")]),
        ],
        recorded=["1.0.0"] if recorded is None else recorded,
    )


def test_review_queue_blobless_inventory_falls_back_to_metadata(tmp_path: Path) -> None:
    _write_blobless_catalog(tmp_path)

    assert review_queue(tmp_path).entries == ()
    assert render_review_queue(tmp_path) == ""


def test_review_queue_repository_cross_check_detects_content_only_edits(tmp_path: Path) -> None:
    upstream = _make_upstream(tmp_path)
    _write_blobless_catalog(tmp_path)

    queue = review_queue(tmp_path, repository=upstream)

    assert [entry.version for entry in queue.entries] == ["1.1.0"]
    entry = queue.entries[0]
    assert entry.added == ()
    assert entry.removed == ()
    assert entry.revised == ()
    assert entry.content_changed == ("docs/zh_cn/a.md",)
    assert entry.tracked_changes == 1


def test_render_review_queue_names_content_changed_files(tmp_path: Path) -> None:
    upstream = _make_upstream(tmp_path)
    _write_blobless_catalog(tmp_path)

    report = render_review_queue(tmp_path, repository=upstream)

    assert "**1.1.0**" in report
    assert "content changed" in report
    assert "`docs/zh_cn/a.md`" in report
    assert "git diff" in report


def test_review_queue_content_detection_ignores_unindexed_paths(tmp_path: Path) -> None:
    upstream = _make_upstream(tmp_path)
    _write_blobless_catalog(tmp_path)

    entry = review_queue(tmp_path, repository=upstream).entries[0]

    assert "README.md" not in entry.content_changed


def test_review_queue_content_detection_respects_recorded_threshold(tmp_path: Path) -> None:
    upstream = _make_upstream(tmp_path)
    _write_blobless_catalog(tmp_path, recorded=["1.1.0"])

    assert review_queue(tmp_path, repository=upstream).entries == ()


def test_review_queue_content_detection_requires_valid_clone(tmp_path: Path) -> None:
    _write_blobless_catalog(tmp_path)

    with pytest.raises(RuntimeError, match="git diff"):
        review_queue(tmp_path, repository=tmp_path / "missing-clone")


BLOB_1 = "1" * 40
BLOB_2 = "2" * 40


def test_review_queue_detects_blob_only_content_change(tmp_path: Path) -> None:
    # Identical title and summary, different content hash: the offline queue must still report it.
    _write_catalog(
        tmp_path,
        [
            ("1.0.0", COMMIT_A, [("docs/zh_cn/a.md", "documentation", "Same summary.", BLOB_1)]),
            ("1.1.0", COMMIT_B, [("docs/zh_cn/a.md", "documentation", "Same summary.", BLOB_2)]),
        ],
        recorded=["1.0.0"],
    )

    queue = review_queue(tmp_path)

    assert [entry.version for entry in queue.entries] == ["1.1.0"]
    assert queue.entries[0].revised == ("docs/zh_cn/a.md",)
    assert queue.entries[0].content_changed == ()
    assert queue.entries[0].tracked_changes == 1


def test_review_queue_does_not_report_unchanged_blob(tmp_path: Path) -> None:
    # The blob is authoritative when both sides carry one, even if copied metadata moved.
    _write_catalog(
        tmp_path,
        [
            ("1.0.0", COMMIT_A, [("docs/zh_cn/a.md", "documentation", "Before.", BLOB_1)]),
            ("1.1.0", COMMIT_B, [("docs/zh_cn/a.md", "documentation", "After.", BLOB_1)]),
        ],
        recorded=["1.0.0"],
    )

    assert review_queue(tmp_path).entries == ()


def test_review_queue_falls_back_when_blob_missing(tmp_path: Path) -> None:
    _write_catalog(
        tmp_path,
        [
            ("1.0.0", COMMIT_A, [("docs/zh_cn/a.md", "documentation", "Before.")]),
            ("1.1.0", COMMIT_B, [("docs/zh_cn/a.md", "documentation", "After.", BLOB_2)]),
        ],
        recorded=["1.0.0"],
    )

    assert [entry.revised for entry in review_queue(tmp_path).entries] == [("docs/zh_cn/a.md",)]


def test_render_review_queue_states_blob_comparison(tmp_path: Path) -> None:
    _write_catalog(
        tmp_path,
        [
            ("1.0.0", COMMIT_A, [("docs/zh_cn/a.md", "documentation", "Same summary.", BLOB_1)]),
            ("1.1.0", COMMIT_B, [("docs/zh_cn/a.md", "documentation", "Same summary.", BLOB_2)]),
        ],
        recorded=["1.0.0"],
    )

    report = render_review_queue(tmp_path)

    assert "git blob ids" in report
    assert "`docs/zh_cn/a.md`" in report
    assert "git diff" not in report


def test_review_queue_cross_check_does_not_duplicate_added_paths(tmp_path: Path) -> None:
    upstream = _make_upstream(tmp_path)
    _write_catalog(
        tmp_path,
        [
            ("1.0.0", COMMIT_A, [("docs/zh_cn/b.md", "documentation", "B.")]),
            (
                "1.1.0",
                COMMIT_B,
                [
                    ("docs/zh_cn/a.md", "documentation", "A."),
                    ("docs/zh_cn/b.md", "documentation", "B."),
                ],
            ),
        ],
        recorded=["1.0.0"],
    )

    entry = review_queue(tmp_path, repository=upstream).entries[0]

    assert entry.added == ("docs/zh_cn/a.md",)
    assert "docs/zh_cn/a.md" not in entry.content_changed


def test_review_queue_cross_check_ignores_non_reviewable_assets(tmp_path: Path) -> None:
    upstream = _make_upstream(tmp_path)
    _write_catalog(
        tmp_path,
        [
            ("1.0.0", COMMIT_A, [("docs/zh_cn/b.md", "documentation", "B.")]),
            (
                "1.1.0",
                COMMIT_B,
                [
                    ("docs/zh_cn/b.md", "documentation", "B."),
                    ("docs/static/arch.svg", "documentation-asset", "Architecture."),
                ],
            ),
        ],
        recorded=["1.0.0"],
    )

    queue = review_queue(tmp_path, repository=upstream)

    assert queue.entries == ()
