from __future__ import annotations

from pathlib import Path, PurePosixPath
from urllib.parse import quote

import yaml
from pydantic import ValidationError

from .models import (
    BindingCompatibilityCatalog,
    ReleaseCatalog,
    RepositoryCatalog,
    SemanticChangeCatalog,
    SourceInventory,
    SourceMap,
)


def _load_yaml(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_repository_catalog(root: Path) -> RepositoryCatalog:
    return RepositoryCatalog.model_validate(_load_yaml(root / "sources" / "repositories.yaml"))


def _source_directory(source_id: str) -> str:
    return "maa-framework" if source_id == "maafw" else source_id


def load_release_catalog(root: Path, source_id: str = "maafw") -> ReleaseCatalog:
    return ReleaseCatalog.model_validate(
        _load_yaml(root / "sources" / _source_directory(source_id) / "releases.yaml")
    )


def load_binding_compatibility(root: Path) -> BindingCompatibilityCatalog:
    return BindingCompatibilityCatalog.model_validate(
        _load_yaml(root / "sources" / "compatibility" / "bindings.yaml")
    )


def load_source_map(root: Path) -> SourceMap:
    return SourceMap.model_validate(
        _load_yaml(root / "sources" / "maa-framework" / "source-map.yaml")
    )


def load_semantic_changes(root: Path) -> SemanticChangeCatalog:
    return SemanticChangeCatalog.model_validate(
        _load_yaml(root / "sources" / "maa-framework" / "semantic-changes.yaml")
    )


def load_source_inventory(root: Path, source_id: str = "maafw") -> SourceInventory:
    return SourceInventory.model_validate(
        _load_yaml(root / "sources" / _source_directory(source_id) / "inventory.yaml")
    )


def load_source_inventories(root: Path, source_id: str = "maafw") -> list[SourceInventory]:
    inventory_root = root / "sources" / _source_directory(source_id) / "inventories"
    return [
        SourceInventory.model_validate(_load_yaml(path))
        for path in sorted(inventory_root.glob("*.yaml"))
    ]


def validate_repository(root: Path) -> list[str]:
    errors: list[str] = []
    try:
        repositories = load_repository_catalog(root)
        releases = load_release_catalog(root)
        source_map = load_source_map(root)
        semantic_changes = load_semantic_changes(root)
        inventory = load_source_inventory(root)
        historical_inventories = load_source_inventories(root)
        binding_compatibility = load_binding_compatibility(root)
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as error:
        return [f"catalog: {error}"]

    repositories_by_id = {repository.id: repository for repository in repositories.repositories}
    repository_ids = set(repositories_by_id)
    if releases.source_id not in repository_ids:
        errors.append(f"release catalog references unknown source: {releases.source_id}")
    if semantic_changes.source_id not in repository_ids:
        errors.append(
            f"semantic-change catalog references unknown source: {semantic_changes.source_id}"
        )
    if inventory.source_id not in repository_ids:
        errors.append(f"source inventory references unknown source: {inventory.source_id}")
    elif repositories_by_id[inventory.source_id].default_revision != inventory.revision:
        errors.append("source inventory revision does not match repository default revision")

    release_commits = {release.version: release.commit for release in releases.releases}
    inventories_by_version = {item.version: item for item in historical_inventories}
    for release in releases.releases:
        historical = inventories_by_version.get(release.version)
        if historical is None:
            errors.append(f"source inventory is missing release: {release.version}")
            continue
        if historical.revision != release.commit:
            errors.append(f"source inventory revision does not match release: {release.version}")
        if not (root / "generated" / "maa-framework" / release.version / "index.md").is_file():
            errors.append(f"generated index is missing release: {release.version}")
    inventory_commit = release_commits.get(inventory.version)
    if inventory_commit is None:
        errors.append(f"source inventory references unknown release: {inventory.version}")
    elif inventory.revision != inventory_commit:
        errors.append(
            f"source inventory revision does not match release {inventory.version}: "
            f"{inventory.revision}"
        )

    generated_root = root / "generated" / "maa-framework"
    expected_index = generated_root / inventory.version / "index.md"
    if not expected_index.is_file():
        errors.append(f"generated inventory index is missing: {expected_index.relative_to(root)}")
    elif (source := repositories_by_id.get(inventory.source_id)) is not None:
        version_root = generated_root / inventory.version
        index_content = "\n".join(
            path.read_text(encoding="utf-8") for path in sorted(version_root.rglob("*.md"))
        )
        bullet_count = sum(line.startswith("- **") for line in index_content.splitlines())
        if bullet_count != len(inventory.artifacts):
            errors.append("generated inventory index artifact count does not match inventory")
        for artifact in inventory.artifacts:
            url = (
                f"{source.url.rstrip('/')}/blob/{inventory.revision}/"
                f"{quote(artifact.path, safe='/')}"
            )
            expected_link = f"[`{artifact.path}`]({url})"
            if expected_link not in index_content:
                errors.append(f"generated inventory index is missing artifact: {artifact.path}")
    release_index = generated_root / "index.md"
    if not release_index.is_file():
        errors.append(f"generated release index is missing: {release_index.relative_to(root)}")

    compatibility_by_key = {
        (item.source_id, item.binding_version): item for item in binding_compatibility.bindings
    }
    for binding_source_id in ("maa-framework-go", "maa-framework-rs"):
        try:
            binding_releases = load_release_catalog(root, binding_source_id)
            binding_inventory = load_source_inventory(root, binding_source_id)
            binding_inventories = load_source_inventories(root, binding_source_id)
        except (OSError, ValueError, ValidationError, yaml.YAMLError) as error:
            errors.append(f"{binding_source_id}: {error}")
            continue
        if binding_releases.source_id != binding_source_id:
            errors.append(f"{binding_source_id} release catalog has mismatched source ID")
        binding_source = repositories_by_id.get(binding_source_id)
        if binding_source is None:
            errors.append(f"binding release catalog references unknown source: {binding_source_id}")
            continue
        if binding_source.default_revision != binding_inventory.revision:
            errors.append(f"{binding_source_id} default revision does not match current inventory")
        if binding_inventory.source_id != binding_source_id:
            errors.append(f"{binding_source_id} current inventory has mismatched source ID")
        if binding_inventory.version != binding_releases.releases[-1].version:
            errors.append(f"{binding_source_id} current inventory is not the latest release")
        inventories_by_version = {item.version: item for item in binding_inventories}
        for release in binding_releases.releases:
            historical = inventories_by_version.get(release.version)
            if historical is None or historical.revision != release.commit:
                errors.append(
                    f"{binding_source_id} inventory is missing release: {release.version}"
                )
                continue
            version_root = root / "generated" / binding_source_id / release.version
            if not (version_root / "index.md").is_file():
                errors.append(f"{binding_source_id} generated index is missing: {release.version}")
            else:
                generated_content = "\n".join(
                    path.read_text(encoding="utf-8") for path in sorted(version_root.glob("*.md"))
                )
                bullet_count = sum(
                    line.startswith("- **") for line in generated_content.splitlines()
                )
                if bullet_count != len(historical.artifacts):
                    errors.append(
                        f"{binding_source_id} generated artifact count differs: {release.version}"
                    )
                for artifact in historical.artifacts:
                    url = (
                        f"{binding_source.url.rstrip('/')}/blob/{historical.revision}/"
                        f"{quote(artifact.path, safe='/')}"
                    )
                    if f"[`{artifact.path}`]({url})" not in generated_content:
                        errors.append(
                            f"{binding_source_id} generated artifact is missing: "
                            f"{release.version}/{artifact.path}"
                        )
            compatibility = compatibility_by_key.get((binding_source_id, release.version))
            if compatibility is None:
                errors.append(f"{binding_source_id} compatibility is missing: {release.version}")
            elif compatibility.binding_revision != release.commit:
                errors.append(
                    f"{binding_source_id} compatibility revision differs: {release.version}"
                )
            elif not set(compatibility.evidence_paths).issubset(
                {artifact.path for artifact in historical.artifacts}
            ):
                errors.append(
                    f"{binding_source_id} compatibility evidence is not indexed: {release.version}"
                )
        if not (root / "generated" / binding_source_id / "index.md").is_file():
            errors.append(f"{binding_source_id} generated release index is missing")

    for topic in source_map.topics:
        if topic.source_id not in repository_ids:
            errors.append(
                f"source-map topic {topic.id} references unknown source: {topic.source_id}"
            )
        for variant in topic.variants:
            expected_commit = release_commits.get(variant.applies_to)
            if expected_commit is None:
                errors.append(
                    f"source-map topic {topic.id} references unknown release: {variant.applies_to}"
                )
            elif variant.revision != expected_commit:
                errors.append(
                    f"source-map revision does not match release {variant.applies_to}: {topic.id}"
                )

    topic_ids = {topic.id for topic in source_map.topics}
    inventory_paths = {
        path
        for historical in historical_inventories
        for path in (artifact.path for artifact in historical.artifacts)
    }
    for change in semantic_changes.changes:
        if change.topic_id not in topic_ids:
            errors.append(f"semantic change references unknown topic: {change.topic_id}")
        expected_commit = release_commits.get(change.first_version)
        if expected_commit is None:
            errors.append(f"semantic change references unknown release: {change.first_version}")
        elif change.revision != expected_commit:
            errors.append(
                f"semantic change revision does not match release {change.first_version}: "
                f"{change.topic_id}"
            )
        for path in change.paths:
            suffix = PurePosixPath(path).suffix.lower()
            if suffix in {".md", ".json", ".h", ".hpp"} and path not in inventory_paths:
                errors.append(f"semantic change references uncatalogued artifact: {path}")
    return errors
