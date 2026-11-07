# pyright: reportPrivateUsage=false
from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pytest
import yaml

from maa_llm_wiki import inventory
from maa_llm_wiki.bindings import (
    BINDING_SPECS,
    BindingSourceSpec,
    PackageDocumentation,
    _binding_compatibility,
    _classify_binding_path,
    _describe_binding_artifact,
    _package_documentation,
    render_binding_version,
    sync_binding_history,
)
from maa_llm_wiki.inventory import (
    discover_maafw_artifacts,
    discover_prereleases,
    discover_stable_releases,
    git_text,
    markdown_metadata,
    render_release_index,
    render_version_indexes,
    resolve_included_in,
    sync_maafw_history,
)
from maa_llm_wiki.models import (
    ArtifactKind,
    BindingCompatibility,
    CompatibilityStatus,
    MachineChangeCatalog,
    PrereleaseRecord,
    ReleaseCatalog,
    ReleaseRecord,
    RepositoryCatalog,
    RepositoryRole,
    RepositorySource,
    SourceArtifact,
    SourceInventory,
    SourceMap,
    UpstreamCommitCatalog,
)

GO_SPEC = BindingSourceSpec(
    source_id="maa-framework-go",
    display_name="MaaFramework Go binding",
    language="Go",
)
RUST_SPEC = BindingSourceSpec(
    source_id="maa-framework-rs",
    display_name="MaaFramework Rust binding",
    language="Rust",
)
CSHARP_SPEC = BindingSourceSpec(
    source_id="maa-framework-csharp",
    display_name="MaaFramework C# binding",
    language="C#",
    tag_major=5,
)
FIXED_DATE = date(2026, 1, 2)
ABSENT_COMMIT = "b" * 40


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _init_repository(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "catalog@example.com")
    _git(path, "config", "user.name", "Catalog Test")
    _git(path, "config", "commit.gpgsign", "false")
    return path


def _commit(repository: Path) -> str:
    _git(repository, "commit", "--allow-empty", "-q", "-m", "work")
    return _git(repository, "rev-parse", "HEAD")


def _commit_files(repository: Path, files: dict[str, str]) -> str:
    for relative, content in files.items():
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        _git(repository, "add", relative)
    _git(repository, "commit", "-q", "-m", "content")
    return _git(repository, "rev-parse", "HEAD")


def _write_yaml(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _repository_source(source_id: str, revision: str) -> RepositorySource:
    return RepositorySource(
        id=source_id,
        name=source_id,
        url=f"https://github.com/MaaXYZ/{source_id}",
        role=RepositoryRole.AUTHORITATIVE,
        enabled=True,
        default_revision=revision,
    )


def _write_maafw_root(
    tmp_path: Path,
    releases: list[ReleaseRecord],
    prereleases: list[PrereleaseRecord] | None = None,
    revision: str | None = None,
) -> Path:
    root = tmp_path / "root"
    revision = revision or releases[0].commit
    catalog = ReleaseCatalog(
        source_id="maafw",
        releases=releases,
        prereleases=prereleases or [],
    )
    _write_yaml(
        root / "sources" / "maa-framework" / "releases.yaml", catalog.model_dump(mode="json")
    )
    _write_yaml(
        root / "sources" / "maa-framework" / "source-map.yaml",
        {
            "topics": [
                {
                    "id": "framework.pipeline-control-flow",
                    "source_id": "maafw",
                    "variants": [
                        {
                            "applies_to": releases[0].version,
                            "revision": revision,
                            "paths": ["docs/test.md"],
                            "symbols": [],
                            "terms": ["timeout"],
                        }
                    ],
                }
            ]
        },
    )
    _write_yaml(
        root / "sources" / "repositories.yaml",
        RepositoryCatalog(repositories=[_repository_source("maafw", revision)]).model_dump(
            mode="json"
        ),
    )
    return root


def _write_binding_root(
    tmp_path: Path,
    source_id: str,
    releases: list[ReleaseRecord],
    revision: str | None = None,
) -> Path:
    root = tmp_path / "root"
    catalog = ReleaseCatalog(source_id=source_id, releases=releases)
    _write_yaml(root / "sources" / source_id / "releases.yaml", catalog.model_dump(mode="json"))
    _write_yaml(
        root / "sources" / "repositories.yaml",
        RepositoryCatalog(
            repositories=[_repository_source(source_id, revision or releases[0].commit)]
        ).model_dump(mode="json"),
    )
    return root


@pytest.fixture()
def upstream(tmp_path: Path) -> Path:
    repository = _init_repository(tmp_path / "upstream")
    first = _commit(repository)
    _git(repository, "tag", "v1.0.0")
    _commit(repository)
    _git(repository, "tag", "v1.1.0-beta.1")
    _commit(repository)
    _git(repository, "tag", "v1.1.0-beta.2")
    _commit(repository)
    _git(repository, "tag", "-a", "v1.1.0", "-m", "release 1.1.0")
    _commit(repository)
    _git(repository, "tag", "v1.2.0-alpha.1")
    assert _git(repository, "rev-parse", "v1.0.0^{commit}") == first
    return repository


def test_discover_functions_spawn_one_git_process(
    upstream: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, ...]] = []

    def counting_git_text(repository: Path, *arguments: str) -> str:
        calls.append(arguments)
        return git_text(repository, *arguments)

    monkeypatch.setattr(inventory, "git_text", counting_git_text)

    discover_stable_releases(upstream)
    assert len(calls) == 1
    assert calls[0][0] == "for-each-ref"
    assert calls[0][-1] == "refs/tags/v*"

    calls.clear()
    discover_prereleases(upstream)
    assert len(calls) == 1
    assert calls[0][0] == "for-each-ref"


def test_resolve_included_in_spawns_one_git_process_per_prerelease(
    upstream: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    releases = discover_stable_releases(upstream)
    prereleases = discover_prereleases(upstream)
    calls: list[tuple[str, ...]] = []

    def counting_git_text(repository: Path, *arguments: str) -> str:
        calls.append(arguments)
        return git_text(repository, *arguments)

    monkeypatch.setattr(inventory, "git_text", counting_git_text)
    resolve_included_in(upstream, prereleases, releases)

    assert len(calls) == len(prereleases)
    for arguments in calls:
        assert arguments[:2] == ("tag", "--contains")
        assert arguments[-2:] == ("--list", "v*")


def test_resolve_included_in_matches_merge_base_oracle(upstream: Path) -> None:
    releases = discover_stable_releases(upstream)
    prereleases = discover_prereleases(upstream)
    resolved = resolve_included_in(upstream, prereleases, releases)

    def is_ancestor(ancestor: str, descendant: str) -> bool:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=upstream,
            check=False,
            capture_output=True,
        )
        return result.returncode == 0

    expected = [
        next(
            (
                release.version
                for release in releases
                if is_ancestor(prerelease.commit, release.commit)
            ),
            None,
        )
        for prerelease in prereleases
    ]
    assert [item.included_in for item in resolved] == expected


def test_discovery_matches_per_tag_rev_parse_and_show(upstream: Path) -> None:
    tags = _git(upstream, "tag", "--list", "v*").splitlines()
    expected_commits = {tag: _git(upstream, "rev-parse", f"{tag}^{{commit}}") for tag in tags}
    expected_dates = {
        tag: date.fromisoformat(_git(upstream, "show", "-s", "--format=%cs", commit))
        for tag, commit in expected_commits.items()
    }

    records = [*discover_stable_releases(upstream), *discover_prereleases(upstream)]
    assert {record.tag for record in records} == set(tags)
    for record in records:
        assert record.commit == expected_commits[record.tag]
        assert record.released_at == expected_dates[record.tag]

    releases = discover_stable_releases(upstream)
    assert [release.version for release in releases] == ["1.0.0", "1.1.0"]
    assert releases[-1].tag == "v1.1.0"
    assert releases[-1].commit == _git(upstream, "rev-parse", "v1.1.0^{commit}")


def test_sync_maafw_history_rejects_dropping_registered_versions(tmp_path: Path) -> None:
    repository = _init_repository(tmp_path / "upstream")
    first = _commit_files(repository, {"docs/test.md": "# Test\n\nSome documentation.\n"})
    _git(repository, "tag", "v1.0.0")
    registered = [
        ReleaseRecord(version="1.0.0", tag="v1.0.0", commit=first, released_at=FIXED_DATE),
        ReleaseRecord(version="1.1.0", tag="v1.1.0", commit=ABSENT_COMMIT, released_at=FIXED_DATE),
    ]
    root = _write_maafw_root(tmp_path, registered, revision=first)

    with pytest.raises(ValueError, match=r"1\.1\.0") as error:
        sync_maafw_history(root=root, repository=repository, major=1)

    assert "Refusing to remove registered MaaFramework versions" in str(error.value)
    assert "--prune" in str(error.value)
    # The guard runs before the catalog is rewritten.
    catalog = ReleaseCatalog.model_validate(
        yaml.safe_load((root / "sources" / "maa-framework" / "releases.yaml").read_text("utf-8"))
    )
    assert [release.version for release in catalog.releases] == ["1.0.0", "1.1.0"]


def test_sync_maafw_history_prune_allows_dropping_registered_versions(tmp_path: Path) -> None:
    repository = _init_repository(tmp_path / "upstream")
    first = _commit_files(repository, {"docs/test.md": "# Test\n\nSome documentation.\n"})
    _git(repository, "tag", "v1.0.0")
    registered = [
        ReleaseRecord(version="1.0.0", tag="v1.0.0", commit=first, released_at=FIXED_DATE),
        ReleaseRecord(version="1.1.0", tag="v1.1.0", commit=ABSENT_COMMIT, released_at=FIXED_DATE),
    ]
    root = _write_maafw_root(tmp_path, registered, revision=first)

    releases, prereleases = sync_maafw_history(
        root=root, repository=repository, major=1, prune=True
    )

    assert [release.version for release in releases] == ["1.0.0"]
    assert prereleases == []
    catalog = ReleaseCatalog.model_validate(
        yaml.safe_load((root / "sources" / "maa-framework" / "releases.yaml").read_text("utf-8"))
    )
    assert [release.version for release in catalog.releases] == ["1.0.0"]
    assert (root / "sources" / "maa-framework" / "inventories" / "1.0.0.yaml").is_file()
    generated = root / "generated" / "maa-framework"
    assert (generated / "1.0.0" / "index.md").is_file()
    index = (generated / "index.md").read_text(encoding="utf-8")
    assert "- [1.0.0](./1.0.0/index.md)" in index
    assert "[Browse curated topic routes](./topics.md)" in index
    assert "[Browse upstream commits by release](./upstream-commits.md)" in index
    assert "# MaaFramework prerelease registry" in (generated / "prereleases.md").read_text("utf-8")
    assert "# Topic routes" in (generated / "topics.md").read_text(encoding="utf-8")
    assert "# Upstream commits" in (generated / "upstream-commits.md").read_text("utf-8")
    assert not (generated / "behaviour-changes.md").exists()


def test_sync_maafw_history_rejects_newer_upstream_major(tmp_path: Path) -> None:
    repository = _init_repository(tmp_path / "upstream")
    first = _commit(repository)
    _git(repository, "tag", "v1.0.0")
    _commit(repository)
    _git(repository, "tag", "v2.0.0")
    root = _write_maafw_root(
        tmp_path,
        [ReleaseRecord(version="1.0.0", tag="v1.0.0", commit=first, released_at=FIXED_DATE)],
        revision=first,
    )

    with pytest.raises(ValueError, match="Upstream has MaaFramework 2.0.0") as error:
        sync_maafw_history(root=root, repository=repository, major=1)

    assert "--major 1" in str(error.value)
    assert "CATALOG_MAJOR" in str(error.value)


def test_sync_maafw_history_rejects_dropping_registered_prereleases(tmp_path: Path) -> None:
    repository = _init_repository(tmp_path / "upstream")
    first = _commit(repository)
    _git(repository, "tag", "v1.0.0")
    root = _write_maafw_root(
        tmp_path,
        [ReleaseRecord(version="1.0.0", tag="v1.0.0", commit=first, released_at=FIXED_DATE)],
        prereleases=[
            PrereleaseRecord(
                version="1.1.0-beta.1",
                tag="v1.1.0-beta.1",
                commit=ABSENT_COMMIT,
                released_at=FIXED_DATE,
            )
        ],
        revision=first,
    )

    with pytest.raises(ValueError, match=r"1\.1\.0-beta\.1") as error:
        sync_maafw_history(root=root, repository=repository, major=1)

    assert "MaaFramework prerelease" in str(error.value)


def test_sync_binding_history_rejects_dropping_registered_versions(tmp_path: Path) -> None:
    repository = _init_repository(tmp_path / "binding")
    first = _commit_files(repository, {"README.md": "# Go binding\n\nText.\n"})
    _git(repository, "tag", "v0.1.0")
    registered = [
        ReleaseRecord(version="0.1.0", tag="v0.1.0", commit=first, released_at=FIXED_DATE),
        ReleaseRecord(version="0.2.0", tag="v0.2.0", commit=ABSENT_COMMIT, released_at=FIXED_DATE),
    ]
    root = _write_binding_root(tmp_path, "maa-framework-go", registered, revision=first)

    with pytest.raises(ValueError, match=r"0\.2\.0") as error:
        sync_binding_history(root=root, repository=repository, source_id="maa-framework-go")

    assert "Refusing to remove registered maa-framework-go versions" in str(error.value)


def test_sync_binding_history_prune_allows_dropping_registered_versions(tmp_path: Path) -> None:
    repository = _init_repository(tmp_path / "binding")
    first = _commit_files(repository, {"README.md": "# Go binding\n\nText.\n"})
    _git(repository, "tag", "v0.1.0")
    registered = [
        ReleaseRecord(version="0.1.0", tag="v0.1.0", commit=first, released_at=FIXED_DATE),
        ReleaseRecord(version="0.2.0", tag="v0.2.0", commit=ABSENT_COMMIT, released_at=FIXED_DATE),
    ]
    root = _write_binding_root(tmp_path, "maa-framework-go", registered, revision=first)

    releases, prereleases = sync_binding_history(
        root=root,
        repository=repository,
        source_id="maa-framework-go",
        prune=True,
    )

    assert [release.version for release in releases] == ["0.1.0"]
    assert prereleases == []
    catalog = ReleaseCatalog.model_validate(
        yaml.safe_load((root / "sources" / "maa-framework-go" / "releases.yaml").read_text("utf-8"))
    )
    assert [release.version for release in catalog.releases] == ["0.1.0"]
    assert (root / "generated" / "maa-framework-go" / "0.1.0" / "index.md").is_file()


def _binding_repository(tmp_path: Path, files: dict[str, str]) -> tuple[Path, str]:
    repository = _init_repository(tmp_path / "binding")
    return repository, _commit_files(repository, files)


def _release(commit: str) -> ReleaseRecord:
    return ReleaseRecord(version="1.0.0", tag="v1.0.0", commit=commit, released_at=FIXED_DATE)


def test_go_compatibility_prefers_release_link_and_keeps_prerelease(tmp_path: Path) -> None:
    repository, commit = _binding_repository(
        tmp_path,
        {
            "README.md": (
                '<a href="https://github.com/MaaXYZ/MaaFramework/releases/tag/v2.0.0-alpha.2">\n'
                '<img alt="maa framework" '
                'src="https://img.shields.io/badge/MaaFramework-v2.0.0--alpha.2-blue">\n'
            )
        },
    )

    compatibility = _binding_compatibility(repository, _release(commit), GO_SPEC)

    assert compatibility.status is CompatibilityStatus.DECLARED
    assert compatibility.framework_version == "2.0.0-alpha.2"
    assert compatibility.evidence_paths == ["README.md"]
    assert "release link" in compatibility.note
    assert "v2.0.0-alpha.2" in compatibility.note
    assert "explicitly references" not in compatibility.note


def test_go_compatibility_prefers_link_over_conflicting_badge(tmp_path: Path) -> None:
    repository, commit = _binding_repository(
        tmp_path,
        {
            "README.md": (
                '<a href="https://github.com/MaaXYZ/MaaFramework/releases/tag/v5.14.3">\n'
                '<img alt="maa framework" '
                'src="https://img.shields.io/badge/MaaFramework-v5.15.0--beta.1-green">\n'
            )
        },
    )

    compatibility = _binding_compatibility(repository, _release(commit), GO_SPEC)

    assert compatibility.framework_version == "5.14.3"
    assert "release link" in compatibility.note


def test_go_compatibility_falls_back_to_badge_and_normalises_escaped_dash(
    tmp_path: Path,
) -> None:
    repository, commit = _binding_repository(
        tmp_path,
        {"README.md": ('src="https://img.shields.io/badge/MaaFramework-v2.0.0--beta.1-blue"\n')},
    )

    compatibility = _binding_compatibility(repository, _release(commit), GO_SPEC)

    assert compatibility.status is CompatibilityStatus.DECLARED
    assert compatibility.framework_version == "2.0.0-beta.1"
    assert "version badge" in compatibility.note


def test_go_compatibility_stays_unknown_without_evidence(tmp_path: Path) -> None:
    repository, commit = _binding_repository(
        tmp_path, {"README.md": "# Go binding\n\nNo framework version here.\n"}
    )

    compatibility = _binding_compatibility(repository, _release(commit), GO_SPEC)

    assert compatibility.status is CompatibilityStatus.UNKNOWN
    assert compatibility.framework_version is None
    assert compatibility.evidence_paths == []


def test_rust_compatibility_accepts_prerelease_dependency(tmp_path: Path) -> None:
    repository, commit = _binding_repository(
        tmp_path,
        {
            "Cargo.toml": (
                "[package]\n"
                'name = "maa-framework"\n'
                "\n"
                "[dependencies]\n"
                'maa-framework-sys = { path = "maa-framework-sys", version = "5.15.0-beta.1" }\n'
            )
        },
    )

    compatibility = _binding_compatibility(repository, _release(commit), RUST_SPEC)

    assert compatibility.status is CompatibilityStatus.DECLARED
    assert compatibility.framework_version == "5.15.0-beta.1"
    assert compatibility.evidence_paths == ["Cargo.toml"]
    assert "maa-framework-sys" in compatibility.note


def test_discover_artifacts_records_blob_ids(tmp_path: Path) -> None:
    repository = _init_repository(tmp_path / "upstream")
    commit = _commit_files(
        repository,
        {
            "docs/guide.md": "# Guide\n\nProse.\n",
            "tools/pipeline.schema.json": "{}\n",
            "include/MaaFramework/MaaDef.h": "#pragma once\n",
            "source/binding/Python/maa/tasker.py": "x = 1\n",
            "notes/unclassified.txt": "ignored\n",
        },
    )

    artifacts = discover_maafw_artifacts(repository, commit)

    assert {artifact.path for artifact in artifacts} == {
        "docs/guide.md",
        "tools/pipeline.schema.json",
        "include/MaaFramework/MaaDef.h",
        "source/binding/Python/maa/tasker.py",
    }
    for artifact in artifacts:
        assert artifact.blob == _git(repository, "rev-parse", f"{commit}:{artifact.path}")


def test_ls_tree_blobs_keeps_symlink_entries(tmp_path: Path) -> None:
    repository = _init_repository(tmp_path / "upstream")
    _commit_files(repository, {"docs/guide.md": "# Guide\n\nProse.\n"})
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        input="guide.md\n",
    ).stdout.strip()
    _git(repository, "update-index", "--add", "--cacheinfo", f"120000,{blob},docs/link.md")
    _git(repository, "commit", "-q", "-m", "symlink")
    commit = _git(repository, "rev-parse", "HEAD")

    artifacts = discover_maafw_artifacts(repository, commit)

    link = next(artifact for artifact in artifacts if artifact.path == "docs/link.md")
    assert link.blob == blob


def test_markdown_metadata_accepts_html_h1_and_skips_language_switcher() -> None:
    content = (
        "<!-- markdownlint-disable MD033 MD041 -->\n"
        '<p align="center">\n'
        '  <img alt="LOGO" src="https://example.invalid/logo.png" />\n'
        "</p>\n"
        "\n"
        '<h1 align="center">MaaFramework Go Binding</h1>\n'
        "\n"
        '<p align="center">\n'
        '  English | <a href="README_zh.md">简体中文</a>\n'
        "</p>\n"
        "\n"
        "Go binding for [MaaFramework](https://github.com/MaaXYZ/MaaFramework), a cross-platform"
        " automation testing framework.\n"
        "\n"
        "## Features\n"
        "\n"
        "- **Cross-platform Controllers** - ADB and Win32.\n"
    )

    title, summary = markdown_metadata(content, "README")

    assert title == "MaaFramework Go Binding"
    assert summary.startswith("Go binding for MaaFramework, a cross-platform automation")
    assert "English" not in summary
    assert "<a" not in summary


def test_markdown_metadata_skips_malformed_multiline_html() -> None:
    content = (
        "# MaaFramework Golang Binding\n"
        "\n"
        "<p>\n"
        '    <a href="https://example.invalid/releases/tag/v2.0.0-alpha.2">\n'
        '        <img alt="maa framework" src="https://example.invalid/badge/MaaFramework-v2.0.0--alpha.2-blue"\n'
        "    </a>\n"
        "</p>\n"
        "\n"
        "English | [简体中文](README_zh.md)\n"
        "\n"
        "This is the Go binding for MaaFramework.\n"
    )

    title, summary = markdown_metadata(content, "README")

    assert title == "MaaFramework Golang Binding"
    assert summary == "This is the Go binding for MaaFramework."


def test_markdown_metadata_uses_list_items_when_no_paragraph_exists() -> None:
    content = (
        "# 2.1 Integration\n"
        "\n"
        "## C++\n"
        "\n"
        "- Interface Status:\n"
        "  - Native interface available\n"
        "  - Full functionality available\n"
        "- [Source](https://example.invalid/source)\n"
    )

    title, summary = markdown_metadata(content, "2.1-Integration")

    assert title == "2.1 Integration"
    assert "Interface Status:" in summary
    assert "Native interface available" in summary
    assert "Official documentation for" not in summary


def test_markdown_metadata_uses_blockquote_when_no_paragraph_exists() -> None:
    content = (
        "# 3.2 Project Interface\n"
        "\n"
        "> [!NOTE]\n"
        "> The current document has been deprecated.\n"
        "> Use the V2 protocol instead.\n"
    )

    title, summary = markdown_metadata(content, "3.2-ProjectInterface")

    assert title == "3.2 Project Interface"
    assert summary == "The current document has been deprecated. Use the V2 protocol instead."
    assert "[!NOTE]" not in summary


def test_markdown_metadata_keeps_generic_fallback_for_link_only_docs() -> None:
    content = (
        "# MaaFW NodeJS\n"
        "\n"
        "[文档](../../../docs/zh_cn/NodeJS/J1.1-快速开始.md)\n"
        "\n"
        "[Document](../../../docs/en_us/NodeJS/J1.1-QuickStarted.md)\n"
    )

    title, summary = markdown_metadata(content, "README")

    assert title == "MaaFW NodeJS"
    assert summary == "Official documentation for MaaFW NodeJS."


def test_render_release_index_links_topics_and_change_pages() -> None:
    releases = [
        ReleaseRecord(version="1.0.0", tag="v1.0.0", commit="a" * 40, released_at=FIXED_DATE)
    ]
    page = render_release_index(releases, [])

    assert "[Browse curated topic routes](./topics.md)" in page
    assert "[Browse declared API changes by release](./machine-changes.md)" in page
    assert "[Browse declared API changes by symbol](./machine-symbols.md)" in page
    assert "[Browse upstream commits by release](./upstream-commits.md)" in page
    assert "behaviour" not in page.lower()


_TOP_LEVEL_PAGES = (
    "index.md",
    "prereleases.md",
    "topics.md",
    "machine-changes.md",
    "machine-symbols.md",
    "upstream-commits.md",
)


def _generated_maafw_pages(root: Path) -> dict[str, str]:
    generated = root / "generated" / "maa-framework"
    return {name: (generated / name).read_text(encoding="utf-8") for name in _TOP_LEVEL_PAGES}


def test_sync_maafw_history_renders_top_level_pages_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _init_repository(tmp_path / "upstream")
    first = _commit_files(repository, {"docs/test.md": "# Test\n\nFirst.\n"})
    _git(repository, "tag", "v1.0.0")
    second = _commit_files(repository, {"docs/test.md": "# Test\n\nSecond.\n"})
    _git(repository, "tag", "v1.1.0")
    registered = [
        ReleaseRecord(version="1.0.0", tag="v1.0.0", commit=first, released_at=FIXED_DATE),
        ReleaseRecord(version="1.1.0", tag="v1.1.0", commit=second, released_at=FIXED_DATE),
    ]
    root = _write_maafw_root(tmp_path, registered, revision=second)

    calls = {"version": 0, "release": 0}
    real_version_indexes = inventory._write_version_indexes
    real_release_pages = inventory._write_release_pages

    def counting_version_indexes(
        root_path: Path,
        source_inventory: SourceInventory,
        repository_url: str,
        previous: SourceInventory | None = None,
        *,
        previous_version: str | None = None,
        next_version: str | None = None,
    ) -> None:
        calls["version"] += 1
        real_version_indexes(
            root_path,
            source_inventory,
            repository_url,
            previous,
            previous_version=previous_version,
            next_version=next_version,
        )

    def counting_release_pages(
        root_path: Path,
        releases: list[ReleaseRecord],
        prereleases: list[PrereleaseRecord],
        repository_url: str,
        source_map: SourceMap,
        machine_changes: MachineChangeCatalog,
        upstream_commits: UpstreamCommitCatalog,
    ) -> None:
        calls["release"] += 1
        real_release_pages(
            root_path,
            releases,
            prereleases,
            repository_url,
            source_map,
            machine_changes,
            upstream_commits,
        )

    monkeypatch.setattr(inventory, "_write_version_indexes", counting_version_indexes)
    monkeypatch.setattr(inventory, "_write_release_pages", counting_release_pages)

    releases, _prereleases = sync_maafw_history(root=root, repository=repository, major=1)

    assert [release.version for release in releases] == ["1.0.0", "1.1.0"]
    assert calls == {"version": 2, "release": 1}
    pages = _generated_maafw_pages(root)
    assert "- [1.0.0](./1.0.0/index.md)" in pages["index.md"]
    assert "- [1.1.0](./1.1.0/index.md)" in pages["index.md"]
    assert "# Topic routes" in pages["topics.md"]
    assert "# Machine changes" in pages["machine-changes.md"]
    assert "# Machine change symbols" in pages["machine-symbols.md"]
    assert "# Upstream commits" in pages["upstream-commits.md"]
    assert "content" in pages["upstream-commits.md"]
    generated = root / "generated" / "maa-framework"
    first_index = (generated / "1.0.0" / "index.md").read_text(encoding="utf-8")
    second_index = (generated / "1.1.0" / "index.md").read_text(encoding="utf-8")
    assert "## Changed since the previous release" in first_index
    assert "## Changed since `1.0.0`" in second_index
    assert "- Added: `0`, removed: `0`, content changed: `1`" in second_index


def _inventory(version: str, artifacts: list[SourceArtifact]) -> SourceInventory:
    return SourceInventory(
        source_id="maafw",
        version=version,
        revision="a" * 40,
        artifacts=artifacts,
    )


def _artifact(
    path: str,
    *,
    kind: ArtifactKind = ArtifactKind.DOCUMENTATION,
    blob: str | None = "f" * 40,
    title: str = "Title",
    summary: str = "Summary",
) -> SourceArtifact:
    return SourceArtifact(path=path, kind=kind, blob=blob, title=title, summary=summary)


def test_render_version_indexes_reports_added_changed_and_removed() -> None:
    previous = _inventory(
        "1.0.0",
        [
            _artifact("docs/a.md", blob="1" * 40),
            _artifact("docs/b.md", blob="2" * 40),
            _artifact("docs/gone.md", blob="3" * 40),
            _artifact("include/Old.h", kind=ArtifactKind.PUBLIC_API, blob="4" * 40),
        ],
    )
    current = _inventory(
        "1.1.0",
        [
            _artifact("docs/a.md", blob="9" * 40),
            _artifact("docs/b.md", blob="2" * 40),
            _artifact("docs/new.md", blob="5" * 40),
            _artifact("include/New.h", kind=ArtifactKind.PUBLIC_API, blob="6" * 40),
        ],
    )

    page = render_version_indexes(current, "https://example.invalid", previous=previous)["index.md"]

    assert "## Changed since `1.0.0`" in page
    assert "- Added: `2`, removed: `2`, content changed: `1`" in page
    assert "- added: `docs/new.md` (documentation)" in page
    assert "- added: `include/New.h` (public-api)" in page
    assert "- changed: `docs/a.md` (documentation)" in page
    assert "- removed: `docs/gone.md` (documentation)" in page
    assert "- removed: `include/Old.h` (public-api)" in page
    section = page.split("## Changed since `1.0.0`", 1)[1]
    assert "docs/b.md" not in section
    assert (
        section.index("- added: `docs/new.md`")
        < section.index("- added: `include/New.h`")
        < section.index("- changed: `docs/a.md`")
        < section.index("- removed: `docs/gone.md`")
    )


def test_render_version_indexes_falls_back_to_metadata_without_blobs() -> None:
    previous = _inventory(
        "1.0.0",
        [
            _artifact("docs/blobless.md", blob=None, title="Old", summary="Same"),
            _artifact("docs/mixed.md", blob=None, title="Same", summary="Same"),
            _artifact("docs/plain.md", blob=None, title="Same", summary="Same"),
        ],
    )
    current = _inventory(
        "1.1.0",
        [
            _artifact("docs/blobless.md", blob=None, title="New", summary="Same"),
            _artifact("docs/mixed.md", blob="7" * 40, title="Same", summary="Same"),
            _artifact("docs/plain.md", blob=None, title="Same", summary="Same"),
        ],
    )

    page = render_version_indexes(current, "https://example.invalid", previous=previous)["index.md"]

    assert "- Added: `0`, removed: `0`, content changed: `1`" in page
    assert "- changed: `docs/blobless.md` (documentation)" in page
    section = page.split("## Changed since `1.0.0`", 1)[1]
    assert "docs/mixed.md" not in section
    assert "docs/plain.md" not in section


def test_render_version_indexes_sorts_and_caps_change_lists() -> None:
    previous = _inventory("1.0.0", [_artifact("docs/keep.md", blob="0" * 40)])
    added = [_artifact(f"docs/new-{index:02d}.md", blob=f"{index:040d}") for index in range(25)]
    current = _inventory("1.1.0", [_artifact("docs/keep.md", blob="0" * 40), *added])

    page = render_version_indexes(current, "https://example.invalid", previous=previous)["index.md"]

    assert "- Added: `25`, removed: `0`, content changed: `0`" in page
    section = page.split("## Changed since `1.0.0`", 1)[1]
    entry_lines = [line for line in section.splitlines() if line.startswith("- added: ")]
    assert entry_lines == sorted(entry_lines)
    assert len(entry_lines) == 20
    assert entry_lines[0] == "- added: `docs/new-00.md` (documentation)"
    assert entry_lines[-1] == "- added: `docs/new-19.md` (documentation)"
    assert "- ... and 5 more added" in section


def test_render_version_indexes_reports_no_change() -> None:
    previous = _inventory("1.0.0", [_artifact("docs/a.md", blob="1" * 40), _artifact("docs/b.md")])
    current = _inventory("1.1.0", [_artifact("docs/a.md", blob="1" * 40), _artifact("docs/b.md")])

    page = render_version_indexes(current, "https://example.invalid", previous=previous)["index.md"]

    assert "## Changed since `1.0.0`" in page
    assert "- No indexed material changed since `1.0.0`." in page
    assert "- Added:" not in page


def test_render_version_indexes_marks_the_first_registered_release() -> None:
    current = _inventory("1.0.0", [_artifact("docs/a.md")])

    page = render_version_indexes(current, "https://example.invalid")["index.md"]

    assert "## Changed since the previous release" in page
    assert "- First indexed release; no previous inventory to compare." in page
    assert render_version_indexes(current, "https://example.invalid") == render_version_indexes(
        current, "https://example.invalid", previous=None
    )


def test_render_version_indexes_only_changes_the_index_page() -> None:
    previous = _inventory("1.0.0", [_artifact("docs/a.md", blob="1" * 40)])
    current = _inventory(
        "1.1.0",
        [_artifact("docs/a.md", blob="1" * 40), _artifact("tools/pipeline.schema.json")],
    )

    without_previous = render_version_indexes(current, "https://example.invalid")
    with_previous = render_version_indexes(current, "https://example.invalid", previous=previous)

    assert set(without_previous) == set(with_previous)
    for name in without_previous:
        if name != "index.md":
            assert without_previous[name] == with_previous[name]
    assert without_previous["index.md"] != with_previous["index.md"]


CSHARP_PACKAGES_PROPS = (
    "<Project>\n"
    "  <ItemGroup>\n"
    '    <PackageVersion Include="Maa.Framework.Runtimes" Version="5.10.5" />\n'
    "  </ItemGroup>\n"
    "</Project>\n"
)


def test_csharp_binding_classification_and_specs() -> None:
    assert BINDING_SPECS["maa-framework-csharp"].tag_major == 5
    assert BINDING_SPECS["maa-framework-go"].tag_major is None
    assert BINDING_SPECS["maa-framework-rs"].tag_major is None

    classify = _classify_binding_path
    assert classify("maa-framework-csharp", "README.md") is ArtifactKind.DOCUMENTATION
    assert classify("maa-framework-csharp", "README.zh_cn.md") is ArtifactKind.DOCUMENTATION
    assert classify("maa-framework-csharp", "CHANGELOG.md") is ArtifactKind.DOCUMENTATION
    assert (
        classify("maa-framework-csharp", "docs/articles/overview-of-wrapper-and-api.md")
        is ArtifactKind.DOCUMENTATION
    )
    assert (
        classify("maa-framework-csharp", "src/MaaFramework.Binding/MaaTasker.cs")
        is ArtifactKind.BINDING_API
    )
    assert (
        classify("maa-framework-csharp", "src/MaaFramework.Binding.UnitTests/Test_Common.cs")
        is None
    )
    assert (
        classify("maa-framework-csharp", "src/MaaFramework/MaaFramework.csproj")
        is ArtifactKind.PACKAGE_MANIFEST
    )
    assert (
        classify("maa-framework-csharp", "src/Directory.Packages.props")
        is ArtifactKind.PACKAGE_MANIFEST
    )
    assert (
        classify("maa-framework-csharp", "src/Directory.Build.props")
        is ArtifactKind.PACKAGE_MANIFEST
    )
    assert classify("maa-framework-csharp", "sample/csharp/1.main.cs") is None
    assert classify("maa-framework-csharp", "sample/README.md") is None
    assert classify("maa-framework-csharp", ".github/workflows/ci.yml") is None
    assert classify("maa-framework-csharp", "docs/build.ps1") is None

    # Go and Rust classification must be unaffected by the new source.
    assert classify("maa-framework-go", "controller/adb.go") is ArtifactKind.BINDING_API
    assert classify("maa-framework-go", "go.mod") is ArtifactKind.PACKAGE_MANIFEST
    assert classify("maa-framework-rs", "maa-framework/src/lib.rs") is ArtifactKind.BINDING_API
    assert classify("maa-framework-rs", "Cargo.toml") is ArtifactKind.PACKAGE_MANIFEST


def test_csharp_binding_descriptions() -> None:
    assert _describe_binding_artifact(
        CSHARP_SPEC, "src/MaaFramework.Binding/MaaTasker.cs", ArtifactKind.BINDING_API, {}
    ) == ("MaaTasker.cs", "Public C# binding declarations for the MaaTasker module.")
    assert _describe_binding_artifact(
        CSHARP_SPEC, "src/Directory.Packages.props", ArtifactKind.PACKAGE_MANIFEST, {}
    ) == ("Directory.Packages.props", "Package and dependency metadata for the C# binding.")


def test_csharp_compatibility_from_packages_props(tmp_path: Path) -> None:
    repository, commit = _binding_repository(
        tmp_path,
        {
            "src/Directory.Packages.props": CSHARP_PACKAGES_PROPS,
            "src/MaaTasker.cs": "class MaaTasker {}\n",
        },
    )

    compatibility = _binding_compatibility(repository, _release(commit), CSHARP_SPEC)

    assert compatibility.status is CompatibilityStatus.DECLARED
    assert compatibility.framework_version == "5.10.5"
    assert compatibility.evidence_paths == ["src/Directory.Packages.props"]
    assert "Maa.Framework.Runtimes" in compatibility.note


def test_csharp_compatibility_falls_back_to_readme_link(tmp_path: Path) -> None:
    repository, commit = _binding_repository(
        tmp_path,
        {
            "README.md": (
                "C# binding for [MaaFramework]"
                "(https://github.com/MaaXYZ/MaaFramework/blob/v5.9.2).\n"
            ),
            "src/MaaTasker.cs": "class MaaTasker {}\n",
        },
    )

    compatibility = _binding_compatibility(repository, _release(commit), CSHARP_SPEC)

    assert compatibility.status is CompatibilityStatus.DECLARED
    assert compatibility.framework_version == "5.9.2"
    assert compatibility.evidence_paths == ["README.md"]
    assert "links" in compatibility.note


def test_csharp_compatibility_unknown_without_evidence(tmp_path: Path) -> None:
    repository, commit = _binding_repository(
        tmp_path,
        {"README.md": "# C# binding\n", "src/MaaTasker.cs": "class MaaTasker {}\n"},
    )

    compatibility = _binding_compatibility(repository, _release(commit), CSHARP_SPEC)

    assert compatibility.status is CompatibilityStatus.UNKNOWN
    assert compatibility.framework_version is None
    assert compatibility.evidence_paths == []


def test_csharp_sync_filters_legacy_major_tags_and_resolves_prereleases(
    tmp_path: Path,
) -> None:
    repository = _init_repository(tmp_path / "csharp")
    default_branch = _git(repository, "symbolic-ref", "--short", "HEAD")
    first = _commit_files(
        repository,
        {
            "README.md": "# C# binding\n",
            "src/Directory.Packages.props": CSHARP_PACKAGES_PROPS,
            "src/MaaTasker.cs": "class MaaTasker {}\n",
        },
    )
    _git(repository, "tag", "v4.5.0")
    _git(repository, "tag", "v5.0.0-preview.1")
    _git(repository, "checkout", "-q", "-b", "preview")
    prerelease_commit = _commit_files(
        repository, {"src/MaaTasker.cs": "class MaaTasker { int Version => 13; }\n"}
    )
    _git(repository, "tag", "v5.13.0-preview.1")
    _git(repository, "checkout", "-q", default_branch)
    stable_commit = _commit_files(
        repository, {"src/MaaTasker.cs": "class MaaTasker { int Version => 2; }\n"}
    )
    _git(repository, "tag", "v5.1.0")
    assert first != stable_commit != prerelease_commit

    root = tmp_path / "root"
    _write_yaml(
        root / "sources" / "repositories.yaml",
        RepositoryCatalog(
            repositories=[_repository_source("maa-framework-csharp", stable_commit)]
        ).model_dump(mode="json"),
    )

    releases, prereleases = sync_binding_history(
        root=root, repository=repository, source_id="maa-framework-csharp"
    )

    assert [release.version for release in releases] == ["5.1.0"]
    assert [prerelease.version for prerelease in prereleases] == [
        "5.0.0-preview.1",
        "5.13.0-preview.1",
    ]
    assert prereleases[0].included_in == "5.1.0"
    assert prereleases[1].included_in is None
    assert all(prerelease.version != "4.5.0" for prerelease in prereleases)

    inventory = SourceInventory.model_validate(
        yaml.safe_load(
            (root / "sources" / "maa-framework-csharp" / "inventories" / "5.1.0.yaml").read_text(
                encoding="utf-8"
            )
        )
    )
    kinds = {artifact.path: artifact.kind for artifact in inventory.artifacts}
    assert kinds["src/MaaTasker.cs"] is ArtifactKind.BINDING_API
    assert kinds["src/Directory.Packages.props"] is ArtifactKind.PACKAGE_MANIFEST
    assert kinds["README.md"] is ArtifactKind.DOCUMENTATION
    assert (root / "generated" / "maa-framework-csharp" / "5.1.0" / "index.md").is_file()


def _csproj(package_id: str) -> str:
    return (
        "<Project>\n"
        "  <PropertyGroup>\n"
        f"    <PackageId>{package_id}</PackageId>\n"
        "    <TargetFrameworks>net7.0;net9.0</TargetFrameworks>\n"
        "  </PropertyGroup>\n"
        "</Project>\n"
    )


def test_csharp_package_documentation_links_each_nuget_package(tmp_path: Path) -> None:
    repository, commit = _binding_repository(
        tmp_path,
        {
            "src/MaaFramework/MaaFramework.csproj": _csproj("Maa.Framework"),
            "src/MaaFramework.Binding/MaaFramework.Binding.csproj": _csproj(
                "Maa.Framework.Binding"
            ),
            "src/Directory.Packages.props": "<Project />\n",
            "src/NotAProject/notes.txt": "no PackageId here\n",
        },
    )
    inventory = _inventory(
        "5.10.0",
        [
            _artifact("src/Directory.Packages.props", kind=ArtifactKind.PACKAGE_MANIFEST),
            _artifact(
                "src/MaaFramework.Binding/MaaFramework.Binding.csproj",
                kind=ArtifactKind.PACKAGE_MANIFEST,
            ),
            _artifact("src/MaaFramework/MaaFramework.csproj", kind=ArtifactKind.PACKAGE_MANIFEST),
        ],
    )

    release = ReleaseRecord(version="5.10.0", tag="v5.10.0", commit=commit, released_at=FIXED_DATE)
    links = _package_documentation(
        repository, release, BINDING_SPECS["maa-framework-csharp"], inventory
    )

    assert [link.label for link in links] == ["Maa.Framework", "Maa.Framework.Binding"]
    assert links[0].url == "https://www.nuget.org/packages/Maa.Framework/5.10.0"
    assert links[1].url == "https://www.nuget.org/packages/Maa.Framework.Binding/5.10.0"


def test_csharp_version_page_shows_the_nuget_section() -> None:
    inventory = _inventory("5.10.0", [_artifact("src/Directory.Packages.props")])
    compatibility = BindingCompatibility(
        source_id="maa-framework-csharp",
        binding_version="5.10.0",
        binding_revision="a" * 40,
        framework_version="5.10.5",
        status=CompatibilityStatus.DECLARED,
        evidence_paths=["src/Directory.Packages.props"],
        note="The package manifest declares this Maa.Framework.Runtimes version.",
    )
    pages = render_binding_version(
        BINDING_SPECS["maa-framework-csharp"],
        inventory,
        compatibility,
        "https://github.com/MaaXYZ/MaaFramework.Binding.CSharp",
        [
            PackageDocumentation(
                label="Maa.Framework", url="https://www.nuget.org/packages/Maa.Framework/5.10.0"
            )
        ],
    )

    assert "## NuGet packages" in pages["index.md"]
    assert "https://www.nuget.org/packages/Maa.Framework/5.10.0" in pages["index.md"]
    rust_pages = render_binding_version(
        BINDING_SPECS["maa-framework-rs"], inventory, compatibility, "https://example.invalid", []
    )
    assert "NuGet" not in rust_pages["index.md"]


def test_rust_package_documentation_links_both_crates(tmp_path: Path) -> None:
    repository, commit = _binding_repository(
        tmp_path,
        {
            "Cargo.toml": (
                "[workspace]\n"
                'members = ["maa-framework", "maa-framework-sys"]\n'
                "\n"
                "[workspace.dependencies]\n"
                'maa-framework-sys = { path = "maa-framework-sys", version = "5.15.0-beta.1" }\n'
            ),
            "maa-framework/Cargo.toml": '[package]\nname = "maa-framework"\n',
            "maa-framework-sys/Cargo.toml": '[package]\nname = "maa-framework-sys"\n',
        },
    )
    inventory = _inventory(
        "1.27.0",
        [
            _artifact("Cargo.toml", kind=ArtifactKind.PACKAGE_MANIFEST),
            _artifact("maa-framework-sys/Cargo.toml", kind=ArtifactKind.PACKAGE_MANIFEST),
            _artifact("maa-framework/Cargo.toml", kind=ArtifactKind.PACKAGE_MANIFEST),
        ],
    )
    release = ReleaseRecord(version="1.27.0", tag="v1.27.0", commit=commit, released_at=FIXED_DATE)

    links = _package_documentation(
        repository, release, BINDING_SPECS["maa-framework-rs"], inventory
    )

    assert [link.label for link in links] == ["maa-framework", "maa-framework-sys"]
    assert links[0].url == "https://docs.rs/maa-framework/1.27.0"
    assert links[1].url == "https://docs.rs/maa-framework-sys/5.15.0-beta.1"


def test_version_index_lists_every_package_of_the_registry() -> None:
    inventory = _inventory("4.0.0", [_artifact("README.md")])
    compatibility = BindingCompatibility(
        source_id="maa-framework-go",
        binding_version="4.0.0",
        binding_revision="a" * 40,
        framework_version="5.15.0",
        status=CompatibilityStatus.DECLARED,
        evidence_paths=["README.md"],
        note="declared",
    )
    pages = render_binding_version(
        BINDING_SPECS["maa-framework-go"],
        inventory,
        compatibility,
        "https://github.com/MaaXYZ/maa-framework-go",
        [
            PackageDocumentation(label="root package", url="https://pkg.go.dev/x@v4.0.0"),
            PackageDocumentation(label="controller", url="https://pkg.go.dev/x/controller@v4.0.0"),
        ],
    )

    assert "## Go API documentation" in pages["index.md"]
    assert "- [root package](https://pkg.go.dev/x@v4.0.0)" in pages["index.md"]
    assert "- [controller](https://pkg.go.dev/x/controller@v4.0.0)" in pages["index.md"]


def test_version_index_navigation_links_neighbours() -> None:
    current = _inventory("1.2.0", [_artifact("README.md")])
    page = render_version_indexes(
        current,
        "https://example.invalid",
        previous_version="1.1.0",
        next_version="1.3.0",
    )["index.md"]

    assert "## Navigation" in page
    assert "- [All indexed versions](../index.md)" in page
    assert "- Previous release: [1.1.0](../1.1.0/index.md)" in page
    assert "- Next release: [1.3.0](../1.3.0/index.md)" in page
    assert "[Machine symbols](../machine-symbols.md)" in page

    first = render_version_indexes(current, "https://example.invalid", next_version="1.3.0")[
        "index.md"
    ]
    assert "Previous release" not in first
    latest = render_version_indexes(current, "https://example.invalid", previous_version="1.1.0")[
        "index.md"
    ]
    assert "Next release" not in latest


def test_binding_index_shows_navigation_and_changed_since() -> None:
    previous = _inventory("3.5.1", [_artifact("rect.go", kind=ArtifactKind.BINDING_API)])
    current = _inventory(
        "4.0.0",
        [
            _artifact("new.go", kind=ArtifactKind.BINDING_API, blob="3" * 40),
            _artifact("rect.go", kind=ArtifactKind.BINDING_API, blob="2" * 40),
        ],
    )
    compatibility = BindingCompatibility(
        source_id="maa-framework-go",
        binding_version="4.0.0",
        binding_revision="a" * 40,
        framework_version="5.15.0",
        status=CompatibilityStatus.DECLARED,
        evidence_paths=["README.md"],
        note="declared",
    )

    pages = render_binding_version(
        BINDING_SPECS["maa-framework-go"],
        current,
        compatibility,
        "https://github.com/MaaXYZ/maa-framework-go",
        [],
        previous=previous,
        previous_version="3.5.1",
        next_version=None,
    )

    page = pages["index.md"]
    assert "## Changed since `3.5.1`" in page
    assert "## Navigation" in page
    assert "- Previous release: [3.5.1](../3.5.1/index.md)" in page
    assert "Next release" not in page
    assert "new.go" in page
