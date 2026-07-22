from __future__ import annotations

import argparse
from pathlib import Path

from .bindings import BINDING_SPECS, sync_binding_history
from .bundle import build_catalog_bundle
from .inventory import sync_latest_maafw, sync_maafw_history, sync_maafw_inventory
from .schemas import generate_schemas
from .validation import validate_repository


def _root_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser


def main() -> int:
    args = _root_parser("Validate MaaLLMWiki content and source metadata").parse_args()
    errors = validate_repository(args.root.resolve())
    if errors:
        for error in errors:
            print(error)  # noqa: T201
        return 1
    print("MaaLLMWiki validation passed")  # noqa: T201
    return 0


def generate_schemas_main() -> int:
    args = _root_parser("Generate MaaLLMWiki metadata schemas").parse_args()
    generate_schemas(args.root.resolve())
    return 0


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


def sync_maafw_history_main() -> int:
    parser = _root_parser("Index all stable releases for a MaaFramework major version")
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--major", type=int, default=5)
    args = parser.parse_args()
    releases = sync_maafw_history(
        root=args.root.resolve(),
        repository=args.repository.resolve(),
        major=args.major,
    )
    print(f"Indexed {len(releases)} MaaFramework {args.major}.x releases")  # noqa: T201
    return 0


def sync_bindings_history_main() -> int:
    parser = _root_parser("Index all stable Go and Rust binding releases")
    parser.add_argument("--go-repository", type=Path, required=True)
    parser.add_argument("--rust-repository", type=Path, required=True)
    args = parser.parse_args()
    repositories = {
        "maa-framework-go": args.go_repository.resolve(),
        "maa-framework-rs": args.rust_repository.resolve(),
    }
    for source_id, repository in repositories.items():
        releases = sync_binding_history(
            root=args.root.resolve(), repository=repository, source_id=source_id
        )
        print(  # noqa: T201
            f"Indexed {len(releases)} stable {BINDING_SPECS[source_id].display_name} releases"
        )
    return 0


def build_bundle_main() -> int:
    parser = _root_parser("Build a versioned MaaLLMWiki catalog snapshot")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    manifest = build_catalog_bundle(
        root=args.root.resolve(),
        output=args.output.resolve(),
        allow_dirty=args.allow_dirty,
    )
    print(  # noqa: T201
        f"Built catalog bundle for {manifest.wiki_revision} with {len(manifest.files)} files"
    )
    return 0
