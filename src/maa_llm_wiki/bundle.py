from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .models import CatalogBundleFile, CatalogBundleManifest, CatalogBundleSource
from .validation import load_source_inventory, validate_repository

_BUNDLE_DIRECTORIES = ("generated", "schemas", "sources")
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


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
    sources: list[CatalogBundleSource] = []
    for source_id in ("maafw", "maa-framework-go", "maa-framework-rs"):
        inventory = load_source_inventory(root, source_id)
        sources.append(
            CatalogBundleSource(
                source_id=source_id,
                version=inventory.version,
                revision=inventory.revision,
            )
        )
    return sources


def _zip_info(path: str) -> ZipInfo:
    info = ZipInfo(path, date_time=_ZIP_TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def build_catalog_bundle(
    *, root: Path, output: Path, allow_dirty: bool = False
) -> CatalogBundleManifest:
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
        archive.writestr(_zip_info("catalog-manifest.json"), serialized_manifest)
        for relative, content in files:
            archive.writestr(_zip_info(PurePosixPath(relative).as_posix()), content)
    return manifest
