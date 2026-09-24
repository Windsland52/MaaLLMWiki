from __future__ import annotations

from pathlib import Path

from maa_llm_wiki.gaps import render_review_queue, review_queue

COMMIT_A = "a" * 40
COMMIT_B = "b" * 40
COMMIT_C = "c" * 40

Artifacts = list[tuple[str, str, str]]
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
        for path, kind, summary in sorted(artifacts):
            inventory_lines.extend(
                [
                    f"- path: {path}",
                    f"  kind: {kind}",
                    "  title: Title",
                    f"  summary: {summary}",
                ]
            )
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
