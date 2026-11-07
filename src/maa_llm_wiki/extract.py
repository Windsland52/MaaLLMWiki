"""Machine-extracted change facts between consecutive MaaFramework releases.

Each registered release pins every indexed file to a git blob id. Files that declare API elements
(headers, in-tree bindings, JSON schemas and the protocol version tables of documents 3.1 and 3.3)
are parsed at every release with ``declarations.parser_for``. For each pair of consecutive releases
the declared elements are compared: an element that appears is ``added``, one that disappears is
``removed``, one whose signature differs is ``modified``, and one that gains a deprecation marker is
``deprecated``. C declarations, in-tree Python modules and NodeJS declarations are compared across
all files of their language, so a declaration that only moves to another file is not reported;
schema and documentation elements are compared within their file.

A changed header, binding or schema file that no element record accounts for, or any parsed file
that cannot be parsed, gets one ``unclassified`` record, so a change the parsers cannot see stays
visible. Documents 3.1 and 3.3 are parsed only for their version tables, and the rest of the
documentation not at all: their prose changes are left to the "Changed since" lists of the version
pages.
"""

from __future__ import annotations

import subprocess
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote as url_quote

from .declarations import (
    NODEJS_BINDING_ROOT,
    PER_FILE_KINDS,
    PYTHON_BINDING_ROOT,
    Declaration,
    DeclarationParseError,
    parser_for,
    squash,
)
from .models import (
    MachineChange,
    MachineChangeCatalog,
    MachineChangeKind,
    ReleaseRecord,
    SourceInventory,
)
from .validation import load_release_catalog, load_source_inventories

QUOTE_LIMIT = 300
CHANGE_ORDER = {"added": 0, "removed": 1, "modified": 2, "deprecated": 3}

_LANGUAGE_SCOPES = (
    ("include/", "c"),
    (PYTHON_BINDING_ROOT, "python"),
    (NODEJS_BINDING_ROOT, "nodejs"),
)


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def element_scope(path: str, kind: MachineChangeKind) -> str:
    """The set of files within which a symbol identifies one element.

    Schema and documentation symbols are unique within their file; C symbols, Python
    ``module:qualname`` symbols and NodeJS declarations are unique within their language.
    """
    if kind not in PER_FILE_KINDS:
        for prefix, scope in _LANGUAGE_SCOPES:
            if path.startswith(prefix):
                return scope
    return path


@dataclass(frozen=True)
class _Parsed:
    declarations: tuple[Declaration, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class _Element:
    signature: str
    quote: str
    deprecated: bool
    note: str
    paths: tuple[str, ...]


_ElementKey = tuple[str, MachineChangeKind, str]


def _trim(text: str) -> str:
    return squash(text)[:QUOTE_LIMIT]


_CONTEXT_BEFORE_DIFFERENCE = 60
_ELISION = "…"


def _contrast(old: str, new: str) -> tuple[str, str]:
    """The previous and current quotes of a modified element, cut so their difference shows.

    Quotes are cut at the record limit, so two long quotes that differ only after the limit would
    look identical; both then start shortly before their first difference, marked with an
    ellipsis.
    """
    old, new = squash(old), squash(new)
    if old[:QUOTE_LIMIT] != new[:QUOTE_LIMIT]:
        return old, new
    first = next(
        (index for index, (a, b) in enumerate(zip(old, new, strict=False)) if a != b),
        min(len(old), len(new)),
    )
    start = max(0, first - _CONTEXT_BEFORE_DIFFERENCE)
    room = QUOTE_LIMIT - len(_ELISION)
    return _ELISION + old[start:][:room], _ELISION + new[start:][:room]


def _read_blobs(repository: Path, blobs: Iterable[str]) -> dict[str, bytes]:
    """Read git blobs by id through one `git cat-file --batch` process."""
    ordered = sorted(set(blobs))
    if not ordered:
        return {}
    result = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=repository,
        check=True,
        capture_output=True,
        input="".join(f"{blob}\n" for blob in ordered).encode("ascii"),
    )
    data = result.stdout
    contents: dict[str, bytes] = {}
    position = 0
    for blob in ordered:
        end = data.index(b"\n", position)
        fields = data[position:end].decode("ascii", "replace").split(" ")
        position = end + 1
        if len(fields) != 3:
            raise ValueError(f"the upstream clone has no blob {blob}; fetch the indexed releases")
        size = int(fields[2])
        contents[blob] = data[position : position + size]
        position += size + 1
    return contents


def _parse(path: str, content: bytes) -> _Parsed:
    parser = parser_for(path)
    if parser is None:
        return _Parsed()
    try:
        text = content.decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeDecodeError as error:
        return _Parsed(error=f"not UTF-8 text ({error.reason})")
    try:
        return _Parsed(declarations=tuple(parser(text)))
    except DeclarationParseError as error:
        return _Parsed(error=str(error) or type(error).__name__)


def _parsed_files(inventory: SourceInventory) -> dict[str, str]:
    """Indexed paths that have a declaration parser, mapped to their blob ids."""
    files: dict[str, str] = {}
    for artifact in inventory.artifacts:
        if parser_for(artifact.path) is None:
            continue
        if artifact.blob is None:
            raise ValueError(
                f"MaaFramework inventory {inventory.version} has no blob for {artifact.path}"
            )
        files[artifact.path] = artifact.blob
    return files


def _elements(files: dict[str, tuple[Declaration, ...]]) -> dict[_ElementKey, _Element]:
    """Fold the declarations of a set of files into one element per scoped symbol."""
    grouped: defaultdict[_ElementKey, list[tuple[str, Declaration]]] = defaultdict(list)
    for path in sorted(files):
        for declaration in files[path]:
            scope = element_scope(path, declaration.kind)
            grouped[(scope, declaration.kind, declaration.symbol)].append((path, declaration))
    elements: dict[_ElementKey, _Element] = {}
    for key, items in grouped.items():
        quotes = list(dict.fromkeys(item.quote.strip() for _, item in items if item.quote.strip()))
        notes = [item.note for _, item in items if item.note]
        elements[key] = _Element(
            signature=" | ".join(sorted({item.signature for _, item in items})),
            quote=" | ".join(quotes) or key[2],
            deprecated=any(item.deprecated for _, item in items),
            note=notes[0] if notes else "",
            paths=tuple(sorted({path for path, _ in items})),
        )
    return elements


def _record(
    release: ReleaseRecord,
    change: str,
    kind: MachineChangeKind,
    symbol: str,
    quote: str,
    paths: Iterable[str],
    previous_quote: str | None = None,
) -> MachineChange:
    previous = _trim(previous_quote) if previous_quote is not None else ""
    return MachineChange.model_validate(
        {
            "version": release.version,
            "commit": release.commit,
            "change": change,
            "kind": kind,
            "symbol": symbol,
            "quote": _trim(quote) or symbol[:QUOTE_LIMIT],
            "previous_quote": previous or None,
            "paths": list(paths),
        }
    )


def _diff(
    release: ReleaseRecord,
    before: dict[_ElementKey, _Element],
    after: dict[_ElementKey, _Element],
) -> tuple[list[MachineChange], set[str]]:
    """Records for every element that changed, and the files those elements live in."""
    records: list[MachineChange] = []
    touched: set[str] = set()
    for key in sorted(before.keys() | after.keys()):
        _, kind, symbol = key
        old = before.get(key)
        new = after.get(key)
        count = len(records)
        if old is None and new is not None:
            records.append(_record(release, "added", kind, symbol, new.quote, new.paths))
        elif new is None and old is not None:
            records.append(_record(release, "removed", kind, symbol, old.quote, old.paths))
        elif old is not None and new is not None:
            if old.signature != new.signature:
                previous_quote, quote = _contrast(old.quote, new.quote)
                records.append(
                    _record(release, "modified", kind, symbol, quote, new.paths, previous_quote)
                )
            if new.deprecated and not old.deprecated:
                records.append(
                    _record(release, "deprecated", kind, symbol, new.note or new.quote, new.paths)
                )
            elif old.deprecated and not new.deprecated and old.signature == new.signature:
                records.append(
                    _record(
                        release,
                        "modified",
                        kind,
                        symbol,
                        new.quote,
                        new.paths,
                        old.note or old.quote,
                    )
                )
        if len(records) > count:
            touched.update(old.paths if old is not None else ())
            touched.update(new.paths if new is not None else ())
    return records, touched


def _unexplained_note(path: str, change: str, declares: bool) -> str:
    """Why a changed file has no element record."""
    if change == "added":
        if declares:
            return f"{path} was added; every element it declares is declared in another file"
        return f"{path} was added without declared elements"
    if change == "removed":
        if declares:
            return f"{path} was removed; every element it declared is declared in another file"
        return f"{path} was removed without declared elements"
    return f"{path} changed without changing any declared element"


def _pair_records(
    release: ReleaseRecord,
    previous_files: dict[str, str],
    current_files: dict[str, str],
    parse: Callable[[str, str], _Parsed],
) -> list[MachineChange]:
    paths = sorted(previous_files.keys() | current_files.keys())
    changed = [path for path in paths if previous_files.get(path) != current_files.get(path)]
    if not changed:
        return []

    before: dict[str, tuple[Declaration, ...]] = {}
    after: dict[str, tuple[Declaration, ...]] = {}
    failures: dict[str, str] = {}
    for path in paths:
        old = parse(path, previous_files[path]) if path in previous_files else None
        new = parse(path, current_files[path]) if path in current_files else None
        old_declarations = old.declarations if old is not None and old.error is None else None
        new_declarations = new.declarations if new is not None and new.error is None else None
        # A side that cannot be parsed borrows the other side's declarations, so the failure
        # surfaces as one unclassified record instead of a burst of false additions or removals.
        if old is not None:
            before[path] = (
                old_declarations if old_declarations is not None else new_declarations or ()
            )
        if new is not None:
            after[path] = (
                new_declarations if new_declarations is not None else old_declarations or ()
            )
        error = (new.error if new is not None else None) or (old.error if old is not None else None)
        if error is not None and path in changed:
            failures[path] = error

    records, accounted = _diff(release, _elements(before), _elements(after))
    for path in changed:
        change = (
            "added"
            if path not in previous_files
            else "removed"
            if path not in current_files
            else "modified"
        )
        if path in failures:
            note = f"{path} could not be parsed: {failures[path]}"
        elif path in accounted or path.startswith("docs/"):
            continue
        else:
            declares = bool(after.get(path) or before.get(path))
            note = _unexplained_note(path, change, declares)
        records.append(
            _record(release, change, MachineChangeKind.UNCLASSIFIED, path, note, (path,))
        )
    return records


def record_sort_key(record: MachineChange) -> tuple[object, ...]:
    return (
        version_key(record.version),
        record.paths[0],
        record.kind.value,
        record.symbol,
        CHANGE_ORDER[record.change],
        record.quote,
    )


def build_machine_changes(root: Path, repository: Path) -> MachineChangeCatalog:
    """Extract the machine-change records for every pair of consecutive registered releases."""
    releases = load_release_catalog(root).releases
    inventories = {inventory.version: inventory for inventory in load_source_inventories(root)}
    files_by_version = {
        version: _parsed_files(inventory) for version, inventory in inventories.items()
    }
    contents = _read_blobs(
        repository, (blob for files in files_by_version.values() for blob in files.values())
    )
    cache: dict[tuple[str, str], _Parsed] = {}

    def parse(path: str, blob: str) -> _Parsed:
        key = (path, blob)
        if key not in cache:
            cache[key] = _parse(path, contents[blob])
        return cache[key]

    records: list[MachineChange] = []
    for previous, release in zip(releases, releases[1:], strict=False):
        previous_files = files_by_version.get(previous.version)
        current_files = files_by_version.get(release.version)
        if previous_files is None or current_files is None:
            continue
        records.extend(_pair_records(release, previous_files, current_files, parse))
    records.sort(key=record_sort_key)
    return MachineChangeCatalog(source_id="maafw", changes=records)


# --------------------------------------------------------------------------------------
# Rendered pages
# --------------------------------------------------------------------------------------

_GENERATOR = "maa-wiki-sync-maafw-history"
_PAGE_QUOTE_LIMIT = 200
_LATER_CHANGES_LIMIT = 6
_CHANGES = tuple(CHANGE_ORDER)


def code_span(text: str) -> str:
    """Inline code that survives backticks inside the text."""
    if "`" not in text:
        return f"`{text}`"
    return f"`` {text} ``"


def _file_link(repository_url: str, commit: str, path: str) -> str:
    url = f"{repository_url.rstrip('/')}/blob/{commit}/{url_quote(path, safe='/')}"
    return f"[`{path}`]({url})"


def _version_link(version: str) -> str:
    return f"[{version}](./{version}/index.md)"


def _page_quote(text: str) -> str:
    shortened = text if len(text) <= _PAGE_QUOTE_LIMIT else text[: _PAGE_QUOTE_LIMIT - 1] + "…"
    return code_span(shortened)


def _record_line(change: MachineChange) -> str:
    if change.kind is MachineChangeKind.UNCLASSIFIED:
        return f"- {change.change} file: {change.quote}"
    line = f"- {change.change} {change.kind.value} {code_span(change.symbol)}: "
    line += _page_quote(change.quote)
    if change.previous_quote is not None:
        line += f" (was {_page_quote(change.previous_quote)})"
    extra = change.paths[1:]
    if extra:
        line += " — also in " + ", ".join(f"`{path}`" for path in extra)
    return line


def render_machine_changes_page(catalog: MachineChangeCatalog, repository_url: str) -> str:
    """Render the machine-change records, newest release first, grouped by file."""
    by_version: defaultdict[str, list[MachineChange]] = defaultdict(list)
    for change in catalog.changes:
        by_version[change.version].append(change)
    versions = sorted(by_version, key=version_key, reverse=True)
    kind_counts = Counter(change.kind.value for change in catalog.changes)

    lines = [
        f"<!-- Generated by {_GENERATOR}. Do not edit manually. -->",
        "# Machine changes",
        "",
        "Declared API elements that changed between consecutive registered releases, extracted "
        "mechanically from the pinned upstream files: C/C++ headers, the in-tree Python and "
        "NodeJS bindings, the JSON schemas and the protocol version tables of documents 3.1 and "
        "3.3. Each record compares a release with the previous registered release: `added` and "
        "`removed` elements, `modified` signatures (with the previous text) and `deprecated` "
        "markers. An `unclassified` record marks a changed header, binding or schema file whose "
        "declared elements did not change (comments or formatting changed, or a construct the "
        "parser does not read), or a file that could not be parsed. Prose documentation changes, "
        "including the prose of documents 3.1 and 3.3, appear only in each version's "
        "`Changed since` list.",
        "",
        "Quotes are upstream text with whitespace collapsed, cut at 300 characters; a modified "
        "pair that would look identical after the cut starts with `…` just before the first "
        "difference. Quotes show what changed, not what it means at run time; read the pinned file "
        "before relying on a record.",
        "",
        "[← Version index](./index.md) · [Symbols](./machine-symbols.md) · "
        "[Upstream commits](./upstream-commits.md) · [Topics](./topics.md)",
        "",
        "Source of truth: `sources/maa-framework/machine-changes.yaml` "
        f"({len(catalog.changes)} records over {len(versions)} releases).",
        "",
        "| Kind | Records |",
        "| --- | --- |",
        *(f"| `{kind}` | {kind_counts[kind]} |" for kind in sorted(kind_counts)),
        "",
        "| Release | " + " | ".join(_CHANGES) + " | unclassified |",
        "| --- |" + " --- |" * (len(_CHANGES) + 1),
    ]
    for version in versions:
        group = by_version[version]
        counts = Counter(
            "unclassified" if change.kind is MachineChangeKind.UNCLASSIFIED else change.change
            for change in group
        )
        cells = " | ".join(str(counts[name]) for name in (*_CHANGES, "unclassified"))
        lines.append(f"| {_version_link(version)} | {cells} |")
    lines.append("")

    for version in versions:
        group = by_version[version]
        commit = group[0].commit
        lines.extend([f"## {_version_link(version)}", "", f"Revision: `{commit}`", ""])
        by_path: defaultdict[str, list[MachineChange]] = defaultdict(list)
        for change in group:
            by_path[change.paths[0]].append(change)
        for path in sorted(by_path):
            lines.extend([f"### {_file_link(repository_url, commit, path)}", ""])
            lines.extend(_record_line(change) for change in by_path[path])
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_machine_symbols_page(catalog: MachineChangeCatalog, *, first_release: str) -> str:
    """Index the machine-change records by element: introduction and later changes."""
    groups: defaultdict[_ElementKey, list[MachineChange]] = defaultdict(list)
    for change in catalog.changes:
        if change.kind is MachineChangeKind.UNCLASSIFIED:
            continue
        groups[(element_scope(change.paths[0], change.kind), change.kind, change.symbol)].append(
            change
        )

    lines = [
        f"<!-- Generated by {_GENERATOR}. Do not edit manually. -->",
        "# Machine change symbols",
        "",
        "Every declared element that changed in at least one release pair, with the release that "
        "introduced it and its later changes. *Introduced* is the release whose previous "
        "registered release did not declare the element; *≤ "
        f"{first_release}* means it was already declared in `{first_release}`, the first indexed "
        "release. An element that never changed is not listed: read the pinned file of the release "
        "you target. C declarations, Python `module:name` symbols and NodeJS declarations are "
        "tracked across all files of their language; schema and documentation symbols within "
        "their file.",
        "",
        "[← Version index](./index.md) · [Machine changes](./machine-changes.md) · "
        "[Upstream commits](./upstream-commits.md)",
        "",
        f"{len(groups)} elements. Source of truth: `sources/maa-framework/machine-changes.yaml`.",
        "",
        "| Symbol | Kind | File | Introduced | Later changes |",
        "| --- | --- | --- | --- | --- |",
    ]
    ordered = sorted(groups.items(), key=lambda item: (item[0][2], item[0][1].value, item[0][0]))
    for (_, kind, symbol), changes in ordered:
        changes.sort(key=lambda change: (version_key(change.version), CHANGE_ORDER[change.change]))
        first = changes[0]
        if first.change == "added":
            introduced = _version_link(first.version)
            later = changes[1:]
        else:
            introduced = f"≤ {first_release}"
            later = changes
        shown = [f"{_version_link(change.version)} {change.change}" for change in later]
        if len(shown) > _LATER_CHANGES_LIMIT:
            shown = [*shown[:_LATER_CHANGES_LIMIT], f"+{len(shown) - _LATER_CHANGES_LIMIT} more"]
        latest = changes[-1]
        files = ", ".join(f"`{path}`" for path in latest.paths)
        symbol_cell = code_span(symbol).replace("|", "\\|")
        lines.append(
            f"| {symbol_cell} | {kind.value} | {files} | {introduced} | {', '.join(shown)} |"
        )
    return "\n".join(lines) + "\n"
