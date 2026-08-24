import hashlib
from pathlib import Path
from zipfile import ZipFile

from maa_llm_wiki.bundle import build_catalog_bundle
from maa_llm_wiki.inventory import parse_stable_tag
from maa_llm_wiki.models import CatalogBundleManifest, RepositoryStatus
from maa_llm_wiki.validation import (
    load_binding_compatibility,
    load_release_catalog,
    load_repository_catalog,
    load_semantic_changes,
    load_source_inventories,
    load_source_inventory,
    validate_repository,
)

ROOT = Path(__file__).parents[1]


def test_repository_content_is_valid() -> None:
    assert validate_repository(ROOT) == []


def test_maa_tutorial_is_disabled_placeholder() -> None:
    catalog = load_repository_catalog(ROOT)
    tutorial = next(item for item in catalog.repositories if item.id == "maa-tutorial")

    assert tutorial.status is RepositoryStatus.PLACEHOLDER
    assert not tutorial.enabled
    assert tutorial.default_revision is None


def test_framework_semantic_changes_are_explicit() -> None:
    changes = load_semantic_changes(ROOT)

    assert {change.first_version for change in changes.changes} == {"5.5.0", "5.8.0"}


def test_framework_inventory_covers_official_material() -> None:
    inventory = load_source_inventory(ROOT)
    paths = {artifact.path for artifact in inventory.artifacts}

    assert "docs/zh_cn/3.1-任务流水线协议.md" in paths
    assert "docs/en_us/3.1-PipelineProtocol.md" in paths
    assert "tools/pipeline.schema.json" in paths
    assert "include/MaaFramework/MaaMsg.h" in paths
    assert "source/binding/Python/maa/tasker.py" in paths
    assert "source/binding/NodeJS/src/apis/tasker.d.ts" in paths
    assert any(artifact.kind.value == "documentation-asset" for artifact in inventory.artifacts)
    assert all(artifact.title and artifact.summary for artifact in inventory.artifacts)
    assert all(
        not path.startswith("source/") or path.startswith("source/binding/") for path in paths
    )


def test_stable_release_tag_parser_rejects_prereleases() -> None:
    assert parse_stable_tag("v5.11.2") == (5, 11, 2)
    assert parse_stable_tag("v5.12.0-alpha.1") is None
    assert parse_stable_tag("nightly") is None


def test_generated_navigation_is_hierarchical() -> None:
    inventory = load_source_inventory(ROOT)
    generated_root = ROOT / "generated" / "maa-framework"
    version_root = generated_root / inventory.version

    assert (generated_root / "index.md").is_file()
    assert (version_root / "index.md").is_file()
    assert (version_root / "documentation" / "index.md").is_file()
    assert (version_root / "bindings" / "python.md").is_file()
    assert (version_root / "bindings" / "nodejs.md").is_file()
    assert (version_root / "native-api" / "framework.md").is_file()
    assert (version_root / "schemas.md").is_file()
    assert (version_root / "documentation" / "diagrams.md").is_file()
    assert not (generated_root / f"{inventory.version}.md").exists()


def test_current_inventory_has_historical_manifest() -> None:
    inventory = load_source_inventory(ROOT)
    inventory_path = (
        ROOT / "sources" / "maa-framework" / "inventories" / f"{inventory.version}.yaml"
    )
    assert inventory_path.is_file()
    assert len(load_source_inventories(ROOT)) >= 2


def test_external_bindings_have_independent_versioned_indexes() -> None:
    go_releases = load_release_catalog(ROOT, "maa-framework-go")
    rust_releases = load_release_catalog(ROOT, "maa-framework-rs")

    for source_id, releases in (
        ("maa-framework-go", go_releases),
        ("maa-framework-rs", rust_releases),
    ):
        latest = releases.releases[-1]
        assert (ROOT / "generated" / source_id / "index.md").is_file()
        assert (ROOT / "generated" / source_id / latest.version / "api.md").is_file()
        assert len(load_source_inventories(ROOT, source_id)) == len(releases.releases)

    go_latest = go_releases.releases[-1]
    go_api = (ROOT / "generated" / "maa-framework-go" / go_latest.version / "api.md").read_text(
        encoding="utf-8"
    )
    assert f"https://pkg.go.dev/github.com/MaaXYZ/maa-framework-go/v3@{go_latest.tag}" in go_api
    assert (
        f"https://pkg.go.dev/github.com/MaaXYZ/maa-framework-go/v3/controller/adb@{go_latest.tag}"
        in go_api
    )


def test_binding_compatibility_is_evidence_backed_or_unknown() -> None:
    catalog = load_binding_compatibility(ROOT)

    assert {item.source_id for item in catalog.bindings} == {
        "maa-framework-go",
        "maa-framework-rs",
    }
    for item in catalog.bindings:
        if item.framework_version is None:
            assert item.status.value == "unknown"
            assert item.evidence_paths == []
        else:
            assert item.status.value in {"declared", "verified"}
            assert item.evidence_paths


def test_catalog_bundle_is_self_describing_and_integrity_checked(tmp_path: Path) -> None:
    output = tmp_path / "catalog.zip"
    manifest = build_catalog_bundle(root=ROOT, output=output, allow_dirty=True)

    with ZipFile(output) as archive:
        bundled = CatalogBundleManifest.model_validate_json(archive.read("catalog-manifest.json"))
        assert bundled == manifest
        assert {source.source_id for source in bundled.sources} == {
            "maafw",
            "maa-framework-go",
            "maa-framework-rs",
        }
        for record in bundled.files:
            content = archive.read(record.path)
            assert len(content) == record.size_bytes
            assert hashlib.sha256(content).hexdigest() == record.sha256
