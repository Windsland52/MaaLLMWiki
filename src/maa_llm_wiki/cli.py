from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from .bindings import BINDING_SPECS, sync_binding_history
from .bundle import build_catalog_bundle, verify_catalog_bundle
from .gaps import render_review_queue
from .inventory import sync_latest_maafw, sync_maafw_history, sync_maafw_inventory
from .schemas import generate_schemas
from .validation import validate_repository


def _error_boundary(action: Callable[[], int]) -> Callable[[], int]:
    """Turn expected failures into one actionable line instead of a traceback."""

    def run() -> int:
        try:
            return action()
        except (OSError, RuntimeError, ValueError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1

    return run


def _root_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser


@_error_boundary
def main() -> int:
    args = _root_parser("Validate MaaLLMWiki content and source metadata").parse_args()
    errors = validate_repository(args.root.resolve())
    if errors:
        for error in errors:
            print(error)  # noqa: T201
        return 1
    print("MaaLLMWiki validation passed")  # noqa: T201
    return 0


@_error_boundary
def generate_schemas_main() -> int:
    args = _root_parser("Generate MaaLLMWiki metadata schemas").parse_args()
    generate_schemas(args.root.resolve())
    return 0


@_error_boundary
def sync_maafw_main() -> int:
    parser = _root_parser("Generate the pinned MaaFramework source inventory")
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    sync_maafw_inventory(
        root=args.root.resolve(),
        repository=args.repository.resolve(),
        version=args.version,
    )
    return 0


@_error_boundary
def sync_latest_maafw_main() -> int:
    parser = _root_parser("Discover and index the latest stable MaaFramework release")
    parser.add_argument("--repository", type=Path, required=True)
    args = parser.parse_args()
    release = sync_latest_maafw(
        root=args.root.resolve(),
        repository=args.repository.resolve(),
    )
    print(f"Indexed MaaFramework {release.tag} at {release.commit}")  # noqa: T201
    return 0


@_error_boundary
def sync_maafw_history_main() -> int:
    parser = _root_parser("Index all stable releases for a MaaFramework major version")
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--major", type=int, default=5)
    parser.add_argument(
        "--prune",
        action="store_true",
        help=(
            "allow the upstream tag list to shrink the registered release/prerelease registry "
            "(do NOT pass from automation)"
        ),
    )
    args = parser.parse_args()
    releases, prereleases = sync_maafw_history(
        root=args.root.resolve(),
        repository=args.repository.resolve(),
        major=args.major,
        prune=args.prune,
    )
    print(  # noqa: T201
        f"Indexed {len(releases)} MaaFramework {args.major}.x releases "
        f"and {len(prereleases)} prereleases"
    )
    return 0


@_error_boundary
def sync_bindings_history_main() -> int:
    parser = _root_parser("Index all stable Go and Rust binding releases")
    parser.add_argument("--go-repository", type=Path, required=True)
    parser.add_argument("--rust-repository", type=Path, required=True)
    parser.add_argument(
        "--prune",
        action="store_true",
        help=(
            "allow the upstream tag list to shrink the registered release/prerelease registry "
            "(do NOT pass from automation)"
        ),
    )
    args = parser.parse_args()
    repositories = {
        "maa-framework-go": args.go_repository.resolve(),
        "maa-framework-rs": args.rust_repository.resolve(),
    }
    for source_id, repository in repositories.items():
        releases, prereleases = sync_binding_history(
            root=args.root.resolve(),
            repository=repository,
            source_id=source_id,
            prune=args.prune,
        )
        print(  # noqa: T201
            f"Indexed {len(releases)} stable {BINDING_SPECS[source_id].display_name} releases "
            f"and {len(prereleases)} prereleases"
        )
    return 0


@_error_boundary
def build_bundle_main() -> int:
    parser = _root_parser("Build a versioned MaaLLMWiki catalog snapshot")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument(
        "--version",
        "--catalog-version",
        dest="catalog_version",
        default=None,
        help=(
            "snapshot tag recorded in catalog-manifest.json as catalog_version "
            "(for example v0.2.0; --catalog-version is kept as an alias)"
        ),
    )
    args = parser.parse_args()
    manifest = build_catalog_bundle(
        root=args.root.resolve(),
        output=args.output.resolve(),
        allow_dirty=args.allow_dirty,
        version=args.catalog_version,
    )
    print(  # noqa: T201
        f"Built catalog bundle for {manifest.wiki_revision} with {len(manifest.files)} files"
    )
    return 0


@_error_boundary
def verify_bundle_main() -> int:
    parser = _root_parser("Verify a versioned MaaLLMWiki catalog bundle")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--expect-revision")
    parser.add_argument("--expect-version")
    args = parser.parse_args()
    manifest = verify_catalog_bundle(
        bundle=args.bundle.resolve(),
        expect_revision=args.expect_revision,
        expect_version=args.expect_version,
    )
    version = manifest.catalog_version or "unversioned"
    print(  # noqa: T201
        f"Verified catalog bundle: {version} {manifest.wiki_revision} ({len(manifest.files)} files)"
    )
    return 0


@_error_boundary
def report_semantic_gaps_main() -> int:
    parser = _root_parser("Report MaaFramework releases awaiting semantic-change review")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repository", type=Path)
    args = parser.parse_args()
    repository = args.repository.resolve() if args.repository is not None else None
    report = render_review_queue(args.root.resolve(), repository)
    if args.output is None:
        print(report, end="")  # noqa: T201
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    return 0
