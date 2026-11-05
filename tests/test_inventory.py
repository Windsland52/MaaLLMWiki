# pyright: reportPrivateUsage=false
from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pytest
import yaml

from maa_llm_wiki import inventory
from maa_llm_wiki.bindings import (
    BindingSourceSpec,
    _binding_compatibility,
    sync_binding_history,
)
from maa_llm_wiki.inventory import (
    discover_prereleases,
    discover_stable_releases,
    git_text,
    resolve_included_in,
    sync_maafw_history,
)
from maa_llm_wiki.models import (
    CompatibilityStatus,
    PrereleaseRecord,
    ReleaseCatalog,
    ReleaseRecord,
    RepositoryCatalog,
    RepositoryRole,
    RepositorySource,
    RepositoryStatus,
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
        status=RepositoryStatus.ACTIVE,
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
    catalog = ReleaseCatalog(
        source_id="maafw",
        releases=releases,
        prereleases=prereleases or [],
    )
    _write_yaml(
        root / "sources" / "maa-framework" / "releases.yaml", catalog.model_dump(mode="json")
    )
    _write_yaml(
        root / "sources" / "repositories.yaml",
        RepositoryCatalog(
            repositories=[_repository_source("maafw", revision or releases[0].commit)]
        ).model_dump(mode="json"),
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
    assert (root / "generated" / "maa-framework" / "1.0.0" / "index.md").is_file()


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
