from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from maa_llm_wiki.cli import diff_main, extract_changes_main
from maa_llm_wiki.models import MachineChange, MachineChangeCatalog, MachineChangeKind

COMMIT_A = "a" * 40
COMMIT_B = "b" * 40
BLOB_1 = "1" * 40
BLOB_2 = "2" * 40
BLOB_3 = "3" * 40

Artifact = tuple[str, str, str, str, str | None]
Release = tuple[str, str, list[Artifact]]


def _write_catalog(root: Path, releases: list[Release], *, source_id: str = "maafw") -> None:
    directory = "maa-framework" if source_id == "maafw" else source_id
    (root / "sources").mkdir(parents=True, exist_ok=True)
    (root / "sources" / "repositories.yaml").write_text(
        "repositories:\n"
        f"- id: {source_id}\n"
        f"  name: {source_id}\n"
        f"  url: https://example.invalid/{source_id}\n"
        "  role: authoritative\n"
        "  status: active\n"
        "  enabled: true\n"
        f"  default_revision: {releases[-1][1]}\n",
        encoding="utf-8",
    )
    inventory_root = root / "sources" / directory / "inventories"
    inventory_root.mkdir(parents=True)
    for version, revision, artifacts in releases:
        lines = [
            f"source_id: {source_id}",
            f"version: {version}",
            f"revision: {revision}",
            "artifacts:",
        ]
        for path, kind, title, summary, blob in sorted(artifacts):
            lines.extend([f"- path: {path}", f"  kind: {kind}"])
            if blob is not None:
                lines.append(f"  blob: '{blob}'")
            lines.extend([f"  title: {title}", f"  summary: {summary}"])
        (inventory_root / f"{version}.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _standard_catalog(root: Path) -> None:
    _write_catalog(
        root,
        [
            (
                "1.0.0",
                COMMIT_A,
                [
                    ("docs/a.md", "documentation", "A", "A doc.", BLOB_1),
                    ("docs/b.md", "documentation", "B", "B doc.", BLOB_2),
                    ("docs/c.md", "documentation", "C", "C doc.", BLOB_3),
                    ("docs/e.md", "documentation", "Old E", "E doc.", None),
                ],
            ),
            (
                "1.1.0",
                COMMIT_B,
                [
                    ("docs/a.md", "documentation", "A", "A doc.", BLOB_1),
                    ("docs/b.md", "documentation", "B", "B doc.", BLOB_3),
                    ("docs/d.md", "documentation", "D", "D doc.", BLOB_1),
                    ("docs/e.md", "documentation", "New E", "E doc.", None),
                ],
            ),
        ],
    )


def _run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *arguments: str,
) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["maa-wiki-diff", *arguments])
    code = diff_main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_diff_markdown_reports_added_removed_and_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _standard_catalog(tmp_path)

    code, out, err = _run(
        monkeypatch, capsys, "--root", str(tmp_path), "--from", "1.0.0", "--to", "1.1.0"
    )

    assert code == 0
    assert err == ""
    assert "# Catalog diff: maafw 1.0.0 -> 1.1.0" in out
    assert "Totals: 1 added, 1 removed, 2 changed." in out
    assert "## Added (1)" in out
    assert "## Removed (1)" in out
    assert "## Changed (2)" in out
    assert "`docs/d.md`" in out
    assert "`docs/c.md`" in out
    assert "`docs/b.md`" in out
    assert "was: Old E" in out
    assert f"`{BLOB_2[:12]}` -> `{BLOB_3[:12]}`" in out


def test_diff_json_is_stable_and_classifies_by_blob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _standard_catalog(tmp_path)

    code, out, err = _run(
        monkeypatch,
        capsys,
        "--root",
        str(tmp_path),
        "--from",
        "1.0.0",
        "--to",
        "1.1.0",
        "--format",
        "json",
    )

    assert code == 0
    assert err == ""
    payload = json.loads(out)
    assert out == json.dumps(payload, indent=2, sort_keys=True) + "\n"
    assert payload["counts"] == {"added": 1, "removed": 1, "changed": 2}
    assert payload["by_kind"] == {"documentation": {"added": 1, "removed": 1, "changed": 2}}
    assert [entry["path"] for entry in payload["added"]] == ["docs/d.md"]
    assert [entry["path"] for entry in payload["removed"]] == ["docs/c.md"]
    changed = {entry["path"]: entry for entry in payload["changed"]}
    assert changed["docs/b.md"]["blob"] == BLOB_3
    assert changed["docs/b.md"]["previous_blob"] == BLOB_2
    assert changed["docs/e.md"]["previous_title"] == "Old E"
    assert changed["docs/e.md"]["blob"] is None


def test_diff_reports_no_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _standard_catalog(tmp_path)

    code, out, err = _run(
        monkeypatch, capsys, "--root", str(tmp_path), "--from", "1.0.0", "--to", "1.0.0"
    )

    assert code == 0
    assert err == ""
    assert "Totals: 0 added, 0 removed, 0 changed." in out
    assert "No artifact changes." in out


def test_diff_groups_by_kind_in_enum_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_catalog(
        tmp_path,
        [
            ("1.0.0", COMMIT_A, [("docs/a.md", "documentation", "A", "A doc.", BLOB_1)]),
            (
                "1.1.0",
                COMMIT_B,
                [
                    ("docs/a.md", "documentation", "A", "A doc.", BLOB_1),
                    ("docs/b.md", "documentation", "B", "B doc.", BLOB_2),
                    ("tools/x.schema.json", "schema", "x", "Schema.", BLOB_3),
                ],
            ),
        ],
    )

    code, out, err = _run(
        monkeypatch, capsys, "--root", str(tmp_path), "--from", "1.0.0", "--to", "1.1.0"
    )

    assert code == 0
    assert err == ""
    assert "## Added (2)" in out
    assert out.index("### documentation") < out.index("### schema")


def test_diff_supports_another_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_catalog(
        tmp_path,
        [
            ("1.0.0", COMMIT_A, [("guide/a.md", "documentation", "A", "A doc.", BLOB_1)]),
            ("1.1.0", COMMIT_B, [("guide/a.md", "documentation", "A", "A doc.", BLOB_1)]),
        ],
        source_id="maatutorial",
    )

    code, out, err = _run(
        monkeypatch,
        capsys,
        "--root",
        str(tmp_path),
        "--source",
        "maatutorial",
        "--from",
        "1.0.0",
        "--to",
        "1.1.0",
    )

    assert code == 0
    assert err == ""
    assert "# Catalog diff: maatutorial 1.0.0 -> 1.1.0" in out
    assert "No artifact changes." in out


def test_diff_unknown_version_uses_error_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _standard_catalog(tmp_path)

    code, out, err = _run(
        monkeypatch, capsys, "--root", str(tmp_path), "--from", "9.9.9", "--to", "1.1.0"
    )

    assert code == 1
    assert out == ""
    assert err.startswith("error: ")
    assert "unknown maafw release: 9.9.9" in err
    assert "Traceback" not in err


def test_diff_unknown_source_uses_error_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _standard_catalog(tmp_path)

    code, out, err = _run(
        monkeypatch,
        capsys,
        "--root",
        str(tmp_path),
        "--source",
        "no-such-source",
        "--from",
        "1.0.0",
        "--to",
        "1.1.0",
    )

    assert code == 1
    assert out == ""
    assert err.startswith("error: ")
    assert "unknown source: no-such-source" in err
    assert "Traceback" not in err


def _machine_change(
    version: str,
    kind: MachineChangeKind,
    symbol: str,
    *,
    quote: str | None = None,
    paths: tuple[str, ...] = ("include/MaaFramework/MaaDef.h",),
) -> MachineChange:
    return MachineChange(
        version=version,
        commit="a" * 40,
        change="added",
        kind=kind,
        symbol=symbol,
        quote=quote or f"#define {symbol} 1",
        paths=list(paths),
    )


def _machine_catalog() -> MachineChangeCatalog:
    return MachineChangeCatalog(
        source_id="maafw",
        changes=[
            _machine_change("5.15.0", MachineChangeKind.ENUM_VALUE, "MaaThing_X"),
            _machine_change("5.16.0", MachineChangeKind.PUBLIC_FUNCTION, "MaaDoThing"),
            _machine_change("5.17.0", MachineChangeKind.SCHEMA_PROPERTY, "option.only_rec"),
        ],
    )


def _write_machine_changes(root: Path, catalog: MachineChangeCatalog) -> Path:
    path = root / "sources" / "maa-framework" / "machine-changes.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(catalog.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _run_extract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    root: Path,
    catalog: MachineChangeCatalog,
    *extra: str,
) -> tuple[int, str, str]:
    def fake_build(*, root: Path, repository: Path) -> MachineChangeCatalog:
        _ = root, repository
        return catalog

    monkeypatch.setattr("maa_llm_wiki.cli._build_machine_changes", fake_build)
    monkeypatch.setattr(
        sys,
        "argv",
        ["maa-wiki-extract-changes", "--root", str(root), "--repository", str(root), *extra],
    )
    code = extract_changes_main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_extract_changes_check_matches_committed_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = _machine_catalog()
    _write_machine_changes(tmp_path, catalog)

    code, out, err = _run_extract(monkeypatch, capsys, tmp_path, catalog, "--check")

    assert code == 0
    assert err == ""
    assert "matches sources/maa-framework/machine-changes.yaml (3 change(s))" in out


def test_extract_changes_check_is_order_insensitive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = _machine_catalog()
    reordered = MachineChangeCatalog(source_id="maafw", changes=list(reversed(catalog.changes)))
    _write_machine_changes(tmp_path, reordered)

    code, out, err = _run_extract(monkeypatch, capsys, tmp_path, catalog, "--check")

    assert code == 0
    assert err == ""
    assert "matches" in out


def test_extract_changes_check_reports_per_version_and_kind_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    committed = MachineChangeCatalog(
        source_id="maafw",
        changes=[
            _machine_change("5.15.0", MachineChangeKind.ENUM_VALUE, "MaaThing_X", quote="old"),
            _machine_change("5.16.0", MachineChangeKind.PUBLIC_FUNCTION, "MaaDoThing"),
        ],
    )
    _write_machine_changes(tmp_path, committed)
    fresh = MachineChangeCatalog(
        source_id="maafw",
        changes=[
            _machine_change("5.15.0", MachineChangeKind.ENUM_VALUE, "MaaThing_X", quote="new"),
            _machine_change("5.17.0", MachineChangeKind.SCHEMA_PROPERTY, "option.only_rec"),
        ],
    )

    code, out, err = _run_extract(monkeypatch, capsys, tmp_path, fresh, "--check")

    assert code == 1
    assert err == ""
    assert "differs from sources/maa-framework/machine-changes.yaml: 2 new, 2 missing" in out
    assert "  5.17.0 schema-property: 1" in out
    assert "  5.16.0 public-function: 1" in out
    assert "5.15.0 enum-value: 1" in out


def test_extract_changes_check_requires_committed_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run_extract(monkeypatch, capsys, tmp_path, _machine_catalog(), "--check")

    assert code == 1
    assert out == ""
    assert err.startswith("error: ")
    assert "committed machine change catalog is missing" in err
    assert "Traceback" not in err


def test_extract_changes_check_rejects_broken_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "sources" / "maa-framework" / "machine-changes.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("changes: [unclosed\n", encoding="utf-8")

    code, out, err = _run_extract(monkeypatch, capsys, tmp_path, _machine_catalog(), "--check")

    assert code == 1
    assert out == ""
    assert err.startswith("error: ")
    assert "not valid YAML" in err


def test_extract_changes_writes_committed_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = _machine_catalog()

    code, out, err = _run_extract(monkeypatch, capsys, tmp_path, catalog)

    path = tmp_path / "sources" / "maa-framework" / "machine-changes.yaml"
    assert code == 0
    assert err == ""
    assert path.is_file()
    assert f"Wrote sources/maa-framework/machine-changes.yaml with {len(catalog.changes)}" in out
    written = MachineChangeCatalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert written == catalog
