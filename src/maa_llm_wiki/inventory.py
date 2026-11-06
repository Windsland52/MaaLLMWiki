from __future__ import annotations

import re
import subprocess
import tarfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import yaml

from .extract import (
    build_machine_changes,
    render_machine_changes_page,
    render_machine_symbols_page,
)
from .models import (
    ArtifactKind,
    MachineChangeCatalog,
    PrereleaseRecord,
    ReleaseCatalog,
    ReleaseRecord,
    SemanticChangeCatalog,
    SourceArtifact,
    SourceInventory,
    SourceMap,
)
from .topics import render_semantic_changes_page, render_topics_page
from .validation import (
    load_release_catalog,
    load_repository_catalog,
    load_semantic_changes,
    load_source_map,
)

STABLE_TAG_PATTERN = re.compile(r"^v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
PRERELEASE_TAG_PATTERN = re.compile(
    r"^v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)-(?P<suffix>[0-9A-Za-z.-]+)$"
)


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


_HTML_TAG_PATTERN = re.compile(r"<[^>]*>")
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)]\([^)]+\)")
_HTML_H1_PATTERN = re.compile(r"<h1\b[^>]*>(?P<title>.*?)</h1>", re.IGNORECASE | re.DOTALL)
_LIST_ITEM_PATTERN = re.compile(r"^(?:[-*+] |\d+\.\s)")
_LANGUAGE_LABELS = frozenset({"english", "简体中文", "繁體中文", "中文", "日本語", "한국어"})


def _plain_text(line: str) -> str:
    """Strip HTML tags and markdown link syntax, keeping the visible text."""
    text = _HTML_TAG_PATTERN.sub("", line)
    text = _MARKDOWN_LINK_PATTERN.sub(r"\1", text)
    return " ".join(text.split())


def _is_language_switcher(text: str) -> bool:
    tokens = [token for token in re.split(r"[\s|·/,，、&]+", text) if token]
    return bool(tokens) and all(token.casefold() in _LANGUAGE_LABELS for token in tokens)


def markdown_metadata(content: str, fallback_title: str) -> tuple[str, str]:
    lines = content.replace("\r\n", "\n").splitlines()
    title = fallback_title
    title_index: int | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# "):
            title, title_index = stripped[2:].strip(), index
            break
        match = _HTML_H1_PATTERN.search(stripped)
        if match is not None:
            candidate = _plain_text(match["title"])
            if candidate:
                title, title_index = candidate, index
                break

    paragraphs: list[str] = []
    quotes: list[str] = []
    list_blocks: list[str] = []
    current: list[str] = []
    quote: list[str] = []
    items: list[str] = []
    in_code = False
    start = title_index + 1 if title_index is not None else 0

    def flush_paragraph() -> None:
        if current:
            paragraphs.append(" ".join(current))
            current.clear()

    def flush_quote() -> None:
        if quote:
            quotes.append(" ".join(quote))
            quote.clear()

    def flush_list() -> None:
        if items:
            if not list_blocks:
                block = "; ".join(items)
                list_blocks.append(block.replace(":; ", ": ").replace(":;", ":"))
            items.clear()

    for line in lines[start : start + 60]:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            flush_paragraph()
            continue
        if in_code:
            continue
        if not stripped:
            flush_paragraph()
            flush_quote()
            flush_list()
            continue
        if stripped.startswith("#"):
            flush_paragraph()
            flush_quote()
            flush_list()
            continue
        plain = _plain_text(stripped)
        if not plain:
            flush_paragraph()
            flush_quote()
            flush_list()
            continue
        if "<" in plain:
            # Malformed multi-line HTML (an unclosed tag) is markup, not prose.
            continue
        if _is_language_switcher(plain):
            continue
        if stripped.startswith(">"):
            flush_paragraph()
            flush_list()
            quoted = plain.removeprefix(">").strip()
            if quoted and not re.fullmatch(r"\[![^\]]+]", quoted):
                quote.append(quoted)
            continue
        if _LIST_ITEM_PATTERN.match(stripped):
            flush_paragraph()
            flush_quote()
            items.append(_LIST_ITEM_PATTERN.sub("", plain, count=1).strip())
            continue
        if stripped.startswith(("!", "|")):
            continue
        if stripped.startswith("[") and stripped.endswith(")"):
            continue
        flush_quote()
        flush_list()
        current.append(plain)
    flush_paragraph()
    flush_quote()
    flush_list()

    summary = next((paragraph for paragraph in paragraphs if paragraph != title), "")
    if not summary and quotes:
        summary = quotes[0]
    if not summary and list_blocks:
        summary = list_blocks[0]
    if not summary:
        summary = f"Official documentation for {title}."
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


_LS_TREE_PATTERN = re.compile(
    r"^(?P<mode>\d{6}) (?P<type>blob|tree|commit) (?P<object>[0-9a-f]{40})\t(?P<path>.+)$"
)


def ls_tree_blobs(
    repository: Path, revision: str, paths: list[str] | None = None
) -> dict[str, str]:
    """Map every indexed file path to the git blob id it resolved to at `revision`."""
    arguments = ["ls-tree", "-r", revision]
    if paths:
        arguments.extend(["--", *paths])
    output = git_text(repository, *arguments)
    blobs: dict[str, str] = {}
    for line in output.splitlines():
        match = _LS_TREE_PATTERN.fullmatch(line)
        # Symlinks are recorded as `120000 blob`; only trees and submodules are dropped.
        if match is None or match["type"] != "blob":
            continue
        blobs[match["path"]] = match["object"]
    return blobs


def discover_maafw_artifacts(repository: Path, revision: str) -> list[SourceArtifact]:
    git_text(repository, "cat-file", "-e", f"{revision}^{{commit}}")
    blobs = ls_tree_blobs(repository, revision, ["docs", "tools", "include", "source/binding"])
    classified = [
        (path, blobs[path], kind) for path in blobs if (kind := _classify(path)) is not None
    ]
    markdown = load_markdown(
        repository,
        revision,
        [path for path, _blob, kind in classified if kind is ArtifactKind.DOCUMENTATION],
    )
    artifacts = [
        SourceArtifact(
            path=path,
            kind=kind,
            blob=blob,
            title=(details := _describe_artifact(path, kind, markdown))[0],
            summary=details[1],
        )
        for path, blob, kind in classified
    ]
    return sorted(artifacts, key=lambda artifact: artifact.path)


def _artifact_category(artifact: SourceArtifact) -> tuple[str, str]:
    path = artifact.path
    if artifact.kind is ArtifactKind.SCHEMA:
        return "schemas.md", "Schemas"
    if artifact.kind is ArtifactKind.DOCUMENTATION_ASSET:
        return "documentation/diagrams.md", "Architecture diagrams"
    if path.startswith("source/binding/") and path.lower().endswith("/readme.md"):
        return "bindings/readmes.md", "Binding documentation"
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
    if path.startswith("docs/en_us/"):
        return "documentation/en-us.md", "English documentation"
    if path.startswith("docs/zh_cn/"):
        return "documentation/zh-cn.md", "Chinese documentation"
    return "documentation/tools.md", "Tool documentation"


def _artifact_link(artifact: SourceArtifact, repository_url: str, revision: str) -> str:
    encoded_path = quote(artifact.path, safe="/")
    url = f"{repository_url.rstrip('/')}/blob/{revision}/{encoded_path}"
    return f"- **{artifact.title}**: {artifact.summary} [`{artifact.path}`]({url})"


_CHANGE_LIST_LIMIT = 20


def _change_entries(
    lines: list[str],
    label: str,
    paths: list[str],
    artifacts: dict[str, SourceArtifact],
) -> None:
    for path in paths[:_CHANGE_LIST_LIMIT]:
        lines.append(f"- {label}: `{path}` ({artifacts[path].kind.value})")
    remaining = len(paths) - _CHANGE_LIST_LIMIT
    if remaining > 0:
        lines.append(f"- ... and {remaining} more {label}")


def _changed_since_lines(
    inventory: SourceInventory,
    previous: SourceInventory | None,
) -> list[str]:
    """Describe the indexed-material delta against the previously registered release."""
    if previous is None:
        return [
            "",
            "## Changed since the previous release",
            "",
            "- First indexed release; no previous inventory to compare.",
        ]

    current = {artifact.path: artifact for artifact in inventory.artifacts}
    earlier = {artifact.path: artifact for artifact in previous.artifacts}
    added = sorted(current.keys() - earlier.keys())
    removed = sorted(earlier.keys() - current.keys())
    changed: list[str] = []
    for path in sorted(current.keys() & earlier.keys()):
        now = current[path]
        before = earlier[path]
        if now.blob is not None and before.blob is not None:
            differs = now.blob != before.blob
        else:
            differs = (now.title, now.summary) != (before.title, before.summary)
        if differs:
            changed.append(path)

    lines = ["", f"## Changed since `{previous.version}`", ""]
    if not added and not removed and not changed:
        lines.append(f"- No indexed material changed since `{previous.version}`.")
        return lines
    lines.append(
        f"- Added: `{len(added)}`, removed: `{len(removed)}`, content changed: `{len(changed)}`"
    )
    _change_entries(lines, "added", added, current)
    _change_entries(lines, "changed", changed, current)
    _change_entries(lines, "removed", removed, earlier)
    return lines


def _version_navigation_lines(
    *,
    version: str,
    previous_version: str | None,
    next_version: str | None,
) -> list[str]:
    """Point a version index at the neighbouring releases and the top-level pages."""
    lines = ["", "## Navigation", "", "- [All indexed versions](../index.md)"]
    if previous_version is not None:
        lines.append(f"- Previous release: [{previous_version}](../{previous_version}/index.md)")
    if next_version is not None:
        lines.append(f"- Next release: [{next_version}](../{next_version}/index.md)")
    lines.extend(
        [
            "- [Topics](../topics.md) · [Machine changes](../machine-changes.md)",
            "- [Machine symbols](../machine-symbols.md) · [Prereleases](../prereleases.md)",
        ]
    )
    return lines


def render_version_indexes(
    inventory: SourceInventory,
    repository_url: str,
    *,
    previous: SourceInventory | None = None,
    previous_version: str | None = None,
    next_version: str | None = None,
) -> dict[str, str]:
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
    main_lines.extend(_changed_since_lines(inventory, previous))
    main_lines.extend(
        _version_navigation_lines(
            version=inventory.version,
            previous_version=previous_version or (previous.version if previous else None),
            next_version=next_version,
        )
    )
    pages["index.md"] = "\n".join(main_lines) + "\n"
    return pages


def render_prereleases_page(
    *,
    display_name: str,
    generator: str,
    repository_url: str,
    releases: list[ReleaseRecord],
    prereleases: list[PrereleaseRecord],
) -> str:
    lines = [
        f"<!-- Generated by {generator}. Do not edit manually. -->",
        f"# {display_name} prerelease registry",
        "",
        "Pre-release tags recorded for traceability, pinned to their exact commits. "
        "Pre-releases are not baseline releases: no inventory is generated for them.",
        "",
    ]
    if not prereleases:
        lines.extend(["No pre-release tags are registered for this source.", ""])
        return "\n".join(lines)

    stable_versions = {release.version for release in releases}
    lines.extend(
        [
            "| Version | Date | Commit | Included in |",
            "| --- | --- | --- | --- |",
        ]
    )
    base_url = repository_url.rstrip("/")
    for prerelease in reversed(prereleases):
        commit_link = f"[`{prerelease.commit[:12]}`]({base_url}/commit/{prerelease.commit})"
        if prerelease.included_in in stable_versions:
            included = f"[{prerelease.included_in}](./{prerelease.included_in}/index.md)"
        else:
            included = "not merged"
        lines.append(
            f"| {prerelease.version} | {prerelease.released_at} | {commit_link} | {included} |"
        )
    return "\n".join(lines) + "\n"


def render_release_index(
    releases: list[ReleaseRecord],
    prereleases: list[PrereleaseRecord],
) -> str:
    has_prereg_page = bool(prereleases)
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
    if has_prereg_page:
        lines.extend(
            [
                "",
                "## Prereleases",
                "",
                "[Pre-release registry](./prereleases.md)",
            ]
        )
    lines.extend(
        [
            "",
            "## Topics",
            "",
            "[Browse curated topic routes](./topics.md)",
            "",
            "## Behaviour changes",
            "",
            "[Browse recorded behaviour changes](./behaviour-changes.md)",
            "",
            "## Machine changes",
            "",
            "[Browse structured machine changes](./machine-changes.md)",
            "",
            "## Machine symbols",
            "",
            "[Browse machine changes by symbol](./machine-symbols.md)",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_version_indexes(
    root: Path,
    inventory: SourceInventory,
    repository_url: str,
    previous: SourceInventory | None = None,
    *,
    previous_version: str | None = None,
    next_version: str | None = None,
) -> None:
    output_root = root / "generated" / "maa-framework"
    version_root = output_root / inventory.version
    version_root.mkdir(parents=True, exist_ok=True)
    legacy_index = output_root / f"{inventory.version}.md"
    if legacy_index.is_file():
        legacy_index.unlink()
    for path in version_root.rglob("*.md"):
        path.unlink()
    for relative_path, content in render_version_indexes(
        inventory,
        repository_url,
        previous=previous,
        previous_version=previous_version,
        next_version=next_version,
    ).items():
        path = version_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


def _write_release_pages(
    root: Path,
    releases: list[ReleaseRecord],
    prereleases: list[PrereleaseRecord],
    repository_url: str,
    source_map: SourceMap,
    semantic_changes: SemanticChangeCatalog,
    *,
    source_id: str,
    machine_changes: MachineChangeCatalog | None = None,
) -> None:
    output_root = root / "generated" / "maa-framework"
    output_root.mkdir(parents=True, exist_ok=True)
    indexed_releases = [
        release for release in releases if (output_root / release.version / "index.md").is_file()
    ]
    (output_root / "index.md").write_text(
        render_release_index(indexed_releases, prereleases),
        encoding="utf-8",
        newline="\n",
    )
    (output_root / "prereleases.md").write_text(
        render_prereleases_page(
            display_name="MaaFramework",
            generator="maa-wiki-sync-maafw-history",
            repository_url=repository_url,
            releases=releases,
            prereleases=prereleases,
        ),
        encoding="utf-8",
        newline="\n",
    )
    (output_root / "topics.md").write_text(
        render_topics_page(
            source_map=source_map,
            repository_url=repository_url,
            latest_release=releases[-1].version,
        ),
        encoding="utf-8",
        newline="\n",
    )
    (output_root / "behaviour-changes.md").write_text(
        render_semantic_changes_page(
            source_id=source_id,
            semantic_changes=semantic_changes,
            source_map=source_map,
            releases=ReleaseCatalog(
                source_id=source_id,
                releases=releases,
                prereleases=prereleases,
            ),
            repository_url=repository_url,
        ),
        encoding="utf-8",
        newline="\n",
    )
    if machine_changes is not None:
        (output_root / "machine-changes.md").write_text(
            render_machine_changes_page(machine_changes, repository_url),
            encoding="utf-8",
            newline="\n",
        )
        (output_root / "machine-symbols.md").write_text(
            render_machine_symbols_page(machine_changes, repository_url),
            encoding="utf-8",
            newline="\n",
        )


def _load_historical_inventory(root: Path, version: str) -> SourceInventory | None:
    path = root / "sources" / "maa-framework" / "inventories" / f"{version}.yaml"
    if not path.is_file():
        return None
    return SourceInventory.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def sync_maafw_inventory(*, root: Path, repository: Path, version: str) -> None:
    releases = load_release_catalog(root)
    source_map = load_source_map(root)
    semantic_changes = load_semantic_changes(root)
    release_index = next(
        (index for index, item in enumerate(releases.releases) if item.version == version),
        None,
    )
    if release_index is None:
        raise ValueError(f"Unknown MaaFramework release: {version}")
    release = releases.releases[release_index]
    previous_inventory = (
        _load_historical_inventory(root, releases.releases[release_index - 1].version)
        if release_index > 0
        else None
    )

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

    machine_changes: MachineChangeCatalog | None = None
    if previous_inventory is not None:
        machine_changes = build_machine_changes(root, repository)
        write_yaml(
            root / "sources" / "maa-framework" / "machine-changes.yaml",
            machine_changes.model_dump(mode="json"),
        )

    _write_version_indexes(
        root,
        inventory,
        source.url,
        previous_inventory,
        previous_version=(
            releases.releases[release_index - 1].version if release_index > 0 else None
        ),
        next_version=(
            releases.releases[release_index + 1].version
            if release_index + 1 < len(releases.releases)
            else None
        ),
    )
    _write_release_pages(
        root,
        releases.releases,
        releases.prereleases,
        source.url,
        source_map,
        semantic_changes,
        source_id=releases.source_id,
        machine_changes=machine_changes,
    )


def parse_stable_tag(tag: str) -> tuple[int, int, int] | None:
    match = STABLE_TAG_PATTERN.fullmatch(tag)
    if match is None:
        return None
    return (
        int(match["major"]),
        int(match["minor"]),
        int(match["patch"]),
    )


def parse_prerelease_tag(tag: str) -> tuple[tuple[int, int, int], str] | None:
    match = PRERELEASE_TAG_PATTERN.fullmatch(tag)
    if match is None:
        return None
    suffix = match["suffix"]
    parts = suffix.split(".")
    if any(part == "" for part in parts):
        return None
    return (int(match["major"]), int(match["minor"]), int(match["patch"])), suffix


def _prerelease_sort_key(suffix: str) -> tuple[tuple[int, int | str], ...]:
    def part_key(part: str) -> tuple[int, int | str]:
        return (0, int(part)) if part.isdigit() else (1, part)

    return tuple(part_key(part) for part in suffix.split("."))


@dataclass(frozen=True)
class TagMetadata:
    commit: str
    released_at: date


TAG_METADATA_FORMAT = (
    "%(refname:short)\t%(if)%(*objectname)%(then)%(*objectname)%(else)%(objectname)%(end)"
    "\t%(creatordate:short)"
)


def _tag_metadata(repository: Path) -> dict[str, TagMetadata]:
    """Read every version tag's commit and date with one git process."""
    output = git_text(repository, "for-each-ref", f"--format={TAG_METADATA_FORMAT}", "refs/tags/v*")
    metadata: dict[str, TagMetadata] = {}
    for line in output.splitlines():
        name, commit, released_at = line.split("\t")
        if not name or not commit:
            continue
        metadata[name] = TagMetadata(commit=commit, released_at=date.fromisoformat(released_at))
    return metadata


def discover_stable_releases(repository: Path, *, major: int | None = None) -> list[ReleaseRecord]:
    metadata = _tag_metadata(repository)
    stable_tags = [
        (version, tag)
        for tag in metadata
        if (version := parse_stable_tag(tag)) is not None and (major is None or version[0] == major)
    ]
    if not stable_tags:
        scope = f" major {major}" if major is not None else ""
        raise ValueError(f"MaaFramework repository contains no stable release for{scope}")

    releases: list[ReleaseRecord] = []
    for version_tuple, tag in sorted(stable_tags):
        details = metadata[tag]
        releases.append(
            ReleaseRecord(
                version=".".join(str(part) for part in version_tuple),
                tag=tag,
                commit=details.commit,
                released_at=details.released_at,
            )
        )
    return releases


def find_latest_stable_release(repository: Path) -> ReleaseRecord:
    return discover_stable_releases(repository)[-1]


def discover_prereleases(repository: Path, *, major: int | None = None) -> list[PrereleaseRecord]:
    metadata = _tag_metadata(repository)
    found: list[tuple[tuple[int, int, int], str, str]] = []
    for tag in metadata:
        parsed = parse_prerelease_tag(tag)
        if parsed is None:
            continue
        version, suffix = parsed
        if major is not None and version[0] != major:
            continue
        found.append((version, suffix, tag))
    found.sort(key=lambda item: (item[0], _prerelease_sort_key(item[1])))

    prereleases: list[PrereleaseRecord] = []
    for version, suffix, tag in found:
        details = metadata[tag]
        prereleases.append(
            PrereleaseRecord(
                version=f"{'.'.join(str(part) for part in version)}-{suffix}",
                tag=tag,
                commit=details.commit,
                released_at=details.released_at,
            )
        )
    return prereleases


def resolve_included_in(
    repository: Path,
    prereleases: list[PrereleaseRecord],
    releases: list[ReleaseRecord],
) -> list[PrereleaseRecord]:
    """Resolve each prerelease to its earliest containing stable release.

    One `git tag --contains` per prerelease replaces the per-(prerelease, release)
    `merge-base --is-ancestor` probe; `releases` is ascending, so the first
    containing entry is the smallest stable version.
    """
    resolved: list[PrereleaseRecord] = []
    for prerelease in prereleases:
        contained_tags = set(
            git_text(repository, "tag", "--contains", prerelease.commit, "--list", "v*").split()
        )
        included_in = next(
            (release.version for release in releases if release.tag in contained_tags),
            None,
        )
        resolved.append(prerelease.model_copy(update={"included_in": included_in}))
    return resolved


def write_yaml(path: Path, value: object) -> None:
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )


def guard_registry_shrink(
    registered: set[str],
    discovered: set[str],
    *,
    prune: bool,
    source: str,
) -> None:
    missing = sorted(registered - discovered)
    if missing and not prune:
        raise ValueError(
            f"Refusing to remove registered {source} versions missing from the clone: "
            f"{', '.join(missing)}. Re-run with --prune only if the upstream tags were really "
            "deleted."
        )


def registered_release_versions(root: Path, source_id: str) -> tuple[set[str], set[str]]:
    directory = "maa-framework" if source_id == "maafw" else source_id
    if not (root / "sources" / directory / "releases.yaml").is_file():
        return set(), set()
    catalog = load_release_catalog(root, source_id)
    return (
        {release.version for release in catalog.releases},
        {prerelease.version for prerelease in catalog.prereleases},
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


def sync_maafw_history(
    *, root: Path, repository: Path, major: int, prune: bool = False
) -> tuple[list[ReleaseRecord], list[PrereleaseRecord]]:
    all_releases = discover_stable_releases(repository)
    newer_releases = [
        release
        for release in all_releases
        if (version := parse_stable_tag(release.tag)) is not None and version[0] > major
    ]
    if newer_releases:
        raise ValueError(
            f"Upstream has MaaFramework {newer_releases[-1].version} but --major {major} was "
            "requested; update the workflow's CATALOG_MAJOR"
        )
    releases = [
        release
        for release in all_releases
        if (version := parse_stable_tag(release.tag)) is not None and version[0] == major
    ]
    if not releases:
        raise ValueError(f"MaaFramework repository contains no stable release for major {major}")
    prereleases = discover_prereleases(repository, major=major)

    release_catalog = load_release_catalog(root)
    source_map = load_source_map(root)
    semantic_changes = load_semantic_changes(root)
    guard_registry_shrink(
        {release.version for release in release_catalog.releases},
        {release.version for release in releases},
        prune=prune,
        source="MaaFramework",
    )
    guard_registry_shrink(
        {prerelease.version for prerelease in release_catalog.prereleases},
        {prerelease.version for prerelease in prereleases},
        prune=prune,
        source="MaaFramework prerelease",
    )

    prereleases = resolve_included_in(repository, prereleases, releases)
    release_catalog.releases = releases
    release_catalog.prereleases = prereleases
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

    previous_inventory: SourceInventory | None = None
    for release_index, release in enumerate(releases):
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
        _write_version_indexes(
            root,
            inventory,
            source.url,
            previous_inventory,
            previous_version=releases[release_index - 1].version if release_index > 0 else None,
            next_version=(
                releases[release_index + 1].version if release_index + 1 < len(releases) else None
            ),
        )
        previous_inventory = inventory
    machine_changes = build_machine_changes(root, repository)
    write_yaml(
        root / "sources" / "maa-framework" / "machine-changes.yaml",
        machine_changes.model_dump(mode="json"),
    )
    _write_release_pages(
        root,
        releases,
        prereleases,
        source.url,
        source_map,
        semantic_changes,
        source_id=release_catalog.source_id,
        machine_changes=machine_changes,
    )
    return releases, prereleases
