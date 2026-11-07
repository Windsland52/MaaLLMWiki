from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, cast
from zipfile import ZipFile

import pytest

from maa_llm_wiki.bundle import (
    build_catalog_bundle,
    bundle_archive_path,
    bundle_paths,
    bundle_sha256,
    bundle_sources,
)
from maa_llm_wiki.cli import (
    build_bundle_main,
    sync_bindings_history_main,
    sync_maafw_history_main,
    verify_bundle_main,
)
from maa_llm_wiki.models import (
    CatalogBundleFile,
    CatalogBundleManifest,
    CatalogBundleSource,
    PrereleaseRecord,
    ReleaseRecord,
)
from maa_llm_wiki.verify_bundle import verify_bundle

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


def _problems(
    bundle: Path, *, expect_revision: str | None = None, expect_version: str | None = None
) -> list[str]:
    problems, _ = verify_bundle(
        bundle=bundle, expect_revision=expect_revision, expect_version=expect_version
    )
    return problems


def _mentions(problems: list[str], text: str) -> bool:
    return any(text in problem for problem in problems)


def test_verify_bundle_accepts_intact_bundle(tmp_path: Path) -> None:
    manifest = _write_bundle(tmp_path / "catalog.zip", catalog_version="v1.2.3")

    problems, summary = verify_bundle(
        bundle=tmp_path / "catalog.zip",
        expect_revision=REVISION,
        expect_version="v1.2.3",
    )

    assert problems == []
    assert summary.startswith(f"Verified catalog bundle: v1.2.3 {REVISION} ")
    assert f"({len(manifest.files)} files)" in summary


def test_verify_bundle_rejects_missing_file(tmp_path: Path) -> None:
    _write_bundle(tmp_path / "catalog.zip")
    _rewrite(
        tmp_path / "catalog.zip",
        tmp_path / "broken.zip",
        drop=("sources/maa-framework/inventory.yaml",),
    )

    assert _mentions(_problems(tmp_path / "broken.zip"), "missing from the bundle")


def test_verify_bundle_rejects_size_mismatch(tmp_path: Path) -> None:
    _write_bundle(tmp_path / "catalog.zip", sizes={"sources/maa-framework/inventory.yaml": 3})

    assert _mentions(_problems(tmp_path / "catalog.zip"), "size mismatch")


def test_verify_bundle_rejects_sha_mismatch(tmp_path: Path) -> None:
    _write_bundle(tmp_path / "catalog.zip")
    original = _FILES["sources/maa-framework/inventory.yaml"]
    _rewrite(
        tmp_path / "catalog.zip",
        tmp_path / "broken.zip",
        replace={"sources/maa-framework/inventory.yaml": b"x" * len(original)},
    )

    assert _mentions(_problems(tmp_path / "broken.zip"), "sha256 mismatch")


def test_verify_bundle_rejects_extra_zip_entry(tmp_path: Path) -> None:
    _write_bundle(tmp_path / "catalog.zip")
    _rewrite(
        tmp_path / "catalog.zip",
        tmp_path / "broken.zip",
        extra={"sources/evil.yaml": b"evil: true\n"},
    )

    assert _mentions(_problems(tmp_path / "broken.zip"), "not listed in the manifest")


def test_verify_bundle_rejects_wrong_expectations(tmp_path: Path) -> None:
    _write_bundle(tmp_path / "catalog.zip", catalog_version="v1.2.3")
    bundle = tmp_path / "catalog.zip"

    assert _mentions(_problems(bundle, expect_revision="0" * 40), "wiki revision mismatch")
    assert _mentions(_problems(bundle, expect_version="v9.9.9"), "catalog version mismatch")


def test_verify_bundle_rejects_missing_catalog_version_when_expected(tmp_path: Path) -> None:
    _write_bundle(tmp_path / "catalog.zip")

    assert _mentions(
        _problems(tmp_path / "catalog.zip", expect_version="v1.2.3"), "no catalog_version"
    )


def _rewrite_manifest(source: Path, target: Path, payload: dict[str, Any]) -> Path:
    _rewrite(source, target, replace={"catalog-manifest.json": json.dumps(payload).encode()})
    return target


def _manifest_payload(bundle: Path) -> dict[str, Any]:
    with ZipFile(bundle) as archive:
        return cast(dict[str, Any], json.loads(archive.read("catalog-manifest.json")))


def test_verify_bundle_accepts_early_and_extended_manifests(tmp_path: Path) -> None:
    # Early bundles (v0.1.0, v0.1.1) have no catalog_version; later v1 bundles may add fields.
    _write_bundle(tmp_path / "catalog.zip")
    payload = _manifest_payload(tmp_path / "catalog.zip")
    payload.pop("catalog_version", None)
    payload["future_field"] = {"nested": True}
    for record in cast(list[dict[str, Any]], payload["sources"]):
        record["future_source_field"] = 1
    for record in cast(list[dict[str, Any]], payload["files"]):
        record["future_file_field"] = "x"
    bundle = _rewrite_manifest(tmp_path / "catalog.zip", tmp_path / "extended.zip", payload)

    problems, summary = verify_bundle(bundle=bundle, expect_revision=REVISION)

    assert problems == []
    assert summary.startswith(f"Verified catalog bundle: unversioned {REVISION} ")


def test_verify_bundle_rejects_a_missing_required_field(tmp_path: Path) -> None:
    _write_bundle(tmp_path / "catalog.zip", catalog_version="v1.2.3")
    for field, message in (
        ("working_tree_clean", "working_tree_clean is not a boolean"),
        ("wiki_revision", "wiki_revision is not 40 lowercase hex characters"),
        ("api_version", "api_version is not"),
        ("sources", "sources is not a non-empty array"),
    ):
        payload = _manifest_payload(tmp_path / "catalog.zip")
        del payload[field]
        bundle = _rewrite_manifest(tmp_path / "catalog.zip", tmp_path / f"no-{field}.zip", payload)

        assert _mentions(_problems(bundle), message), field


def test_verify_bundle_aggregates_all_problems(tmp_path: Path) -> None:
    manifest = _write_bundle(tmp_path / "catalog.zip", catalog_version="v1.2.3")
    _rewrite(
        tmp_path / "catalog.zip",
        tmp_path / "broken.zip",
        drop=(manifest.files[0].path,),
        extra={"sources/evil.yaml": b"evil: true\n"},
    )

    problems = _problems(tmp_path / "broken.zip", expect_revision="0" * 40, expect_version="v9.9.9")

    assert len(problems) == 4
    assert _mentions(problems, "not listed in the manifest")
    assert _mentions(problems, "missing from the bundle")
    assert _mentions(problems, "wiki revision mismatch")
    assert _mentions(problems, "catalog version mismatch")


def test_verify_bundle_rejects_invalid_manifest(tmp_path: Path) -> None:
    path = tmp_path / "catalog.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("catalog-manifest.json", "{not json")

    assert _mentions(_problems(path), "catalog-manifest.json is invalid")


def test_verify_bundle_rejects_bundle_without_manifest(tmp_path: Path) -> None:
    path = tmp_path / "catalog.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("generated/index.md", b"# index\n")

    assert _mentions(_problems(path), "catalog-manifest.json is missing")


def test_build_catalog_bundle_records_catalog_version(tmp_path: Path) -> None:
    output = tmp_path / "catalog.zip"
    manifest = build_catalog_bundle(root=ROOT, output=output, allow_dirty=True, version="v1.2.3")

    assert manifest.catalog_version == "v1.2.3"
    # The manifest must list exactly the allowlisted published layout (grows with the catalog,
    # e.g. when sources/maa-framework/machine-changes.yaml is added by the sync).
    assert {record.path for record in manifest.files} == {
        bundle_archive_path(path.relative_to(ROOT).as_posix()) for path in bundle_paths(ROOT)
    }
    with ZipFile(output) as archive:
        bundled = CatalogBundleManifest.model_validate_json(archive.read("catalog-manifest.json"))
    assert bundled.catalog_version == "v1.2.3"
    assert _problems(output, expect_version="v1.2.3") == []


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
    expected_digest = hashlib.sha256((tmp_path / "catalog.zip").read_bytes()).hexdigest()
    assert captured.out.strip() == (
        f"Verified catalog bundle: v1.2.3 {REVISION} (2 files) sha256={expected_digest}"
    )
    assert captured.err == ""


def test_cli_verify_bundle_checks_checksums(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = tmp_path / "catalog.zip"
    _write_bundle(bundle, catalog_version="v1.2.3")
    checksums = tmp_path / "SHA256SUMS"
    checksums.write_text(f"{'0' * 64}  catalog.zip\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["maa-wiki-verify-bundle", "--bundle", str(bundle), "--checksums", str(checksums)],
    )

    assert verify_bundle_main() == 1
    assert "no SHA256SUMS entry matches catalog.zip" in capsys.readouterr().err


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
            "maa-wiki-sync-maafw-history",
            "--root",
            str(tmp_path),
            "--repository",
            str(tmp_path / "missing-clone"),
        ],
    )

    assert sync_maafw_history_main() == 1
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


def _write_published_layout(root: Path) -> dict[str, str]:
    """Minimal real-shaped catalog tree: one indexed source plus the hand-authored files."""
    inventory = (
        "source_id: maa-framework-go\n"
        "version: 1.0.0\n"
        f"revision: {COMMIT}\n"
        "artifacts:\n"
        "- path: go.mod\n"
        "  kind: package-manifest\n"
        "  title: go.mod\n"
        "  summary: Manifest.\n"
    )
    files = {
        "generated/maa-framework/1.0.0/index.md": "# index\n",
        "generated/maa-framework/index.md": "# releases\n",
        "schemas/source-inventory.schema.json": "{}\n",
        "sources/repositories.yaml": (
            "repositories:\n"
            "- id: maa-framework-go\n"
            "  name: MaaFramework Go binding\n"
            "  url: https://example.invalid/maa-framework-go\n"
            "  role: authoritative\n"
            "  enabled: true\n"
            f"  default_revision: {COMMIT}\n"
        ),
        "sources/compatibility/bindings.yaml": "bindings: []\n",
        "sources/maa-framework-go/releases.yaml": "source_id: maa-framework-go\nreleases: []\n",
        "sources/maa-framework-go/inventory.yaml": inventory,
        "sources/maa-framework-go/inventories/1.0.0.yaml": inventory,
        "sources/maa-framework/source-map.yaml": "topics: []\n",
        "sources/maa-framework/machine-changes.yaml": "source_id: maafw\nchanges: []\n",
        "sources/maa-framework/upstream-commits.yaml": "source_id: maafw\ncommits: []\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return files


def test_bundle_paths_accepts_the_published_layout(tmp_path: Path) -> None:
    files = _write_published_layout(tmp_path)

    relative = [path.relative_to(tmp_path).as_posix() for path in bundle_paths(tmp_path)]

    assert relative == sorted(files)


def test_bundle_paths_rejects_stray_generated_file(tmp_path: Path) -> None:
    _write_published_layout(tmp_path)
    (tmp_path / "generated" / "notes.txt").write_text("stray\n", encoding="utf-8")

    with pytest.raises(ValueError, match="generated/notes.txt"):
        bundle_paths(tmp_path)


def test_bundle_paths_rejects_stray_sources_file(tmp_path: Path) -> None:
    _write_published_layout(tmp_path)
    (tmp_path / "sources" / "maa-framework-go" / "notes.md").write_text(
        "# notes\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="sources/maa-framework-go/notes.md"):
        bundle_paths(tmp_path)


def test_bundle_paths_rejects_stray_schemas_file(tmp_path: Path) -> None:
    _write_published_layout(tmp_path)
    (tmp_path / "schemas" / "extra.schema.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="schemas/extra.schema.json"):
        bundle_paths(tmp_path)


def test_bundle_paths_rejects_unregistered_source_directory(tmp_path: Path) -> None:
    _write_published_layout(tmp_path)
    source_root = tmp_path / "sources" / "unregistered"
    source_root.mkdir(parents=True)
    (source_root / "inventory.yaml").write_text("source_id: unregistered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="sources/unregistered/inventory.yaml"):
        bundle_paths(tmp_path)


def test_bundle_sha256_matches_the_file_digest(tmp_path: Path) -> None:
    bundle = tmp_path / "catalog.zip"
    _write_bundle(bundle, catalog_version="v1.2.3")

    assert bundle_sha256(bundle) == hashlib.sha256(bundle.read_bytes()).hexdigest()


def test_bundle_zip_entries_pin_the_host_field(tmp_path: Path) -> None:
    """Windows and POSIX builds must produce the same central directory."""
    output = tmp_path / "platform.zip"
    build_catalog_bundle(root=ROOT, output=output, allow_dirty=True, version="v0.0.1")

    with ZipFile(output) as archive:
        entries = archive.infolist()

    assert entries
    assert {entry.create_system for entry in entries} == {3}
    assert {entry.external_attr for entry in entries} == {0o100644 << 16}
    assert {entry.date_time for entry in entries} == {(1980, 1, 1, 0, 0, 0)}


def _corrupt_member(path: Path, member: str) -> None:
    """Flip one byte inside a member's compressed data, keeping the zip structure valid."""
    data = bytearray(path.read_bytes())
    with ZipFile(path) as archive:
        info = archive.getinfo(member)
    header_offset = info.header_offset
    name_length = int.from_bytes(data[header_offset + 26 : header_offset + 28], "little")
    extra_length = int.from_bytes(data[header_offset + 28 : header_offset + 30], "little")
    data_start = header_offset + 30 + name_length + extra_length
    data[data_start + info.compress_size // 2] ^= 0xFF
    path.write_bytes(bytes(data))


def test_corrupt_member_is_reported_without_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "corrupt.zip"
    build_catalog_bundle(root=ROOT, output=output, allow_dirty=True, version="v0.0.5")
    _corrupt_member(output, "catalog-manifest.json")

    # A corrupt member is a verification problem, never an escaping BadZipFile.
    assert _problems(output)

    monkeypatch.setattr(sys, "argv", ["maa-wiki-verify-bundle", "--bundle", str(output)])
    assert verify_bundle_main() == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("error: ")
    assert "Traceback" not in captured.err


def test_bundle_paths_accept_machine_change_catalog_and_reject_near_misses(tmp_path: Path) -> None:
    _write_published_layout(tmp_path)
    relative = [path.relative_to(tmp_path).as_posix() for path in bundle_paths(tmp_path)]
    assert "sources/maa-framework/machine-changes.yaml" in relative
    assert "sources/maa-framework/upstream-commits.yaml" in relative

    (tmp_path / "sources" / "maa-framework" / "machine-changes.yml").write_text(
        "source_id: maafw\nchanges: []\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="machine-changes.yml"):
        bundle_paths(tmp_path)
