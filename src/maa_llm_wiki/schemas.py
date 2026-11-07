from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from .models import (
    BindingCompatibilityCatalog,
    CatalogBundleManifest,
    MachineChangeCatalog,
    ReleaseCatalog,
    RepositoryCatalog,
    SourceInventory,
    SourceMap,
    UpstreamCommitCatalog,
)

SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "binding-compatibility-catalog.schema.json": BindingCompatibilityCatalog,
    "catalog-bundle-manifest.schema.json": CatalogBundleManifest,
    "machine-change-catalog.schema.json": MachineChangeCatalog,
    "release-catalog.schema.json": ReleaseCatalog,
    "repository-catalog.schema.json": RepositoryCatalog,
    "source-inventory.schema.json": SourceInventory,
    "source-map.schema.json": SourceMap,
    "upstream-commit-catalog.schema.json": UpstreamCommitCatalog,
}


def generate_schemas(root: Path) -> None:
    output = root / "schemas"
    output.mkdir(parents=True, exist_ok=True)
    for filename, model in SCHEMA_MODELS.items():
        content = json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2)
        (output / filename).write_text(content + "\n", encoding="utf-8", newline="\n")
