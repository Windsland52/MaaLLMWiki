from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import yaml

from .inventory import (
    discover_prereleases,
    discover_stable_releases,
    git_text,
    guard_registry_shrink,
    load_markdown,
    ls_tree_blobs,
    markdown_metadata,
    registered_release_versions,
    render_prereleases_page,
    resolve_included_in,
    write_yaml,
)
from .models import (
    ArtifactKind,
    BindingCompatibility,
    BindingCompatibilityCatalog,
    CompatibilityStatus,
    PrereleaseRecord,
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
    tag_major: int | None = None
    package_heading: str = "## Package documentation"
    package_registry: str | None = None


@dataclass(frozen=True)
class PackageDocumentation:
    label: str
    url: str


BINDING_SPECS = {
    "maa-framework-go": BindingSourceSpec(
        source_id="maa-framework-go",
        display_name="MaaFramework Go binding",
        language="Go",
        package_heading="## Go API documentation",
        package_registry="pkg.go.dev",
    ),
    "maa-framework-rs": BindingSourceSpec(
        source_id="maa-framework-rs",
        display_name="MaaFramework Rust binding",
        language="Rust",
        package_heading="## Crates",
        package_registry="docs.rs",
    ),
    "maa-framework-csharp": BindingSourceSpec(
        source_id="maa-framework-csharp",
        display_name="MaaFramework C# binding",
        language="C#",
        tag_major=5,
        package_heading="## NuGet packages",
        package_registry="nuget.org",
    ),
}


def _classify_binding_path(source_id: str, path: str) -> ArtifactKind | None:
    lowered = path.lower()
    if source_id == "maa-framework-csharp":
        if path.startswith(("sample/", "src/MaaFramework.Binding.UnitTests/")):
            return None
        name = PurePosixPath(path).name
        if (
            name.startswith("README")
            or path == "CHANGELOG.md"
            or (path.startswith("docs/") and lowered.endswith(".md"))
        ):
            return ArtifactKind.DOCUMENTATION
        if path.startswith("src/") and lowered.endswith(".cs"):
            return ArtifactKind.BINDING_API
        if path.startswith("src/") and lowered.endswith(".csproj"):
            return ArtifactKind.PACKAGE_MANIFEST
        if path in {"src/Directory.Build.props", "src/Directory.Packages.props"}:
            return ArtifactKind.PACKAGE_MANIFEST
        return None
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
    blobs = ls_tree_blobs(repository, revision)
    classified = [
        (path, blobs[path], kind)
        for path in blobs
        if (kind := _classify_binding_path(spec.source_id, path)) is not None
    ]
    markdown = load_markdown(
        repository,
        revision,
        [path for path, _blob, kind in classified if kind is ArtifactKind.DOCUMENTATION],
    )
    return sorted(
        [
            SourceArtifact(
                path=path,
                kind=kind,
                blob=blob,
                title=(details := _describe_binding_artifact(spec, path, kind, markdown))[0],
                summary=details[1],
            )
            for path, blob, kind in classified
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


RUST_WORKSPACE_MEMBERS_PATTERN = re.compile(r"(?m)^members\s*=\s*\[(?P<members>[^\]]*)\]")
RUST_CRATE_NAME_PATTERN = re.compile(r'"(?P<name>[A-Za-z0-9_-]+)"')


def _rust_package_documentation(
    repository: Path,
    revision: str,
    version: str,
    inventory: SourceInventory,
) -> list[PackageDocumentation]:
    """Link the workspace crates on docs.rs at the versions this release publishes."""
    manifest = _read_revision_file(repository, revision, "Cargo.toml")
    if manifest is None:
        return []
    members = RUST_WORKSPACE_MEMBERS_PATTERN.search(manifest)
    crate_names = RUST_CRATE_NAME_PATTERN.findall(members["members"]) if members is not None else []
    sys_version: str | None = None
    sys_dependency = RUST_FRAMEWORK_DEPENDENCY_PATTERN.search(manifest)
    if sys_dependency is not None:
        sys_version = sys_dependency["version"]
    links: list[PackageDocumentation] = []
    for crate in crate_names:
        crate_version = sys_version if crate.endswith("-sys") and sys_version else version
        links.append(
            PackageDocumentation(
                label=crate, url=f"https://docs.rs/{quote(crate, safe='-')}/{crate_version}"
            )
        )
    return sorted(links, key=lambda item: item.label)


CSHARP_PACKAGE_ID_PATTERN = re.compile(r"<PackageId>\s*(?P<id>[^<\s]+)\s*</PackageId>")


def _csharp_package_documentation(
    repository: Path,
    revision: str,
    version: str,
    inventory: SourceInventory,
) -> list[PackageDocumentation]:
    """Link each shipped NuGet package at the version this release publishes."""
    links: list[PackageDocumentation] = []
    for artifact in inventory.artifacts:
        if not artifact.path.endswith(".csproj"):
            continue
        content = _read_revision_file(repository, revision, artifact.path)
        if content is None:
            continue
        match = CSHARP_PACKAGE_ID_PATTERN.search(content)
        if match is None:
            continue
        package_id = match["id"]
        encoded = quote(package_id, safe=".")
        links.append(
            PackageDocumentation(
                label=package_id,
                url=f"https://www.nuget.org/packages/{encoded}/{quote(version, safe='.-')}",
            )
        )
    return sorted(links, key=lambda item: item.label)


def _package_documentation(
    repository: Path,
    release: ReleaseRecord,
    spec: BindingSourceSpec,
    inventory: SourceInventory,
) -> list[PackageDocumentation]:
    if spec.source_id == "maa-framework-go":
        return _go_package_documentation(repository, release.commit, release.tag, inventory)
    if spec.source_id == "maa-framework-csharp":
        return _csharp_package_documentation(repository, release.commit, release.version, inventory)
    if spec.source_id == "maa-framework-rs":
        return _rust_package_documentation(repository, release.commit, release.version, inventory)
    return []


GO_RELEASE_LINK_PATTERN = re.compile(
    r"MaaFramework/releases/tag/v(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?)",
    flags=re.IGNORECASE,
)
GO_VERSION_BADGE_PATTERN = re.compile(
    r"img\.shields\.io/badge/MaaFramework-v(?P<version>\d+\.\d+\.\d+(?:--[0-9A-Za-z.]+)*)",
    flags=re.IGNORECASE,
)
RUST_FRAMEWORK_DEPENDENCY_PATTERN = re.compile(
    r"maa-framework-sys\s*=\s*\{[^}]*version\s*=\s*\""
    r"(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)\""
)
CSHARP_RUNTIME_PACKAGE_PATTERN = re.compile(
    r'Maa\.Framework\.Runtimes"\s+Version="(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)"'
)
CSHARP_README_LINK_PATTERN = re.compile(
    r"MaaFramework/blob/v(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)\)",
    flags=re.IGNORECASE,
)


def _go_compatibility_evidence(content: str) -> tuple[str, str] | None:
    """Return the declared framework version and which README element carries it.

    The release-link anchor is the primary evidence; the shields.io badge is the
    fallback. Badge text escapes `-` as `--`, so the badge version is normalised.
    """
    link = GO_RELEASE_LINK_PATTERN.search(content)
    if link is not None:
        return link["version"], "release link"
    badge = GO_VERSION_BADGE_PATTERN.search(content)
    if badge is not None:
        return badge["version"].replace("--", "-"), "version badge"
    return None


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
            evidence = _go_compatibility_evidence(content)
            if evidence is not None:
                version, basis = evidence
                return BindingCompatibility(
                    source_id=spec.source_id,
                    binding_version=release.version,
                    binding_revision=release.commit,
                    framework_version=version,
                    status=CompatibilityStatus.DECLARED,
                    evidence_paths=[path],
                    note=(
                        f"The binding README {basis} points at MaaFramework v{version}; "
                        "runtime compatibility has not been independently verified."
                    ),
                )
    elif spec.source_id == "maa-framework-rs":
        content = _read_revision_file(repository, release.commit, "Cargo.toml")
        if content is not None:
            match = RUST_FRAMEWORK_DEPENDENCY_PATTERN.search(content)
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
    else:
        packages = _read_revision_file(repository, release.commit, "src/Directory.Packages.props")
        if packages is not None:
            match = CSHARP_RUNTIME_PACKAGE_PATTERN.search(packages)
            if match is not None:
                version = match["version"]
                return BindingCompatibility(
                    source_id=spec.source_id,
                    binding_version=release.version,
                    binding_revision=release.commit,
                    framework_version=version,
                    status=CompatibilityStatus.DECLARED,
                    evidence_paths=["src/Directory.Packages.props"],
                    note=(
                        "The package manifest declares Maa.Framework.Runtimes "
                        f"{version}; runtime compatibility has not been independently verified."
                    ),
                )
        for path in ("README.md", "README.zh_cn.md"):
            content = _read_revision_file(repository, release.commit, path)
            if content is None:
                continue
            match = CSHARP_README_LINK_PATTERN.search(content)
            if match is not None:
                version = match["version"]
                return BindingCompatibility(
                    source_id=spec.source_id,
                    binding_version=release.version,
                    binding_revision=release.commit,
                    framework_version=version,
                    status=CompatibilityStatus.DECLARED,
                    evidence_paths=[path],
                    note=(
                        f"The binding README links MaaFramework v{version}; "
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


def render_artifact_page(
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


def render_binding_version(
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
    if package_documentation:
        package_link = package_documentation[0]
        registry = spec.package_registry or "the package registry"
        index_lines.extend(
            [
                "",
                spec.package_heading,
                "",
                f"[Browse {package_link.label} on {registry}]({package_link.url})",
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
        "api.md": render_artifact_page(
            spec,
            inventory,
            repository_url,
            ArtifactKind.BINDING_API,
            "Public binding API",
            package_documentation,
        ),
        "documentation.md": render_artifact_page(
            spec, inventory, repository_url, ArtifactKind.DOCUMENTATION, "Documentation"
        ),
        "manifests.md": render_artifact_page(
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
    prereleases: list[PrereleaseRecord],
    package_documentation: list[PackageDocumentation],
) -> None:
    output_root = root / "generated" / spec.source_id
    version_root = output_root / inventory.version
    version_root.mkdir(parents=True, exist_ok=True)
    for path in version_root.glob("*.md"):
        path.unlink()
    for relative_path, content in render_binding_version(
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
    if prereleases:
        lines.extend(
            [
                "",
                "## Prereleases",
                "",
                "[Pre-release registry](./prereleases.md)",
            ]
        )
    (output_root / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    (output_root / "prereleases.md").write_text(
        render_prereleases_page(
            display_name=spec.display_name,
            generator="maa-wiki-sync-bindings-history",
            repository_url=repository_url,
            releases=releases,
            prereleases=prereleases,
        ),
        encoding="utf-8",
        newline="\n",
    )


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
    prune: bool = False,
) -> tuple[list[ReleaseRecord], list[PrereleaseRecord]]:
    spec = BINDING_SPECS.get(source_id)
    if spec is None:
        raise ValueError(f"Unsupported binding source: {source_id}")
    repositories = load_repository_catalog(root)
    source = next((item for item in repositories.repositories if item.id == source_id), None)
    if source is None:
        raise ValueError(f"Unknown repository source: {source_id}")

    releases = discover_stable_releases(repository, major=spec.tag_major)
    prereleases = discover_prereleases(repository, major=spec.tag_major)
    registered_releases, registered_prereleases = registered_release_versions(root, source_id)
    guard_registry_shrink(
        registered_releases,
        {release.version for release in releases},
        prune=prune,
        source=source_id,
    )
    guard_registry_shrink(
        registered_prereleases,
        {prerelease.version for prerelease in prereleases},
        prune=prune,
        source=f"{source_id} prerelease",
    )
    prereleases = resolve_included_in(repository, prereleases, releases)
    source.default_revision = releases[-1].commit
    source_root = root / "sources" / source_id
    source_root.mkdir(parents=True, exist_ok=True)
    write_yaml(
        source_root / "releases.yaml",
        ReleaseCatalog(
            source_id=source_id,
            releases=releases,
            prereleases=prereleases,
        ).model_dump(mode="json"),
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
        package_documentation = _package_documentation(repository, release, spec, inventory)
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
            prereleases,
            package_documentation,
        )

    catalog.bindings.extend(compatibilities)
    catalog.bindings.sort(key=lambda item: (item.source_id, item.binding_version))
    compatibility_path = root / "sources" / "compatibility" / "bindings.yaml"
    compatibility_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(compatibility_path, catalog.model_dump(mode="json"))
    return releases, prereleases
