import hashlib
import re
from pathlib import Path
from zipfile import ZipFile

from maa_llm_wiki.bindings import BINDING_SPECS
from maa_llm_wiki.bundle import build_catalog_bundle
from maa_llm_wiki.inventory import parse_stable_tag
from maa_llm_wiki.models import CatalogBundleManifest
from maa_llm_wiki.validation import (
    load_binding_compatibility,
    load_machine_changes,
    load_release_catalog,
    load_source_inventories,
    load_source_inventory,
    validate_repository,
)

ROOT = Path(__file__).parents[1]


def test_repository_content_is_valid() -> None:
    assert validate_repository(ROOT) == []


def _recorded(kind: str, symbol: str) -> dict[str, str]:
    """Release -> change for one element of the committed machine catalog."""
    return {
        change.version: change.change
        for change in load_machine_changes(ROOT).changes
        if change.kind.value == kind and change.symbol == symbol
    }


def test_machine_catalog_records_known_upstream_changes() -> None:
    # Facts checked by hand against the MaaFramework tags; each one was missing or misdated in an
    # earlier extractor.
    assert _recorded("public-function", "MaaLinuxControllerCreate") == {"5.13.0": "added"}
    assert _recorded("public-function", "MaaKWinControllerCreate").get("5.13.0") == "deprecated"
    assert _recorded("constant", "MaaWin32InputMethod_Interception") == {"5.12.1": "added"}
    assert _recorded("schema-definition", "$defs.Shell").get("5.2.1") == "added"
    assert _recorded("binding-api", "maa.controller:Controller.post_shell").get("5.2.1") == "added"
    assert "5.5.0" not in _recorded("binding-api", "maa.context:Context.override_pipeline")
    kwin_python = _recorded("binding-api", "maa.controller:KWinController.__init__")
    assert kwin_python.get("5.13.0") == "deprecated"
    assert _recorded("schema-branch", "$defs.ActionV1.anyOf[#/$defs/ShellV1]") == {"5.2.1": "added"}


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


def _go_module_path(tag: str) -> str:
    major = int(tag.removeprefix("v").split(".", 1)[0])
    return "github.com/MaaXYZ/maa-framework-go" + (f"/v{major}" if major >= 2 else "")


def test_external_bindings_have_independent_versioned_indexes() -> None:
    go_releases = load_release_catalog(ROOT, "maa-framework-go")
    rust_releases = load_release_catalog(ROOT, "maa-framework-rs")
    csharp_releases = load_release_catalog(ROOT, "maa-framework-csharp")

    for source_id, releases in (
        ("maa-framework-go", go_releases),
        ("maa-framework-rs", rust_releases),
        ("maa-framework-csharp", csharp_releases),
    ):
        latest = releases.releases[-1]
        assert (ROOT / "generated" / source_id / "index.md").is_file()
        assert (ROOT / "generated" / source_id / latest.version / "api.md").is_file()
        assert len(load_source_inventories(ROOT, source_id)) == len(releases.releases)

    go_latest = go_releases.releases[-1]
    go_api = (ROOT / "generated" / "maa-framework-go" / go_latest.version / "api.md").read_text(
        encoding="utf-8"
    )
    go_module = _go_module_path(go_latest.tag)
    assert f"https://pkg.go.dev/{go_module}@{go_latest.tag}" in go_api
    assert f"https://pkg.go.dev/{go_module}/controller/adb@{go_latest.tag}" in go_api


def test_binding_compatibility_is_evidence_backed_or_unknown() -> None:
    catalog = load_binding_compatibility(ROOT)

    assert {item.source_id for item in catalog.bindings} == set(BINDING_SPECS)
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
        assert {source.source_id for source in bundled.sources} == {"maafw", *BINDING_SPECS}
        bundled_paths = {record.path for record in bundled.files}
        for name in (
            "START-HERE.md",
            "README.md",
            "CATALOG-CONTRACT.md",
            "LICENSE",
            "LICENSE-DATA",
            "NOTICE",
            "docs/operations.md",
            "docs/operations.zh.md",
        ):
            assert name in bundled_paths, f"bundle should carry {name}"
        for record in bundled.files:
            content = archive.read(record.path)
            assert len(content) == record.size_bytes
            assert hashlib.sha256(content).hexdigest() == record.sha256


def test_bundle_readme_links_resolve_inside_the_bundle(tmp_path: Path) -> None:
    output = tmp_path / "catalog.zip"
    manifest = build_catalog_bundle(root=ROOT, output=output, allow_dirty=True)
    bundled_paths = {record.path for record in manifest.files}

    missing: list[str] = []
    for name in ("README.md", "README.en.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            if target not in bundled_paths:
                missing.append(f"{name} -> {target}")
    assert missing == []
