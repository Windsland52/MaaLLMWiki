# pyright: reportPrivateUsage=false
from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import yaml

from maa_llm_wiki.extract import build_machine_changes, render_machine_changes_page
from maa_llm_wiki.inventory import discover_maafw_artifacts
from maa_llm_wiki.models import ReleaseCatalog, ReleaseRecord, SourceInventory

REPOSITORY_URL = "https://github.com/MaaXYZ/MaaFramework"
FIXED_DATE = date(2026, 1, 1)

BASE_FILES = {
    "include/MaaFramework/MaaDef.h": (
        "#pragma once\n"
        "\n"
        "typedef enum MaaFoo {\n"
        "    MaaFoo_One = 1,\n"
        "    MaaFoo_Two = 2,\n"
        "} MaaFoo;\n"
        "\n"
        "#define MaaMsg_Test_Started 1\n"
    ),
    "tools/pipeline.schema.json": (
        "{\n"
        '  "type": "object",\n'
        '  "properties": {\n'
        '    "task": {\n'
        '      "type": "object",\n'
        '      "properties": {\n'
        '        "name": {"type": "string"},\n'
        '        "mode": {"enum": ["a"]},\n'
        '        "count": {"type": "integer", "default": 1}\n'
        "      },\n"
        '      "required": ["name"]\n'
        "    }\n"
        "  },\n"
        '  "required": ["task"]\n'
        "}\n"
    ),
    "docs/en_us/3.3-ProjectInterfaceV2.md": (
        "# 3.3 Project Interface V2\n"
        "\n"
        "| Release | Version |\n"
        "| --- | --- |\n"
        "| 2025-01-01 | v2.6.0 |\n"
    ),
    "source/binding/Python/maa/tasker.py": (
        "class Tasker:\n    pass\n\n\ndef old_function() -> None:\n    pass\n"
    ),
    "source/binding/NodeJS/src/apis/tasker.d.ts": (
        "export declare function oldFunction(): void;\n"
    ),
    "docs/en_us/2.1-Integration.md": "# 2.1 Integration\n\nPlain prose.\n",
}

CHANGED_FILES = {
    "include/MaaFramework/MaaDef.h": (
        "#pragma once\n"
        "\n"
        "typedef enum MaaFoo {\n"
        "    MaaFoo_One = 1,\n"
        "    MaaFoo_Two = 2,\n"
        "    MaaFoo_Three = 3,\n"
        "} MaaFoo;\n"
        "\n"
        "#define MaaMsg_Test_Started 1\n"
        "#define MaaMsg_Test_Finished 2\n"
        "\n"
        "MAA_CALL void MaaTaskerNew(MaaTasker* handle);\n"
    ),
    "tools/pipeline.schema.json": (
        "{\n"
        '  "type": "object",\n'
        '  "properties": {\n'
        '    "task": {\n'
        '      "type": "object",\n'
        '      "properties": {\n'
        '        "name": {"type": "string"},\n'
        '        "id": {"type": "string"},\n'
        '        "mode": {"enum": ["a", "b"]},\n'
        '        "count": {"type": "integer", "default": 2}\n'
        "      },\n"
        '      "required": ["name", "id"]\n'
        "    }\n"
        "  },\n"
        '  "required": ["task"]\n'
        "}\n"
    ),
    "docs/en_us/3.3-ProjectInterfaceV2.md": (
        "# 3.3 Project Interface V2\n"
        "\n"
        "| Release | Version |\n"
        "| --- | --- |\n"
        "| 2025-01-01 | v2.6.0 |\n"
        "| 2026-01-01 | v2.7.0 |\n"
    ),
    "source/binding/Python/maa/tasker.py": (
        "class Tasker:\n    pass\n\n\ndef new_function() -> None:\n    pass\n"
    ),
    "source/binding/NodeJS/src/apis/tasker.d.ts": (
        "export declare function newFunction(): void;\n"
    ),
}


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _init_repository(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "catalog@example.com")
    _git(path, "config", "user.name", "Catalog Test")
    _git(path, "config", "commit.gpgsign", "false")
    return path


def _commit_files(repository: Path, files: dict[str, str]) -> str:
    for relative, content in files.items():
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "-m", "content")
    return _git(repository, "rev-parse", "HEAD")


def _write_root(tmp_path: Path, repository: Path, versions: list[str], commits: list[str]) -> Path:
    root = tmp_path / "root"
    inventory_root = root / "sources" / "maa-framework" / "inventories"
    inventory_root.mkdir(parents=True)
    releases: list[ReleaseRecord] = []
    for version, commit in zip(versions, commits, strict=True):
        releases.append(
            ReleaseRecord(
                version=version,
                tag=f"v{version}",
                commit=commit,
                released_at=FIXED_DATE,
            )
        )
        inventory = SourceInventory(
            source_id="maafw",
            version=version,
            revision=commit,
            artifacts=discover_maafw_artifacts(repository, commit),
        )
        (inventory_root / f"{version}.yaml").write_text(
            yaml.safe_dump(inventory.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    catalog = ReleaseCatalog(source_id="maafw", releases=releases)
    (root / "sources" / "maa-framework" / "releases.yaml").write_text(
        yaml.safe_dump(catalog.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return root


def _build_pair(tmp_path: Path, changed_files: dict[str, str]) -> tuple[Path, Path]:
    repository = _init_repository(tmp_path / "upstream")
    first = _commit_files(repository, BASE_FILES)
    second = _commit_files(repository, changed_files)
    root = _write_root(tmp_path, repository, ["1.0.0", "1.1.0"], [first, second])
    return root, repository


def test_extracts_every_structured_kind(tmp_path: Path) -> None:
    root, repository = _build_pair(tmp_path, CHANGED_FILES)

    catalog = build_machine_changes(root, repository)
    records = {(change.kind.value, change.symbol, change.change) for change in catalog.changes}

    assert ("enum-value", "MaaFoo_Three", "added") in records
    assert ("public-function", "MaaTaskerNew", "added") in records
    assert ("callback-message", "MaaMsg_Test_Finished", "added") in records
    assert ("schema-property", "task.id", "added") in records
    assert ("schema-enum", 'task.mode = "b"', "added") in records
    assert ("schema-default", "task.count", "modified") in records
    assert ("schema-required", "task.id", "added") in records
    assert ("documentation-version", "v2.7.0", "added") in records
    assert ("binding-api", "new_function", "added") in records
    assert ("binding-api", "newFunction", "added") in records
    assert all(change.version == "1.1.0" for change in catalog.changes)


def test_removed_lines_are_extracted(tmp_path: Path) -> None:
    root, repository = _build_pair(tmp_path, CHANGED_FILES)

    catalog = build_machine_changes(root, repository)
    removed = {(change.kind.value, change.symbol, change.change) for change in catalog.changes}

    assert ("binding-api", "old_function", "removed") in removed
    assert ("binding-api", "oldFunction", "removed") in removed


def test_unclassified_marks_unstructured_indexed_diff(tmp_path: Path) -> None:
    changed = dict(BASE_FILES)
    changed["docs/en_us/2.1-Integration.md"] = "# 2.1 Integration\n\nDifferent prose.\n"
    root, repository = _build_pair(tmp_path, changed)

    catalog = build_machine_changes(root, repository)

    assert len(catalog.changes) == 1
    record = catalog.changes[0]
    assert record.kind.value == "unclassified"
    assert record.change == "modified"
    assert record.symbol == "unclassified"
    assert record.quote == "1 indexed files changed without a structured change"
    assert record.paths == ["docs/en_us/2.1-Integration.md"]


def test_unindexed_paths_are_ignored(tmp_path: Path) -> None:
    changed = dict(BASE_FILES)
    changed["notes/private.txt"] = "only tracked here, never indexed\n"
    root, repository = _build_pair(tmp_path, changed)

    catalog = build_machine_changes(root, repository)

    assert catalog.changes == []


def test_quote_is_verbatim_and_trimmed(tmp_path: Path) -> None:
    long_comment = "x" * 400
    changed = dict(BASE_FILES)
    changed["source/binding/Python/maa/tasker.py"] = (
        f"def new_function() -> None:  # {long_comment}\n    pass\n"
    )
    root, repository = _build_pair(tmp_path, changed)

    catalog = build_machine_changes(root, repository)
    record = next(
        change
        for change in catalog.changes
        if change.kind.value == "binding-api" and change.change == "added"
    )

    assert record.quote.startswith("def new_function() -> None:  # ")
    assert len(record.quote) == 300
    assert record.paths == ["source/binding/Python/maa/tasker.py"]


def test_extraction_is_deterministic(tmp_path: Path) -> None:
    root, repository = _build_pair(tmp_path, CHANGED_FILES)

    first = build_machine_changes(root, repository)
    second = build_machine_changes(root, repository)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert render_machine_changes_page(first, REPOSITORY_URL) == render_machine_changes_page(
        second, REPOSITORY_URL
    )


def test_records_are_sorted(tmp_path: Path) -> None:
    root, repository = _build_pair(tmp_path, CHANGED_FILES)

    catalog = build_machine_changes(root, repository)
    keys = [
        (change.version, change.kind.value, change.symbol, change.change, change.quote)
        for change in catalog.changes
    ]

    assert keys == sorted(keys)


def test_renderer_lists_records_and_kind_counts(tmp_path: Path) -> None:
    root, repository = _build_pair(tmp_path, CHANGED_FILES)

    catalog = build_machine_changes(root, repository)
    page = render_machine_changes_page(catalog, REPOSITORY_URL)

    assert page.startswith("<!-- Generated by maa-wiki-sync-maafw. Do not edit manually. -->")
    assert "# Machine changes" in page
    assert "| Kind | Records |" in page
    assert "| `enum-value` |" in page
    assert "## 1.1.0" in page
    assert "- `enum-value` `MaaFoo_Three` (added):" in page
    assert "- `schema-property` `task.id` (added):" in page
    assert f"[`include/MaaFramework/MaaDef.h`]({REPOSITORY_URL}/blob/" in page
    assert page.endswith("\n") and not page.endswith("\n\n")


def test_schema_file_added_and_removed(tmp_path: Path) -> None:
    repository = _init_repository(tmp_path / "upstream")
    first = _commit_files(
        repository,
        {
            "tools/pipeline.schema.json": (
                '{"type": "object", "properties": {"a": {"type": "string"}}}\n'
            )
        },
    )
    (repository / "tools/pipeline.schema.json").unlink()
    second = _commit_files(
        repository,
        {
            "tools/interface.schema.json": (
                '{"type": "object", "properties": {"b": {"type": "string"}}}\n'
            )
        },
    )
    root = _write_root(tmp_path, repository, ["1.0.0", "1.1.0"], [first, second])

    catalog = build_machine_changes(root, repository)

    symbols = {(change.symbol, change.change) for change in catalog.changes}
    assert ("a", "removed") in symbols
    assert ("b", "added") in symbols
