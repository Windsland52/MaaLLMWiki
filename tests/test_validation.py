from __future__ import annotations

import shutil
from pathlib import Path

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
