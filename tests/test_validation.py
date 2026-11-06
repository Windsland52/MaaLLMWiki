from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, cast

import pytest

from maa_llm_wiki.validation import validate_repository

REPO = Path(__file__).parents[1]


@pytest.fixture(scope="session")
def catalog_copy(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One pristine copy of the catalog data, reused by every mutation test."""
    target = tmp_path_factory.mktemp("catalog")
    for directory in ("sources", "generated", "schemas"):
        shutil.copytree(REPO / directory, target / directory)
    return target


def _append_line(path: Path, text: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + text + "\n", encoding="utf-8", newline="\n")


def test_pristine_catalog_is_valid(catalog_copy: Path) -> None:
    assert validate_repository(catalog_copy) == []


def test_tampered_generated_pages_are_detected(catalog_copy: Path) -> None:
    version_root = catalog_copy / "generated" / "maa-framework" / "5.15.0"
    page = version_root / "documentation" / "zh-cn.md"
    release_index = catalog_copy / "generated" / "maa-framework" / "index.md"
    stray_page = version_root / "notes.md"
    page_backup = page.read_text(encoding="utf-8")
    index_backup = release_index.read_text(encoding="utf-8")
    try:
        _append_line(page, "hand-written summary tail")
        _append_line(
            release_index, "- [9.9.9](./9.9.9/index.md) `0000000000000000000000000000000000000000`"
        )
        stray_page.write_text("# stray page\n", encoding="utf-8")
        errors = validate_repository(catalog_copy)
    finally:
        page.write_text(page_backup, encoding="utf-8", newline="\n")
        release_index.write_text(index_backup, encoding="utf-8", newline="\n")
        stray_page.unlink(missing_ok=True)

    joined = "\n".join(errors)
    assert (
        "generated page is stale: generated/maa-framework/5.15.0/documentation/zh-cn.md" in joined
    )
    assert "notes.md" in joined
    assert "not produced by the generator" in joined
    assert "MaaFramework release index is stale" in joined


def test_registry_and_schema_drift_is_detected(catalog_copy: Path) -> None:
    missing_inventory = catalog_copy / "sources" / "maa-framework" / "inventories" / "5.0.0.yaml"
    unregistered_dir = catalog_copy / "generated" / "maa-framework" / "9.9.9"
    schema = catalog_copy / "schemas" / "source-inventory.schema.json"
    default_inventory = catalog_copy / "sources" / "maa-framework" / "inventory.yaml"
    default_backup = default_inventory.read_text(encoding="utf-8")
    try:
        missing_inventory.unlink()
        unregistered_dir.mkdir(parents=True)
        (unregistered_dir / "index.md").write_text("# bogus release\n", encoding="utf-8")
        _append_line(schema, "")
        default_inventory.write_text(
            default_backup.replace("title: ", "title: TAMPERED-", 1),
            encoding="utf-8",
            newline="\n",
        )
        errors = validate_repository(catalog_copy)
    finally:
        shutil.copy(
            REPO / "sources" / "maa-framework" / "inventories" / "5.0.0.yaml", missing_inventory
        )
        shutil.rmtree(unregistered_dir)
        shutil.copy(REPO / "schemas" / "source-inventory.schema.json", schema)
        default_inventory.write_text(default_backup, encoding="utf-8", newline="\n")

    joined = "\n".join(errors)
    assert "MaaFramework inventory is missing release: 5.0.0" in joined
    assert "generated directory is not a registered release: 9.9.9" in joined
    assert "generated JSON schema is stale: schemas/source-inventory.schema.json" in joined
    assert "MaaFramework default inventory disagrees with inventories/5.15.0.yaml" in joined


def test_unproduced_binding_page_is_rejected(catalog_copy: Path) -> None:
    stray = catalog_copy / "generated" / "maa-framework-go" / "4.0.0" / "notes.md"
    stray.write_text("# stray page\n", encoding="utf-8")
    try:
        errors = validate_repository(catalog_copy)
    finally:
        stray.unlink(missing_ok=True)

    assert any("not produced by the generator" in error for error in errors)


def test_stale_binding_page_is_detected(catalog_copy: Path) -> None:
    page = catalog_copy / "generated" / "maa-framework-rs" / "1.27.0" / "api.md"
    backup = page.read_text(encoding="utf-8")
    try:
        _append_line(page, "- **ghost.rs**: invented entry.")
        errors = validate_repository(catalog_copy)
    finally:
        page.write_text(backup, encoding="utf-8", newline="\n")

    assert any("maa-framework-rs" in error and "stale" in error for error in errors)


def test_stray_files_are_rejected(catalog_copy: Path) -> None:
    strays = [
        catalog_copy / "sources" / "stray.yaml",
        catalog_copy / "sources" / "compatibility" / "extra.yaml",
        catalog_copy / "generated" / "maa-framework" / "stray.md",
        catalog_copy / "generated" / "maa-framework-go" / "stray.bin",
    ]
    for path in strays:
        path.write_text("stray\n", encoding="utf-8")
    try:
        errors = validate_repository(catalog_copy)
    finally:
        for path in strays:
            path.unlink(missing_ok=True)

    joined = "\n".join(errors)
    assert "unexpected file under sources/: sources/stray.yaml" in joined
    assert "unexpected file under sources/: sources/compatibility/extra.yaml" in joined
    assert "unexpected file under generated/maa-framework/: stray.md" in joined
    assert "unexpected file under generated/maa-framework-go/: stray.bin" in joined


def test_orphan_inventory_and_compatibility_entry_are_rejected(catalog_copy: Path) -> None:
    orphan = catalog_copy / "sources" / "maa-framework" / "inventories" / "9.9.9.yaml"
    compatibility = catalog_copy / "sources" / "compatibility" / "bindings.yaml"
    compatibility_backup = compatibility.read_text(encoding="utf-8")
    try:
        shutil.copy(REPO / "sources" / "maa-framework" / "inventories" / "5.15.0.yaml", orphan)
        compatibility.write_text(
            compatibility_backup
            + "- source_id: maa-framework-go\n"
            + "  binding_version: 9.9.9\n"
            + "  binding_revision: "
            + "a" * 40
            + "\n"
            + "  framework_version: 5.15.0\n"
            + "  status: declared\n"
            + "  evidence_paths:\n"
            + "  - README.md\n"
            + "  note: synthetic entry\n",
            encoding="utf-8",
            newline="\n",
        )
        errors = validate_repository(catalog_copy)
    finally:
        orphan.unlink(missing_ok=True)
        compatibility.write_text(compatibility_backup, encoding="utf-8", newline="\n")

    joined = "\n".join(errors)
    assert "sources/maa-framework/inventories/9.9.9.yaml" in joined
    assert "compatibility is not a registered release: 9.9.9" in joined


def _machine_catalog(catalog_copy: Path) -> Path:
    return catalog_copy / "sources" / "maa-framework" / "machine-changes.yaml"


def test_machine_change_invariants_are_enforced(catalog_copy: Path) -> None:
    import yaml

    path = _machine_catalog(catalog_copy)
    original = path.read_text(encoding="utf-8")
    payload = cast(dict[str, Any], yaml.safe_load(original))
    changes = payload["changes"]
    assert changes, "the machine catalog should not be empty once the extractor has run"
    try:
        payload["changes"] = [
            {
                **changes[0],
                "version": "9.9.9",
            },
            {
                **changes[0],
                "commit": "a" * 40,
            },
            {
                **changes[0],
                "paths": ["docs/zh_cn/does-not-exist.md"],
            },
        ]
        path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
            newline="\n",
        )
        errors = validate_repository(catalog_copy)
    finally:
        path.write_text(original, encoding="utf-8", newline="\n")

    joined = "\n".join(errors)
    assert "machine change references unknown release: 9.9.9" in joined
    assert "machine change revision does not match release" in joined
    assert "machine change references an unindexed path" in joined


def test_stale_machine_change_page_is_detected(catalog_copy: Path) -> None:
    page = catalog_copy / "generated" / "maa-framework" / "machine-changes.md"
    backup = page.read_text(encoding="utf-8")
    try:
        _append_line(page, "hand-written line")
        errors = validate_repository(catalog_copy)
    finally:
        page.write_text(backup, encoding="utf-8", newline="\n")

    assert any("machine change catalog is stale" in error for error in errors)
