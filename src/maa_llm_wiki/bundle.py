from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

from pydantic import ValidationError

from .models import CatalogBundleFile, CatalogBundleManifest, CatalogBundleSource
from .schemas import SCHEMA_MODELS
from .validation import load_repository_catalog, load_source_inventory, validate_repository

_BUNDLE_DIRECTORIES = ("generated", "schemas", "sources")
# The release artifact ships the consumer-facing documents with it, so a download is
# self-contained: what it is, the guarantees, the licences that cover the data.
_BUNDLE_ROOT_FILES = (
    "README.md",
    "README.en.md",
    "CATALOG-CONTRACT.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "LICENSE",
    "LICENSE-DATA",
    "NOTICE",
)
_BUNDLE_DOC_FILES = ("docs/operations.md", "docs/operations.zh.md")
# Renamed on the way into the zip: the archive needs an entry point at its root.
_BUNDLE_RENAMED = {"docs/bundle-start-here.md": "START-HERE.md"}
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_MANIFEST_NAME = "catalog-manifest.json"
_CATALOG_VERSION_PATTERN = re.compile(r"^v\d+\.\d+\.\d+$")
_SOURCE_CATALOG_FILES = frozenset({"releases.yaml", "inventory.yaml"})
_HAND_AUTHORED_SOURCES = frozenset(
    {
        "sources/repositories.yaml",
        "sources/compatibility/bindings.yaml",
        "sources/maa-framework/source-map.yaml",
        "sources/maa-framework/semantic-changes.yaml",
    }
)
_SYNCED_SOURCE_FILES = frozenset({"sources/maa-framework/machine-changes.yaml"})


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _source_directories(root: Path) -> set[str]:
    """Directories under ``sources/`` that hold an indexed catalog for a registered source."""
    directories: set[str] = set()
    for repository in load_repository_catalog(root).repositories:
        for candidate in (repository.id, "maa-framework"):
            if (root / "sources" / candidate / "inventory.yaml").is_file():
                directories.add(candidate)
    return directories


def _is_published_path(relative: str, source_directories: set[str]) -> bool:
    """Whether a bundled path belongs to the published catalog layout.

    ``generated/`` holds only rendered Markdown, ``schemas/`` only the committed schema files, and
    ``sources/`` only the registered per-source catalogs plus the hand-authored files and the
    sync-generated machine-change catalog.
    """
    parts = PurePosixPath(relative).parts
    if not parts:
        return False
    if parts[0] == "generated":
        return relative.endswith(".md")
    if parts[0] == "schemas":
        return len(parts) == 2 and parts[1] in SCHEMA_MODELS
    if relative in _HAND_AUTHORED_SOURCES or relative in _SYNCED_SOURCE_FILES:
        return True
    if len(parts) == 3 and parts[0] == "sources" and parts[2] in _SOURCE_CATALOG_FILES:
        return parts[1] in source_directories
    if (
        len(parts) == 4
        and parts[0] == "sources"
        and parts[2] == "inventories"
        and parts[3].endswith(".yaml")
    ):
        return parts[1] in source_directories
    return False


def _bundle_paths(root: Path) -> list[Path]:
    """Files the catalog publishes, or ValueError naming the first file outside the allowlist."""
    source_directories = _source_directories(root)
    paths: list[Path] = [
        candidate
        for candidate in (
            *(root / name for name in _BUNDLE_ROOT_FILES),
            *(root / name for name in _BUNDLE_DOC_FILES),
            *(root / name for name in _BUNDLE_RENAMED),
        )
        if candidate.is_file()
    ]
    for directory in _BUNDLE_DIRECTORIES:
        directory_root = root / directory
        if not directory_root.is_dir():
            continue
        for path in sorted(directory_root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if not _is_published_path(relative, source_directories):
                raise ValueError(f"refusing to bundle an unpublished file: {relative}")
            paths.append(path)
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def _bundle_sources(root: Path) -> list[CatalogBundleSource]:
    """Every registered source that actually has an indexed inventory, in catalog order.

    A repository entry without ``sources/<dir>/inventory.yaml`` (placeholder or not yet indexed)
    is skipped instead of being hard-coded out of the manifest.
    """
    sources: list[CatalogBundleSource] = []
    for repository in load_repository_catalog(root).repositories:
        try:
            inventory = load_source_inventory(root, repository.id)
        except OSError:
            continue
        sources.append(
            CatalogBundleSource(
                source_id=repository.id,
                version=inventory.version,
                revision=inventory.revision,
            )
        )
    return sources


def bundle_sources(root: Path) -> list[CatalogBundleSource]:
    """Public view of the manifest source list, for checks and tests."""
    return _bundle_sources(root)


def bundle_paths(root: Path) -> list[Path]:
    """Public view of the published bundle file set, for checks and tests."""
    return _bundle_paths(root)


def bundle_sha256(bundle: Path) -> str:
    """SHA-256 of the whole bundle file, for cross-checking a published SHA256SUMS."""
    digest = hashlib.sha256()
    with bundle.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _zip_info(path: str) -> ZipInfo:
    info = ZipInfo(path, date_time=_ZIP_TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    # `create_system` defaults to 0 (FAT) on Windows and 3 (Unix) elsewhere; pinning it to Unix
    # keeps the central directory identical whichever platform builds the bundle.
    info.create_system = 3
    return info


def _require_catalog_version(version: str) -> str:
    if _CATALOG_VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError(f"catalog version must look like vX.Y.Z: {version!r}")
    return version


def build_catalog_bundle(
    *, root: Path, output: Path, allow_dirty: bool = False, version: str | None = None
) -> CatalogBundleManifest:
    if version is not None:
        _require_catalog_version(version)
    errors = validate_repository(root)
    if errors:
        raise ValueError("Cannot bundle invalid catalog: " + "; ".join(errors))
    revision = _git(root, "rev-parse", "HEAD")
    clean = not bool(_git(root, "status", "--short"))
    if not clean and not allow_dirty:
        raise ValueError("Refusing to build a release catalog from a dirty working tree")

    files: list[tuple[str, bytes]] = []
    records: list[CatalogBundleFile] = []
    for path in _bundle_paths(root):
        relative = path.relative_to(root).as_posix()
        archive_path = _BUNDLE_RENAMED.get(relative, relative)
        content = path.read_bytes()
        files.append((archive_path, content))
        records.append(
            CatalogBundleFile(
                path=archive_path,
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )
    manifest = CatalogBundleManifest(
        catalog_version=version,
        wiki_revision=revision,
        working_tree_clean=clean,
        sources=_bundle_sources(root),
        files=records,
    )
    serialized_manifest = (
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    ).encode()

    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w") as archive:
        archive.writestr(_zip_info(_MANIFEST_NAME), serialized_manifest)
        for relative, content in files:
            archive.writestr(_zip_info(PurePosixPath(relative).as_posix()), content)
    return manifest


def verify_catalog_bundle(
    *,
    bundle: Path,
    expect_revision: str | None = None,
    expect_version: str | None = None,
) -> CatalogBundleManifest:
    """Verify a catalog bundle's manifest against its own contents.

    Every problem is collected before raising, so one shard of a broken bundle still reports all
    detectable defects. Raises ValueError when anything does not line up.
    """
    problems: list[str] = []
    # Hashing the whole file also proves the archive is readable end to end; the digest is part of
    # a failed verification report and is what the CLI prints for SHA256SUMS cross-checking.
    digest = bundle_sha256(bundle)
    try:
        archive = ZipFile(bundle)
    except BadZipFile as error:
        raise ValueError(f"not a valid zip archive: {bundle}") from error
    with archive:
        names = archive.namelist()
        if _MANIFEST_NAME not in names:
            raise ValueError(f"{_MANIFEST_NAME} is missing from {bundle}")
        try:
            raw_manifest = archive.read(_MANIFEST_NAME)
        except BadZipFile as error:
            raise ValueError(f"{_MANIFEST_NAME} could not be read: {error}") from error
        try:
            manifest = CatalogBundleManifest.model_validate_json(raw_manifest)
        except ValidationError as error:
            raise ValueError(f"{_MANIFEST_NAME} is invalid: {error}") from error

        expected = {record.path: record for record in manifest.files}
        present = set(names)
        for name in sorted(present - {_MANIFEST_NAME} - set(expected)):
            problems.append(f"bundle contains an entry not listed in the manifest: {name}")
        for path, record in expected.items():
            if path not in present:
                problems.append(f"manifest file is missing from the bundle: {path}")
                continue
            try:
                content = archive.read(path)
            except BadZipFile as error:
                problems.append(f"bundle member is not readable: {path} ({error})")
                continue
            if len(content) != record.size_bytes:
                problems.append(
                    f"size mismatch for {path}: manifest {record.size_bytes}, bundle {len(content)}"
                )
            if hashlib.sha256(content).hexdigest() != record.sha256:
                problems.append(f"sha256 mismatch for {path}")

    if expect_revision is not None and manifest.wiki_revision != expect_revision:
        problems.append(
            f"wiki revision mismatch: bundle {manifest.wiki_revision}, expected {expect_revision}"
        )
    if expect_version is not None:
        if manifest.catalog_version is None:
            problems.append(f"bundle has no catalog_version, expected {expect_version}")
        elif manifest.catalog_version != expect_version:
            problems.append(
                f"catalog version mismatch: bundle {manifest.catalog_version}, "
                f"expected {expect_version}"
            )
    if problems:
        raise ValueError(f"bundle sha256={digest}: " + "; ".join(problems))
    return manifest
