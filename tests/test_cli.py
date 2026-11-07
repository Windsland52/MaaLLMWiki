from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

from maa_llm_wiki.bindings import BINDING_SPECS
from maa_llm_wiki.bundle import build_catalog_bundle
from maa_llm_wiki.cli import (
    diff_main,
    extract_changes_main,
    release_notes_main,
    sync_bindings_history_main,
)
from maa_llm_wiki.models import (
    MachineChange,
    MachineChangeCatalog,
    MachineChangeKind,
    PrereleaseRecord,
    ReleaseRecord,
    UpstreamCommit,
    UpstreamCommitCatalog,
)

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


def _commit_catalog(subject: str = "feat: add a thing (#12)") -> UpstreamCommitCatalog:
    return UpstreamCommitCatalog(
        source_id="maafw",
        commits=[
            UpstreamCommit(
                version="5.16.0",
                commit=COMMIT_B,
                subject=subject,
                pull_request=12,
                path_count=1,
                paths=["include/MaaFramework/MaaDef.h"],
            )
        ],
    )


def _write_committed(
    root: Path, changes: MachineChangeCatalog, commits: UpstreamCommitCatalog
) -> None:
    directory = root / "sources" / "maa-framework"
    directory.mkdir(parents=True, exist_ok=True)
    for name, catalog in (
        ("machine-changes.yaml", changes),
        ("upstream-commits.yaml", commits),
    ):
        (directory / name).write_text(
            yaml.safe_dump(
                catalog.model_dump(mode="json", exclude_none=True),
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )


def _run_extract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    root: Path,
    changes: MachineChangeCatalog,
    *extra: str,
    commits: UpstreamCommitCatalog | None = None,
) -> tuple[int, str, str]:
    def fake_changes(*, root: Path, repository: Path) -> MachineChangeCatalog:
        _ = root, repository
        return changes

    def fake_commits(*, root: Path, repository: Path) -> UpstreamCommitCatalog:
        _ = root, repository
        return commits if commits is not None else _commit_catalog()

    monkeypatch.setattr("maa_llm_wiki.cli._build_machine_changes", fake_changes)
    monkeypatch.setattr("maa_llm_wiki.cli._build_upstream_commits", fake_commits)
    monkeypatch.setattr(
        sys,
        "argv",
        ["maa-wiki-extract-changes", "--root", str(root), "--repository", str(root), *extra],
    )
    code = extract_changes_main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_extract_changes_check_matches_committed_catalogs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = _machine_catalog()
    _write_committed(tmp_path, catalog, _commit_catalog())

    code, out, err = _run_extract(monkeypatch, capsys, tmp_path, catalog, "--check")

    assert code == 0
    assert err == ""
    assert "matches sources/maa-framework/machine-changes.yaml (3 record(s))" in out
    assert "matches sources/maa-framework/upstream-commits.yaml (1 record(s))" in out


def test_extract_changes_check_is_order_insensitive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = _machine_catalog()
    reordered = MachineChangeCatalog(source_id="maafw", changes=list(reversed(catalog.changes)))
    _write_committed(tmp_path, reordered, _commit_catalog())

    code, out, err = _run_extract(monkeypatch, capsys, tmp_path, catalog, "--check")

    assert code == 0
    assert err == ""
    assert "Machine change catalog matches" in out


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
    _write_committed(tmp_path, committed, _commit_catalog())
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
    assert "Upstream commit index matches" in out


def test_extract_changes_check_reports_a_stale_commit_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = _machine_catalog()
    _write_committed(tmp_path, catalog, _commit_catalog("fix: old subject (#12)"))

    code, out, err = _run_extract(monkeypatch, capsys, tmp_path, catalog, "--check")

    assert code == 1
    assert err == ""
    assert "Machine change catalog matches" in out
    assert "differs from sources/maa-framework/upstream-commits.yaml: 1 new, 1 missing" in out
    assert "5.16.0 commit: 1" in out


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


def test_extract_changes_writes_committed_catalogs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = _machine_catalog()

    code, out, err = _run_extract(monkeypatch, capsys, tmp_path, catalog)

    directory = tmp_path / "sources" / "maa-framework"
    assert code == 0
    assert err == ""
    assert f"Wrote sources/maa-framework/machine-changes.yaml with {len(catalog.changes)}" in out
    assert "Wrote sources/maa-framework/upstream-commits.yaml with 1" in out
    written = MachineChangeCatalog.model_validate(
        yaml.safe_load((directory / "machine-changes.yaml").read_text(encoding="utf-8"))
    )
    assert written == catalog
    commits = UpstreamCommitCatalog.model_validate(
        yaml.safe_load((directory / "upstream-commits.yaml").read_text(encoding="utf-8"))
    )
    assert commits == _commit_catalog()


def _run_release_notes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *arguments: str,
) -> tuple[int, str, str]:
    monkeypatch.setattr(
        sys,
        "argv",
        ["maa-wiki-release-notes", *arguments],
    )
    code = release_notes_main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_release_notes_cli_prints_to_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_build(
        *, root: Path, version: str, previous_tag: str | None, bundle: Path | None
    ) -> str:
        _ = root, version, previous_tag, bundle
        return "# Catalog snapshot v0.2.0\n\nBody.\n"

    monkeypatch.setattr("maa_llm_wiki.cli.build_release_notes", fake_build)

    code, out, err = _run_release_notes(
        monkeypatch, capsys, "--root", str(tmp_path), "--version", "v0.2.0", "--previous", "v0.1.0"
    )

    assert code == 0
    assert err == ""
    assert out == "# Catalog snapshot v0.2.0\n\nBody.\n"


def test_release_notes_cli_writes_output_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_build(
        *, root: Path, version: str, previous_tag: str | None, bundle: Path | None
    ) -> str:
        _ = root, version, previous_tag, bundle
        return "BODY\n"

    monkeypatch.setattr("maa_llm_wiki.cli.build_release_notes", fake_build)
    output = tmp_path / "notes" / "release.md"

    code, out, err = _run_release_notes(
        monkeypatch,
        capsys,
        "--root",
        str(tmp_path),
        "--version",
        "v0.2.0",
        "--previous",
        "v0.1.0",
        "--output",
        str(output),
    )

    assert code == 0
    assert out == ""
    assert err == ""
    assert output.read_text(encoding="utf-8") == "BODY\n"


def test_release_notes_cli_missing_previous_passes_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[str | None] = []

    def fake_build(
        *, root: Path, version: str, previous_tag: str | None, bundle: Path | None
    ) -> str:
        _ = root, version, bundle
        seen.append(previous_tag)
        return "INITIAL\n"

    monkeypatch.setattr("maa_llm_wiki.cli.build_release_notes", fake_build)

    code, out, err = _run_release_notes(
        monkeypatch, capsys, "--root", str(tmp_path), "--version", "v0.1.0"
    )

    assert code == 0
    assert err == ""
    assert out == "INITIAL\n"
    assert seen == [None]


def test_release_notes_cli_unknown_tag_uses_error_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_build(
        *, root: Path, version: str, previous_tag: str | None, bundle: Path | None
    ) -> str:
        _ = root, version, previous_tag, bundle
        raise ValueError("unknown previous tag: v9.9.9")

    monkeypatch.setattr("maa_llm_wiki.cli.build_release_notes", fake_build)

    code, out, err = _run_release_notes(
        monkeypatch,
        capsys,
        "--root",
        str(tmp_path),
        "--version",
        "v0.2.0",
        "--previous",
        "v9.9.9",
    )

    assert code == 1
    assert out == ""
    assert err.startswith("error: ")
    assert "unknown previous tag: v9.9.9" in err
    assert "Traceback" not in err


def test_release_notes_cli_reports_real_bundle_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = Path(__file__).parents[1]
    bundle = tmp_path / "maa-llm-wiki-catalog-v9.9.9.zip"
    build_catalog_bundle(root=root, output=bundle, allow_dirty=True, version="v9.9.9")

    code, out, err = _run_release_notes(
        monkeypatch,
        capsys,
        "--root",
        str(root),
        "--version",
        "v9.9.9",
        "--previous",
        "v0.1.20",
        "--bundle",
        str(bundle),
        "--output",
        str(tmp_path / "release.md"),
    )

    assert code == 0
    assert out == ""
    assert err == ""
    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read("catalog-manifest.json"))
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    body = (tmp_path / "release.md").read_text(encoding="utf-8")
    assert f"sha256 `{digest}`" in body
    assert f"{bundle.stat().st_size} bytes" in body
    assert f"{len(manifest['files'])} files" in body
    assert "## Assets" in body
    assert "`maa-llm-wiki-catalog-latest.zip` (byte-identical copy)" in body


class _BindingSyncRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []

    def __call__(
        self, *, root: Path, repository: Path, source_id: str, prune: bool
    ) -> tuple[list[ReleaseRecord], list[PrereleaseRecord]]:
        _ = root, prune
        self.calls.append((source_id, repository))
        return [], []


def _run_bindings_sync(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    recorder: _BindingSyncRecorder,
    *arguments: str,
) -> tuple[int, str, str]:
    monkeypatch.setattr("maa_llm_wiki.cli.sync_binding_history", recorder)
    monkeypatch.setattr(
        sys,
        "argv",
        ["maa-wiki-sync-bindings-history", *arguments],
    )
    code = sync_bindings_history_main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_sync_bindings_history_accepts_repeated_repository_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = _BindingSyncRecorder()
    go_path = tmp_path / "maa-framework-go"
    rust_path = tmp_path / "maa-framework-rs"

    code, out, err = _run_bindings_sync(
        monkeypatch,
        capsys,
        recorder,
        "--repository",
        f"maa-framework-go={go_path}",
        "--repository",
        f"maa-framework-rs={rust_path}",
    )

    assert code == 0
    assert err == ""
    requested = {"maa-framework-go", "maa-framework-rs"}
    expected_order = [source_id for source_id in BINDING_SPECS if source_id in requested]
    assert [source_id for source_id, _ in recorder.calls] == expected_order
    assert [path for _, path in recorder.calls] == [go_path.resolve(), rust_path.resolve()]
    assert "Indexed 0 stable MaaFramework Go binding releases and 0 prereleases" in out
    assert "Indexed 0 stable MaaFramework Rust binding releases and 0 prereleases" in out


def test_sync_bindings_history_legacy_flags_still_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = _BindingSyncRecorder()

    code, out, err = _run_bindings_sync(
        monkeypatch,
        capsys,
        recorder,
        "--go-repository",
        str(tmp_path / "go"),
        "--rust-repository",
        str(tmp_path / "rs"),
    )

    assert code == 0
    assert err == ""
    assert "Indexed" in out
    assert [source_id for source_id, _ in recorder.calls] == [
        "maa-framework-go",
        "maa-framework-rs",
    ]
    assert [path for _, path in recorder.calls] == [
        (tmp_path / "go").resolve(),
        (tmp_path / "rs").resolve(),
    ]


def test_sync_bindings_history_explicit_repository_wins_over_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = _BindingSyncRecorder()
    explicit = tmp_path / "explicit-go"

    code, out, err = _run_bindings_sync(
        monkeypatch,
        capsys,
        recorder,
        "--go-repository",
        str(tmp_path / "legacy-go"),
        "--repository",
        f"maa-framework-go={explicit}",
    )

    assert code == 0
    assert err == ""
    assert "Indexed" in out
    assert recorder.calls == [("maa-framework-go", explicit.resolve())]


def test_sync_bindings_history_unknown_source_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = _BindingSyncRecorder()

    code, out, err = _run_bindings_sync(
        monkeypatch, capsys, recorder, "--repository", f"not-a-binding-source={tmp_path}"
    )

    assert code == 1
    assert out == ""
    assert err.startswith("error: ")
    assert "unsupported binding source: not-a-binding-source" in err
    assert "Traceback" not in err
    assert recorder.calls == []


def test_sync_bindings_history_requires_at_least_one_repository(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = _BindingSyncRecorder()

    code, out, err = _run_bindings_sync(monkeypatch, capsys, recorder)

    assert code == 1
    assert out == ""
    assert err.startswith("error: ")
    assert "no binding repositories given" in err
    assert recorder.calls == []


def test_sync_bindings_history_rejects_malformed_repository_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = _BindingSyncRecorder()

    code, out, err = _run_bindings_sync(monkeypatch, capsys, recorder, "--repository", "nonsense")

    assert code == 1
    assert out == ""
    assert err.startswith("error: ")
    assert "expected SOURCE_ID=PATH" in err
    assert recorder.calls == []


def test_sync_bindings_history_rejects_duplicate_repository_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = _BindingSyncRecorder()

    code, out, err = _run_bindings_sync(
        monkeypatch,
        capsys,
        recorder,
        "--repository",
        f"maa-framework-go={tmp_path / 'one'}",
        "--repository",
        f"maa-framework-go={tmp_path / 'two'}",
    )

    assert code == 1
    assert out == ""
    assert "duplicate --repository entry for binding source: maa-framework-go" in err
    assert recorder.calls == []


@pytest.mark.skipif(
    "maa-framework-csharp" not in BINDING_SPECS,
    reason="C# binding source is not registered in BINDING_SPECS yet",
)
def test_sync_bindings_history_supports_a_third_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = _BindingSyncRecorder()

    code, out, err = _run_bindings_sync(
        monkeypatch,
        capsys,
        recorder,
        "--repository",
        f"maa-framework-go={tmp_path / 'go'}",
        "--repository",
        f"maa-framework-csharp={tmp_path / 'csharp'}",
    )

    assert code == 0
    assert err == ""
    expected_order = [
        source_id
        for source_id in BINDING_SPECS
        if source_id in {"maa-framework-go", "maa-framework-csharp"}
    ]
    assert [source_id for source_id, _ in recorder.calls] == expected_order
    assert "Indexed 0 stable MaaFramework C# binding releases and 0 prereleases" in out
