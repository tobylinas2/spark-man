"""订阅模块测试"""
from claude_man.subscribe import match_subscribe


def test_match_simple():
    """测试简单类型匹配"""
    rules = [{"type": "github.issue", "props": {}}]
    assert match_subscribe("github.issue", {}, rules)
    assert not match_subscribe("github.pr", {}, rules)


def test_match_with_props():
    """测试带属性匹配"""
    rules = [{"type": "github.issue", "props": {"repo": "tobyprime/claude-man"}}]
    assert match_subscribe("github.issue", {"repo": "tobyprime/claude-man"}, rules)
    assert not match_subscribe("github.issue", {"repo": "other/repo"}, rules)


def test_match_empty_pattern():
    """测试空 pattern 应跳过（不匹配）"""
    rules = [{"type": "test.type", "props": {"key": ""}}]
    assert not match_subscribe("test.type", {"key": "anything"}, rules)
