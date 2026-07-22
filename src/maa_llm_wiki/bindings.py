from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import yaml

from .inventory import (
    discover_stable_releases,
    git_text,
    load_markdown,
    markdown_metadata,
    write_yaml,
)
from .models import (
    ArtifactKind,
    BindingCompatibility,
    BindingCompatibilityCatalog,
    CompatibilityStatus,
    ReleaseCatalog,
    ReleaseRecord,
    SourceArtifact,
    SourceInventory,
)
from .validation import load_repository_catalog


@dataclass(frozen=True)
class BindingSourceSpec:
    source_id: str
    display_name: str
    language: str


@dataclass(frozen=True)
class PackageDocumentation:
    label: str
    url: str


BINDING_SPECS = {
    "maa-framework-go": BindingSourceSpec(
        source_id="maa-framework-go",
        display_name="MaaFramework Go binding",
        language="Go",
    ),
    "maa-framework-rs": BindingSourceSpec(
        source_id="maa-framework-rs",
        display_name="MaaFramework Rust binding",
        language="Rust",
    ),
}


def _classify_binding_path(source_id: str, path: str) -> ArtifactKind | None:
    lowered = path.lower()
    if path in {"README.md", "README_zh.md", "CHANGELOG.md"}:
        return ArtifactKind.DOCUMENTATION
    if source_id == "maa-framework-go":
        if path == "go.mod":
            return ArtifactKind.PACKAGE_MANIFEST
        if lowered.endswith(".go") and not lowered.endswith("_test.go"):
            if "/" not in path or path.startswith("controller/"):
                return ArtifactKind.BINDING_API
        return None
    if path in {"Cargo.toml", "maa-framework/Cargo.toml", "maa-framework-sys/Cargo.toml"}:
        return ArtifactKind.PACKAGE_MANIFEST
    if lowered.endswith(".rs") and path.startswith(
        ("maa-framework/src/", "maa-framework-sys/src/")
    ):
        return ArtifactKind.BINDING_API
    return None


def _describe_binding_artifact(
    spec: BindingSourceSpec,
    path: str,
    kind: ArtifactKind,
    markdown: dict[str, str],
) -> tuple[str, str]:
    filename = PurePosixPath(path).name
    if kind is ArtifactKind.DOCUMENTATION:
        return markdown_metadata(markdown.get(path, ""), PurePosixPath(path).stem)
    if kind is ArtifactKind.PACKAGE_MANIFEST:
        return filename, f"Package and dependency metadata for the {spec.language} binding."
    module = PurePosixPath(path).stem
    return filename, f"Public {spec.language} binding declarations for the {module} module."


def discover_binding_artifacts(
    repository: Path,
    revision: str,
    spec: BindingSourceSpec,
) -> list[SourceArtifact]:
    git_text(repository, "cat-file", "-e", f"{revision}^{{commit}}")
    paths = git_text(repository, "ls-tree", "-r", "--name-only", revision).splitlines()
    classified = [
        (path, kind)
        for path in paths
        if (kind := _classify_binding_path(spec.source_id, path)) is not None
    ]
    markdown = load_markdown(
        repository,
        revision,
        [path for path, kind in classified if kind is ArtifactKind.DOCUMENTATION],
    )
    return sorted(
        [
            SourceArtifact(
                path=path,
                kind=kind,
                title=(details := _describe_binding_artifact(spec, path, kind, markdown))[0],
                summary=details[1],
            )
            for path, kind in classified
        ],
        key=lambda artifact: artifact.path,
    )


def _read_revision_file(repository: Path, revision: str, path: str) -> str | None:
    try:
        return git_text(repository, "show", f"{revision}:{path}")
    except subprocess.CalledProcessError:
        return None


def _go_package_documentation(
    repository: Path,
    revision: str,
    tag: str,
    inventory: SourceInventory,
) -> list[PackageDocumentation]:
    module = _read_revision_file(repository, revision, "go.mod")
    if module is None:
        return []
    match = re.search(r"(?m)^module\s+(?P<path>\S+)\s*$", module)
    if match is None:
        return []
    module_path = match["path"]
    package_dirs = sorted(
        {
            PurePosixPath(artifact.path).parent.as_posix()
            for artifact in inventory.artifacts
            if artifact.kind is ArtifactKind.BINDING_API
        }
    )
    links: list[PackageDocumentation] = []
    for package_dir in package_dirs:
        package_path = module_path if package_dir == "." else f"{module_path}/{package_dir}"
        encoded = quote(f"{package_path}@{tag}", safe="/@.")
        label = "root package" if package_dir == "." else package_dir
        links.append(PackageDocumentation(label=label, url=f"https://pkg.go.dev/{encoded}"))
    return links


def _binding_compatibility(
    repository: Path,
    release: ReleaseRecord,
    spec: BindingSourceSpec,
) -> BindingCompatibility:
    if spec.source_id == "maa-framework-go":
        for path in ("README.md", "README_zh.md"):
            content = _read_revision_file(repository, release.commit, path)
            if content is None:
                continue
            match = re.search(
                r"MaaFramework(?:/releases/tag/|-v)(?P<version>\d+\.\d+\.\d+)",
                content,
                flags=re.IGNORECASE,
            )
            if match is not None:
                version = match["version"]
                return BindingCompatibility(
                    source_id=spec.source_id,
                    binding_version=release.version,
                    binding_revision=release.commit,
                    framework_version=version,
                    status=CompatibilityStatus.DECLARED,
                    evidence_paths=[path],
                    note=f"The binding README explicitly references MaaFramework v{version}.",
                )
    else:
        content = _read_revision_file(repository, release.commit, "Cargo.toml")
        if content is not None:
            match = re.search(
                r"maa-framework-sys\s*=\s*\{[^}]*version\s*=\s*\"(?P<version>\d+\.\d+\.\d+)\"",
                content,
            )
            if match is not None:
                version = match["version"]
                return BindingCompatibility(
                    source_id=spec.source_id,
                    binding_version=release.version,
                    binding_revision=release.commit,
                    framework_version=version,
                    status=CompatibilityStatus.DECLARED,
                    evidence_paths=["Cargo.toml"],
                    note=(
                        "The workspace manifest declares this maa-framework-sys version; "
                        "runtime compatibility has not been independently verified."
                    ),
                )
    return BindingCompatibility(
        source_id=spec.source_id,
        binding_version=release.version,
        binding_revision=release.commit,
        framework_version=None,
        status=CompatibilityStatus.UNKNOWN,
        evidence_paths=[],
        note="No exact MaaFramework version declaration was found in indexed package metadata.",
    )


def _artifact_page(
    spec: BindingSourceSpec,
    inventory: SourceInventory,
    repository_url: str,
    kind: ArtifactKind,
    title: str,
    package_documentation: list[PackageDocumentation] | None = None,
) -> str:
    lines = [
        "<!-- Generated by maa-wiki-sync-bindings-history. Do not edit manually. -->",
        f"# {title}",
        "",
        f"{spec.display_name} `{inventory.version}` at `{inventory.revision}`.",
        "",
    ]
    if kind is ArtifactKind.BINDING_API and package_documentation:
        lines.extend(["## Package documentation", ""])
        lines.extend(f"- [{item.label}]({item.url})" for item in package_documentation)
        lines.extend(["", "## Source files", ""])
    for artifact in inventory.artifacts:
        if artifact.kind is not kind:
            continue
        encoded_path = quote(artifact.path, safe="/")
        url = f"{repository_url.rstrip('/')}/blob/{inventory.revision}/{encoded_path}"
        lines.append(f"- **{artifact.title}**: {artifact.summary} [`{artifact.path}`]({url})")
    return "\n".join(lines) + "\n"


def _render_binding_version(
    spec: BindingSourceSpec,
    inventory: SourceInventory,
    compatibility: BindingCompatibility,
    repository_url: str,
    package_documentation: list[PackageDocumentation],
) -> dict[str, str]:
    framework = compatibility.framework_version or "not declared"
    index_lines = [
        "<!-- Generated by maa-wiki-sync-bindings-history. Do not edit manually. -->",
        f"# {spec.display_name} {inventory.version}",
        "",
        f"Revision: `{inventory.revision}`",
        "",
        "## Compatibility",
        "",
        f"- Status: `{compatibility.status.value}`",
        f"- MaaFramework version: `{framework}`",
        f"- Basis: {compatibility.note}",
    ]
    if compatibility.evidence_paths:
        links: list[str] = []
        for path in compatibility.evidence_paths:
            encoded_path = quote(path, safe="/")
            url = f"{repository_url.rstrip('/')}/blob/{inventory.revision}/{encoded_path}"
            links.append(f"[`{path}`]({url})")
        index_lines.append(f"- Evidence: {', '.join(links)}")
    index_lines.extend(
        [
            "",
            "## Go API documentation" if package_documentation else "",
        ]
    )
    if package_documentation:
        package_link = package_documentation[0]
        index_lines.extend(
            [
                "",
                f"[Browse {package_link.label} on pkg.go.dev]({package_link.url})",
            ]
        )
    index_lines.extend(
        [
            "",
            "## Sources",
            "",
            "- [Public binding API](api.md)",
            "- [Documentation](documentation.md)",
            "- [Package manifests](manifests.md)",
        ]
    )
    index = "\n".join(index_lines)
    return {
        "index.md": index + "\n",
        "api.md": _artifact_page(
            spec,
            inventory,
            repository_url,
            ArtifactKind.BINDING_API,
            "Public binding API",
            package_documentation,
        ),
        "documentation.md": _artifact_page(
            spec, inventory, repository_url, ArtifactKind.DOCUMENTATION, "Documentation"
        ),
        "manifests.md": _artifact_page(
            spec, inventory, repository_url, ArtifactKind.PACKAGE_MANIFEST, "Package manifests"
        ),
    }


def _write_binding_indexes(
    root: Path,
    spec: BindingSourceSpec,
    inventory: SourceInventory,
    compatibility: BindingCompatibility,
    repository_url: str,
    releases: list[ReleaseRecord],
    package_documentation: list[PackageDocumentation],
) -> None:
    output_root = root / "generated" / spec.source_id
    version_root = output_root / inventory.version
    version_root.mkdir(parents=True, exist_ok=True)
    for path in version_root.glob("*.md"):
        path.unlink()
    for relative_path, content in _render_binding_version(
        spec, inventory, compatibility, repository_url, package_documentation
    ).items():
        (version_root / relative_path).write_text(content, encoding="utf-8", newline="\n")

    lines = [
        "<!-- Generated by maa-wiki-sync-bindings-history. Do not edit manually. -->",
        f"# {spec.display_name} source indexes",
        "",
        "Binding versions are independent from MaaFramework versions. Select compatibility "
        "from the evidence shown in each release index.",
        "",
        "## Releases",
        "",
    ]
    for release in reversed(releases):
        if (output_root / release.version / "index.md").is_file():
            lines.append(f"- [{release.version}](./{release.version}/index.md) `{release.commit}`")
    (output_root / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _load_compatibility(root: Path) -> BindingCompatibilityCatalog:
    path = root / "sources" / "compatibility" / "bindings.yaml"
    if not path.is_file():
        return BindingCompatibilityCatalog()
    with path.open("r", encoding="utf-8") as handle:
        return BindingCompatibilityCatalog.model_validate(yaml.safe_load(handle))


def sync_binding_history(
    *,
    root: Path,
    repository: Path,
    source_id: str,
) -> list[ReleaseRecord]:
    spec = BINDING_SPECS.get(source_id)
    if spec is None:
        raise ValueError(f"Unsupported binding source: {source_id}")
    repositories = load_repository_catalog(root)
    source = next((item for item in repositories.repositories if item.id == source_id), None)
    if source is None:
        raise ValueError(f"Unknown repository source: {source_id}")

    releases = discover_stable_releases(repository)
    source.default_revision = releases[-1].commit
    source_root = root / "sources" / source_id
    source_root.mkdir(parents=True, exist_ok=True)
    write_yaml(
        source_root / "releases.yaml",
        ReleaseCatalog(source_id=source_id, releases=releases).model_dump(mode="json"),
    )
    write_yaml(root / "sources" / "repositories.yaml", repositories.model_dump(mode="json"))

    catalog = _load_compatibility(root)
    catalog.bindings = [item for item in catalog.bindings if item.source_id != source_id]
    compatibilities: list[BindingCompatibility] = []
    for release in releases:
        inventory = SourceInventory(
            source_id=source_id,
            version=release.version,
            revision=release.commit,
            artifacts=discover_binding_artifacts(repository, release.commit, spec),
        )
        compatibility = _binding_compatibility(repository, release, spec)
        package_documentation = (
            _go_package_documentation(repository, release.commit, release.tag, inventory)
            if source_id == "maa-framework-go"
            else []
        )
        compatibilities.append(compatibility)
        inventory_root = source_root / "inventories"
        inventory_root.mkdir(parents=True, exist_ok=True)
        write_yaml(inventory_root / f"{release.version}.yaml", inventory.model_dump(mode="json"))
        if release == releases[-1]:
            write_yaml(source_root / "inventory.yaml", inventory.model_dump(mode="json"))
        _write_binding_indexes(
            root,
            spec,
            inventory,
            compatibility,
            source.url,
            releases,
            package_documentation,
        )

    catalog.bindings.extend(compatibilities)
    catalog.bindings.sort(key=lambda item: (item.source_id, item.binding_version))
    compatibility_path = root / "sources" / "compatibility" / "bindings.yaml"
    compatibility_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(compatibility_path, catalog.model_dump(mode="json"))
    return releases
