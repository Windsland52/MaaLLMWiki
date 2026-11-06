from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

from maa_llm_wiki.bundle import build_catalog_bundle, bundle_sources, verify_catalog_bundle
from maa_llm_wiki.cli import (
    build_bundle_main,
    sync_bindings_history_main,
    sync_maafw_history_main,
    sync_maafw_main,
    verify_bundle_main,
)
from maa_llm_wiki.models import (
    CatalogBundleFile,
    CatalogBundleManifest,
    CatalogBundleSource,
    PrereleaseRecord,
    ReleaseRecord,
)

ROOT = Path(__file__).parents[1]
COMMIT = "a" * 40
REVISION = "b" * 40
_FILES = {
    "generated/maa-framework/1.0.0/index.md": b"# index\n",
    "sources/maa-framework/inventory.yaml": b"source_id: maafw\n",
}


def _write_bundle(
    path: Path,
    *,
    catalog_version: str | None = None,
    wiki_revision: str = REVISION,
    files: dict[str, bytes] | None = None,
    sizes: dict[str, int] | None = None,
    unrelated: dict[str, bytes] | None = None,
) -> CatalogBundleManifest:
    payload = dict(_FILES if files is None else files)
    size_overrides = sizes or {}
    records = [
        CatalogBundleFile(
            path=name,
            size_bytes=size_overrides.get(name, len(content)),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        for name, content in payload.items()
    ]
    manifest = CatalogBundleManifest(
        catalog_version=catalog_version,
        wiki_revision=wiki_revision,
        working_tree_clean=True,
        sources=[CatalogBundleSource(source_id="maafw", version="1.0.0", revision=COMMIT)],
        files=records,
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("catalog-manifest.json", manifest.model_dump_json(indent=2) + "\n")
        for name, content in payload.items():
            archive.writestr(name, content)
    return manifest


def _rewrite(
    source: Path,
    target: Path,
    *,
    drop: tuple[str, ...] = (),
    replace: dict[str, bytes] | None = None,
    extra: dict[str, bytes] | None = None,
) -> None:
    replacements = replace or {}
    with ZipFile(source) as original, ZipFile(target, "w") as rewritten:
        for name in original.namelist():
            if name in drop:
                continue
            content = replacements.get(name, original.read(name))
            rewritten.writestr(name, content)
        for name, content in (extra or {}).items():
            rewritten.writestr(name, content)


def test_verify_bundle_accepts_intact_bundle(tmp_path: Path) -> None:
    manifest = _write_bundle(tmp_path / "catalog.zip", catalog_version="v1.2.3")

    verified = verify_catalog_bundle(
        bundle=tmp_path / "catalog.zip",
        expect_revision=REVISION,
        expect_version="v1.2.3",
    )

    assert verified == manifest
    assert verified.catalog_version == "v1.2.3"
    assert len(verified.files) == len(_FILES)


def test_verify_bundle_rejects_missing_file(tmp_path: Path) -> None:
    _write_bundle(tmp_path / "catalog.zip")
    _rewrite(
        tmp_path / "catalog.zip",
        tmp_path / "broken.zip",
        drop=("sources/maa-framework/inventory.yaml",),
    )

    with pytest.raises(ValueError, match="missing from the bundle"):
        verify_catalog_bundle(bundle=tmp_path / "broken.zip")


def test_verify_bundle_rejects_size_mismatch(tmp_path: Path) -> None:
    _write_bundle(tmp_path / "catalog.zip", sizes={"sources/maa-framework/inventory.yaml": 3})

    with pytest.raises(ValueError, match="size mismatch"):
        verify_catalog_bundle(bundle=tmp_path / "catalog.zip")


def test_verify_bundle_rejects_sha_mismatch(tmp_path: Path) -> None:
    _write_bundle(tmp_path / "catalog.zip")
    original = _FILES["sources/maa-framework/inventory.yaml"]
    _rewrite(
        tmp_path / "catalog.zip",
        tmp_path / "broken.zip",
        replace={"sources/maa-framework/inventory.yaml": b"x" * len(original)},
    )

    with pytest.raises(ValueError, match="sha256 mismatch"):
        verify_catalog_bundle(bundle=tmp_path / "broken.zip")


def test_verify_bundle_rejects_extra_zip_entry(tmp_path: Path) -> None:
    _write_bundle(tmp_path / "catalog.zip")
    _rewrite(
        tmp_path / "catalog.zip",
        tmp_path / "broken.zip",
        extra={"sources/evil.yaml": b"evil: true\n"},
    )

    with pytest.raises(ValueError, match="not listed in the manifest"):
        verify_catalog_bundle(bundle=tmp_path / "broken.zip")


def test_verify_bundle_rejects_wrong_expectations(tmp_path: Path) -> None:
    _write_bundle(tmp_path / "catalog.zip", catalog_version="v1.2.3")

    with pytest.raises(ValueError, match="wiki revision mismatch"):
        verify_catalog_bundle(bundle=tmp_path / "catalog.zip", expect_revision="0" * 40)
    with pytest.raises(ValueError, match="catalog version mismatch"):
        verify_catalog_bundle(bundle=tmp_path / "catalog.zip", expect_version="v9.9.9")


def test_verify_bundle_rejects_missing_catalog_version(tmp_path: Path) -> None:
    _write_bundle(tmp_path / "catalog.zip")

    with pytest.raises(ValueError, match="no catalog_version"):
        verify_catalog_bundle(bundle=tmp_path / "catalog.zip", expect_version="v1.2.3")


def test_verify_bundle_aggregates_all_problems(tmp_path: Path) -> None:
    manifest = _write_bundle(tmp_path / "catalog.zip", catalog_version="v1.2.3")
    _rewrite(
        tmp_path / "catalog.zip",
        tmp_path / "broken.zip",
        drop=(manifest.files[0].path,),
        extra={"sources/evil.yaml": b"evil: true\n"},
    )

    with pytest.raises(ValueError) as raised:
        verify_catalog_bundle(
            bundle=tmp_path / "broken.zip",
            expect_revision="0" * 40,
            expect_version="v9.9.9",
        )

    problems = str(raised.value).split("; ")
    assert len(problems) == 4
    assert any("not listed in the manifest" in problem for problem in problems)
    assert any("missing from the bundle" in problem for problem in problems)
    assert any("wiki revision mismatch" in problem for problem in problems)
    assert any("catalog version mismatch" in problem for problem in problems)


def test_verify_bundle_rejects_invalid_manifest(tmp_path: Path) -> None:
    path = tmp_path / "catalog.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("catalog-manifest.json", "{not json")

    with pytest.raises(ValueError, match="catalog-manifest.json is invalid"):
        verify_catalog_bundle(bundle=path)


def test_verify_bundle_rejects_bundle_without_manifest(tmp_path: Path) -> None:
    path = tmp_path / "catalog.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("generated/index.md", b"# index\n")

    with pytest.raises(ValueError, match="catalog-manifest.json is missing"):
        verify_catalog_bundle(bundle=path)


def test_build_catalog_bundle_records_catalog_version(tmp_path: Path) -> None:
    output = tmp_path / "catalog.zip"
    manifest = build_catalog_bundle(root=ROOT, output=output, allow_dirty=True, version="v1.2.3")

    assert manifest.catalog_version == "v1.2.3"
    with ZipFile(output) as archive:
        bundled = CatalogBundleManifest.model_validate_json(archive.read("catalog-manifest.json"))
    assert bundled.catalog_version == "v1.2.3"
    assert verify_catalog_bundle(bundle=output, expect_version="v1.2.3") == manifest


def test_build_catalog_bundle_rejects_malformed_version(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must look like vX.Y.Z"):
        build_catalog_bundle(
            root=tmp_path, output=tmp_path / "catalog.zip", allow_dirty=True, version="1.2.3"
        )


def test_cli_verify_bundle_prints_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_bundle(tmp_path / "catalog.zip", catalog_version="v1.2.3")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "maa-wiki-verify-bundle",
            "--bundle",
            str(tmp_path / "catalog.zip"),
            "--expect-revision",
            REVISION,
            "--expect-version",
            "v1.2.3",
        ],
    )

    assert verify_bundle_main() == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == f"Verified catalog bundle: v1.2.3 {REVISION} (2 files)"
    assert captured.err == ""


def test_cli_verify_bundle_reports_error_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_bundle(tmp_path / "catalog.zip")
    _rewrite(
        tmp_path / "catalog.zip",
        tmp_path / "broken.zip",
        extra={"sources/evil.yaml": b"evil: true\n"},
    )
    monkeypatch.setattr(
        sys, "argv", ["maa-wiki-verify-bundle", "--bundle", str(tmp_path / "broken.zip")]
    )

    assert verify_bundle_main() == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("error: ")
    assert "not listed in the manifest" in captured.err
    assert "Traceback" not in captured.err + captured.out


def test_cli_error_boundary_hides_tracebacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "maa-wiki-sync-maafw",
            "--root",
            str(tmp_path),
            "--repository",
            str(tmp_path),
            "--version",
            "9.9.9",
        ],
    )

    assert sync_maafw_main() == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("error: ")
    assert "Traceback" not in captured.err + captured.out


def test_cli_history_commands_pass_prune(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[bool] = []

    def fake_maafw_history(
        *, root: Path, repository: Path, major: int, prune: bool
    ) -> tuple[list[ReleaseRecord], list[PrereleaseRecord]]:
        seen.append(prune)
        return ([], [])

    def fake_bindings_history(
        *, root: Path, repository: Path, source_id: str, prune: bool
    ) -> tuple[list[ReleaseRecord], list[PrereleaseRecord]]:
        seen.append(prune)
        return ([], [])

    monkeypatch.setattr("maa_llm_wiki.cli.sync_maafw_history", fake_maafw_history)
    monkeypatch.setattr("maa_llm_wiki.cli.sync_binding_history", fake_bindings_history)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "maa-wiki-sync-maafw-history",
            "--root",
            ".",
            "--repository",
            ".",
            "--prune",
        ],
    )
    assert sync_maafw_history_main() == 0
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "maa-wiki-sync-bindings-history",
            "--root",
            ".",
            "--go-repository",
            ".",
            "--rust-repository",
            ".",
            "--prune",
        ],
    )
    assert sync_bindings_history_main() == 0
    capsys.readouterr()

    assert seen == [True, True, True]


def test_cli_history_commands_default_to_no_prune(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[bool] = []

    def fake_maafw_history(
        *, root: Path, repository: Path, major: int, prune: bool
    ) -> tuple[list[ReleaseRecord], list[PrereleaseRecord]]:
        seen.append(prune)
        return ([], [])

    monkeypatch.setattr("maa_llm_wiki.cli.sync_maafw_history", fake_maafw_history)
    monkeypatch.setattr(
        sys,
        "argv",
        ["maa-wiki-sync-maafw-history", "--root", ".", "--repository", "."],
    )
    assert sync_maafw_history_main() == 0
    capsys.readouterr()

    assert seen == [False]


def test_cli_build_bundle_version_flag_and_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[str | None] = []

    def fake_build(*, root: Path, output: Path, allow_dirty: bool, version: str | None):
        seen.append(version)
        raise ValueError("stop after capturing the parsed flag")

    monkeypatch.setattr("maa_llm_wiki.cli.build_catalog_bundle", fake_build)
    monkeypatch.setattr(
        sys,
        "argv",
        ["maa-wiki-build-bundle", "--output", str(tmp_path / "catalog.zip"), "--version", "v1.2.3"],
    )
    assert build_bundle_main() == 1
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "maa-wiki-build-bundle",
            "--output",
            str(tmp_path / "catalog.zip"),
            "--catalog-version",
            "v1.2.4",
        ],
    )
    assert build_bundle_main() == 1
    capsys.readouterr()

    assert seen == ["v1.2.3", "v1.2.4"]


def _write_source_entry(root: Path, source_id: str, *, indexed: bool) -> None:
    directory = "maa-framework" if source_id == "maafw" else source_id
    source_root = root / "sources" / directory
    source_root.mkdir(parents=True, exist_ok=True)
    if not indexed:
        return
    (source_root / "inventory.yaml").write_text(
        f"source_id: {source_id}\n"
        "version: 1.0.0\n"
        f"revision: {COMMIT}\n"
        "artifacts:\n"
        "- path: docs/a.md\n"
        "  kind: documentation\n"
        "  title: A\n"
        "  summary: A doc.\n",
        encoding="utf-8",
    )


def _write_repository_catalog(root: Path, source_ids: list[str]) -> None:
    lines = ["repositories:"]
    for source_id in source_ids:
        lines.extend(
            [
                f"- id: {source_id}",
                f"  name: {source_id}",
                f"  url: https://example.invalid/{source_id}",
                "  role: authoritative",
                "  status: active",
                "  enabled: true",
                f"  default_revision: {COMMIT}",
            ]
        )
    (root / "sources").mkdir(parents=True, exist_ok=True)
    (root / "sources" / "repositories.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_bundle_sources_follow_catalog_order_and_skip_missing_inventories(tmp_path: Path) -> None:
    _write_repository_catalog(tmp_path, ["maa-framework-go", "maatutorial", "maa-framework-rs"])
    _write_source_entry(tmp_path, "maa-framework-go", indexed=True)
    _write_source_entry(tmp_path, "maatutorial", indexed=False)
    _write_source_entry(tmp_path, "maa-framework-rs", indexed=True)

    sources = bundle_sources(tmp_path)

    assert [source.source_id for source in sources] == ["maa-framework-go", "maa-framework-rs"]
    assert [source.version for source in sources] == ["1.0.0", "1.0.0"]
    assert [source.revision for source in sources] == [COMMIT, COMMIT]


def test_bundle_sources_include_extra_registered_source_with_inventory(tmp_path: Path) -> None:
    _write_repository_catalog(tmp_path, ["maa-framework-go", "maatutorial"])
    _write_source_entry(tmp_path, "maa-framework-go", indexed=True)
    _write_source_entry(tmp_path, "maatutorial", indexed=True)

    sources = bundle_sources(tmp_path)

    assert [source.source_id for source in sources] == ["maa-framework-go", "maatutorial"]
