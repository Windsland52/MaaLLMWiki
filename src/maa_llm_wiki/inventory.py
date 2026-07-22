from __future__ import annotations

import re
import subprocess
import tarfile
from collections import defaultdict
from datetime import date
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import yaml

from .models import (
    ArtifactKind,
    ReleaseRecord,
    SourceArtifact,
    SourceInventory,
)
from .validation import load_release_catalog, load_repository_catalog

STABLE_TAG_PATTERN = re.compile(r"^v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")


def git_text(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def git_bytes(repository: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    return result.stdout


def _classify(path: str) -> ArtifactKind | None:
    lowered = path.lower()
    if path.startswith("docs/") and lowered.endswith(".md"):
        return ArtifactKind.DOCUMENTATION
    if (
        path.startswith("docs/")
        and lowered.endswith((".png", ".svg"))
        and not lowered.endswith(("maafw.svg", "mirrorc-en.svg", "mirrorc-zh.svg"))
    ):
        return ArtifactKind.DOCUMENTATION_ASSET
    if path.startswith("source/binding/") and lowered.endswith("/readme.md"):
        return ArtifactKind.DOCUMENTATION
    if path.startswith("source/binding/Python/maa/") and lowered.endswith(".py"):
        return ArtifactKind.BINDING_API
    if path.startswith("source/binding/NodeJS/src/apis/") and lowered.endswith(".d.ts"):
        return ArtifactKind.BINDING_API
    if path.startswith("tools/") and lowered.endswith("/readme.md"):
        return ArtifactKind.DOCUMENTATION
    if path.startswith("tools/") and lowered.endswith(".schema.json"):
        return ArtifactKind.SCHEMA
    if path.startswith("include/") and lowered.endswith((".h", ".hpp")):
        return ArtifactKind.PUBLIC_API
    return None


def markdown_metadata(content: str, fallback_title: str) -> tuple[str, str]:
    lines = content.replace("\r\n", "\n").splitlines()
    title_index = next((index for index, line in enumerate(lines) if line.startswith("# ")), None)
    title = (
        lines[title_index].removeprefix("# ").strip() if title_index is not None else fallback_title
    )
    paragraphs: list[str] = []
    current: list[str] = []
    in_code = False
    start = title_index + 1 if title_index is not None else 0
    for line in lines[start : start + 60]:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or stripped.startswith(("#", "<", "!", "- ", "|", ">")):
            continue
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if stripped.startswith("[") and stripped.endswith(")"):
            continue
        current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))
    summary = next((paragraph for paragraph in paragraphs if paragraph != title), "")
    if not summary:
        summary = f"Official documentation for {title}."
    summary = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", summary)
    if len(summary) > 240:
        summary = summary[:237].rstrip() + "..."
    return title, summary


def load_markdown(repository: Path, revision: str, paths: list[str]) -> dict[str, str]:
    if not paths:
        return {}
    archive = git_bytes(repository, "archive", "--format=tar", revision, "--", *paths)
    contents: dict[str, str] = {}
    with tarfile.open(fileobj=BytesIO(archive), mode="r:") as handle:
        for member in handle.getmembers():
            if not member.isfile():
                continue
            extracted = handle.extractfile(member)
            if extracted is not None:
                contents[member.name] = extracted.read().decode("utf-8", errors="replace")
    return contents


def _describe_artifact(path: str, kind: ArtifactKind, markdown: dict[str, str]) -> tuple[str, str]:
    filename = PurePosixPath(path).name
    if kind is ArtifactKind.DOCUMENTATION:
        return markdown_metadata(markdown.get(path, ""), PurePosixPath(path).stem)
    if kind is ArtifactKind.DOCUMENTATION_ASSET:
        return (
            "MaaFramework architecture diagram",
            "Architecture diagram referenced by the official integration documentation.",
        )
    if kind is ArtifactKind.SCHEMA:
        subject = filename.removesuffix(".schema.json").replace("_", " ")
        return filename, f"JSON Schema for {subject} configuration."
    if kind is ArtifactKind.BINDING_API:
        if path.startswith("source/binding/Python/"):
            return filename, f"Public Python binding module for {PurePosixPath(path).stem}."
        return filename, f"Public TypeScript declarations for {filename.removesuffix('.d.ts')}."
    native_summaries = {
        "MaaAPI.h": "Umbrella header for the MaaFramework C API.",
        "MaaBuffer.h": "C API declarations for framework-owned data buffers.",
        "MaaContext.h": "C API declarations for task context and custom task operations.",
        "MaaController.h": "C API declarations for screen capture, input, and device control.",
        "MaaCustomController.h": "Callback interface for implementing a custom controller.",
        "MaaDef.h": "Shared MaaFramework handles, identifiers, statuses, and data types.",
        "MaaGlobal.h": "Global MaaFramework initialization and configuration declarations.",
        "MaaMsg.h": "Callback event message constants and notification categories.",
        "MaaPort.h": "Platform export, visibility, and calling-convention definitions.",
        "MaaResource.h": "C API declarations for loading pipelines, models, and resources.",
        "MaaTasker.h": "C API declarations for task execution and runtime coordination.",
        "MaaUtility.h": "General MaaFramework utility API declarations.",
    }
    return filename, native_summaries.get(
        filename, f"Native C/C++ declarations provided by {filename}."
    )


def discover_maafw_artifacts(repository: Path, revision: str) -> list[SourceArtifact]:
    git_text(repository, "cat-file", "-e", f"{revision}^{{commit}}")
    paths = git_text(
        repository,
        "ls-tree",
        "-r",
        "--name-only",
        revision,
        "--",
        "docs",
        "tools",
        "include",
        "source/binding",
    ).splitlines()
    classified = [(path, kind) for path in paths if (kind := _classify(path)) is not None]
    markdown = load_markdown(
        repository,
        revision,
        [path for path, kind in classified if kind is ArtifactKind.DOCUMENTATION],
    )
    artifacts = [
        SourceArtifact(
            path=path,
            kind=kind,
            title=(details := _describe_artifact(path, kind, markdown))[0],
            summary=details[1],
        )
        for path, kind in classified
    ]
    return sorted(artifacts, key=lambda artifact: artifact.path)


def _artifact_category(artifact: SourceArtifact) -> tuple[str, str]:
    path = artifact.path
    if artifact.kind is ArtifactKind.SCHEMA:
        return "schemas.md", "Schemas"
    if artifact.kind is ArtifactKind.DOCUMENTATION_ASSET:
        return "documentation/diagrams.md", "Architecture diagrams"
    if artifact.kind is ArtifactKind.BINDING_API:
        if path.startswith("source/binding/Python/"):
            return "bindings/python.md", "Python binding API"
        return "bindings/nodejs.md", "NodeJS binding API"
    if artifact.kind is ArtifactKind.PUBLIC_API:
        if path.startswith("include/MaaFramework/"):
            return "native-api/framework.md", "MaaFramework native API"
        if path.startswith("include/MaaToolkit/"):
            return "native-api/toolkit.md", "MaaToolkit native API"
        if path.startswith("include/MaaControlUnit/"):
            return "native-api/control-units.md", "Control-unit native API"
        return "native-api/agents.md", "Agent client and server API"
    if path.startswith("docs/en_us/NodeJS/"):
        return "documentation/nodejs.md", "NodeJS documentation"
    if path.startswith("docs/zh_cn/NodeJS/"):
        return "documentation/nodejs.md", "NodeJS documentation"
    if path.startswith("docs/en_us/"):
        return "documentation/en-us.md", "English documentation"
    if path.startswith("docs/zh_cn/"):
        return "documentation/zh-cn.md", "Chinese documentation"
    return "documentation/tools.md", "Tool documentation"


def _artifact_link(artifact: SourceArtifact, repository_url: str, revision: str) -> str:
    encoded_path = quote(artifact.path, safe="/")
    url = f"{repository_url.rstrip('/')}/blob/{revision}/{encoded_path}"
    return f"- **{artifact.title}**: {artifact.summary} [`{artifact.path}`]({url})"


def _render_version_indexes(inventory: SourceInventory, repository_url: str) -> dict[str, str]:
    grouped: defaultdict[str, list[SourceArtifact]] = defaultdict(list)
    titles: dict[str, str] = {}
    for artifact in inventory.artifacts:
        category, title = _artifact_category(artifact)
        grouped[category].append(artifact)
        titles[category] = title

    pages: dict[str, str] = {}
    for category, artifacts in grouped.items():
        lines = [
            "<!-- Generated by maa-wiki-sync-maafw. Do not edit manually. -->",
            f"# {titles[category]}",
            "",
            f"MaaFramework `{inventory.version}` at `{inventory.revision}`.",
            "",
        ]
        lines.extend(
            _artifact_link(artifact, repository_url, inventory.revision) for artifact in artifacts
        )
        pages[category] = "\n".join(lines) + "\n"

    sections: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for category, title in titles.items():
        section = category.split("/", maxsplit=1)[0]
        sections[section].append((title, category))

    def section_page(section: str, title: str) -> str:
        lines = [
            "<!-- Generated by maa-wiki-sync-maafw. Do not edit manually. -->",
            f"# {title}",
            "",
            f"MaaFramework `{inventory.version}` at `{inventory.revision}`.",
            "",
        ]
        for item_title, category in sorted(sections[section]):
            lines.extend(
                [f"## {item_title}", "", f"[{item_title}]({PurePosixPath(category).name})", ""]
            )
        return "\n".join(lines).rstrip() + "\n"

    for section, title in {
        "documentation": "Documentation",
        "bindings": "In-tree bindings",
        "native-api": "Native API",
    }.items():
        if section in sections:
            pages[f"{section}/index.md"] = section_page(section, title)

    main_lines = [
        "<!-- Generated by maa-wiki-sync-maafw. Do not edit manually. -->",
        f"# MaaFramework {inventory.version}",
        "",
        f"Revision: `{inventory.revision}`",
        "",
        "This is a navigation index for immutable MaaFramework material. "
        "Authored guidance belongs in MaaTutorial.",
        "",
        "## Documentation",
        "",
        "[Browse documentation](documentation/index.md)",
        "",
        "## Bindings",
        "",
        "[Browse in-tree binding APIs](bindings/index.md)",
        "",
        "## Native API",
        "",
        "[Browse native API](native-api/index.md)",
        "",
        "## Schemas",
        "",
        "[Browse schemas](schemas.md)",
    ]
    pages["index.md"] = "\n".join(main_lines) + "\n"
    return pages


def _render_release_index(releases: list[ReleaseRecord]) -> str:
    lines = [
        "<!-- Generated by maa-wiki-sync-maafw. Do not edit manually. -->",
        "# MaaFramework source indexes",
        "",
        "Select a version before using framework facts or APIs.",
        "",
        "## Releases",
        "",
    ]
    for release in reversed(releases):
        lines.append(f"- [{release.version}](./{release.version}/index.md) `{release.commit}`")
    return "\n".join(lines) + "\n"


def _write_generated_indexes(
    root: Path,
    inventory: SourceInventory,
    repository_url: str,
    releases: list[ReleaseRecord],
) -> None:
    output_root = root / "generated" / "maa-framework"
    version_root = output_root / inventory.version
    version_root.mkdir(parents=True, exist_ok=True)
    legacy_index = output_root / f"{inventory.version}.md"
    if legacy_index.is_file():
        legacy_index.unlink()
    for path in version_root.rglob("*.md"):
        path.unlink()
    for relative_path, content in _render_version_indexes(inventory, repository_url).items():
        path = version_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    output_root.mkdir(parents=True, exist_ok=True)
    indexed_releases = [
        release for release in releases if (output_root / release.version / "index.md").is_file()
    ]
    (output_root / "index.md").write_text(
        _render_release_index(indexed_releases), encoding="utf-8", newline="\n"
    )


def sync_maafw_inventory(*, root: Path, repository: Path, version: str) -> None:
    releases = load_release_catalog(root)
    release = next((item for item in releases.releases if item.version == version), None)
    if release is None:
        raise ValueError(f"Unknown MaaFramework release: {version}")

    repositories = load_repository_catalog(root)
    source = next(
        (item for item in repositories.repositories if item.id == releases.source_id), None
    )
    if source is None:
        raise ValueError(f"Unknown repository source: {releases.source_id}")

    inventory = SourceInventory(
        source_id=source.id,
        version=release.version,
        revision=release.commit,
        artifacts=discover_maafw_artifacts(repository, release.commit),
    )
    inventory_path = root / "sources" / "maa-framework" / "inventory.yaml"
    inventory_path.write_text(
        yaml.safe_dump(
            inventory.model_dump(mode="json"),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )

    _write_generated_indexes(root, inventory, source.url, releases.releases)


def parse_stable_tag(tag: str) -> tuple[int, int, int] | None:
    match = STABLE_TAG_PATTERN.fullmatch(tag)
    if match is None:
        return None
    return (
        int(match["major"]),
        int(match["minor"]),
        int(match["patch"]),
    )


def discover_stable_releases(repository: Path, *, major: int | None = None) -> list[ReleaseRecord]:
    tags = git_text(repository, "tag", "--list", "v*").splitlines()
    stable_tags = [
        (version, tag)
        for tag in tags
        if (version := parse_stable_tag(tag)) is not None and (major is None or version[0] == major)
    ]
    if not stable_tags:
        scope = f" major {major}" if major is not None else ""
        raise ValueError(f"MaaFramework repository contains no stable release for{scope}")

    releases: list[ReleaseRecord] = []
    for version_tuple, tag in sorted(stable_tags):
        commit = git_text(repository, "rev-parse", f"{tag}^{{commit}}").strip()
        released_at = date.fromisoformat(
            git_text(repository, "show", "-s", "--format=%cs", commit).strip()
        )
        releases.append(
            ReleaseRecord(
                version=".".join(str(part) for part in version_tuple),
                tag=tag,
                commit=commit,
                released_at=released_at,
            )
        )
    return releases


def find_latest_stable_release(repository: Path) -> ReleaseRecord:
    return discover_stable_releases(repository)[-1]


def write_yaml(path: Path, value: object) -> None:
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )


def sync_latest_maafw(*, root: Path, repository: Path) -> ReleaseRecord:
    latest = find_latest_stable_release(repository)
    releases = load_release_catalog(root)
    existing = next(
        (release for release in releases.releases if release.version == latest.version),
        None,
    )
    if existing is not None:
        if existing.tag != latest.tag or existing.commit != latest.commit:
            raise ValueError(f"Registered release metadata differs from tag {latest.tag}")
        latest = existing
    else:
        releases.releases.append(latest)
        releases.releases.sort(key=lambda release: parse_stable_tag(release.tag) or (0, 0, 0))
        write_yaml(
            root / "sources" / "maa-framework" / "releases.yaml",
            releases.model_dump(mode="json"),
        )

    repositories = load_repository_catalog(root)
    source = next(
        (
            repository_source
            for repository_source in repositories.repositories
            if repository_source.id == releases.source_id
        ),
        None,
    )
    if source is None:
        raise ValueError(f"Unknown repository source: {releases.source_id}")
    if source.default_revision != latest.commit:
        source.default_revision = latest.commit
        write_yaml(
            root / "sources" / "repositories.yaml",
            repositories.model_dump(mode="json"),
        )

    sync_maafw_inventory(root=root, repository=repository, version=latest.version)
    return latest


def sync_maafw_history(*, root: Path, repository: Path, major: int) -> list[ReleaseRecord]:
    releases = discover_stable_releases(repository, major=major)
    release_catalog = load_release_catalog(root)
    release_catalog.releases = releases
    write_yaml(
        root / "sources" / "maa-framework" / "releases.yaml",
        release_catalog.model_dump(mode="json"),
    )

    repositories = load_repository_catalog(root)
    source = next(
        (item for item in repositories.repositories if item.id == release_catalog.source_id),
        None,
    )
    if source is None:
        raise ValueError(f"Unknown repository source: {release_catalog.source_id}")
    source.default_revision = releases[-1].commit
    write_yaml(root / "sources" / "repositories.yaml", repositories.model_dump(mode="json"))

    for release in releases:
        inventory = SourceInventory(
            source_id=source.id,
            version=release.version,
            revision=release.commit,
            artifacts=discover_maafw_artifacts(repository, release.commit),
        )
        inventory_path = (
            root / "sources" / "maa-framework" / "inventories" / f"{release.version}.yaml"
        )
        inventory_path.parent.mkdir(parents=True, exist_ok=True)
        write_yaml(inventory_path, inventory.model_dump(mode="json"))
        if release == releases[-1]:
            write_yaml(
                root / "sources" / "maa-framework" / "inventory.yaml",
                inventory.model_dump(mode="json"),
            )
        _write_generated_indexes(root, inventory, source.url, releases)
    return releases
