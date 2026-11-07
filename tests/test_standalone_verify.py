from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast
from zipfile import ZipFile

import pytest

from maa_llm_wiki.bundle import build_catalog_bundle
from maa_llm_wiki.verify_bundle import main, verify_bundle

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "src" / "maa_llm_wiki" / "verify_bundle.py"
MANIFEST = "catalog-manifest.json"
VERSION = "v9.9.9"


@pytest.fixture(scope="module")
def good_bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("bundle") / "maa-llm-wiki-catalog-v9.9.9.zip"
    build_catalog_bundle(root=ROOT, output=output, allow_dirty=True, version=VERSION)
    return output


def _manifest(bundle: Path) -> dict[str, object]:
    with ZipFile(bundle) as archive:
        payload: object = json.loads(archive.read(MANIFEST))
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def _summary(bundle: Path) -> str:
    payload = _manifest(bundle)
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    files = cast(list[object], payload["files"])
    return (
        f"Verified catalog bundle: {payload['catalog_version']} {payload['wiki_revision']} "
        f"({len(files)} files) sha256={digest}"
    )


def _copy_zip(
    source: Path,
    target: Path,
    *,
    drop: tuple[str, ...] = (),
    replace: dict[str, bytes] | None = None,
    extra: dict[str, bytes] | None = None,
) -> Path:
    replacements = replace or {}
    with ZipFile(source) as original, ZipFile(target, "w") as rewritten:
        for name in original.namelist():
            if name not in drop:
                rewritten.writestr(name, replacements.get(name, original.read(name)))
        for name, content in (extra or {}).items():
            rewritten.writestr(name, content)
    return target


def _mutate_manifest(
    source: Path, target: Path, mutate: Callable[[dict[str, object]], None]
) -> Path:
    payload = _manifest(source)
    mutate(payload)
    return _copy_zip(source, target, replace={MANIFEST: json.dumps(payload).encode()})


def _first_listed(bundle: Path) -> str:
    files = cast(list[object], _manifest(bundle)["files"])
    first = files[0]
    assert isinstance(first, dict)
    return str(cast(dict[str, object], first)["path"])


def _corrupt_member_data(good: Path, member: str, target: Path) -> Path:
    """Overwrite a member's whole compressed payload so the archive is malformed, not just stale.

    Flipping a single byte is platform-dependent: it can land in deflate padding bits and decode to
    the original content. Overwriting the payload always breaks the stream or the CRC.
    """
    data = bytearray(good.read_bytes())
    with ZipFile(good) as archive:
        info = archive.getinfo(member)
    header = info.header_offset
    name_length = int.from_bytes(data[header + 26 : header + 28], "little")
    extra_length = int.from_bytes(data[header + 28 : header + 30], "little")
    start = header + 30 + name_length + extra_length
    size = info.compress_size
    data[start : start + size] = b"\xff" * size
    target.write_bytes(bytes(data))
    return target


def _tampered(name: str, good: Path, tmp_path: Path) -> Path:
    listed = _first_listed(good)
    if name == "good":
        return good
    if name == "missing_file":
        return _copy_zip(good, tmp_path / "missing.zip", drop=(listed,))
    if name == "size_mismatch":
        return _copy_zip(good, tmp_path / "size.zip", replace={listed: b"x"})
    if name == "sha_mismatch":
        with ZipFile(good) as archive:
            original = archive.read(listed)
        return _copy_zip(good, tmp_path / "sha.zip", replace={listed: b"y" * len(original)})
    if name == "extra_entry":
        return _copy_zip(good, tmp_path / "extra.zip", extra={"sources/evil.yaml": b"evil: true\n"})
    if name == "missing_manifest":
        return _copy_zip(good, tmp_path / "no-manifest.zip", drop=(MANIFEST,))
    if name == "malformed_manifest":
        return _copy_zip(good, tmp_path / "bad-json.zip", replace={MANIFEST: b"{not json"})
    if name == "unsorted_manifest":

        def reverse(payload: dict[str, object]) -> None:
            cast(list[object], payload["files"]).reverse()

        return _mutate_manifest(good, tmp_path / "unsorted.zip", reverse)
    if name == "duplicate_manifest_path":

        def duplicate(payload: dict[str, object]) -> None:
            files = cast(list[object], payload["files"])
            files.append(files[0])

        return _mutate_manifest(good, tmp_path / "duplicate.zip", duplicate)
    if name == "corrupted_member":
        return _corrupt_member_data(good, listed, tmp_path / "corrupted.zip")
    if name == "truncated_bundle":
        path = tmp_path / "truncated.zip"
        path.write_bytes(good.read_bytes()[: good.stat().st_size // 2])
        return path
    if name == "missing_bundle":
        return tmp_path / "does-not-exist.zip"
    if name == "non_zip":
        path = tmp_path / "not-a-zip.zip"
        path.write_bytes(b"this is not a zip archive\n")
        return path
    raise AssertionError(f"unknown mutation {name}")


MUTATIONS = [
    "good",
    "missing_file",
    "size_mismatch",
    "sha_mismatch",
    "extra_entry",
    "missing_manifest",
    "malformed_manifest",
    "unsorted_manifest",
    "duplicate_manifest_path",
    "corrupted_member",
    "truncated_bundle",
    "missing_bundle",
    "non_zip",
]


def _write_checksums(path: Path, bundle: Path, *, name: str | None = None) -> Path:
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    path.write_text(f"{digest}  {name or bundle.name}\n", encoding="utf-8")
    return path


def test_standalone_accepts_good_bundle(good_bundle: Path) -> None:
    problems, summary = verify_bundle(bundle=good_bundle, expect_version=VERSION)

    assert problems == []
    assert summary == _summary(good_bundle)


def test_standalone_cli_prints_single_summary_line(
    good_bundle: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = _manifest(good_bundle)

    assert (
        main(
            [
                "--bundle",
                str(good_bundle),
                "--expect-version",
                VERSION,
                "--expect-revision",
                str(payload["wiki_revision"]),
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.out.strip() == _summary(good_bundle)
    assert len(captured.out.strip().splitlines()) == 1
    assert captured.err == ""


def test_standalone_cli_aggregates_every_problem(
    good_bundle: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = _copy_zip(
        good_bundle,
        tmp_path / "broken.zip",
        drop=(_first_listed(good_bundle),),
        extra={"sources/evil.yaml": b"evil: true\n"},
    )

    assert (
        main(["--bundle", str(broken), "--expect-version", "v0.0.1", "--expect-revision", "0" * 40])
        == 1
    )
    captured = capsys.readouterr()
    errors = [line for line in captured.err.splitlines() if line.startswith("error: ")]
    assert len(errors) >= 4
    assert any("not listed in the manifest" in line for line in errors)
    assert any("missing from the bundle" in line for line in errors)
    assert any("catalog version mismatch" in line for line in errors)
    assert any("wiki revision mismatch" in line for line in errors)
    assert captured.out == ""
    assert "Traceback" not in captured.err


def test_standalone_reports_unreadable_inputs(
    good_bundle: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, expected in (
        ("missing_bundle", "cannot read bundle"),
        ("non_zip", "not a valid zip archive"),
        ("missing_manifest", "catalog-manifest.json is missing"),
        ("malformed_manifest", "catalog-manifest.json is invalid"),
    ):
        target = _tampered(name, good_bundle, tmp_path)
        capsys.readouterr()
        assert main(["--bundle", str(target)]) == 1
        captured = capsys.readouterr()
        assert expected in captured.err
        assert "Traceback" not in captured.err


def test_standalone_checksums_accepts_matching_line(good_bundle: Path, tmp_path: Path) -> None:
    checksums = _write_checksums(tmp_path / "SHA256SUMS", good_bundle)

    problems, _ = verify_bundle(bundle=good_bundle, checksums=checksums)

    assert problems == []


def test_standalone_checksums_accepts_latest_alias_line(good_bundle: Path, tmp_path: Path) -> None:
    checksums = _write_checksums(
        tmp_path / "SHA256SUMS", good_bundle, name="maa-llm-wiki-catalog-latest.zip"
    )

    problems, _ = verify_bundle(bundle=good_bundle, checksums=checksums)

    assert problems == []


def test_standalone_checksums_rejects_wrong_digest(good_bundle: Path, tmp_path: Path) -> None:
    checksums = tmp_path / "SHA256SUMS"
    checksums.write_text(f"{'0' * 64}  {good_bundle.name}\n", encoding="utf-8")

    problems, _ = verify_bundle(bundle=good_bundle, checksums=checksums)

    assert len(problems) == 1
    assert "no SHA256SUMS entry matches" in problems[0]


def test_standalone_checksums_reports_unreadable_file(good_bundle: Path, tmp_path: Path) -> None:
    problems, _ = verify_bundle(bundle=good_bundle, checksums=tmp_path / "absent-SHA256SUMS")

    assert len(problems) == 1
    assert "cannot read checksums file" in problems[0]


@pytest.mark.parametrize("mutation", MUTATIONS)
def test_standalone_rejects_every_tampered_bundle(
    mutation: str, good_bundle: Path, tmp_path: Path
) -> None:
    target = _tampered(mutation, good_bundle, tmp_path)

    problems, _ = verify_bundle(bundle=target, expect_version=VERSION)

    assert bool(problems) == (mutation != "good")


def test_standalone_imports_only_the_standard_library() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module.split(".")[0])
    assert modules <= {
        "__future__",
        "argparse",
        "collections",
        "hashlib",
        "json",
        "pathlib",
        "re",
        "sys",
        "typing",
        "zipfile",
    }
    assert "maa_llm_wiki" not in modules


def test_standalone_runs_as_a_bare_script(good_bundle: Path) -> None:
    payload = _manifest(good_bundle)
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(SCRIPT),
            "--bundle",
            str(good_bundle),
            "--expect-version",
            VERSION,
            "--expect-revision",
            str(payload["wiki_revision"]),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == _summary(good_bundle)
    assert result.stderr == ""


def test_standalone_reports_corruption_without_traceback(
    good_bundle: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("corrupted_member", "truncated_bundle"):
        target = _tampered(name, good_bundle, tmp_path)
        capsys.readouterr()
        assert main(["--bundle", str(target)]) == 1
        captured = capsys.readouterr()
        assert captured.err.startswith("error: ")
        assert "Traceback" not in captured.err
