"""Declarations of the in-tree Python and NodeJS bindings.

Python modules are read with :mod:`ast`. Symbols are ``module:qualname``: public functions and
classes, methods (public names plus ``__init__`` and ``__call__``), class attributes such as enum
members and dataclass fields, and public module-level names. Signatures are rebuilt from the syntax
tree, so docstrings, comments and formatting never count as a change.

The NodeJS ``.d.ts`` files are hand-written declaration files: ``declare global { namespace maa {
... } }`` around type aliases, interfaces, classes, functions and constants, with newline-terminated
members. A small scanner splits them into declarations and members, qualified by their enclosing
namespaces and declarations (``maa.Controller.post_click``, ``maa.ClickParam.contact``).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from .declarations import (
    Declaration,
    DeclarationParseError,
    SourceText,
    bracket_pairs,
    compact,
    scan_source,
    squash,
)
from .models import MachineChangeKind

_KIND = MachineChangeKind.BINDING_API

# --------------------------------------------------------------------------------------
# Python
# --------------------------------------------------------------------------------------

_PUBLIC_DUNDERS = frozenset({"__init__", "__call__"})
_DEPRECATED_DECORATORS = frozenset({"deprecated"})
# `.. deprecated::`, and the one-dot form that some upstream docstrings use.
_DEPRECATED_DIRECTIVE = re.compile(r"^\.\.? deprecated::")


def _call_name(node: ast.expr) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    return ""


def _docstring_deprecation(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str:
    """A deprecation stated by the docstring: a leading `Deprecated` or a `deprecated::` directive.

    A directive without text on its own line takes the next non-empty line as its text.
    """
    lines = [line.strip() for line in (ast.get_docstring(node) or "").splitlines()]
    if lines and lines[0].lower().startswith("deprecated"):
        return squash(lines[0])
    for index, line in enumerate(lines):
        if not _DEPRECATED_DIRECTIVE.match(line):
            continue
        if line.rstrip(":").endswith("deprecated"):
            following = next((item for item in lines[index + 1 :] if item), "")
            return squash(f"{line} {following}")
        return squash(line)
    return ""


def _warning_deprecation(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """A deprecation stated by a ``warnings.warn(..., DeprecationWarning)`` call in the body.

    Nested functions and classes are not searched: their warnings belong to them.
    """
    pending: list[ast.AST] = list(node.body)
    while pending:
        current = pending.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(current, ast.Call) and _call_name(current) == "warn":
            values = [*current.args, *(keyword.value for keyword in current.keywords)]
            if any(_call_name(value).endswith("DeprecationWarning") for value in values):
                message = current.args[0] if current.args else None
                if isinstance(message, ast.Constant) and isinstance(message.value, str):
                    return squash(f"DeprecationWarning: {message.value}")
                return "DeprecationWarning"
        pending.extend(ast.iter_child_nodes(current))
    return ""


class _PythonModule:
    def __init__(self, text: str, module: str) -> None:
        self.lines = text.splitlines()
        self.module = module
        self.declarations: list[Declaration] = []

    def _quote(self, node: ast.stmt) -> str:
        """The declaration's source from its first decorator up to the end of its header."""
        start = node.lineno - 1
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definition_line = start
            if node.decorator_list:
                start = min(item.lineno for item in node.decorator_list) - 1
            stop = max(definition_line + 1, node.body[0].lineno - 1) if node.body else start + 1
            text = " ".join(line.strip() for line in self.lines[start:stop])
            header_end = text.rfind(":")
            return squash(text[:header_end] if header_end > 0 else text)
        stop = node.end_lineno or node.lineno
        return squash(" ".join(line.strip() for line in self.lines[start:stop]))

    def _add(self, symbol: str, signature: str, node: ast.stmt, note: str) -> None:
        self.declarations.append(
            Declaration(
                kind=_KIND,
                symbol=f"{self.module}:{symbol}",
                signature=compact(signature),
                quote=self._quote(node),
                deprecated=bool(note),
                note=note,
            )
        )

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, owner: str) -> None:
        names = [_call_name(item) for item in node.decorator_list]
        deprecated = next(
            (
                ast.unparse(item)
                for item, name in zip(node.decorator_list, names, strict=True)
                if name in _DEPRECATED_DECORATORS
            ),
            "",
        )
        decorators = [
            f"@{ast.unparse(item)}"
            for item, name in zip(node.decorator_list, names, strict=True)
            if name not in _DEPRECATED_DECORATORS
        ]
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
        signature = " ".join(
            [*decorators, f"{prefix} {node.name}({ast.unparse(node.args)}){returns}"]
        )
        note = (
            f"@{deprecated}"
            if deprecated
            else _docstring_deprecation(node) or _warning_deprecation(node)
        )
        self._add(f"{owner}{node.name}", signature, node, note)

    def _class(self, node: ast.ClassDef, owner: str) -> None:
        arguments = [ast.unparse(base) for base in node.bases]
        arguments.extend(ast.unparse(keyword) for keyword in node.keywords)
        decorators = [f"@{ast.unparse(item)}" for item in node.decorator_list]
        heading = f"class {node.name}" + (f"({', '.join(arguments)})" if arguments else "")
        self._add(
            f"{owner}{node.name}",
            " ".join([*decorators, heading]),
            node,
            _docstring_deprecation(node),
        )
        self._body(node.body, f"{owner}{node.name}.", in_class=True)

    def _comment_deprecation(self, node: ast.stmt) -> str:
        """A `# Deprecated ...` comment in the comment block directly above a statement."""
        index = node.lineno - 2
        while index >= 0:
            line = self.lines[index].strip()
            if not line.startswith("#"):
                return ""
            body = line.lstrip("#").strip()
            if body.lower().startswith("deprecated"):
                return squash(body)
            index -= 1
        return ""

    def _assignment(self, node: ast.Assign | ast.AnnAssign, owner: str) -> None:
        """Public names bound by a simple assignment: constants, enum members, fields."""
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and not target.id.startswith("_"):
                note = self._comment_deprecation(node)
                self._add(f"{owner}{target.id}", ast.unparse(node), node, note)

    def _body(self, body: list[ast.stmt], owner: str, *, in_class: bool) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_") or node.name in _PUBLIC_DUNDERS and in_class:
                    self._function(node, owner)
            elif isinstance(node, ast.ClassDef):
                if not node.name.startswith("_"):
                    self._class(node, owner)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                self._assignment(node, owner)
            elif isinstance(node, ast.If):
                self._body(node.body, owner, in_class=in_class)
                self._body(node.orelse, owner, in_class=in_class)
            elif isinstance(node, ast.Try):
                for block in (node.body, node.orelse, node.finalbody):
                    self._body(block, owner, in_class=in_class)
                for handler in node.handlers:
                    self._body(handler.body, owner, in_class=in_class)

    def parse(self, text: str) -> list[Declaration]:
        try:
            tree = ast.parse(text)
        except SyntaxError as error:
            raise DeclarationParseError(f"Python syntax error at line {error.lineno}") from error
        self._body(tree.body, "", in_class=False)
        return self.declarations


def parse_python_module(text: str, module: str) -> list[Declaration]:
    """Public declarations of one in-tree Python binding module, as ``module:qualname``."""
    return _PythonModule(text, module).parse(text)


# --------------------------------------------------------------------------------------
# TypeScript declaration files
# --------------------------------------------------------------------------------------

_MODIFIERS = frozenset(
    {"export", "declare", "default", "abstract", "public", "private", "protected", "async"}
)
_CONTINUES_NEXT_LINE = ("|", "&", "?", ":", "=>", ".", "extends", "=")
_CONTINUES_FROM_END = ("=", "|", "&", ",", "=>", ":", "(", "<", "extends", "?")
_SKIPPED_STATEMENTS = ("import ", "export {", "export *", "///")
_ACCESSOR_WORDS = ("get", "set", "static", "readonly")
_DECLARATION = re.compile(
    r"^(?P<keyword>namespace|module|class|interface|type|function|const|let|var|enum)\b\s*"
    r"(?P<name>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)?"
)
_MEMBER_NAME = re.compile(
    r"^(?:(?:static|readonly|get|set|async|public|private|protected|abstract)\s+)*"
    r"(?P<name>[A-Za-z_$][\w$]*|'[^']*'|\"[^\"]*\")"
)
# A union or intersection operator right after `=`, `:`, `<`, `(`, `[` or `,` only starts a
# multi-line union (`type Mode =\n | 'a'\n | 'b'`); it is formatting, not part of the type.
_LEADING_OPERATOR = re.compile(r"([=:<(\[,])[|&]")


@dataclass(frozen=True)
class _Span:
    start: int
    stop: int


class _TypeScriptFile:
    def __init__(self, text: str) -> None:
        self.text = text
        self.source: SourceText = scan_source(text, "'\"`", multiline_quotes="`")
        self.masked = self.source.masked
        self.code = self.source.code
        self.pairs = bracket_pairs(self.masked)
        self.declarations: list[Declaration] = []

    # ---- statement splitting --------------------------------------------------------

    def _statement_end(self, start: int, stop: int) -> int:
        """The end of the statement starting at ``start``.

        A statement ends at `;`, at a `,` outside brackets, or at a newline when every bracket
        (including generic `<...>`) is closed and neither the text before nor the next line
        continues it.
        """
        index = start
        angle = 0
        while index < stop:
            char = self.masked[index]
            if char in "([{":
                index = self.pairs[index] + 1
                continue
            if char == "<":
                angle += 1
            elif char == ">" and self.masked[index - 1] != "=" and angle > 0:
                angle -= 1
            elif char in ";," and angle == 0:
                return index
            elif char == "\n" and angle == 0:
                before = self.masked[start:index].rstrip()
                following = self.masked[index:stop].lstrip()
                if (
                    before
                    and not before.endswith(_CONTINUES_FROM_END)
                    and not following.startswith(_CONTINUES_NEXT_LINE)
                ):
                    return index
            index += 1
        return stop

    def _statements(self, start: int, stop: int) -> list[_Span]:
        spans: list[_Span] = []
        index = start
        while index < stop:
            while index < stop and (self.masked[index].isspace() or self.masked[index] in ";,"):
                index += 1
            if index >= stop:
                break
            end = self._statement_end(index, stop)
            spans.append(_Span(index, end))
            index = end + 1
        return spans

    # ---- declarations ---------------------------------------------------------------

    def _body_brace(self, span: _Span) -> int | None:
        """The `{` opening the body of a namespace, class or interface statement."""
        index = span.start
        while index < span.stop:
            char = self.masked[index]
            if char == "{":
                return index
            if char in "([":
                index = self.pairs[index] + 1
                continue
            index += 1
        return None

    def _note(self, offset: int) -> str:
        return self.source.deprecation_note(offset)

    def _add(
        self, symbol: str, signature: str, span: _Span, note: str, *, structured: bool = True
    ) -> None:
        """Record a declaration.

        With ``structured``, the signature is rebuilt from the span itself so that object-literal
        types nested inside it read the same whether their members are on one line or several;
        ``signature`` is used as given otherwise (a head such as `type ClickParam`).
        """
        text = self._normalized(span.start, span.stop) if structured else signature
        self.declarations.append(
            Declaration(
                kind=_KIND,
                symbol=symbol,
                signature=_LEADING_OPERATOR.sub(r"\1", compact(self._strip_modifiers(text))),
                quote=squash(self.code[span.start : span.stop]),
                deprecated=bool(note),
                note=note,
            )
        )

    def _normalized(self, start: int, stop: int) -> str:
        """The code of a span with every nested `{...}` rewritten as `{member; member}`.

        A declaration file separates object members by newlines or by `;`/`,`; both forms
        become the same text, so reflowing an inline object type is not a modification.
        """
        parts: list[str] = []
        index = start
        while index < stop:
            brace = self.masked.find("{", index, stop)
            if brace < 0:
                parts.append(self.code[index:stop])
                break
            close = self.pairs[brace]
            parts.append(self.code[index:brace])
            members = [
                squash(self._normalized(member.start, member.stop))
                for member in self._statements(brace + 1, close)
            ]
            parts.append("{" + "; ".join(item for item in members if item) + "}")
            index = close + 1
        return squash("".join(parts))

    def _strip_modifiers(self, text: str) -> str:
        words = text.split()
        while words and words[0] in _MODIFIERS:
            words.pop(0)
        return " ".join(words)

    def _scope(self, start: int, stop: int, prefix: str) -> None:
        for span in self._statements(start, stop):
            self._declaration(span, prefix)

    def _declaration(self, span: _Span, prefix: str) -> None:
        raw = self.code[span.start : span.stop]
        text = self._strip_modifiers(squash(raw))
        if not text or text.startswith(_SKIPPED_STATEMENTS):
            return
        if text.startswith("global"):
            brace = self._body_brace(span)
            if brace is not None:
                self._scope(brace + 1, self.pairs[brace], prefix)
            return
        match = _DECLARATION.match(text)
        if match is None or match["name"] is None:
            return
        keyword, name = match["keyword"], match["name"]
        symbol = f"{prefix}{name}"
        note = self._note(span.start)
        if keyword in ("namespace", "module"):
            brace = self._body_brace(span)
            if brace is not None:
                self._scope(brace + 1, self.pairs[brace], f"{symbol}.")
            return
        if keyword in ("class", "interface"):
            brace = self._body_brace(span)
            head = self.code[span.start : brace] if brace is not None else raw
            self._add(symbol, squash(head), span, note, structured=False)
            if brace is not None:
                self._members(brace + 1, self.pairs[brace], f"{symbol}.")
            return
        if keyword == "type":
            self._object_or_value(text, span, symbol, note, separator="=")
            return
        if keyword in ("const", "let", "var"):
            self._object_or_value(text, span, symbol, note, separator=":")
            return
        if keyword == "enum":
            brace = self._body_brace(span)
            self._add(symbol, f"enum {name}", span, note, structured=False)
            if brace is not None:
                for member in self._statements(brace + 1, self.pairs[brace]):
                    member_text = squash(self.code[member.start : member.stop])
                    member_name = member_text.split("=", 1)[0].strip()
                    if member_name:
                        self._add(f"{symbol}.{member_name}", member_text, member, "")
            return
        self._add(symbol, text, span, note)

    def _object_or_value(
        self, text: str, span: _Span, symbol: str, note: str, *, separator: str
    ) -> None:
        """A type alias (`type X = ...`) or a variable (`const X: ...`).

        When the type is one object literal, the declaration keeps only its head and every
        member becomes a declaration of its own (`maa.ClickParam.contact`, `maa.Global.version`).
        """
        head, _, value = text.partition(separator)
        mark = self.masked.find(separator, span.start, span.stop)
        brace = self.masked.find("{", mark, span.stop) if mark >= 0 else -1
        last = span.start + len(self.masked[span.start : span.stop].rstrip()) - 1
        if value.strip().startswith("{") and brace >= 0 and self.pairs[brace] == last:
            self._add(symbol, squash(head), span, note, structured=False)
            self._members(brace + 1, self.pairs[brace], f"{symbol}.")
            return
        self._add(symbol, text, span, note)

    def _members(self, start: int, stop: int, prefix: str) -> None:
        for span in self._statements(start, stop):
            text = squash(self.code[span.start : span.stop])
            if not text or text.startswith("["):
                # Index signatures and mapped types have no member name.
                continue
            match = _MEMBER_NAME.match(text)
            if match is None:
                continue
            name = match["name"].strip("'\"")
            rest = text[match.end() :].lstrip()
            if name in _ACCESSOR_WORDS and not rest.startswith(("(", "?", ":", "<")):
                continue
            self._add(f"{prefix}{name}", text, span, self._note(span.start))

    def parse(self) -> list[Declaration]:
        self._scope(0, len(self.masked), "")
        return self.declarations


def parse_typescript_declarations(text: str) -> list[Declaration]:
    """Declarations of one NodeJS ``.d.ts`` file, qualified by namespace and declaration."""
    return _TypeScriptFile(text).parse()
