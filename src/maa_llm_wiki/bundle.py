from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

from pydantic import ValidationError

from .models import CatalogBundleFile, CatalogBundleManifest, CatalogBundleSource
from .validation import load_repository_catalog, load_source_inventory, validate_repository

_BUNDLE_DIRECTORIES = ("generated", "schemas", "sources")
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_MANIFEST_NAME = "catalog-manifest.json"
_CATALOG_VERSION_PATTERN = re.compile(r"^v\d+\.\d+\.\d+$")


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _bundle_paths(root: Path) -> list[Path]:
    return sorted(
        (
            path
            for directory in _BUNDLE_DIRECTORIES
            for path in (root / directory).rglob("*")
            if path.is_file()
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )


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


def _zip_info(path: str) -> ZipInfo:
    info = ZipInfo(path, date_time=_ZIP_TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
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
        content = path.read_bytes()
        files.append((relative, content))
        records.append(
            CatalogBundleFile(
                path=relative,
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
    try:
        archive = ZipFile(bundle)
    except BadZipFile as error:
        raise ValueError(f"not a valid zip archive: {bundle}") from error
    with archive:
        names = archive.namelist()
        if _MANIFEST_NAME not in names:
            raise ValueError(f"{_MANIFEST_NAME} is missing from {bundle}")
        try:
            manifest = CatalogBundleManifest.model_validate_json(archive.read(_MANIFEST_NAME))
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
            content = archive.read(path)
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
        raise ValueError("; ".join(problems))
    return manifest
