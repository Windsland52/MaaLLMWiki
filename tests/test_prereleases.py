import subprocess
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from maa_llm_wiki.inventory import (
    discover_prereleases,
    discover_stable_releases,
    parse_prerelease_tag,
    render_prereleases_page,
    resolve_included_in,
)
from maa_llm_wiki.models import PrereleaseRecord, ReleaseCatalog, ReleaseRecord

COMMIT_A = "a" * 40
COMMIT_B = "b" * 40


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


@pytest.fixture()
def upstream(tmp_path: Path) -> Path:
    repository = tmp_path / "upstream"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "catalog@example.com")
    _git(repository, "config", "user.name", "Catalog Test")
    _git(repository, "config", "commit.gpgsign", "false")

    def commit() -> None:
        _git(repository, "commit", "--allow-empty", "-q", "-m", "work")

    commit()
    _git(repository, "tag", "v1.0.0")
    commit()
    _git(repository, "tag", "v1.1.0-beta.1")
    commit()
    _git(repository, "tag", "v1.1.0-beta.2")
    commit()
    _git(repository, "tag", "v1.1.0-beta.10")
    commit()
    _git(repository, "tag", "v1.1.0")
    commit()
    _git(repository, "tag", "v1.2.0-alpha.1")
    return repository


def test_parse_prerelease_tag_accepts_semver_suffixes() -> None:
    assert parse_prerelease_tag("v5.13.0-beta.6") == ((5, 13, 0), "beta.6")
    assert parse_prerelease_tag("v3.6.0-beta.1") == ((3, 6, 0), "beta.1")


def test_parse_prerelease_tag_rejects_other_tags() -> None:
    assert parse_prerelease_tag("v5.12.2") is None
    assert parse_prerelease_tag("nightly") is None
    assert parse_prerelease_tag("v5.13.0-") is None
    assert parse_prerelease_tag("v5.13.0-beta.") is None


def test_discover_prereleases_are_sorted_by_semver_precedence(upstream: Path) -> None:
    prereleases = discover_prereleases(upstream)
    assert [prerelease.version for prerelease in prereleases] == [
        "1.1.0-beta.1",
        "1.1.0-beta.2",
        "1.1.0-beta.10",
        "1.2.0-alpha.1",
    ]
    assert all(prerelease.included_in is None for prerelease in prereleases)


def test_discover_prereleases_respects_major_filter(upstream: Path) -> None:
    assert [prerelease.version for prerelease in discover_prereleases(upstream, major=9)] == []


def test_resolve_included_in_tracks_first_containing_stable(upstream: Path) -> None:
    releases = discover_stable_releases(upstream)
    resolved = resolve_included_in(upstream, discover_prereleases(upstream), releases)

    by_version = {prerelease.version: prerelease for prerelease in resolved}
    assert by_version["1.1.0-beta.1"].included_in == "1.1.0"
    assert by_version["1.1.0-beta.10"].included_in == "1.1.0"
    assert by_version["1.2.0-alpha.1"].included_in is None


def test_render_prereleases_page_lists_traceability_columns() -> None:
    release = ReleaseRecord(
        version="1.1.0", tag="v1.1.0", commit=COMMIT_A, released_at=date(2026, 1, 2)
    )
    prereleases = [
        PrereleaseRecord(
            version="1.1.0-beta.1",
            tag="v1.1.0-beta.1",
            commit=COMMIT_B,
            released_at=date(2025, 12, 20),
            included_in="1.1.0",
        ),
        PrereleaseRecord(
            version="1.2.0-alpha.1",
            tag="v1.2.0-alpha.1",
            commit=COMMIT_A,
            released_at=date(2026, 1, 5),
            included_in=None,
        ),
    ]

    page = render_prereleases_page(
        display_name="MaaFramework",
        generator="maa-wiki-sync-maafw-history",
        repository_url="https://github.com/MaaXYZ/MaaFramework",
        releases=[release],
        prereleases=prereleases,
    )

    assert "# MaaFramework prerelease registry" in page
    assert "./1.2.0-alpha.1/index.md" not in page  # prereleases get no inventory links
    assert f"[`{COMMIT_A[:12]}`]" in page
    assert "[1.1.0](./1.1.0/index.md)" in page
    assert "| not merged |" in page


def test_release_catalog_rejects_inconsistent_preregistries() -> None:
    stable = ReleaseRecord(
        version="1.1.0", tag="v1.1.0", commit=COMMIT_A, released_at=date(2026, 1, 2)
    )

    with pytest.raises(ValidationError, match="unknown stable release"):
        ReleaseCatalog(
            source_id="maafw",
            releases=[stable],
            prereleases=[
                PrereleaseRecord(
                    version="1.2.0-beta.1",
                    tag="v1.2.0-beta.1",
                    commit=COMMIT_B,
                    released_at=date(2026, 1, 5),
                    included_in="9.9.9",
                )
            ],
        )

    with pytest.raises(ValidationError, match="collides with a stable release"):
        ReleaseCatalog(
            source_id="maafw",
            releases=[stable],
            prereleases=[
                PrereleaseRecord(
                    version="1.1.0",
                    tag="v1.1.0-beta.0",
                    commit=COMMIT_B,
                    released_at=date(2026, 1, 1),
                )
            ],
        )

    with pytest.raises(ValidationError, match="stable release commit"):
        ReleaseCatalog(
            source_id="maafw",
            releases=[stable],
            prereleases=[
                PrereleaseRecord(
                    version="1.1.0-rc.1",
                    tag="v1.1.0-rc.1",
                    commit=COMMIT_A,
                    released_at=date(2026, 1, 1),
                )
            ],
        )

    with pytest.raises(ValidationError, match="Duplicate prerelease entry"):
        duplicate = PrereleaseRecord(
            version="1.2.0-beta.1",
            tag="v1.2.0-beta.1",
            commit=COMMIT_B,
            released_at=date(2026, 1, 5),
        )
        ReleaseCatalog(source_id="maafw", releases=[stable], prereleases=[duplicate, duplicate])
