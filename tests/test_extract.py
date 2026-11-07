# pyright: reportPrivateUsage=false
from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pytest
import yaml

from maa_llm_wiki.commits import build_upstream_commits, parse_log, render_upstream_commits_page
from maa_llm_wiki.declarations import parse_json_schema, parse_version_table
from maa_llm_wiki.extract import (
    build_machine_changes,
    render_machine_changes_page,
    render_machine_symbols_page,
)
from maa_llm_wiki.inventory import discover_maafw_artifacts
from maa_llm_wiki.models import (
    MachineChange,
    MachineChangeCatalog,
    MachineChangeKind,
    ReleaseCatalog,
    ReleaseRecord,
    SourceInventory,
)

REPOSITORY_URL = "https://github.com/MaaXYZ/MaaFramework"
FIXED_DATE = date(2026, 1, 1)

# Shapes copied from the upstream headers: functions are exported with MAA_FRAMEWORK_API, the macro
# can stand on its own line, deprecation is a doc comment, constants are #define bit flags.
BASE_FILES = {
    "include/MaaFramework/MaaDef.h": (
        "#pragma once\n"
        "\n"
        "enum MaaFooEnum\n"
        "{\n"
        "    MaaFoo_One = 1,\n"
        "    MaaFoo_Two = 2,\n"
        "};\n"
        "\n"
        "#define MaaWin32InputMethod_Seize 1ULL\n"
    ),
    "include/MaaFramework/MaaMsg.h": '#define MaaMsg_Test_Started "Test.Started"\n',
    "include/MaaFramework/Instance/MaaController.h": (
        "#pragma once\n"
        "\n"
        '#include "../MaaDef.h"\n'
        "\n"
        "#ifdef __cplusplus\n"
        'extern "C"\n'
        "{\n"
        "#endif\n"
        "\n"
        "    MAA_FRAMEWORK_API MaaController* MaaKWinControllerCreate(const char* device_node);\n"
        "\n"
        "    MAA_FRAMEWORK_API MaaBool MaaControllerPostClick(MaaController* ctrl, int32_t x);\n"
        "\n"
        "#ifdef __cplusplus\n"
        "}\n"
        "#endif\n"
    ),
    "tools/pipeline.schema.json": (
        "{\n"
        '  "$defs": {\n'
        '    "Click": {"type": "object", "properties": {"target": {"type": "string"}}}\n'
        "  },\n"
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
        "  }\n"
        "}\n"
    ),
    "docs/en_us/3.3-ProjectInterfaceV2.md": (
        "# 3.3 Project Interface V2\n"
        "\n"
        "| Release | Version | Notes |\n"
        "| --- | --- | --- |\n"
        "| 2025-01-01 | v2.6.0 | Added `hash` |\n"
    ),
    "source/binding/Python/maa/tasker.py": (
        "class Tasker:\n"
        "    def post_task(self, entry: str) -> None:\n"
        "        pass\n"
        "\n"
        "\n"
        "def old_function() -> None:\n"
        "    pass\n"
    ),
    "source/binding/NodeJS/src/apis/tasker.d.ts": (
        "declare global {\n    namespace maa {\n        function oldFunction(): void\n    }\n}\n"
    ),
    "docs/en_us/2.1-Integration.md": "# 2.1 Integration\n\nPlain prose.\n",
}

CHANGED_FILES = {
    "include/MaaFramework/MaaDef.h": (
        "#pragma once\n"
        "\n"
        "enum MaaFooEnum\n"
        "{\n"
        "    MaaFoo_One = 1,\n"
        "    MaaFoo_Two = 2,\n"
        "    MaaFoo_Three = 3,\n"
        "};\n"
        "\n"
        "#define MaaWin32InputMethod_Seize 1ULL\n"
        "#define MaaWin32InputMethod_Interception (1ULL << 9)\n"
    ),
    "include/MaaFramework/MaaMsg.h": (
        '#define MaaMsg_Test_Started "Test.Started"\n#define MaaMsg_Test_Finished "Test.Finished"\n'
    ),
    "include/MaaFramework/Instance/MaaController.h": (
        "#pragma once\n"
        "\n"
        '#include "../MaaDef.h"\n'
        "\n"
        "#ifdef __cplusplus\n"
        'extern "C"\n'
        "{\n"
        "#endif\n"
        "\n"
        "    /**\n"
        "     * @deprecated Use MaaLinuxControllerCreate instead.\n"
        "     */\n"
        "    MAA_FRAMEWORK_API MaaController* MaaKWinControllerCreate(const char* device_node);\n"
        "\n"
        "    MAA_FRAMEWORK_API MaaBool\n"
        "        MaaControllerPostClick(MaaController* ctrl, int32_t x, int32_t contact);\n"
        "\n"
        "    MAA_FRAMEWORK_API\n"
        "    MaaController* MaaLinuxControllerCreate(const char* config_json);\n"
        "\n"
        "#ifdef __cplusplus\n"
        "}\n"
        "#endif\n"
    ),
    "tools/pipeline.schema.json": (
        "{\n"
        '  "$defs": {\n'
        '    "Click": {"type": "object", "properties": {"target": {"type": "string"}}},\n'
        '    "Shell": {"type": "object", "properties": {"cmd": {"type": "string"}}}\n'
        "  },\n"
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
        "  }\n"
        "}\n"
    ),
    "docs/en_us/3.3-ProjectInterfaceV2.md": (
        "# 3.3 Project Interface V2\n"
        "\n"
        "| Release | Version | Notes |\n"
        "| --- | --- | --- |\n"
        "| 2025-01-01 | v2.6.0 | Added `hash` |\n"
        "| 2026-01-01 | v2.7.0 | Added `pretask` |\n"
    ),
    "source/binding/Python/maa/tasker.py": (
        "class Tasker:\n"
        "    def post_task(self, entry: str) -> None:\n"
        "        pass\n"
        "\n"
        "\n"
        "def new_function() -> None:\n"
        "    pass\n"
    ),
    "source/binding/NodeJS/src/apis/tasker.d.ts": (
        "declare global {\n    namespace maa {\n        function newFunction(): void\n    }\n}\n"
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


def _commit_files(repository: Path, files: dict[str, str], message: str = "content") -> str:
    for relative, content in files.items():
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "-m", message)
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
    second = _commit_files(repository, changed_files, "feat: second release (#7)")
    root = _write_root(tmp_path, repository, ["1.0.0", "1.1.0"], [first, second])
    return root, repository


def _records(catalog: MachineChangeCatalog) -> set[tuple[str, str, str]]:
    return {(change.kind.value, change.symbol, change.change) for change in catalog.changes}


def test_extracts_every_structured_kind(tmp_path: Path) -> None:
    root, repository = _build_pair(tmp_path, CHANGED_FILES)

    catalog = build_machine_changes(root, repository)
    records = _records(catalog)

    assert ("enum-value", "MaaFoo_Three", "added") in records
    assert ("public-function", "MaaLinuxControllerCreate", "added") in records
    assert ("public-function", "MaaControllerPostClick", "modified") in records
    assert ("public-function", "MaaKWinControllerCreate", "deprecated") in records
    assert ("constant", "MaaWin32InputMethod_Interception", "added") in records
    assert ("callback-message", "MaaMsg_Test_Finished", "added") in records
    assert ("schema-definition", "$defs.Shell", "added") in records
    assert ("schema-property", "$defs.Shell.cmd", "added") in records
    assert ("schema-property", "task.id", "added") in records
    assert ("schema-enum", 'task.mode = "b"', "added") in records
    assert ("schema-default", "task.count", "modified") in records
    assert ("schema-required", "task.id", "added") in records
    assert ("documentation-version", "v2.7.0", "added") in records
    assert ("binding-api", "maa.tasker:new_function", "added") in records
    assert ("binding-api", "maa.tasker:old_function", "removed") in records
    assert all(change.version == "1.1.0" for change in catalog.changes)


def test_unchanged_elements_produce_no_record(tmp_path: Path) -> None:
    root, repository = _build_pair(tmp_path, CHANGED_FILES)

    symbols = {change.symbol for change in build_machine_changes(root, repository).changes}

    assert "MaaFoo_One" not in symbols
    assert "$defs.Click" not in symbols
    assert "maa.tasker:Tasker.post_task" not in symbols


def test_modified_records_keep_the_previous_text(tmp_path: Path) -> None:
    root, repository = _build_pair(tmp_path, CHANGED_FILES)

    record = next(
        change
        for change in build_machine_changes(root, repository).changes
        if change.symbol == "MaaControllerPostClick"
    )

    assert record.change == "modified"
    assert "int32_t contact" in record.quote
    assert record.previous_quote is not None
    assert "contact" not in record.previous_quote
    assert record.paths == ["include/MaaFramework/Instance/MaaController.h"]


def test_deprecation_record_quotes_the_upstream_note(tmp_path: Path) -> None:
    root, repository = _build_pair(tmp_path, CHANGED_FILES)

    record = next(
        change
        for change in build_machine_changes(root, repository).changes
        if change.symbol == "MaaKWinControllerCreate"
    )

    assert record.change == "deprecated"
    assert "Use MaaLinuxControllerCreate instead." in record.quote


def test_comment_only_change_is_one_unclassified_record(tmp_path: Path) -> None:
    changed = dict(BASE_FILES)
    changed["include/MaaFramework/MaaDef.h"] = (
        "// a new comment\n" + BASE_FILES["include/MaaFramework/MaaDef.h"]
    )
    root, repository = _build_pair(tmp_path, changed)

    catalog = build_machine_changes(root, repository)

    assert len(catalog.changes) == 1
    record = catalog.changes[0]
    assert record.kind is MachineChangeKind.UNCLASSIFIED
    assert record.change == "modified"
    assert record.symbol == "include/MaaFramework/MaaDef.h"
    assert "changed without changing any declared element" in record.quote


def test_prose_documentation_is_left_to_the_version_pages(tmp_path: Path) -> None:
    changed = dict(BASE_FILES)
    changed["docs/en_us/2.1-Integration.md"] = "# 2.1 Integration\n\nDifferent prose.\n"
    changed["docs/en_us/3.3-ProjectInterfaceV2.md"] = BASE_FILES[
        "docs/en_us/3.3-ProjectInterfaceV2.md"
    ].replace("# 3.3 Project Interface V2\n", "# 3.3 Project Interface V2\n\nNew prose.\n")
    root, repository = _build_pair(tmp_path, changed)

    assert build_machine_changes(root, repository).changes == []


def test_unparsable_file_is_unclassified_instead_of_a_burst_of_records(tmp_path: Path) -> None:
    changed = dict(BASE_FILES)
    changed["tools/pipeline.schema.json"] = '{"$defs": {'
    root, repository = _build_pair(tmp_path, changed)

    catalog = build_machine_changes(root, repository)

    assert [(change.kind.value, change.symbol) for change in catalog.changes] == [
        ("unclassified", "tools/pipeline.schema.json")
    ]
    assert "could not be parsed" in catalog.changes[0].quote


def test_declaration_moving_between_files_is_not_a_change(tmp_path: Path) -> None:
    moved = (
        "#pragma once\n"
        "    MAA_FRAMEWORK_API MaaBool MaaControllerPostClick(MaaController* ctrl, int32_t x);\n"
    )
    changed = dict(BASE_FILES)
    changed["include/MaaFramework/Instance/MaaController.h"] = (
        "    MAA_FRAMEWORK_API MaaController* MaaKWinControllerCreate(const char* device_node);\n"
    )
    changed["include/MaaFramework/Instance/MaaInput.h"] = moved
    root, repository = _build_pair(tmp_path, changed)

    catalog = build_machine_changes(root, repository)
    records = _records(catalog)

    assert not any(symbol == "MaaControllerPostClick" for _, symbol, _ in records)
    assert ("unclassified", "include/MaaFramework/Instance/MaaInput.h", "added") in records
    moved = next(
        change
        for change in catalog.changes
        if change.symbol == "include/MaaFramework/Instance/MaaInput.h"
    )
    assert "every element it declares is declared in another file" in moved.quote


def test_unindexed_paths_are_ignored(tmp_path: Path) -> None:
    changed = dict(BASE_FILES)
    changed["notes/private.txt"] = "only tracked here, never indexed\n"
    root, repository = _build_pair(tmp_path, changed)

    assert build_machine_changes(root, repository).changes == []


def test_quotes_are_collapsed_and_trimmed(tmp_path: Path) -> None:
    changed = dict(BASE_FILES)
    changed["source/binding/Python/maa/tasker.py"] = (
        BASE_FILES["source/binding/Python/maa/tasker.py"]
        + "\n\ndef long_function("
        + ", ".join(f"argument_{index}: int" for index in range(40))
        + ") -> None:\n    pass\n"
    )
    root, repository = _build_pair(tmp_path, changed)

    record = next(
        change
        for change in build_machine_changes(root, repository).changes
        if change.symbol == "maa.tasker:long_function"
    )

    assert record.quote.startswith("def long_function(argument_0: int")
    assert len(record.quote) == 300
    assert "  " not in record.quote


def test_extraction_is_deterministic_and_sorted(tmp_path: Path) -> None:
    root, repository = _build_pair(tmp_path, CHANGED_FILES)

    first = build_machine_changes(root, repository)
    second = build_machine_changes(root, repository)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert render_machine_changes_page(first, REPOSITORY_URL) == render_machine_changes_page(
        second, REPOSITORY_URL
    )
    keys = [(change.paths[0], change.kind.value, change.symbol) for change in first.changes]
    assert keys == sorted(keys)


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

    records = {
        (change.symbol, change.change) for change in build_machine_changes(root, repository).changes
    }

    assert ("a", "removed") in records
    assert ("b", "added") in records


def test_schema_parser_names_definitions_branches_and_items() -> None:
    declarations = parse_json_schema(
        '{"$defs": {"Action": {"anyOf": ['
        '{"title": "Click", "properties": {"target": {"type": "string"}}},'
        '{"properties": {"action": {"const": "Swipe"}, "end": {"type": "array",'
        ' "items": {"properties": {"x": {"type": "integer"}}}}}}'
        "]}}}"
    )
    symbols = {(item.kind.value, item.symbol) for item in declarations}

    assert ("schema-definition", "$defs.Action") in symbols
    assert ("schema-property", "$defs.Action.anyOf[Click].target") in symbols
    assert ("schema-enum", '$defs.Action.anyOf[action="Swipe"].action = "Swipe"') in symbols
    assert ("schema-property", '$defs.Action.anyOf[action="Swipe"].end[].x') in symbols


def test_schema_parser_records_reference_only_branches() -> None:
    before = parse_json_schema('{"$defs": {"ActionV1": {"anyOf": [{"$ref": "#/$defs/ClickV1"}]}}}')
    after = parse_json_schema(
        '{"$defs": {"ActionV1": {"anyOf": [{"$ref": "#/$defs/ClickV1"},'
        ' {"$ref": "#/$defs/ShellV1"}]}}}'
    )

    added = {(item.kind.value, item.symbol) for item in after} - {
        (item.kind.value, item.symbol) for item in before
    }

    assert added == {("schema-branch", "$defs.ActionV1.anyOf[#/$defs/ShellV1]")}


def test_schema_parser_ignores_prose_keywords() -> None:
    first = parse_json_schema('{"properties": {"a": {"type": "string", "description": "old"}}}')
    second = parse_json_schema('{"properties": {"a": {"type": "string", "description": "new"}}}')

    assert [item.signature for item in first] == [item.signature for item in second]


def test_version_table_parser_reads_both_table_shapes() -> None:
    rows = parse_version_table(
        "| v5.3 | Added `Shell` |\n| 2026-01-30 | v2.1.0 | Standalone release |\n| x | y |\n"
    )

    assert [row.symbol for row in rows] == ["v5.3", "v2.1.0"]
    respaced = parse_version_table("| v5.3 | Added `Shell`（action） |\n")
    compact_row = parse_version_table("| v5.3 | Added `Shell`（action）|\n")
    assert respaced[0].signature == compact_row[0].signature


def test_long_modified_quotes_start_at_the_first_difference(tmp_path: Path) -> None:
    parameters = ", ".join(f"int32_t argument_{index}" for index in range(30))
    base = dict(BASE_FILES)
    base["include/MaaFramework/Instance/MaaController.h"] = (
        f"MAA_FRAMEWORK_API MaaBool MaaLongFunction({parameters});\n"
    )
    changed = dict(base)
    changed["include/MaaFramework/Instance/MaaController.h"] = (
        f"MAA_FRAMEWORK_API MaaBool MaaLongFunction({parameters}, int32_t extra);\n"
    )
    repository = _init_repository(tmp_path / "upstream")
    first = _commit_files(repository, base)
    second = _commit_files(repository, changed)
    root = _write_root(tmp_path, repository, ["1.0.0", "1.1.0"], [first, second])

    record = next(
        change
        for change in build_machine_changes(root, repository).changes
        if change.symbol == "MaaLongFunction"
    )

    assert record.change == "modified"
    assert record.previous_quote is not None
    assert record.quote.startswith("…") and record.previous_quote.startswith("…")
    assert "int32_t extra" in record.quote
    assert record.quote != record.previous_quote
    assert len(record.quote) <= 300


def _change(
    version: str,
    change: str,
    symbol: str,
    *,
    kind: MachineChangeKind = MachineChangeKind.PUBLIC_FUNCTION,
    path: str = "include/MaaFramework/MaaDef.h",
) -> MachineChange:
    return MachineChange.model_validate(
        {
            "version": version,
            "commit": "a" * 40,
            "change": change,
            "kind": kind,
            "symbol": symbol,
            "quote": f"MaaBool {symbol}()",
            "paths": [path],
        }
    )


def test_machine_page_groups_releases_and_files() -> None:
    catalog = MachineChangeCatalog(
        source_id="maafw",
        changes=[
            _change("5.14.0", "added", "MaaOld"),
            _change("5.15.0", "added", "MaaNew"),
            _change(
                "5.15.0",
                "modified",
                "docs/en_us/3.3-ProjectInterfaceV2.md",
                kind=MachineChangeKind.UNCLASSIFIED,
                path="docs/en_us/3.3-ProjectInterfaceV2.md",
            ),
        ],
    )

    page = render_machine_changes_page(catalog, "https://github.com/example/catalog")

    assert "| Release | added | removed | modified | deprecated | unclassified |" in page
    assert "| [5.15.0](./5.15.0/index.md) | 1 | 0 | 0 | 0 | 1 |" in page
    assert page.index("## [5.15.0]") < page.index("## [5.14.0]")
    assert "### [`include/MaaFramework/MaaDef.h`](https://github.com/example/catalog/blob/" in page
    assert "- added public-function `MaaNew`: `MaaBool MaaNew()`" in page
    assert page.endswith("\n") and not page.endswith("\n\n")


def test_symbols_page_reports_introduction_and_older_elements() -> None:
    catalog = MachineChangeCatalog(
        source_id="maafw",
        changes=[
            _change("5.15.0", "added", "MaaNew"),
            _change("5.16.0", "deprecated", "MaaNew"),
            _change("5.16.0", "modified", "MaaOld"),
        ],
    )

    page = render_machine_symbols_page(catalog, first_release="5.0.0")

    assert (
        "| `MaaNew` | public-function | `include/MaaFramework/MaaDef.h` | "
        "[5.15.0](./5.15.0/index.md) | [5.16.0](./5.16.0/index.md) deprecated |"
    ) in page
    assert (
        "| `MaaOld` | public-function | `include/MaaFramework/MaaDef.h` | ≤ 5.0.0 | "
        "[5.16.0](./5.16.0/index.md) modified |"
    ) in page
    assert "2 elements." in page


def test_symbols_page_keeps_same_named_schema_symbols_apart() -> None:
    catalog = MachineChangeCatalog(
        source_id="maafw",
        changes=[
            _change(
                "5.15.0",
                "added",
                "option.label",
                kind=MachineChangeKind.SCHEMA_PROPERTY,
                path="tools/interface.schema.json",
            ),
            _change(
                "5.16.0",
                "added",
                "option.label",
                kind=MachineChangeKind.SCHEMA_PROPERTY,
                path="tools/interface_import.schema.json",
            ),
        ],
    )

    page = render_machine_symbols_page(catalog, first_release="5.0.0")

    rows = [line for line in page.splitlines() if line.startswith("| `option.label`")]
    assert len(rows) == 2


def test_parse_log_splits_commits_and_paths() -> None:
    output = (
        b"a" * 40
        + b"\x1ffix: first (#1)\x00\nsrc/a.cpp\x00src/b.cpp\x00"
        + b"b" * 40
        + b"\x1fdocs: second\x00\ndocs/x.md\x00"
    )

    assert parse_log(output) == [
        ("a" * 40, "fix: first (#1)", ["src/a.cpp", "src/b.cpp"]),
        ("b" * 40, "docs: second", ["docs/x.md"]),
    ]


def test_upstream_commits_file_each_commit_under_its_first_release(tmp_path: Path) -> None:
    repository = _init_repository(tmp_path / "upstream")
    first = _commit_files(repository, BASE_FILES, "feat: initial (#1)")
    _commit_files(repository, {"docs/en_us/2.1-Integration.md": "# 2.1\n\nA.\n"}, "docs: a")
    _commit_files(
        repository,
        {"docs/en_us/2.1-Integration.md": "# 2.1\n\nB.\n"},
        "styles: Format C++ files [skip changelog]",
    )
    second = _commit_files(repository, CHANGED_FILES, "feat: add Linux controller (#42)")
    root = _write_root(tmp_path, repository, ["1.0.0", "1.1.0"], [first, second])

    catalog = build_upstream_commits(root, repository)

    assert [commit.subject for commit in catalog.commits] == [
        "docs: a",
        "feat: add Linux controller (#42)",
    ]
    assert {commit.version for commit in catalog.commits} == {"1.1.0"}
    assert catalog.commits[0].pull_request is None
    assert catalog.commits[1].pull_request == 42
    assert catalog.commits[1].path_count == len(CHANGED_FILES)
    assert "include/MaaFramework/Instance/MaaController.h" in catalog.commits[1].paths

    releases = ReleaseCatalog.model_validate(
        yaml.safe_load((root / "sources" / "maa-framework" / "releases.yaml").read_text("utf-8"))
    ).releases
    page = render_upstream_commits_page(catalog, releases, REPOSITORY_URL)
    assert "## [1.1.0](./1.1.0/index.md)" in page
    assert f"[compare]({REPOSITORY_URL}/compare/v1.0.0...v1.1.0)" in page
    assert f"[`{second[:10]}`]({REPOSITORY_URL}/commit/{second}) feat: add Linux" in page
    assert f"controller ([#42]({REPOSITORY_URL}/pull/42))" in page
    assert "[skip changelog]" in page  # explained in the header, never listed as a commit
    assert "styles: Format" not in page


# --------------------------------------------------------------------------------------
# Golden checks against a local MaaFramework clone (skipped when none is present)
# --------------------------------------------------------------------------------------

_CLONE_CANDIDATES = (Path("tmp/MaaFramework"), Path("tmp/MaaFramework-latest"))
_ROOT = Path(__file__).parents[1]


def _upstream_clone() -> Path | None:
    for candidate in _CLONE_CANDIDATES:
        clone = _ROOT / candidate
        if (clone / ".git").exists():
            return clone
    return None


@pytest.mark.skipif(_upstream_clone() is None, reason="no MaaFramework clone under tmp/")
def test_committed_catalog_matches_a_fresh_extraction() -> None:
    clone = _upstream_clone()
    assert clone is not None
    committed = MachineChangeCatalog.model_validate(
        yaml.safe_load(
            (_ROOT / "sources" / "maa-framework" / "machine-changes.yaml").read_text("utf-8")
        )
    )

    fresh = build_machine_changes(_ROOT, clone)

    assert fresh == committed
