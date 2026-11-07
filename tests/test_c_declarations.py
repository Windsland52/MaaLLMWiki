from __future__ import annotations

import pytest

from maa_llm_wiki.c_declarations import parse_c_header
from maa_llm_wiki.declarations import Declaration, DeclarationParseError, merge_declarations


def _declarations(text: str) -> dict[tuple[str, str], Declaration]:
    return {
        (kind.value, symbol): declaration
        for (kind, symbol), declaration in merge_declarations(parse_c_header(text)).items()
    }


CONTROLLER = """\
#pragma once

#include "../MaaDef.h"

#ifdef __cplusplus
extern "C"
{
#endif

    MAA_FRAMEWORK_API MaaCtrlId MaaControllerPostClick(MaaController* ctrl, int32_t x, int32_t y);

    MAA_FRAMEWORK_API MaaCtrlId
        MaaControllerPostSwipe(MaaController* ctrl, int32_t x1, int32_t y1, int32_t duration);

    MAA_AGENT_SERVER_API
    MaaBool MaaAgentServerStartUp(const char* identifier);

    /**
     * @brief Create a KWin controller.
     * @deprecated Use MaaLinuxControllerCreate instead.
     */
    MAA_FRAMEWORK_API MaaController* MaaKWinControllerCreate(const char* device_node);

    MAA_DEPRECATED MAA_FRAMEWORK_API MaaCtrlId MaaControllerPostPressKey(MaaController* c, int k);

    void internal_helper(int value);

#ifdef __cplusplus
}
#endif
"""


def test_exported_functions_in_every_layout() -> None:
    declarations = _declarations(CONTROLLER)
    functions = {symbol for kind, symbol in declarations if kind == "public-function"}

    assert functions == {
        "MaaControllerPostClick",
        "MaaControllerPostSwipe",
        "MaaAgentServerStartUp",
        "MaaKWinControllerCreate",
        "MaaControllerPostPressKey",
    }
    click = declarations[("public-function", "MaaControllerPostClick")]
    assert (
        click.signature
        == "MaaCtrlId MaaControllerPostClick(MaaController*ctrl,int32_t x,int32_t y)"
    )
    assert click.quote.startswith("MAA_FRAMEWORK_API MaaCtrlId MaaControllerPostClick(")


def test_deprecation_comes_from_doc_comments_and_macros() -> None:
    declarations = _declarations(CONTROLLER)

    kwin = declarations[("public-function", "MaaKWinControllerCreate")]
    assert kwin.deprecated
    assert kwin.note == "@deprecated Use MaaLinuxControllerCreate instead."
    press = declarations[("public-function", "MaaControllerPostPressKey")]
    assert press.deprecated
    assert "MAA_DEPRECATED" not in press.signature
    assert not declarations[("public-function", "MaaControllerPostClick")].deprecated


def test_deprecation_does_not_change_the_signature() -> None:
    plain = CONTROLLER.replace("     * @deprecated Use MaaLinuxControllerCreate instead.\n", "")

    before = _declarations(plain)[("public-function", "MaaKWinControllerCreate")]
    after = _declarations(CONTROLLER)[("public-function", "MaaKWinControllerCreate")]

    assert not before.deprecated
    assert before.signature == after.signature


DEFINITIONS = """\
#pragma once

typedef int32_t MaaCtrlOption;
typedef struct MaaTasker MaaTasker;
typedef MaaBool(MAA_CALL* MaaCustomActionCallback)(MaaContext* context, void* trans_arg);

enum MaaCtrlOptionEnum
{
    MaaCtrlOption_Invalid = 0,
    // a comment with { braces } and ; semicolons
    MaaCtrlOption_ScreenshotTargetLongSide = 1,
#if defined(__cplusplus)
    MaaCtrlOption_Legacy [[deprecated]] = 3,
#else
    MaaCtrlOption_Legacy = 3,
#endif
};

#define MaaWin32InputMethod_Seize 1ULL
#define MaaWin32InputMethod_Interception \\
    (1ULL << 9)
#define MaaMsg_Node_Action_Starting "Node.Action.Starting"
#define MaaMakeId(x) ((MaaId)(x))
#define MAA_FRAMEWORK_API __declspec(dllexport)
"""


def test_typedefs_enums_and_constants() -> None:
    declarations = _declarations(DEFINITIONS)

    assert ("type-definition", "MaaCtrlOption") in declarations
    assert ("type-definition", "MaaTasker") in declarations
    assert ("type-definition", "MaaCustomActionCallback") in declarations
    assert ("type-definition", "MaaCtrlOptionEnum") in declarations
    assert declarations[("enum-value", "MaaCtrlOption_ScreenshotTargetLongSide")].signature == "1"
    legacy = declarations[("enum-value", "MaaCtrlOption_Legacy")]
    assert legacy.deprecated and legacy.signature == "3"
    assert declarations[("constant", "MaaWin32InputMethod_Interception")].signature == "(1ULL<<9)"
    message = declarations[("callback-message", "MaaMsg_Node_Action_Starting")]
    assert message.signature == '"Node.Action.Starting"'
    symbols = {symbol for _, symbol in declarations}
    assert "MaaMakeId" not in symbols
    assert "MAA_FRAMEWORK_API" not in symbols


CPP = """\
#pragma once

MAA_CTRL_UNIT_NS_BEGIN

class ControlUnitAPI
{
public:
    virtual ~ControlUnitAPI() = default;

    virtual bool connect() = 0;
    virtual MaaControllerFeature get_features() const = 0;
    virtual bool shell(const std::string& cmd, std::string& output,
                       std::chrono::milliseconds timeout)
    {
        return false;
    }

protected:
    int retries_ = 3;
};

enum class RecordType
{
    invalid,
    click,
};

struct RecordClick
{
    int x = 0;
    int y = 0;

    MEO_JSONIZATION(x, y);
};

using MaaControlUnitHandle = MAA_CTRL_UNIT_NS::ControlUnitAPI*;

MAA_CTRL_UNIT_NS_END
"""


def test_cpp_classes_members_and_scoped_enums() -> None:
    declarations = _declarations(CPP)
    symbols = set(declarations)

    assert ("type-definition", "ControlUnitAPI") in symbols
    assert ("public-function", "ControlUnitAPI::connect") in symbols
    assert ("public-function", "ControlUnitAPI::get_features") in symbols
    assert ("public-function", "ControlUnitAPI::shell") in symbols
    assert ("struct-field", "ControlUnitAPI.retries_") in symbols
    assert ("enum-value", "RecordType::click") in symbols
    assert ("struct-field", "RecordClick.x") in symbols
    assert ("type-definition", "MaaControlUnitHandle") in symbols
    assert not any("~" in symbol or "MEO_JSONIZATION" in symbol for _, symbol in symbols)
    shell = declarations[("public-function", "ControlUnitAPI::shell")]
    assert "return" not in shell.signature
    assert declarations[("public-function", "ControlUnitAPI::connect")].signature.endswith("=0")


def test_struct_fields_include_function_pointers() -> None:
    text = """\
struct MaaCustomControllerCallbacks
{
    MaaBool (*connect)(void* trans_arg);

    /// Write result to buffer.
    MaaBool (*shell)(const char* cmd, void* trans_arg, /* out */ MaaStringBuffer* buffer);
};
"""
    declarations = _declarations(text)

    assert ("struct-field", "MaaCustomControllerCallbacks.connect") in declarations
    shell = declarations[("struct-field", "MaaCustomControllerCallbacks.shell")]
    assert "/*" not in shell.signature
    assert shell.signature.endswith("void*trans_arg,MaaStringBuffer*buffer)")


def test_formatting_and_comments_do_not_change_signatures() -> None:
    reformatted = (
        CONTROLLER.replace(
            "MaaControllerPostClick(MaaController* ctrl, int32_t x, int32_t y);",
            "MaaControllerPostClick(\n        MaaController*  ctrl,   // the controller\n"
            "        int32_t x,\n        int32_t y);",
        )
        + "\n// trailing comment\n"
    )

    before = _declarations(CONTROLLER)
    after = _declarations(reformatted)

    assert {key: item.signature for key, item in before.items()} == {
        key: item.signature for key, item in after.items()
    }


def test_unbalanced_braces_are_a_parse_error() -> None:
    with pytest.raises(DeclarationParseError, match="unclosed"):
        parse_c_header("struct Broken\n{\n    int x;\n")


def test_comment_over_a_commented_out_member_does_not_deprecate_the_next_one() -> None:
    # MaaDef.h keeps removed options as comments under a `// Deprecated` heading.
    text = """\
enum MaaGlobalOptionEnum
{
    MaaGlobalOption_SaveDraw = 2,

    // Deprecated
    // Whether to show hit draw
    // MaaGlobalOption_ShowHitDraw = 5,

    /// Whether to debug
    MaaGlobalOption_DebugMode = 6,
};
"""
    declarations = _declarations(text)

    assert not declarations[("enum-value", "MaaGlobalOption_DebugMode")].deprecated
    assert ("enum-value", "MaaGlobalOption_ShowHitDraw") not in declarations


def test_trailing_comment_deprecates_its_own_line() -> None:
    text = """\
#define MaaWin32InputMethod_LegacyEvent (1ULL << 3)
#define MaaWin32InputMethod_PostThreadMessage (1ULL << 4) // Deprecated
enum MaaE
{
    MaaE_Old = 1, // Deprecated: use MaaE_New
    MaaE_New = 2,
};
"""
    declarations = _declarations(text)

    post = declarations[("constant", "MaaWin32InputMethod_PostThreadMessage")]
    assert post.deprecated and post.note == "Deprecated"
    assert post.signature == "(1ULL<<4)"
    assert not declarations[("constant", "MaaWin32InputMethod_LegacyEvent")].deprecated
    assert declarations[("enum-value", "MaaE_Old")].note == "Deprecated: use MaaE_New"
    assert not declarations[("enum-value", "MaaE_New")].deprecated


def test_deprecation_attributes_keep_symbol_and_signature() -> None:
    text = """\
enum MaaE
{
    MaaE_A [[deprecated("use MaaE_C")]] = 1,
    MaaE_B __attribute__((deprecated)) = 2,
    MaaE_C = 3,
};
__declspec(deprecated("use MaaNew")) MAA_FRAMEWORK_API MaaBool MaaOld(void);
"""
    declarations = _declarations(text)

    first = declarations[("enum-value", "MaaE_A")]
    assert first.deprecated and first.note == '[[deprecated("use MaaE_C")]]'
    assert first.signature == "1"
    assert declarations[("enum-value", "MaaE_B")].signature == "2"
    old = declarations[("public-function", "MaaOld")]
    assert old.deprecated and old.signature == "MaaBool MaaOld(void)"


def test_typedef_and_struct_of_one_name_agree() -> None:
    forward = _declarations("typedef struct MaaCallbacks MaaCallbacks;\n")
    definition = _declarations("struct MaaCallbacks\n{\n    int x;\n};\n")

    key = ("type-definition", "MaaCallbacks")
    assert forward[key].signature == definition[key].signature == "struct MaaCallbacks"


def test_class_head_keeps_its_bases() -> None:
    text = """\
class Win32ControlUnitAPI
    : public ControlUnitAPI
    , public ScrollableUnit
{
public:
    virtual ~Win32ControlUnitAPI() = default;
};
"""
    declarations = _declarations(text)

    head = declarations[("type-definition", "Win32ControlUnitAPI")]
    assert head.signature == "class Win32ControlUnitAPI:public ControlUnitAPI,public ScrollableUnit"
    assert not any(kind == "public-function" for kind, _ in declarations)


def test_inline_and_template_functions_drop_their_bodies() -> None:
    text = """\
MAA_CTRL_UNIT_NS_BEGIN

template <typename ParamT>
inline json::value make_record_json(const RecordLine& line, const ParamT& param)
{
    json::value j = line;
    for (auto& [k, v] : param.as_object()) {
        j[k] = std::move(v);
    }
    return j;
}

inline json::value make_record_json(const RecordLine& line)
{
    return json::value(line);
}

MAA_CTRL_UNIT_NS_END
"""
    declarations = _declarations(text)

    assert set(declarations) == {("public-function", "make_record_json")}
    assert declarations[("public-function", "make_record_json")].signature == (
        "inline json::value make_record_json(const RecordLine&line)"
        " | template<typename ParamT>inline json::value make_record_json("
        "const RecordLine&line,const ParamT&param)"
    )


def test_member_initializers_and_constructors() -> None:
    text = """\
class Session
{
public:
    Session() : retries_{1}, name_("x") { reset(); }
    std::function<void(int)> callback {};
    int retries_{3};
};
"""
    declarations = _declarations(text)

    assert declarations[("public-function", "Session::Session")].signature == "Session()"
    assert declarations[("struct-field", "Session.callback")].signature == (
        "std::function<void(int)>callback{}"
    )
    assert declarations[("struct-field", "Session.retries_")].signature == "int retries_{3}"


def test_strings_and_comments_are_not_code() -> None:
    text = """\
/* struct Hidden { int x; }; */
// MAA_FRAMEWORK_API void MaaCommented(void);
MAA_FRAMEWORK_API MaaBool MaaSplit(const char* text /* { */, char sep = '}');
#define MaaMsg_Brace ("Brace.{x;y}")
"""
    declarations = _declarations(text)

    assert set(declarations) == {
        ("public-function", "MaaSplit"),
        ("callback-message", "MaaMsg_Brace"),
    }
    assert declarations[("public-function", "MaaSplit")].signature == (
        "MaaBool MaaSplit(const char*text,char sep='}')"
    )
    assert declarations[("callback-message", "MaaMsg_Brace")].signature == '("Brace.{x;y}")'
