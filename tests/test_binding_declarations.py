from __future__ import annotations

import pytest

from maa_llm_wiki.binding_declarations import parse_python_module, parse_typescript_declarations
from maa_llm_wiki.declarations import Declaration, DeclarationParseError, merge_declarations


def _python(text: str, module: str = "maa.controller") -> dict[str, Declaration]:
    return {
        symbol: declaration
        for (_, symbol), declaration in merge_declarations(
            parse_python_module(text, module)
        ).items()
    }


def _typescript(text: str) -> dict[str, Declaration]:
    return {
        symbol: declaration
        for (_, symbol), declaration in merge_declarations(
            parse_typescript_declarations(text)
        ).items()
    }


PYTHON = '''\
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .job import Job


class MaaWin32InputMethodEnum:
    Seize = 1
    Interception = 1 << 9


class Controller:
    """A controller."""

    _handle: int

    def __init__(self, handle: int) -> None:
        self._handle = handle

    def post_shell(self, cmd: str, timeout: int = 20000) -> "Job":
        """Run a shell command."""
        return self._post(cmd, timeout)

    @property
    def connected(self) -> bool:
        return True

    @connected.setter
    def connected(self, value: bool) -> None:
        pass

    def _post(self, cmd: str, timeout: int) -> "Job":
        raise NotImplementedError

    @deprecated("use post_shell")
    def post_command(self, cmd: str) -> "Job":
        return self.post_shell(cmd)


def helper() -> None:
    pass


def _private() -> None:
    pass
'''


def test_python_symbols_are_module_qualified() -> None:
    symbols = set(_python(PYTHON))

    assert symbols == {
        "maa.controller:MaaWin32InputMethodEnum",
        "maa.controller:MaaWin32InputMethodEnum.Seize",
        "maa.controller:MaaWin32InputMethodEnum.Interception",
        "maa.controller:Controller",
        "maa.controller:Controller.__init__",
        "maa.controller:Controller.post_shell",
        "maa.controller:Controller.connected",
        "maa.controller:Controller.post_command",
        "maa.controller:helper",
    }


def test_python_signatures_and_deprecation() -> None:
    declarations = _python(PYTHON)

    shell = declarations["maa.controller:Controller.post_shell"]
    assert shell.signature == "def post_shell(self,cmd:str,timeout:int=20000)->'Job'"
    assert shell.quote == 'def post_shell(self, cmd: str, timeout: int = 20000) -> "Job"'
    command = declarations["maa.controller:Controller.post_command"]
    assert command.deprecated
    assert command.note == "@deprecated('use post_shell')"
    assert "deprecated" not in command.signature
    assert "@property" in declarations["maa.controller:Controller.connected"].signature


def test_python_docstrings_and_bodies_do_not_change_signatures() -> None:
    edited = PYTHON.replace(
        '"""Run a shell command."""', '"""Run a command in a shell."""'
    ).replace("return self._post(cmd, timeout)", "return self._post(cmd, timeout=timeout)")

    before = {symbol: item.signature for symbol, item in _python(PYTHON).items()}
    after = {symbol: item.signature for symbol, item in _python(edited).items()}

    assert before == after


def test_python_deprecation_from_directives_and_warnings() -> None:
    text = '''\
import warnings


class KWinController:
    def __init__(self, device_node: str):
        """Create a KWin controller.

        . deprecated::
            Use LinuxController instead.
        """


class WlRootsController:
    def __init__(self, socket: str):
        warnings.warn("use LinuxController", DeprecationWarning, stacklevel=2)

    def connect(self) -> None:
        def inner() -> None:
            warnings.warn("inner", DeprecationWarning)
'''
    declarations = _python(text)

    kwin = declarations["maa.controller:KWinController.__init__"]
    assert kwin.deprecated
    assert kwin.note == ". deprecated:: Use LinuxController instead."
    wlroots = declarations["maa.controller:WlRootsController.__init__"]
    assert wlroots.note == "DeprecationWarning: use LinuxController"
    assert not declarations["maa.controller:WlRootsController.connect"].deprecated


def test_python_quotes_include_decorators() -> None:
    text = (
        "from abc import abstractmethod\n\n\n"
        "class CustomController:\n"
        "    @abstractmethod\n"
        "    def scroll(self, dx: int, dy: int) -> bool:\n"
        "        raise NotImplementedError\n"
    )

    scroll = _python(text)["maa.controller:CustomController.scroll"]

    assert scroll.quote == "@abstractmethod def scroll(self, dx: int, dy: int) -> bool"
    assert scroll.signature.startswith("@abstractmethod def scroll(")


def test_python_syntax_error_is_a_parse_error() -> None:
    with pytest.raises(DeclarationParseError, match="Python syntax error"):
        parse_python_module("def broken(:\n    pass\n", "maa.broken")


TYPESCRIPT = """\
declare global {
    namespace maa {
        type ClickParam = {
            point: Point
            contact?: number // touch contact
        }

        type Mode =
            | 'strict'
            | 'fragment'

        type Callback<T> = (value: T) => MaybePromise<void>

        type Strict<Mode> = RequiredIfStrict<
            {
                roi?: Rect
            },
            'roi',
            Mode
        >

        const Status: Record<'Invalid' | 'Pending', Status>

        /**
         * @deprecated Use Controller instead.
         */
        class LegacyController {
            constructor(handle?: string)
        }

        class Controller {
            constructor(handle?: string)

            set screenshot_target_long_side(value: number)
            post_click(
                x: number,
                y: number,
                contact?: number,
            ): Job<CtrlId, Controller>
            static find(): Promise<Device[] | null>
            static find(adb: string): Promise<Device[] | null>
        }

        interface CustomActor {
            connect?(): MaybePromise<boolean>
            // connected?(): MaybePromise<boolean>
        }
    }
}

export {}
"""


def test_typescript_symbols_follow_namespaces_and_declarations() -> None:
    symbols = set(_typescript(TYPESCRIPT))

    assert symbols == {
        "maa.ClickParam",
        "maa.ClickParam.point",
        "maa.ClickParam.contact",
        "maa.Mode",
        "maa.Callback",
        "maa.Strict",
        "maa.Status",
        "maa.LegacyController",
        "maa.LegacyController.constructor",
        "maa.Controller",
        "maa.Controller.constructor",
        "maa.Controller.screenshot_target_long_side",
        "maa.Controller.post_click",
        "maa.Controller.find",
        "maa.CustomActor",
        "maa.CustomActor.connect",
    }


def test_typescript_signatures_span_continuation_lines() -> None:
    declarations = _typescript(TYPESCRIPT)

    assert declarations["maa.Mode"].signature == "type Mode='strict'|'fragment'"
    assert (
        declarations["maa.Callback"].signature == "type Callback<T>=(value:T)=>MaybePromise<void>"
    )
    assert "'roi'" in declarations["maa.Strict"].signature
    assert declarations["maa.ClickParam"].signature == "type ClickParam"
    assert declarations["maa.ClickParam.contact"].signature == "contact?:number"
    click = declarations["maa.Controller.post_click"]
    assert click.signature == "post_click(x:number,y:number,contact?:number):Job<CtrlId,Controller>"
    find = declarations["maa.Controller.find"].signature
    assert "static find():" in find and "static find(adb:string):" in find


def test_typescript_deprecation_and_comment_stability() -> None:
    declarations = _typescript(TYPESCRIPT)
    assert declarations["maa.LegacyController"].deprecated
    assert declarations["maa.LegacyController"].note == "@deprecated Use Controller instead."
    assert not declarations["maa.Controller"].deprecated

    edited = TYPESCRIPT.replace("// touch contact", "// the touch contact id").replace(
        "            point: Point\n", "            point:   Point\n"
    )
    before = {symbol: item.signature for symbol, item in declarations.items()}
    after = {symbol: item.signature for symbol, item in _typescript(edited).items()}
    assert before == after


def test_typescript_object_constants_are_split_into_members() -> None:
    text = """\
declare global {
    namespace maa {
        const Global: {
            get version(): string
            set log_dir(value: string)
            macos_check_permission(perm: MacOSPermission): boolean
        }
        const Status: Record<'Invalid' | 'Pending', Status>
    }
}
"""
    declarations = _typescript(text)

    assert set(declarations) == {
        "maa.Global",
        "maa.Global.version",
        "maa.Global.log_dir",
        "maa.Global.macos_check_permission",
        "maa.Status",
    }
    assert declarations["maa.Global"].signature == "const Global"


def test_typescript_nested_object_reflow_is_formatting() -> None:
    inline = (
        "declare global {\n    namespace maa {\n        type Notify = {\n"
        "            list: { name: string; jump_back: boolean }[]\n        }\n    }\n}\n"
    )
    reflowed = (
        "declare global {\n    namespace maa {\n        type Notify = {\n"
        "            list: {\n                name: string\n                jump_back: boolean\n"
        "            }[]\n        }\n    }\n}\n"
    )

    before = _typescript(inline)["maa.Notify.list"]
    after = _typescript(reflowed)["maa.Notify.list"]

    assert before.signature == after.signature == "list:{name:string;jump_back:boolean}[]"


def test_python_enum_member_deprecated_by_comment() -> None:
    text = (
        "class MaaInferenceExecutionProviderEnum:\n"
        "    DirectML = 2\n\n"
        "    # Deprecated. MaaDeps no longer ships the CoreML execution provider. Use WebGPU.\n"
        "    # The value is kept so existing callers still work.\n"
        "    CoreML = 3\n"
    )

    declarations = _python(text, "maa.define")

    coreml = declarations["maa.define:MaaInferenceExecutionProviderEnum.CoreML"]
    assert coreml.deprecated
    assert coreml.note.startswith("Deprecated. MaaDeps no longer ships")
    assert not declarations["maa.define:MaaInferenceExecutionProviderEnum.DirectML"].deprecated


def test_typescript_leading_union_operator_is_formatting() -> None:
    one_line = "declare global {\n    namespace maa {\n        type Mode = 'a' | 'b'\n    }\n}\n"
    multi_line = (
        "declare global {\n    namespace maa {\n        type Mode =\n"
        "            | 'a'\n            | 'b'\n    }\n}\n"
    )

    assert (
        _typescript(one_line)["maa.Mode"].signature == _typescript(multi_line)["maa.Mode"].signature
    )


def test_reference_only_files_declare_nothing() -> None:
    text = (
        '/// <reference path="./client.d.ts" />\n'
        '/// <reference path="./types.d.ts" />\n'
        "\n"
        "export {}\n"
    )

    assert parse_typescript_declarations(text) == []


def test_typescript_unbalanced_brackets_are_a_parse_error() -> None:
    with pytest.raises(DeclarationParseError):
        parse_typescript_declarations("declare global {\n    namespace maa {\n")
