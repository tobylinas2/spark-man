"""GitHub 公共函数测试"""
from claude_man.source_github_common import ensure_list


def test_ensure_list_with_list():
    """测试输入已是列表"""
    assert ensure_list([1, 2, 3]) == [1, 2, 3]


def test_ensure_list_with_none():
    """测试输入为 None"""
    assert ensure_list(None) == []


def test_ensure_list_with_empty():
    """测试输入为空列表"""
    assert ensure_list([]) == []


def test_ensure_list_with_string():
    """测试输入为字符串（非列表应返回空列表）"""
    assert ensure_list("hello") == []
