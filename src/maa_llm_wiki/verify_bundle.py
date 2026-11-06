"""Verify a published MaaLLMWiki catalog bundle with the Python standard library only.

Shipped verbatim as a release asset: keep it self-contained, no ``maa_llm_wiki`` imports.
``python verify_bundle.py --bundle maa-llm-wiki-catalog-v1.2.3.zip --expect-version v1.2.3``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import NamedTuple, TypeGuard, cast

_MANIFEST_NAME = "catalog-manifest.json"
_API_VERSION = "maa-llm-wiki-catalog/v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"[0-9a-f]{40}")
_VERSION = re.compile(r"v\d+\.\d+\.\d+")
_ID = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
_MANIFEST_KEYS = frozenset(
    {"api_version", "catalog_version", "wiki_revision", "working_tree_clean", "sources", "files"}
)
_SOURCE_KEYS = frozenset({"source_id", "version", "revision"})
_FILE_KEYS = frozenset({"path", "size_bytes", "sha256"})


class BundleFile(NamedTuple):
    path: str
    size_bytes: int
    sha256: str


class BundleManifest(NamedTuple):
    catalog_version: str | None
    wiki_revision: str
    files: tuple[BundleFile, ...]


def _matches(value: object, pattern: re.Pattern[str]) -> TypeGuard[str]:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _valid_source(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    record = cast(dict[str, object], value)
    return (
        frozenset(record) == _SOURCE_KEYS
        and _matches(record.get("source_id"), _ID)
        and isinstance(record.get("version"), str)
        and bool(record.get("version"))
        and _matches(record.get("revision"), _REVISION)
    )


def _bundle_sha256(bundle: Path) -> str:
    digest = hashlib.sha256()
    with bundle.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_manifest(value: object) -> tuple[BundleManifest | None, list[str]]:
    if not isinstance(value, dict):
        return None, [f"{_MANIFEST_NAME} is not a JSON object"]
    data = cast(dict[str, object], value)
    problems: list[str] = []
    if frozenset(data) != _MANIFEST_KEYS:
        problems.append(f"{_MANIFEST_NAME} has keys outside the contract")
    if data.get("api_version") != _API_VERSION:
        problems.append(f"{_MANIFEST_NAME} api_version is not {_API_VERSION!r}")
    version = data.get("catalog_version")
    if version is not None and not _matches(version, _VERSION):
        problems.append(f"{_MANIFEST_NAME} catalog_version is not vX.Y.Z")
    revision = data.get("wiki_revision")
    if not _matches(revision, _REVISION):
        problems.append(f"{_MANIFEST_NAME} wiki_revision is not 40 lowercase hex characters")
    if not isinstance(data.get("working_tree_clean"), bool):
        problems.append(f"{_MANIFEST_NAME} working_tree_clean is not a boolean")
    sources = data.get("sources")
    if not (
        isinstance(sources, list)
        and sources
        and all(_valid_source(source) for source in cast(list[object], sources))
    ):
        problems.append(f"{_MANIFEST_NAME} sources is not a non-empty array of source records")
    raw_files = data.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        return None, [*problems, f"{_MANIFEST_NAME} files is not a non-empty array"]
    entries: list[BundleFile] = []
    for index, item in enumerate(cast(list[object], raw_files)):
        if not isinstance(item, dict) or frozenset(cast(dict[str, object], item)) != _FILE_KEYS:
            problems.append(f"{_MANIFEST_NAME} files[{index}] is not a contract file record")
            continue
        record = cast(dict[str, object], item)
        path, size, sha = record["path"], record["size_bytes"], record["sha256"]
        if not isinstance(path, str) or not path:
            problems.append(f"{_MANIFEST_NAME} files[{index}] has no path")
        elif not isinstance(size, int) or isinstance(size, bool) or size < 0:
            problems.append(f"{_MANIFEST_NAME} file {path} has an invalid size_bytes")
        elif not _matches(sha, _SHA256):
            problems.append(f"{_MANIFEST_NAME} file {path} has an invalid sha256")
        else:
            entries.append(BundleFile(path, size, sha))
    paths = [entry.path for entry in entries]
    if len(paths) != len(set(paths)):
        problems.append(f"{_MANIFEST_NAME} files has duplicate paths")
    if paths != sorted(paths):
        problems.append(f"{_MANIFEST_NAME} files is not sorted by path")
    if problems:
        return None, problems
    return BundleManifest(cast(str | None, version), cast(str, revision), tuple(entries)), []


def _checksums_problems(checksums: Path, bundle_name: str, digest: str) -> list[str]:
    try:
        text = checksums.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return [f"cannot read checksums file {checksums}: {error}"]
    entries = [
        (fields[0].lower(), PurePosixPath(fields[1].lstrip("*").replace("\\", "/")).name)
        for line in text.splitlines()
        if len(fields := line.strip().split(maxsplit=1)) == 2
        and _matches(fields[0].lower(), _SHA256)
        and fields[1].strip()
    ]
    if not entries:
        return [f"checksums file has no usable entries: {checksums}"]
    for candidate, name in entries:
        if candidate != digest:
            continue
        if (
            name == bundle_name
            or name.endswith("-latest.zip")
            or bundle_name.endswith("-latest.zip")
        ):
            return []
    return [f"no SHA256SUMS entry matches {bundle_name} with sha256={digest}"]


def verify_bundle(
    *,
    bundle: Path,
    expect_version: str | None = None,
    expect_revision: str | None = None,
    checksums: Path | None = None,
) -> tuple[list[str], str]:
    """Return (problems, success summary); problems is empty only when every check passed."""
    try:
        digest = _bundle_sha256(bundle)
    except OSError as error:
        return [f"cannot read bundle {bundle}: {error}"], ""
    problems = _checksums_problems(checksums, bundle.name, digest) if checksums else []
    try:
        archive = zipfile.ZipFile(bundle)
    except zipfile.BadZipFile:
        return [*problems, f"not a valid zip archive: {bundle}"], ""
    with archive:
        names = archive.namelist()
        if _MANIFEST_NAME not in names:
            return [*problems, f"{_MANIFEST_NAME} is missing from {bundle}"], ""
        try:
            parsed: object = json.loads(archive.read(_MANIFEST_NAME))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            return [*problems, f"{_MANIFEST_NAME} is invalid: {error}"], ""
        except Exception as error:  # corrupt member data must never escape as a traceback
            return [*problems, f"{_MANIFEST_NAME} could not be read: {error}"], ""
        manifest, manifest_problems = _parse_manifest(parsed)
        if manifest is None:
            return [*problems, *manifest_problems], ""
        # The manifest is a zip entry on purpose, but it is never listed in files[].
        listed = {entry.path: entry for entry in manifest.files}
        present = set(names)
        for name in sorted(present - {_MANIFEST_NAME} - set(listed)):
            problems.append(f"bundle contains an entry not listed in the manifest: {name}")
        for path, entry in listed.items():
            if path not in present:
                problems.append(f"manifest file is missing from the bundle: {path}")
                continue
            try:
                content = archive.read(path)
            except Exception as error:  # unreadable member is a verification problem
                problems.append(f"cannot read bundle entry {path}: {error}")
                continue
            if len(content) != entry.size_bytes:
                problems.append(
                    f"size mismatch for {path}: manifest {entry.size_bytes}, got {len(content)}"
                )
            if hashlib.sha256(content).hexdigest() != entry.sha256:
                problems.append(f"sha256 mismatch for {path}")
    if expect_revision is not None and manifest.wiki_revision != expect_revision:
        problems.append(
            f"wiki revision mismatch: bundle {manifest.wiki_revision}, expected {expect_revision}"
        )
    if expect_version is not None:
        if manifest.catalog_version is None:
            problems.append(f"bundle has no catalog_version, expected {expect_version}")
        elif manifest.catalog_version != expect_version:
            problems.append(f"catalog version mismatch: bundle {manifest.catalog_version}")
    if problems:
        return problems, ""
    version = manifest.catalog_version or "unversioned"
    summary = (
        f"Verified catalog bundle: {version} {manifest.wiki_revision} "
        f"({len(manifest.files)} files) sha256={digest}"
    )
    return [], summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a MaaLLMWiki catalog bundle offline")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--expect-version")
    parser.add_argument("--expect-revision")
    parser.add_argument("--checksums", type=Path)
    args = parser.parse_args(argv)
    problems, summary = verify_bundle(
        bundle=args.bundle,
        expect_version=args.expect_version,
        expect_revision=args.expect_revision,
        checksums=args.checksums,
    )
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
