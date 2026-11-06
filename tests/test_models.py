from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from maa_llm_wiki.models import (
    MachineChange,
    MachineChangeCatalog,
    MachineChangeKind,
)
from maa_llm_wiki.schemas import SCHEMA_MODELS

ROOT = Path(__file__).parents[1]
COMMIT = "a" * 40

KIND_VALUES = [
    "enum-value",
    "public-function",
    "callback-message",
    "schema-property",
    "schema-enum",
    "schema-default",
    "schema-required",
    "documentation-version",
    "binding-api",
    "unclassified",
]


def _change(**overrides: object) -> MachineChange:
    fields: dict[str, object] = {
        "version": "5.15.0",
        "commit": COMMIT,
        "change": "added",
        "kind": MachineChangeKind.ENUM_VALUE,
        "symbol": "MaaThing_X",
        "quote": "#define MaaThing_X 1",
        "paths": ["include/MaaFramework/MaaDef.h"],
    }
    fields.update(overrides)
    return MachineChange.model_validate(fields)


def test_machine_change_kind_values_are_fixed() -> None:
    assert [kind.value for kind in MachineChangeKind] == KIND_VALUES
    assert MachineChangeKind("enum-value") is MachineChangeKind.ENUM_VALUE
    assert MachineChangeKind("unclassified") is MachineChangeKind.UNCLASSIFIED


def test_machine_change_catalog_round_trips() -> None:
    catalog = MachineChangeCatalog(
        source_id="maafw",
        changes=[
            _change(),
            _change(version="5.16.0", change="removed", kind=MachineChangeKind.BINDING_API),
        ],
    )

    dumped = catalog.model_dump(mode="json")

    assert MachineChangeCatalog.model_validate(dumped) == catalog
    assert dumped["changes"][0] == {
        "version": "5.15.0",
        "commit": COMMIT,
        "change": "added",
        "kind": "enum-value",
        "symbol": "MaaThing_X",
        "quote": "#define MaaThing_X 1",
        "paths": ["include/MaaFramework/MaaDef.h"],
    }


def test_machine_change_catalog_allows_an_empty_change_list() -> None:
    catalog = MachineChangeCatalog(source_id="maafw")

    assert catalog.changes == []
    assert catalog.model_dump(mode="json") == {"source_id": "maafw", "changes": []}


def test_machine_change_paths_are_normalized() -> None:
    change = _change(paths=["docs\\zh_cn\\3.1-任务流水线协议.md"])

    assert change.paths == ["docs/zh_cn/3.1-任务流水线协议.md"]
    with pytest.raises(ValidationError):
        _change(paths=["../outside.md"])
    with pytest.raises(ValidationError):
        _change(paths=[])


def test_machine_change_quote_and_symbol_lengths_are_enforced() -> None:
    assert _change(quote="x" * 300).quote == "x" * 300
    with pytest.raises(ValidationError):
        _change(quote="x" * 301)
    with pytest.raises(ValidationError):
        _change(symbol="")
    with pytest.raises(ValidationError):
        _change(quote="")


def test_machine_change_change_is_a_fixed_literal() -> None:
    for value in ("added", "removed", "modified"):
        assert _change(change=value).change == value
    with pytest.raises(ValidationError):
        _change(change="renamed")


def test_machine_change_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _change(unexpected="value")
    with pytest.raises(ValidationError):
        MachineChangeCatalog.model_validate(
            {"source_id": "maafw", "changes": [], "unexpected": True}
        )


def test_machine_change_commit_requires_full_lowercase_sha() -> None:
    with pytest.raises(ValidationError):
        _change(commit="abc123")
    with pytest.raises(ValidationError):
        _change(commit="A" * 40)


def test_machine_change_schema_is_registered_and_committed() -> None:
    model = SCHEMA_MODELS["machine-change-catalog.schema.json"]
    expected = json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
    path = ROOT / "schemas" / "machine-change-catalog.schema.json"

    assert path.is_file()
    assert path.read_text(encoding="utf-8") == expected
    schema = json.loads(expected)
    assert set(schema["$defs"]) == {"MachineChange", "MachineChangeKind"}
    assert schema["$defs"]["MachineChange"]["required"] == [
        "version",
        "commit",
        "change",
        "kind",
        "symbol",
        "quote",
        "paths",
    ]
    assert schema["$defs"]["MachineChangeKind"]["enum"] == KIND_VALUES
