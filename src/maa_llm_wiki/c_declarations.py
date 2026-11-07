"""Declarations of the public C and C++ headers under ``include/``.

The parser reads the declaration shapes the MaaFramework headers use: exported functions
(``MAA_FRAMEWORK_API`` and the other ``MAA_*_API`` macros, also with the macro on a line of its
own), ``#define Maa*`` constants and callback messages, C and C++ enums, structs and their fields
(function-pointer fields included), C++ classes with their member functions and data members, and
typedef and ``using`` aliases. Every branch of an ``#if`` block is read, and namespaces do not
qualify symbols. A ``@deprecated`` or ``Deprecated`` comment directly above a declaration or after
it on its last line, a ``MAA_DEPRECATED`` macro and a deprecation attribute (``[[deprecated]]``,
``__declspec(deprecated)``, ``__attribute__((deprecated))``) mark the declaration as deprecated
without changing its signature.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from .declarations import (
    Declaration,
    SourceText,
    blank,
    bracket_pairs,
    compact,
    scan_source,
    squash,
)
from .models import MachineChangeKind

_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
_DEFINE = re.compile(r"^[ \t]*#[ \t]*define[ \t]+(?P<name>[A-Za-z_]\w*)(?P<function>\()?")
_EXPORT_MACRO = re.compile(r"\bMAA_[A-Z0-9_]*_API\b")
_DEPRECATED_MACRO = re.compile(r"\bMAA_DEPRECATED\b")
_CALLING_CONVENTION = re.compile(r"\bMAA_CALL\b")
_NAMESPACE_MACRO = re.compile(r"\bMAA_(?:[A-Z0-9_]*_)?NS_(?:BEGIN|END)\b")
_STRING = r'"(?:[^"\\\n]|\\.)*"'
_ARGUMENTS = rf'(?:[^()"]|{_STRING}|\((?:[^()"]|{_STRING})*\))*'
_ATTRIBUTE = re.compile(
    rf'\[\[(?:[^\[\]"]|{_STRING})*\]\]'
    rf"|__declspec\s*\({_ARGUMENTS}\)"
    rf"|__attribute__\s*\(\({_ARGUMENTS}\)\)"
)
_DEPRECATION = re.compile(r"deprecated", re.IGNORECASE)
_DEPRECATED_LINE = re.compile(r"@deprecated\b|^deprecated\b", re.IGNORECASE)
_COMMENT_MARKER = re.compile(r"^\s*(?:/\*+[!<]?|//+[!/<]?|\*+(?!/))?\s*")
_EXTERN_C = re.compile(r'\bextern\s+"[^"]*"')
_NAMESPACE = re.compile(r"^(?:inline\s+)?namespace\b")
_TEMPLATE = re.compile(r"^template\s*<")
_CONTAINER = re.compile(
    r"^(?P<keyword>class|struct|union|enum(?:\s+(?:class|struct)\b)?)"
    r"(?:\s+(?P<name>[A-Za-z_]\w*))?\s*(?:\bfinal\b\s*)?(?::(?!:).*)?$"
)
_FORWARD_DECLARATION = re.compile(
    r"^(?:class|struct|union|enum(?:\s+(?:class|struct)\b)?)\s+[A-Za-z_][\w:]*(?:\s*:[^:].*)?$"
)
_SAME_NAME_TAG = re.compile(r"^(?P<tag>struct|union|enum|class) (?P<name>[A-Za-z_]\w*) (?P=name)$")
_USING = re.compile(r"^using\s+(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<value>.+)$")
_MACRO_CALL = re.compile(r"^[A-Z_][A-Z0-9_]*\s*\(")
_SKIPPED_STATEMENT = re.compile(r"^(?:static_assert|friend|using\s+namespace)\b")
_CALLABLE_NAME = re.compile(r"((?:[A-Za-z_]\w*\s*::\s*)*~?\s*[A-Za-z_]\w*)\s*$")
_OPERATOR = re.compile(r"\boperator\b\s*(?P<symbol>\(\s*\)|\[\s*\]|[^\s(][^(]*?)\s*\(")
# The `(*shell)` of `MaaBool (*shell)(const char* cmd)`, matched after MAA_CALL is removed.
_POINTER_DECLARATOR = re.compile(
    r"\(\s*(?:[A-Za-z_]\w*\b\s*)*?[*&^]+\s*(?:const\b\s*)?(?P<name>[A-Za-z_]\w*)\s*"
    r"(?:\[[^\]]*\]\s*)*\)"
)
_NOT_FUNCTIONS = frozenset({"decltype", "sizeof", "alignof", "alignas", "noexcept"})
_ACCESS_LABELS = frozenset({"public", "private", "protected"})
_QUALIFIERS = frozenset(
    {"const", "volatile", "mutable", "static", "constexpr", "inline", "extern", "register"}
)
_BUILTIN_TYPES = frozenset(
    {"void", "bool", "char", "short", "int", "long", "float", "double", "signed", "unsigned"}
)


def _deprecation_line(comments: list[str]) -> str:
    """The first comment line that deprecates, such as `@deprecated Use X instead.`."""
    for body in comments:
        for raw in body.splitlines():
            line = _COMMENT_MARKER.sub("", raw).strip().removesuffix("*/").strip()
            if _DEPRECATED_LINE.search(line):
                return squash(line)
    return ""


def _marker_note(text: str) -> str:
    """The deprecation attribute or ``MAA_DEPRECATED`` macro in declaration text, or ``""``."""
    for match in _ATTRIBUTE.finditer(text):
        if _DEPRECATION.search(match.group(0)):
            return squash(match.group(0))
    return "MAA_DEPRECATED" if _DEPRECATED_MACRO.search(text) else ""


def _without_markers(text: str) -> str:
    """Declaration text without attributes, ``MAA_DEPRECATED`` and the ``MAA_CALL`` convention."""
    text = _DEPRECATED_MACRO.sub(" ", _ATTRIBUTE.sub(" ", text))
    return squash(_CALLING_CONVENTION.sub(" ", text))


def _is_scope(text: str, index: int) -> bool:
    """Whether the character at ``index`` belongs to a `::` scope separator."""
    return text[index] == ":" and (
        text[index - 1 : index] == ":" or text[index + 1 : index + 2] == ":"
    )


def _top_level_index(text: str, targets: str) -> int:
    """The offset of the first character of ``targets`` outside brackets, or ``len(text)``."""
    depth = 0
    for index, char in enumerate(text):
        if depth == 0 and char in targets and not _is_scope(text, index):
            return index
        if char in "([{<":
            depth += 1
        elif char in ")]}>":
            depth = max(depth - 1, 0)
    return len(text)


def _split_top_level(text: str) -> list[str]:
    """Split a declarator list such as `a, *b, c[4]` at the commas outside brackets."""
    parts: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char in "([{<":
            depth += 1
        elif char in ")]}>":
            depth = max(depth - 1, 0)
        elif char == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


def _declared_name(part: str, *, typed: bool) -> str | None:
    """The name one declarator declares: `x` in `int x = 0`, `shell` in `(*shell)(...)`.

    With ``typed`` the part also carries the type, so a part that is only a type declares nothing.
    """
    declarator = part[: _top_level_index(part, "={")]
    head_end = _top_level_index(declarator, "([:")
    if declarator.startswith("(", head_end):
        pointer = _POINTER_DECLARATOR.match(declarator, head_end)
        if pointer is not None:
            return pointer["name"]
    words = [word for word in _IDENTIFIER.findall(declarator[:head_end]) if word not in _QUALIFIERS]
    if not words or (typed and len(words) < 2) or words[-1] in _BUILTIN_TYPES:
        return None
    return words[-1]


def _declarator_names(text: str, *, typed: bool = False) -> list[str]:
    names: list[str] = []
    for index, part in enumerate(_split_top_level(text)):
        name = _declared_name(part, typed=typed and index == 0)
        if name is not None and name not in names:
            names.append(name)
    return names


def _split_template(text: str) -> tuple[str, str]:
    """Split a leading `template <...>` header from declaration text."""
    if not _TEMPLATE.match(text):
        return "", text
    depth = 0
    for index, char in enumerate(text):
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
            if depth == 0:
                return text[: index + 1], squash(text[index + 1 :])
    return "", text


def _is_initializer(head: str) -> bool:
    """Whether the braces after ``head`` initialize a variable instead of holding a body.

    `int values[] =` and `std::function<void(int)> callback` precede an initializer; a head with
    a parameter list outside template arguments, such as `bool scroll(int dx)`, precedes a body.
    """
    if re.search(r"\boperator\b", head):
        return False
    index = _top_level_index(head, "(=")
    return index == len(head) or head[index] == "="


def _initializer_follows(masked: str, index: int, stop: int) -> bool:
    """Whether the text from ``index`` continues a declaration: a `,` or `;` comes next."""
    while index < stop and masked[index].isspace():
        index += 1
    return index < stop and masked[index] in ",;"


def _without_member_initializers(head: str) -> str:
    """A function definition head without a constructor's member-initializer list."""
    depth = 0
    closed = False
    for index, char in enumerate(head):
        if char in "([{<":
            depth += 1
        elif char in ")]}>":
            depth = max(depth - 1, 0)
            closed = closed or (char == ")" and depth == 0)
        elif char == ":" and depth == 0 and closed and not _is_scope(head, index):
            return head[:index].rstrip()
    return head


@dataclass(frozen=True)
class _Context:
    """Where a statement sits: the qualified owner name and the kind of block."""

    owner: str
    block: str  # "file", "namespace" or "record" (the body of a struct, class or union)

    @property
    def type_name(self) -> str:
        """The unqualified name of the enclosing record, which its constructors carry."""
        return self.owner.rpartition("::")[2] if self.block == "record" else ""


class _HeaderParser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.source: SourceText = scan_source(text, "\"'")
        self.comment_starts = [start for start, _, _ in self.source.comments]
        self.declarations: list[Declaration] = []
        masked = list(self.source.masked)
        code = list(self.source.code)
        self._read_preprocessor(masked, code)
        # Namespace macros such as MAA_CTRL_UNIT_NS_BEGIN are transparent, like `namespace X {`.
        for match in _NAMESPACE_MACRO.finditer(self.source.masked):
            blank(masked, match.start(), match.end())
            blank(code, match.start(), match.end())
        self.masked = "".join(masked)
        self.code = "".join(code)
        self.pairs = bracket_pairs(self.masked)

    # ---- documentation comments -----------------------------------------------------

    def _comments_above(self, start: int) -> list[str]:
        """The comments directly above ``start``, each on a line of its own, in file order.

        A blank line ends the run, so a comment over a commented-out declaration does not document
        the declaration after it.
        """
        masked = self.source.masked
        found: list[str] = []
        position = start
        index = bisect_right(self.source.comment_ends, position) - 1
        while index >= 0:
            comment_start, comment_end, body = self.source.comments[index]
            gap = masked[comment_end:position]
            line_start = masked.rfind("\n", 0, comment_start) + 1
            if gap.strip() or gap.count("\n") > 1 or masked[line_start:comment_start].strip():
                break
            found.append(body)
            position = comment_start
            index -= 1
        found.reverse()
        return found

    def _comments_after(self, end: int) -> list[str]:
        """The comments that follow ``end`` on its line, past a `,` or `;` at most."""
        masked = self.source.masked
        found: list[str] = []
        position = end
        index = bisect_left(self.comment_starts, end)
        while index < len(self.source.comments):
            comment_start, comment_end, body = self.source.comments[index]
            gap = masked[position:comment_start]
            if "\n" in gap or gap.strip(" \t,;"):
                break
            found.append(body)
            position = comment_end
            index += 1
        return found

    def _comments_within(self, start: int, stop: int) -> list[str]:
        first = bisect_left(self.comment_starts, start)
        last = bisect_left(self.comment_starts, stop)
        return [body for _, _, body in self.source.comments[first:last]]

    def _deprecation(self, start: int, end: int | None = None) -> str:
        """The deprecation sentence of the comments documenting code from ``start`` to ``end``."""
        comments = self._comments_above(start)
        if end is not None:
            comments += self._comments_after(end)
        return _deprecation_line(comments)

    # ---- preprocessor ---------------------------------------------------------------

    def _read_preprocessor(self, masked: list[str], code: list[str]) -> None:
        """Record ``#define Maa*`` macros, then remove every directive from the code views."""
        source = self.source.masked
        size = len(source)
        index = 0
        while index < size:
            line_end = source.find("\n", index)
            line_end = size if line_end < 0 else line_end
            if not source[index:line_end].lstrip().startswith("#"):
                index = line_end + 1
                continue
            stop = line_end
            while stop < size and source[stop - 1] == "\\":
                next_end = source.find("\n", stop + 1)
                stop = size if next_end < 0 else next_end
            self._define(index, stop)
            blank(masked, index, stop)
            blank(code, index, stop)
            index = stop + 1

    def _define(self, start: int, stop: int) -> None:
        directive = self.source.code[start:stop]
        match = _DEFINE.match(directive)
        if match is None or match["function"] is not None or not match["name"].startswith("Maa"):
            return
        name = match["name"]
        kind = (
            MachineChangeKind.CALLBACK_MESSAGE
            if name.startswith("MaaMsg_")
            else MachineChangeKind.CONSTANT
        )
        comments = self._comments_above(start) + self._comments_within(start + match.end(), stop)
        note = _deprecation_line(comments)
        self.declarations.append(
            Declaration(
                kind=kind,
                symbol=name,
                signature=compact(directive[match.end() :].replace("\\\n", " ")),
                quote=squash(self.text[start:stop].replace("\\\n", " ")),
                deprecated=bool(note),
                note=note,
            )
        )

    # ---- blocks ---------------------------------------------------------------------

    def parse(self) -> list[Declaration]:
        self._block(0, len(self.masked), _Context(owner="", block="file"))
        return self.declarations

    def _skip_space(self, index: int, stop: int) -> int:
        while index < stop and self.masked[index].isspace():
            index += 1
        return index

    def _block(self, start: int, stop: int, context: _Context) -> None:
        """Split a block into statements: each ends at `;` or at the body of a definition."""
        index = self._skip_space(start, stop)
        statement_start = index
        while index < stop:
            char = self.masked[index]
            if char in "([":
                index = self.pairs[index] + 1
                continue
            if char == ";":
                self._statement(statement_start, index, False, context)
                index = self._skip_space(index + 1, stop)
                statement_start = index
                continue
            if char == "{":
                index = self._skip_space(self._braced(statement_start, index, stop, context), stop)
                statement_start = index
                continue
            if char == ":" and context.block == "record":
                label = self.masked[statement_start:index].strip()
                if label in _ACCESS_LABELS:
                    index = self._skip_space(index + 1, stop)
                    statement_start = index
                    continue
            index += 1
        if self.masked[statement_start:stop].strip():
            self._statement(statement_start, stop, False, context)

    def _braced(self, start: int, open_index: int, stop: int, context: _Context) -> int:
        """Handle a statement whose head is followed by a braced body; return the next offset."""
        close = self.pairs[open_index]
        after = close + 1
        head = squash(self.masked[start:open_index])
        if not head or _EXTERN_C.fullmatch(head):
            self._block(open_index + 1, close, context)
            return after
        if _NAMESPACE.match(head):
            self._block(open_index + 1, close, _Context(owner=context.owner, block="namespace"))
            return after
        text = squash(self.code[start:open_index])
        template, plain = _split_template(squash(_EXPORT_MACRO.sub(" ", _without_markers(text))))
        container = _CONTAINER.match(plain.removeprefix("typedef "))
        if container is not None:
            terminator = self._statement_end(after, stop)
            self._container(
                start,
                open_index,
                terminator,
                container,
                typedef=plain.startswith("typedef "),
                template=template,
                note=self._deprecation(start, terminator if terminator < stop else None)
                or _marker_note(text),
                context=context,
            )
            return min(terminator + 1, stop)
        if head.endswith("=") or (
            _is_initializer(head) and _initializer_follows(self.masked, after, stop)
        ):
            # `int values[] = {1, 2}` or `int retries{3}`: one statement up to its semicolon.
            terminator = self._statement_end(after, stop)
            self._statement(start, terminator, False, context)
            return min(terminator + 1, stop)
        # A function definition: the body is not part of the declaration.
        body = self._function_body(start, open_index, stop)
        self._statement(start, body, True, context)
        after = self.pairs[body] + 1
        following = self._skip_space(after, stop)
        return following + 1 if following < stop and self.masked[following] == ";" else after

    def _function_body(self, start: int, open_index: int, stop: int) -> int:
        """The `{` that opens a function body, past the braces of member initializers.

        In `Foo() : a_{1}, b_{2} {}` the first braces follow a member name; the body follows the
        `)` or `}` that ends the last initializer.
        """
        head = squash(self.masked[start:open_index])
        if _without_member_initializers(head) == head:
            return open_index
        index = open_index
        while index < stop:
            char = self.masked[index]
            if char == "{":
                previous = index - 1
                while previous > start and self.masked[previous].isspace():
                    previous -= 1
                if not (self.masked[previous].isalnum() or self.masked[previous] in "_>"):
                    return index
                index = self.pairs[index] + 1
            elif char in "([":
                index = self.pairs[index] + 1
            elif char == ";":
                break
            else:
                index += 1
        return open_index

    def _statement_end(self, index: int, stop: int) -> int:
        while index < stop:
            char = self.masked[index]
            if char in "([{":
                index = self.pairs[index] + 1
                continue
            if char == ";":
                return index
            index += 1
        return stop

    # ---- containers -----------------------------------------------------------------

    def _container(
        self,
        start: int,
        open_index: int,
        terminator: int,
        container: re.Match[str],
        *,
        typedef: bool,
        template: str,
        note: str,
        context: _Context,
    ) -> None:
        """A struct, class, union or enum definition, its members, and its typedef names."""
        keyword = squash(container["keyword"])
        name = container["name"]
        close = self.pairs[open_index]
        # The head without its body, so a struct and its `typedef struct X X;` agree.
        signature = compact(f"{template} {container.group(0)}")
        quote = squash(self.code[start:open_index])
        trailing = squash(self.masked[close + 1 : terminator])
        declared = _declarator_names(trailing)
        names = [name] if name else []
        if typedef:
            names.extend(item for item in declared if item not in names)
        for item in names:
            self._add(
                MachineChangeKind.TYPE_DEFINITION,
                self._qualify(context, item),
                signature,
                quote,
                note,
            )
        if not typedef and context.block == "record" and context.owner:
            # `struct Inner { ... } inner;` inside a record also declares the field `inner`.
            for item in declared:
                self._add(
                    MachineChangeKind.STRUCT_FIELD,
                    f"{context.owner}.{item}",
                    f"{signature} {trailing}",
                    f"{quote} {trailing};",
                    note,
                )
        owner_name = name or (declared[0] if typedef and declared else "")
        if owner_name:
            owner = self._qualify(context, owner_name)
        elif declared and context.block == "record" and context.owner:
            # The fields of `struct { int a; } inner;` are reached as `inner.a`.
            owner = f"{context.owner}.{declared[0]}"
        else:
            # An anonymous union's members belong to the enclosing record.
            owner = context.owner
        if keyword.startswith("enum"):
            if keyword != "enum":
                prefix = owner
            else:
                prefix = context.owner if context.block == "record" else ""
            self._enumerators(open_index + 1, close, prefix)
            return
        self._block(open_index + 1, close, _Context(owner=owner, block="record"))

    def _enumerators(self, start: int, stop: int, owner: str) -> None:
        index = start
        while index < stop:
            item_end = index
            while item_end < stop and self.masked[item_end] != ",":
                if self.masked[item_end] in "([{":
                    item_end = self.pairs[item_end] + 1
                    continue
                item_end += 1
            self._enumerator(index, item_end, owner)
            index = item_end + 1

    def _enumerator(self, start: int, stop: int, owner: str) -> None:
        text = self.code[start:stop]
        if not text.strip():
            return
        offset = start + len(text) - len(text.lstrip())
        end = start + len(text.rstrip())
        name_part, _, value = _without_markers(text).partition("=")
        name = _IDENTIFIER.search(name_part)
        if name is None:
            return
        self._add(
            MachineChangeKind.ENUM_VALUE,
            f"{owner}::{name.group(0)}" if owner else name.group(0),
            value,
            text,
            self._deprecation(offset, end) or _marker_note(text),
        )

    # ---- single statements ----------------------------------------------------------

    def _statement(self, start: int, stop: int, has_body: bool, context: _Context) -> None:
        """Classify one statement ending at ``stop`` (a `;`, or the `{` of a function body)."""
        raw = self.code[start:stop]
        text = squash(_EXTERN_C.sub(" ", raw))
        if not text or _SKIPPED_STATEMENT.match(text):
            return
        template, text = _split_template(text)
        if _FORWARD_DECLARATION.match(text):
            return
        note = self._deprecation(start, None if has_body else stop) or _marker_note(text)
        plain = _without_markers(text)
        quote = squash(raw) + ("" if has_body else ";")
        if plain.startswith("typedef "):
            self._typedef(plain, quote, note, context)
            return
        if plain.startswith("using "):
            alias = _USING.match(plain)
            if alias is not None:
                name = self._qualify(context, alias["name"])
                self._add(MachineChangeKind.TYPE_DEFINITION, name, alias["value"], quote, note)
            return
        exported = bool(_EXPORT_MACRO.search(plain))
        plain = squash(_EXPORT_MACRO.sub(" ", plain))
        function = self._function_name(plain, context)
        if function is not None:
            # A file-scope prototype without an export macro is not part of the public API.
            if (exported or has_body or context.block == "record") and not function.startswith("~"):
                head = _without_member_initializers(plain) if has_body else plain
                symbol = self._qualify(context, function)
                signature = f"{template} {head}"
                self._add(MachineChangeKind.PUBLIC_FUNCTION, symbol, signature, quote, note)
            return
        if context.block == "record" and context.owner and not _MACRO_CALL.match(plain):
            for name in _declarator_names(plain, typed=True):
                symbol = f"{context.owner}.{name}"
                self._add(MachineChangeKind.STRUCT_FIELD, symbol, plain, quote, note)

    def _function_name(self, plain: str, context: _Context) -> str | None:
        """The declared function name, or None when the statement declares no function.

        A function has a parameter list right after its name and a return type (or a `~` for a
        destructor, or the record name for a constructor) before it. A parenthesised declarator
        such as the ``(*name)`` of a function-pointer field, a macro call and a variable with an
        initializer are not functions; parentheses inside template arguments do not count.
        """
        operator = _OPERATOR.search(plain)
        if operator is not None and "=" not in plain[: operator.start()]:
            return compact(f"operator {operator['symbol']}")
        depth = 0
        for index, char in enumerate(plain):
            if char == "<":
                depth += 1
            elif char == ">":
                depth = max(depth - 1, 0)
            elif depth:
                continue
            elif char == "=":
                return None
            elif char == "(":
                before = plain[:index].rstrip()
                match = _CALLABLE_NAME.search(before)
                if match is None:
                    return None
                name = compact(match.group(1))
                if name in _NOT_FUNCTIONS:
                    return None
                if not before[: match.start()].strip() and not name.startswith("~"):
                    return name if name == context.type_name else None
                return name
        return None

    def _typedef(self, plain: str, quote: str, note: str, context: _Context) -> None:
        body = plain.removeprefix("typedef ").strip()
        same = _SAME_NAME_TAG.match(body)
        if same is not None:
            # `typedef struct MaaTasker MaaTasker;` agrees with `struct MaaTasker { ... };`.
            names, signature = [same["name"]], f"{same['tag']} {same['name']}"
        else:
            names, signature = _declarator_names(body, typed=True), body
        for name in names:
            self._add(
                MachineChangeKind.TYPE_DEFINITION,
                self._qualify(context, name),
                signature,
                quote,
                note,
            )

    def _qualify(self, context: _Context, name: str) -> str:
        if context.block == "record" and context.owner:
            return f"{context.owner}::{name}"
        return name

    def _add(
        self, kind: MachineChangeKind, symbol: str, signature: str, quote: str, note: str
    ) -> None:
        self.declarations.append(
            Declaration(
                kind=kind,
                symbol=symbol,
                signature=compact(signature),
                quote=squash(quote),
                deprecated=bool(note),
                note=squash(note),
            )
        )


def parse_c_header(text: str) -> list[Declaration]:
    """Declarations of one C/C++ header.

    Symbols are global C names (``MaaControllerPostShell``, ``MaaWin32InputMethod_Interception``),
    ``Type::member`` for members of C++ classes and scoped enums, and ``Struct.field`` for data
    members.
    """
    return _HeaderParser(text.replace("\r\n", "\n")).parse()
