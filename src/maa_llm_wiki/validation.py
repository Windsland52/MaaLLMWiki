from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import yaml
from pydantic import ValidationError

from .models import (
    BindingCompatibility,
    BindingCompatibilityCatalog,
    MachineChangeCatalog,
    ReleaseCatalog,
    RepositoryCatalog,
    RepositorySource,
    SemanticChangeCatalog,
    SourceInventory,
    SourceMap,
)
from .schemas import SCHEMA_MODELS

_MAAFW_DIRECTORY = "maa-framework"
_MAAFW_DISPLAY_NAME = "MaaFramework"
_MAAFW_GENERATOR = "maa-wiki-sync-maafw-history"
_BINDINGS_GENERATOR = "maa-wiki-sync-bindings-history"
_GO_SOURCE_ID = "maa-framework-go"
_CSHARP_SOURCE_ID = "maa-framework-csharp"
_PACKAGE_SECTION_HEADINGS = frozenset(
    {
        "## Package documentation",
        "## Source files",
        "## Go API documentation",
        "## NuGet packages",
    }
)
_PACKAGE_REGISTRY_MARKERS = ("pkg.go.dev", "nuget.org")


_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def _load_yaml(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.load(handle, Loader=_YAML_LOADER)


def load_repository_catalog(root: Path) -> RepositoryCatalog:
    return RepositoryCatalog.model_validate(_load_yaml(root / "sources" / "repositories.yaml"))


def _source_directory(source_id: str) -> str:
    return _MAAFW_DIRECTORY if source_id == "maafw" else source_id


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


def load_machine_changes(root: Path) -> MachineChangeCatalog:
    return MachineChangeCatalog.model_validate(
        _load_yaml(root / "sources" / "maa-framework" / "machine-changes.yaml")
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


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


# --------------------------------------------------------------------------------------
# Generated navigation
# --------------------------------------------------------------------------------------


def _non_blank_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def _strip_package_sections(text: str) -> list[str]:
    """Drop sections whose links need a live checkout, keeping everything deterministic."""
    lines: list[str] = []
    for line in _non_blank_lines(text):
        if line in _PACKAGE_SECTION_HEADINGS:
            continue
        if any(marker in line for marker in _PACKAGE_REGISTRY_MARKERS):
            continue
        lines.append(line)
    return lines


def _generated_directories(generated_root: Path) -> set[str]:
    if not generated_root.is_dir():
        return set()
    return {path.name for path in generated_root.iterdir() if path.is_dir()}


def _check_page_set(
    version_root: Path,
    expected_names: set[str],
    *,
    label: str,
    errors: list[str],
) -> None:
    on_disk = {
        path.relative_to(version_root).as_posix()
        for path in version_root.rglob("*")
        if path.is_file()
    }
    for missing in sorted(expected_names - on_disk):
        errors.append(f"{label} generated page is missing: {version_root.name}/{missing}")
    for unexpected in sorted(on_disk - expected_names):
        errors.append(
            f"{label} generated page is not produced by the generator: "
            f"{version_root.name}/{unexpected}"
        )


def _public_path(path: Path) -> str:
    parts = path.parts
    if "generated" in parts:
        return "/".join(parts[parts.index("generated") :])
    if "schemas" in parts:
        return "/".join(parts[parts.index("schemas") :])
    return path.as_posix()


def _check_page(
    path: Path,
    expected: str,
    *,
    label: str,
    errors: list[str],
    description: str = "generated page",
) -> None:
    if not path.is_file():
        return
    if path.read_text(encoding="utf-8") != expected:
        errors.append(f"{label} {description} is stale: {_public_path(path)}")


def _check_line_page(
    path: Path,
    expected: str,
    *,
    label: str,
    errors: list[str],
) -> None:
    if not path.is_file():
        return
    if _strip_package_sections(path.read_text(encoding="utf-8")) != _strip_package_sections(
        expected
    ):
        errors.append(f"{label} generated page is stale: {_public_path(path)}")


def _check_registered_directories(
    root: Path,
    source_id: str,
    versions: set[str],
    *,
    label: str,
    errors: list[str],
) -> None:
    generated_root = root / "generated" / source_id
    present = _generated_directories(generated_root)
    for missing in sorted(versions - present):
        errors.append(f"{label} generated directory is missing: {missing}")
    for unexpected in sorted(present - versions):
        errors.append(f"{label} generated directory is not a registered release: {unexpected}")


def _check_maafw_generated(
    root: Path,
    inventories: list[SourceInventory],
    releases: ReleaseCatalog,
    source: RepositorySource,
    source_map: SourceMap,
    semantic_changes: SemanticChangeCatalog,
) -> list[str]:
    from .inventory import render_prereleases_page, render_release_index, render_version_indexes

    errors: list[str] = []
    generated_root = root / "generated" / _MAAFW_DIRECTORY
    if not generated_root.is_dir():
        return [f"MaaFramework generated directory is missing: generated/{_MAAFW_DIRECTORY}"]

    ordered = sorted(inventories, key=lambda item: _version_key(item.version))
    for index, inventory in enumerate(ordered):
        version_root = generated_root / inventory.version
        if not version_root.is_dir():
            continue
        previous = ordered[index - 1] if index > 0 else None
        rendered = render_version_indexes(inventory, source.url, previous=previous)
        _check_page_set(version_root, set(rendered), label="MaaFramework", errors=errors)
        for relative, expected in sorted(rendered.items()):
            _check_page(version_root / relative, expected, label="MaaFramework", errors=errors)

    _check_page(
        generated_root / "index.md",
        render_release_index(releases.releases, releases.prereleases),
        label="MaaFramework",
        description="release index",
        errors=errors,
    )
    _check_page(
        generated_root / "prereleases.md",
        render_prereleases_page(
            display_name=_MAAFW_DISPLAY_NAME,
            generator=_MAAFW_GENERATOR,
            repository_url=source.url,
            releases=releases.releases,
            prereleases=releases.prereleases,
        ),
        label="MaaFramework",
        description="prerelease registry",
        errors=errors,
    )
    from .topics import render_semantic_changes_page, render_topics_page

    latest_release = releases.releases[-1].version
    _check_page(
        generated_root / "topics.md",
        render_topics_page(
            source_map=source_map,
            repository_url=source.url,
            latest_release=latest_release,
        ),
        label="MaaFramework",
        description="topic routes",
        errors=errors,
    )
    _check_page(
        generated_root / "behaviour-changes.md",
        render_semantic_changes_page(
            source_id=releases.source_id,
            semantic_changes=semantic_changes,
            source_map=source_map,
            releases=releases,
            repository_url=source.url,
        ),
        label="MaaFramework",
        description="behaviour-change registry",
        errors=errors,
    )
    return errors


def _check_binding_generated(
    root: Path,
    source_id: str,
    inventories: list[SourceInventory],
    releases: ReleaseCatalog,
    source: RepositorySource,
    compatibility: dict[tuple[str, str], BindingCompatibility],
) -> list[str]:
    from .bindings import BINDING_SPECS, render_artifact_page, render_binding_version
    from .inventory import render_prereleases_page
    from .models import ArtifactKind

    spec = BINDING_SPECS[source_id]
    errors: list[str] = []
    generated_root = root / "generated" / source_id
    if not generated_root.is_dir():
        return [f"{source_id} generated directory is missing"]

    for inventory in inventories:
        version_root = generated_root / inventory.version
        if not version_root.is_dir():
            continue
        entry = compatibility.get((source_id, inventory.version))
        if entry is None:
            continue
        rendered_index = render_binding_version(spec, inventory, entry, source.url, [])
        deterministic = {
            "api.md": render_artifact_page(
                spec, inventory, source.url, ArtifactKind.BINDING_API, "Public binding API"
            ),
            "documentation.md": render_artifact_page(
                spec, inventory, source.url, ArtifactKind.DOCUMENTATION, "Documentation"
            ),
            "manifests.md": render_artifact_page(
                spec, inventory, source.url, ArtifactKind.PACKAGE_MANIFEST, "Package manifests"
            ),
        }
        expected_names = set(deterministic) | {"index.md"}
        if source_id in {_GO_SOURCE_ID, _CSHARP_SOURCE_ID}:
            # These indexes and API pages embed registry links derived from a live checkout.
            _check_page_set(version_root, expected_names, label=source_id, errors=errors)
            _check_line_page(
                version_root / "api.md",
                deterministic["api.md"],
                label=source_id,
                errors=errors,
            )
            _check_line_page(
                version_root / "index.md",
                rendered_index["index.md"],
                label=source_id,
                errors=errors,
            )
            for name in ("documentation.md", "manifests.md"):
                _check_page(
                    version_root / name, deterministic[name], label=source_id, errors=errors
                )
        else:
            deterministic["index.md"] = rendered_index["index.md"]
            _check_page_set(version_root, expected_names, label=source_id, errors=errors)
            for name, expected in sorted(deterministic.items()):
                _check_page(version_root / name, expected, label=source_id, errors=errors)

    _check_page(
        generated_root / "prereleases.md",
        render_prereleases_page(
            display_name=spec.display_name,
            generator=_BINDINGS_GENERATOR,
            repository_url=source.url,
            releases=releases.releases,
            prereleases=releases.prereleases,
        ),
        label=source_id,
        description="prerelease registry",
        errors=errors,
    )
    release_index = generated_root / "index.md"
    if not release_index.is_file():
        errors.append(f"{source_id} generated release index is missing")
    else:
        listed = set(release_index.read_text(encoding="utf-8").splitlines())
        for version in releases.releases:
            expected = f"- [{version.version}](./{version.version}/index.md) `{version.commit}`"
            if expected not in listed:
                errors.append(f"{source_id} generated release index is missing: {version.version}")
    return errors


# --------------------------------------------------------------------------------------
# Registries, manifests, hand-authored catalogs, schemas
# --------------------------------------------------------------------------------------


def _check_inventory_blobs(
    inventories: list[SourceInventory],
    *,
    label: str,
    errors: list[str],
) -> None:
    """Every indexed artifact must carry the git blob id of the content it describes."""
    missing = [
        f"{inventory.version}/{artifact.path}"
        for inventory in inventories
        for artifact in inventory.artifacts
        if artifact.blob is None
    ]
    for item in missing[:10]:
        errors.append(f"{label} inventory artifact has no blob id: {item}")
    if len(missing) > 10:
        errors.append(f"{label} inventory has {len(missing) - 10} more artifacts without a blob id")


def _check_sources_layout(
    root: Path,
    repositories: RepositoryCatalog,
    catalogs: dict[str, ReleaseCatalog],
    errors: list[str],
) -> None:
    """sources/ may only contain the files the catalog publishes."""
    sources_root = root / "sources"
    if not sources_root.is_dir():
        errors.append("sources directory is missing")
        return
    allowed = {"sources/repositories.yaml", "sources/compatibility/bindings.yaml"}
    for repository in repositories.repositories:
        directory = _source_directory(repository.id)
        prefix = f"sources/{directory}"
        allowed.add(f"{prefix}/releases.yaml")
        allowed.add(f"{prefix}/inventory.yaml")
        catalog = catalogs.get(repository.id)
        if catalog is not None:
            for release in catalog.releases:
                allowed.add(f"{prefix}/inventories/{release.version}.yaml")
        if directory == _MAAFW_DIRECTORY:
            allowed.add(f"{prefix}/source-map.yaml")
            allowed.add(f"{prefix}/semantic-changes.yaml")
            allowed.add(f"{prefix}/machine-changes.yaml")
    for path in sorted(p for p in sources_root.rglob("*") if p.is_file()):
        relative = f"sources/{path.relative_to(sources_root).as_posix()}"
        if relative not in allowed:
            errors.append(f"unexpected file under sources/: {relative}")


def _check_generated_layout(
    root: Path,
    top_level_files: dict[str, set[str]],
    errors: list[str],
) -> None:
    """generated/<source>/ may only contain registered version directories and known pages."""
    for directory, allowed in top_level_files.items():
        generated_root = root / "generated" / directory
        if not generated_root.is_dir():
            errors.append(f"generated directory is missing: generated/{directory}")
            continue
        for entry in sorted(generated_root.iterdir()):
            if entry.is_dir():
                continue
            if entry.name not in allowed:
                errors.append(f"unexpected file under generated/{directory}/: {entry.name}")


def _check_compatibility_registry(
    compatibility: BindingCompatibilityCatalog,
    binding_catalogs: dict[str, ReleaseCatalog],
    errors: list[str],
) -> None:
    for entry in compatibility.bindings:
        catalog = binding_catalogs.get(entry.source_id)
        if catalog is None:
            errors.append(f"compatibility references unknown binding source: {entry.source_id}")
            continue
        if entry.binding_version not in {release.version for release in catalog.releases}:
            errors.append(
                f"{entry.source_id} compatibility is not a registered release: "
                f"{entry.binding_version}"
            )


def _check_machine_changes(
    root: Path,
    catalog: MachineChangeCatalog,
    releases: ReleaseCatalog,
    inventories: list[SourceInventory],
    source: RepositorySource,
    errors: list[str],
) -> None:
    """The machine catalog is generated: its facts and its page must match the renderer."""
    release_commits = {release.version: release.commit for release in releases.releases}
    ordered = sorted(inventories, key=lambda item: _version_key(item.version))
    previous_by_version: dict[str, set[str]] = {}
    for index, inventory in enumerate(ordered):
        paths = {artifact.path for artifact in inventory.artifacts}
        if index > 0:
            paths |= {artifact.path for artifact in ordered[index - 1].artifacts}
        previous_by_version[inventory.version] = paths

    for change in catalog.changes:
        expected_commit = release_commits.get(change.version)
        if expected_commit is None:
            errors.append(f"machine change references unknown release: {change.version}")
            continue
        if change.commit != expected_commit:
            errors.append(
                f"machine change revision does not match release {change.version}: "
                f"{change.kind} {change.symbol}"
            )
        indexed = previous_by_version.get(change.version, set())
        for path in change.paths:
            if path not in indexed:
                errors.append(
                    f"machine change references an unindexed path: {change.version}/{path}"
                )

    from .extract import render_machine_changes_page

    _check_page(
        root / "generated" / "maa-framework" / "machine-changes.md",
        render_machine_changes_page(catalog, source.url),
        label="MaaFramework",
        description="machine change catalog",
        errors=errors,
    )


def _check_release_registry(
    releases: ReleaseCatalog,
    historical: list[SourceInventory],
    current: SourceInventory,
    *,
    label: str,
    errors: list[str],
) -> None:
    registered = {release.version for release in releases.releases}
    committed = {inventory.version for inventory in historical}
    for missing in sorted(registered - committed, key=_version_key):
        errors.append(f"{label} inventory is missing release: {missing}")
    for unexpected in sorted(committed - registered, key=_version_key):
        errors.append(f"{label} inventory is not a registered release: {unexpected}")
    latest = releases.releases[-1].version
    if current.version != latest:
        errors.append(f"{label} default inventory is not the latest release: {current.version}")
    matching = next((inventory for inventory in historical if inventory.version == latest), None)
    if matching is not None and matching.model_dump(mode="json") != current.model_dump(mode="json"):
        errors.append(f"{label} default inventory disagrees with inventories/{latest}.yaml")


def _check_schemas(root: Path) -> list[str]:
    schema_root = root / "schemas"
    if not schema_root.is_dir():
        return ["generated JSON schema directory is missing: schemas/"]
    errors: list[str] = []
    expected = {
        filename: json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
        for filename, model in SCHEMA_MODELS.items()
    }
    present = {path.name for path in schema_root.iterdir() if path.is_file()}
    for missing in sorted(set(expected) - present):
        errors.append(f"generated JSON schema is missing: schemas/{missing}")
    for unexpected in sorted(present - set(expected)):
        errors.append(f"JSON schema is not produced by the generator: schemas/{unexpected}")
    for filename, content in sorted(expected.items()):
        path = schema_root / filename
        if path.is_file() and path.read_text(encoding="utf-8") != content:
            errors.append(f"generated JSON schema is stale: schemas/{filename}")
    return errors


def _check_source_map(
    source_map: SourceMap,
    release_commits: dict[str, str],
    repository_ids: set[str],
) -> list[str]:
    errors: list[str] = []
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
    return errors


def _check_semantic_changes(
    semantic_changes: SemanticChangeCatalog,
    source_map: SourceMap,
    release_commits: dict[str, str],
    inventory_paths: set[str],
    repository_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    if semantic_changes.source_id not in repository_ids:
        errors.append(
            f"semantic-change catalog references unknown source: {semantic_changes.source_id}"
        )
    topic_ids = {topic.id for topic in source_map.topics}
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
        return [f"release catalog references unknown source: {releases.source_id}"]
    if inventory.source_id not in repository_ids:
        return [f"source inventory references unknown source: {inventory.source_id}"]
    maafw_source = repositories_by_id[inventory.source_id]
    if maafw_source.default_revision != inventory.revision:
        errors.append("source inventory revision does not match repository default revision")

    release_commits = {release.version: release.commit for release in releases.releases}
    from .bindings import BINDING_SPECS

    _check_release_registry(
        releases,
        historical_inventories,
        inventory,
        label="MaaFramework",
        errors=errors,
    )
    _check_registered_directories(
        root,
        _MAAFW_DIRECTORY,
        set(release_commits),
        label="MaaFramework",
        errors=errors,
    )
    _check_inventory_blobs(historical_inventories, label="MaaFramework", errors=errors)
    errors.extend(
        _check_maafw_generated(
            root,
            historical_inventories,
            releases,
            maafw_source,
            source_map,
            semantic_changes,
        )
    )

    compatibility_by_key = {
        (item.source_id, item.binding_version): item for item in binding_compatibility.bindings
    }
    binding_catalogs: dict[str, ReleaseCatalog] = {}
    for binding_source_id in BINDING_SPECS:
        try:
            binding_releases = load_release_catalog(root, binding_source_id)
            binding_inventory = load_source_inventory(root, binding_source_id)
            binding_inventories = load_source_inventories(root, binding_source_id)
        except (OSError, ValueError, ValidationError, yaml.YAMLError) as error:
            errors.append(f"{binding_source_id}: {error}")
            continue
        binding_catalogs[binding_source_id] = binding_releases
        binding_source = repositories_by_id.get(binding_source_id)
        if binding_source is None:
            errors.append(f"binding release catalog references unknown source: {binding_source_id}")
            continue
        if binding_releases.source_id != binding_source_id:
            errors.append(f"{binding_source_id} release catalog has mismatched source ID")
        if binding_source.default_revision != binding_inventory.revision:
            errors.append(f"{binding_source_id} default revision does not match current inventory")
        if binding_inventory.source_id != binding_source_id:
            errors.append(f"{binding_source_id} current inventory has mismatched source ID")
        _check_release_registry(
            binding_releases,
            binding_inventories,
            binding_inventory,
            label=binding_source_id,
            errors=errors,
        )
        _check_registered_directories(
            root,
            binding_source_id,
            {release.version for release in binding_releases.releases},
            label=binding_source_id,
            errors=errors,
        )
        _check_inventory_blobs(binding_inventories, label=binding_source_id, errors=errors)
        errors.extend(
            _check_binding_generated(
                root,
                binding_source_id,
                binding_inventories,
                binding_releases,
                binding_source,
                compatibility_by_key,
            )
        )
        for release in binding_releases.releases:
            compatibility = compatibility_by_key.get((binding_source_id, release.version))
            if compatibility is None:
                errors.append(f"{binding_source_id} compatibility is missing: {release.version}")
                continue
            if compatibility.binding_revision != release.commit:
                errors.append(
                    f"{binding_source_id} compatibility revision differs: {release.version}"
                )
                continue
            inventory_paths = {
                artifact.path
                for historical in binding_inventories
                if historical.version == release.version
                for artifact in historical.artifacts
            }
            for evidence_path in compatibility.evidence_paths:
                if evidence_path not in inventory_paths:
                    errors.append(
                        f"{binding_source_id} compatibility evidence is not indexed: "
                        f"{release.version}/{evidence_path}"
                    )

    catalogs_by_source = {releases.source_id: releases, **binding_catalogs}
    _check_sources_layout(root, repositories, catalogs_by_source, errors)
    _check_generated_layout(
        root,
        {
            _MAAFW_DIRECTORY: {
                "index.md",
                "prereleases.md",
                "topics.md",
                "behaviour-changes.md",
                "machine-changes.md",
            },
            **{source_id: {"index.md", "prereleases.md"} for source_id in BINDING_SPECS},
        },
        errors=errors,
    )
    _check_compatibility_registry(binding_compatibility, binding_catalogs, errors=errors)
    try:
        machine_changes = load_machine_changes(root)
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as error:
        errors.append(f"machine-change catalog: {error}")
    else:
        _check_machine_changes(
            root,
            machine_changes,
            releases,
            historical_inventories,
            maafw_source,
            errors,
        )
    errors.extend(_check_source_map(source_map, release_commits, repository_ids))
    errors.extend(
        _check_semantic_changes(
            semantic_changes,
            source_map,
            release_commits,
            {
                path
                for historical in historical_inventories
                for path in (artifact.path for artifact in historical.artifacts)
            },
            repository_ids,
        )
    )
    errors.extend(_check_schemas(root))
    return errors
