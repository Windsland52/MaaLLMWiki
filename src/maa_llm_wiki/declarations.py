"""Declared API elements of indexed upstream files.

Each parser turns the text of one upstream file into ``Declaration`` values. The extractor compares
the declarations of consecutive releases: a symbol that appears was added, one that disappears was
removed, and one whose signature differs was modified or deprecated. The C/C++ header parser and
the binding parsers live in their own modules; this module holds the shared types, the JSON-schema
and protocol-version-table parsers, and the dispatch from an indexed path to its parser.
"""

from __future__ import annotations

import json
import re
from bisect import bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import cast

from .models import MachineChangeKind


class DeclarationParseError(ValueError):
    """Upstream text that a declaration parser cannot read."""


@dataclass(frozen=True)
class Declaration:
    """One declared API element of one upstream file.

    ``symbol`` identifies the element across releases. ``signature`` is the normalized text whose
    change counts as a modification; it leaves out comments, formatting and deprecation markers, so
    deprecating an element is reported on its own. ``quote`` is upstream text for display, and
    ``note`` carries the upstream deprecation text when ``deprecated`` is set.
    """

    kind: MachineChangeKind
    symbol: str
    signature: str
    quote: str
    deprecated: bool = False
    note: str = ""


DeclarationKey = tuple[MachineChangeKind, str]
Parser = Callable[[str], list[Declaration]]

PYTHON_BINDING_ROOT = "source/binding/Python/"
NODEJS_BINDING_ROOT = "source/binding/NodeJS/src/apis/"

# Schema and documentation symbols are only unique within their file; every other kind names a
# global C symbol, a Python ``module:qualname`` or a NodeJS declaration.
PER_FILE_KINDS = frozenset(
    {
        MachineChangeKind.SCHEMA_DEFINITION,
        MachineChangeKind.SCHEMA_BRANCH,
        MachineChangeKind.SCHEMA_PROPERTY,
        MachineChangeKind.SCHEMA_ENUM,
        MachineChangeKind.SCHEMA_DEFAULT,
        MachineChangeKind.SCHEMA_REQUIRED,
        MachineChangeKind.DOCUMENTATION_VERSION,
    }
)

_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION_SPACING = re.compile(r"\s*([()\[\]{}<>,;:=|&*?!+\-/%^~])\s*")
_TRAILING_SEPARATOR = re.compile(r"[,;]+([)\]}>])")


def squash(text: str) -> str:
    """Collapse runs of whitespace, so reformatting does not read as a change."""
    return _WHITESPACE.sub(" ", text).strip()


def compact(text: str) -> str:
    """A formatting-independent form of declaration text, for use as a signature.

    Whitespace collapses, spaces next to punctuation disappear, and a separator before a closing
    bracket is dropped, so `f(\\n  int a,\\n)` and `f(int a)` compare equal. Spaces between two
    words remain, so `unsigned long` and `unsignedlong` stay different.
    """
    text = _PUNCTUATION_SPACING.sub(r"\1", squash(text))
    return _TRAILING_SEPARATOR.sub(r"\1", text)


# --------------------------------------------------------------------------------------
# Source scanning shared by the C and TypeScript parsers
# --------------------------------------------------------------------------------------

_OPENING_BRACKET = {")": "(", "]": "[", "}": "{"}
_COMMENT_MARKERS = re.compile(r"^\s*(?:/\*+!?|//+[!/<]?|\*+(?!/))?\s*")
_DEPRECATED_LINE = re.compile(r"@deprecated\b|^deprecated\b", re.IGNORECASE)


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def blank(chars: list[str], start: int, stop: int, fill: str = " ") -> None:
    """Overwrite a span in place, keeping newlines so that offsets and line numbers stay put."""
    for index in range(start, stop):
        if chars[index] != "\n":
            chars[index] = fill


@dataclass(frozen=True)
class SourceText:
    """Views of one source file that share the offsets of the original text.

    ``code`` has every comment replaced by spaces. ``masked`` additionally replaces the contents of
    string literals, so brackets and separators inside strings do not count as structure.
    """

    code: str
    masked: str
    comments: tuple[tuple[int, int, str], ...]
    comment_ends: tuple[int, ...]

    def leading_comments(self, start: int) -> list[str]:
        """The comments directly above ``start``, each on a line of its own, in file order.

        A comment that ends a line holding other code belongs to that code, not to the
        declaration below it.
        """
        found: list[str] = []
        position = start
        index = bisect_right(self.comment_ends, position) - 1
        while index >= 0:
            comment_start, comment_end, body = self.comments[index]
            if self.masked[comment_end:position].strip():
                break
            line_start = self.masked.rfind("\n", 0, comment_start) + 1
            if self.masked[line_start:comment_start].strip():
                break
            found.append(body)
            position = comment_start
            index -= 1
        found.reverse()
        return found

    def deprecation_note(self, start: int) -> str:
        """The deprecation sentence of the comments above ``start``, or an empty string."""
        for body in self.leading_comments(start):
            for raw in body.splitlines():
                line = _COMMENT_MARKERS.sub("", raw).strip()
                line = line.removesuffix("*/").strip()
                if _DEPRECATED_LINE.search(line):
                    return squash(line)
        return ""


def scan_source(text: str, quotes: str, *, multiline_quotes: str = "") -> SourceText:
    """Locate the comments and string literals of C-family source text.

    ``quotes`` are the string delimiters; a literal ends at its closing quote or at the end of the
    line, except for the delimiters in ``multiline_quotes``.
    """
    code = list(text)
    masked = list(text)
    comments: list[tuple[int, int, str]] = []
    index = 0
    size = len(text)
    while index < size:
        char = text[index]
        if text.startswith("//", index):
            stop = text.find("\n", index)
            stop = size if stop < 0 else stop
        elif text.startswith("/*", index):
            stop = text.find("*/", index + 2)
            if stop < 0:
                raise DeclarationParseError(
                    f"unterminated comment at line {line_number(text, index)}"
                )
            stop += 2
        elif char in quotes:
            stop = index + 1
            while stop < size and text[stop] != char:
                if text[stop] == "\n" and char not in multiline_quotes:
                    break
                stop += 2 if text[stop] == "\\" else 1
            blank(masked, index + 1, min(stop, size), "_")
            index = stop + 1
            continue
        else:
            index += 1
            continue
        comments.append((index, stop, text[index:stop]))
        blank(code, index, stop)
        blank(masked, index, stop)
        index = stop
    return SourceText(
        code="".join(code),
        masked="".join(masked),
        comments=tuple(comments),
        comment_ends=tuple(stop for _, stop, _ in comments),
    )


def bracket_pairs(masked: str) -> dict[int, int]:
    """Map the offset of every opening bracket to the offset of its closing bracket."""
    pairs: dict[int, int] = {}
    stack: list[int] = []
    for index, char in enumerate(masked):
        if char in "([{":
            stack.append(index)
        elif char in ")]}":
            if not stack or masked[stack[-1]] != _OPENING_BRACKET[char]:
                raise DeclarationParseError(
                    f"unbalanced '{char}' at line {line_number(masked, index)}"
                )
            pairs[stack.pop()] = index
    if stack:
        raise DeclarationParseError(
            f"unclosed '{masked[stack[-1]]}' at line {line_number(masked, stack[-1])}"
        )
    return pairs


def merge_declarations(declarations: Iterable[Declaration]) -> dict[DeclarationKey, Declaration]:
    """Fold repeated declarations of one symbol into one.

    Overloads, accessor pairs and declarations repeated in ``#if``/``#else`` branches share a
    symbol. The merged signature lists every distinct signature in sorted order, and the symbol is
    deprecated when any of its declarations is.
    """
    grouped: dict[DeclarationKey, list[Declaration]] = {}
    for declaration in declarations:
        grouped.setdefault((declaration.kind, declaration.symbol), []).append(declaration)
    merged: dict[DeclarationKey, Declaration] = {}
    for key, items in grouped.items():
        notes = [item.note for item in items if item.note]
        merged[key] = replace(
            items[0],
            signature=" | ".join(sorted({item.signature for item in items})),
            deprecated=any(item.deprecated for item in items),
            note=notes[0] if notes else "",
        )
    return merged


def python_module(path: str) -> str:
    """Dotted module name of an in-tree Python binding file, such as ``maa.agent.agent_server``."""
    parts = list(PurePosixPath(path.removeprefix(PYTHON_BINDING_ROOT)).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def parser_for(path: str) -> Parser | None:
    """The declaration parser for an indexed path, or None when the file declares no API."""
    name = PurePosixPath(path).name
    if path.startswith("include/") and name.endswith((".h", ".hpp")):
        from .c_declarations import parse_c_header

        return parse_c_header
    if path.startswith(PYTHON_BINDING_ROOT) and name.endswith(".py"):
        from .binding_declarations import parse_python_module

        module = python_module(path)
        return lambda text: parse_python_module(text, module)
    if path.startswith(NODEJS_BINDING_ROOT) and name.endswith(".d.ts"):
        from .binding_declarations import parse_typescript_declarations

        return parse_typescript_declarations
    if path.startswith("tools/") and name.endswith(".schema.json"):
        return parse_json_schema
    if path.startswith("docs/") and name.endswith(".md") and name.startswith(("3.1-", "3.3-")):
        return parse_version_table
    return None


# --------------------------------------------------------------------------------------
# JSON schemas
# --------------------------------------------------------------------------------------

_SCHEMA_DEFINITIONS = ("$defs", "definitions")
_SCHEMA_COMBINATORS = ("allOf", "anyOf", "oneOf")
_SCHEMA_CLOSURES = ("additionalProperties", "unevaluatedProperties")
# Keywords that constrain a node itself; a change to any of them is a modification of the node.
_SCHEMA_SIGNATURE_KEYS = frozenset(
    {
        "$ref",
        "type",
        "format",
        "pattern",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
    }
)
# Prose and editor hints: neither declarations nor schemas to descend into.
_SCHEMA_ANNOTATIONS = frozenset(
    {
        "$comment",
        "$id",
        "$schema",
        "title",
        "description",
        "markdownDescription",
        "examples",
        "defaultSnippets",
        "deprecated",
        "enumDescriptions",
        "markdownEnumDescriptions",
        "errorMessage",
    }
)
# Child schemas, which are declarations of their own and stay out of a node's quote.
_SCHEMA_CHILDREN = frozenset(
    {
        "properties",
        "patternProperties",
        "items",
        "prefixItems",
        "contains",
        "if",
        "then",
        "else",
        "not",
        "dependentSchemas",
        "propertyNames",
        "defaultSnippets",
        *_SCHEMA_DEFINITIONS,
        *_SCHEMA_COMBINATORS,
    }
)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): item for key, item in cast("dict[object, object]", value).items()}


def _sequence(value: object) -> list[object]:
    return cast("list[object]", value) if isinstance(value, list) else []


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def _schema_element(kind: MachineChangeKind, symbol: str, node: dict[str, object]) -> Declaration:
    signature = {
        key: value
        for key, value in node.items()
        if key in _SCHEMA_SIGNATURE_KEYS or (key in _SCHEMA_CLOSURES and isinstance(value, bool))
    }
    deprecated = node.get("deprecated") is True
    shown = {key: value for key, value in node.items() if key not in _SCHEMA_CHILDREN}
    return Declaration(
        kind=kind,
        symbol=symbol,
        signature=_canonical(signature),
        quote=_canonical(shown),
        deprecated=deprecated,
        note='"deprecated": true' if deprecated else "",
    )


def _schema_value(kind: MachineChangeKind, symbol: str, value: object) -> Declaration:
    text = _canonical(value)
    return Declaration(kind=kind, symbol=symbol, signature=text, quote=text)


def _branch_label(branch: dict[str, object], index: int) -> str:
    """Name a combinator branch by what it declares, falling back to its position.

    The label is the branch title, its reference, a `const` discriminator, its required names or
    its type, in that order. A position shifts whenever an earlier branch is inserted, so it is only
    the last resort.
    """
    title = branch.get("title")
    if isinstance(title, str) and title:
        return title
    reference = branch.get("$ref")
    if isinstance(reference, str) and reference:
        return reference
    for holder in (_mapping(branch.get("if")), branch):
        properties = _mapping(holder.get("properties")) if holder is not None else None
        for name, spec in (properties or {}).items():
            spec_node = _mapping(spec)
            if spec_node is not None and "const" in spec_node:
                return f"{name}={_canonical(spec_node['const'])}"
    required = [item for item in _sequence(branch.get("required")) if isinstance(item, str)]
    if required:
        return "required=" + ",".join(sorted(required))
    if "type" in branch:
        return f"type={_canonical(branch['type'])}"
    return f"#{index}"


def _walk_schema(node: dict[str, object], path: str, out: list[Declaration]) -> None:
    for key, value in node.items():
        if key in ("properties", "patternProperties"):
            for name, child in (_mapping(value) or {}).items():
                child_node = _mapping(child)
                if child_node is None:
                    continue
                child_path = _join(path, name)
                out.append(
                    _schema_element(MachineChangeKind.SCHEMA_PROPERTY, child_path, child_node)
                )
                _walk_schema(child_node, child_path, out)
        elif key in _SCHEMA_DEFINITIONS:
            for name, child in (_mapping(value) or {}).items():
                child_node = _mapping(child)
                if child_node is None:
                    continue
                child_path = _join(path, f"{key}.{name}")
                out.append(
                    _schema_element(MachineChangeKind.SCHEMA_DEFINITION, child_path, child_node)
                )
                _walk_schema(child_node, child_path, out)
        elif key in _SCHEMA_COMBINATORS:
            branches = [
                (index, branch_node)
                for index, branch in enumerate(_sequence(value))
                if (branch_node := _mapping(branch)) is not None
            ]
            labels = [_branch_label(branch_node, index) for index, branch_node in branches]
            repeated = {label for label in labels if labels.count(label) > 1}
            for (index, branch_node), label in zip(branches, labels, strict=True):
                if label in repeated:
                    label = f"{label}#{index}"
                branch_path = _join(path, f"{key}[{label}]")
                # The branch itself is an element: a `$ref`-only branch declares nothing else.
                out.append(
                    _schema_element(MachineChangeKind.SCHEMA_BRANCH, branch_path, branch_node)
                )
                _walk_schema(branch_node, branch_path, out)
        elif key in ("items", "prefixItems"):
            item_node = _mapping(value)
            if item_node is not None:
                _walk_schema(item_node, f"{path}[]", out)
            for index, item in enumerate(_sequence(value)):
                indexed = _mapping(item)
                if indexed is not None:
                    _walk_schema(indexed, f"{path}[{index}]", out)
        elif key == "enum":
            for item in _sequence(value):
                symbol = f"{path} = {_canonical(item)}" if path else _canonical(item)
                out.append(_schema_value(MachineChangeKind.SCHEMA_ENUM, symbol, item))
        elif key == "const":
            symbol = f"{path} = {_canonical(value)}" if path else _canonical(value)
            out.append(_schema_value(MachineChangeKind.SCHEMA_ENUM, symbol, value))
        elif key == "required":
            for item in _sequence(value):
                if isinstance(item, str):
                    out.append(
                        _schema_value(MachineChangeKind.SCHEMA_REQUIRED, _join(path, item), item)
                    )
        elif key == "default":
            out.append(_schema_value(MachineChangeKind.SCHEMA_DEFAULT, path or "(root)", value))
        elif key not in _SCHEMA_ANNOTATIONS:
            child_node = _mapping(value)
            if child_node is not None:
                _walk_schema(child_node, _join(path, key), out)


def parse_json_schema(text: str) -> list[Declaration]:
    """Definitions, combinator branches, properties, enum and const values, required names and
    defaults of a schema.

    Symbols are dotted paths that leave out ``properties``, so ``$defs.Shell.cmd`` is the ``cmd``
    property of the ``Shell`` definition. Each ``allOf``/``anyOf``/``oneOf`` branch is an element
    of its own, ``anyOf[label]``, so a branch that only references a definition
    (``$defs.ActionV1.anyOf[#/$defs/ShellV1]``) is visible; array items appear as ``[]``.
    """
    try:
        document: object = json.loads(text)
    except json.JSONDecodeError as error:
        raise DeclarationParseError(f"invalid JSON: {error}") from error
    root = _mapping(document)
    if root is None:
        raise DeclarationParseError("the schema root is not an object")
    declarations: list[Declaration] = []
    _walk_schema(root, "", declarations)
    return declarations


# --------------------------------------------------------------------------------------
# Protocol version tables
# --------------------------------------------------------------------------------------

# `| 2026-01-30 | v2.1.0 | ... |` in document 3.3 and `| v5.3 | ... |` in document 3.1.
_VERSION_ROW = re.compile(
    r"^\|\s*(?:\d{4}-\d{1,2}-\d{1,2}\s*\|\s*)?(?P<version>v\d+(?:\.\d+)*)\s*\|"
)


def parse_version_table(text: str) -> list[Declaration]:
    """Rows of the protocol version tables in documents 3.1 and 3.3, keyed by protocol version."""
    declarations: list[Declaration] = []
    for line in text.splitlines():
        row = line.strip()
        match = _VERSION_ROW.match(row)
        if match is not None:
            declarations.append(
                Declaration(
                    kind=MachineChangeKind.DOCUMENTATION_VERSION,
                    symbol=match["version"],
                    signature=compact(row),
                    quote=row,
                )
            )
    return declarations
