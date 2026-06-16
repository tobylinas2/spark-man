"""预览模块测试"""
from claude_man.preview import _parse_props, format_brief, format_preview


def test_parse_props_valid():
    """测试解析有效 props"""
    result = _parse_props({"props": '{"summary":"test","number":42}'})
    assert result == {"summary": "test", "number": 42}


def test_parse_props_empty():
    """测试解析空 props"""
    assert _parse_props({"props": ""}) == {}
    assert _parse_props({"props": "{}"}) == {}


def test_parse_props_no_props():
    """测试无 props 字段"""
    assert _parse_props({}) == {}


def test_parse_props_invalid():
    """测试解析无效 JSON"""
    assert _parse_props({"props": "not json"}) == {}
