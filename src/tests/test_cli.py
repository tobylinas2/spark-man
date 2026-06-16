"""CLI 模块测试"""
from claude_man.cli import TOOL_NAMES, _get_template_dir, cmd_template_list


def test_tool_names():
    """测试工具名列表完整"""
    assert "msg_list.py" in TOOL_NAMES
    assert "msg_show.py" in TOOL_NAMES
    assert "msg_mark.py" in TOOL_NAMES
    assert "sub_list.py" in TOOL_NAMES
    assert "sub_add.py" in TOOL_NAMES
    assert "sub_remove.py" in TOOL_NAMES
    assert "gh_config.py" in TOOL_NAMES
    assert len(TOOL_NAMES) == 7


def test_template_dir():
    """测试模板目录路径"""
    path = _get_template_dir("default")
    assert path.endswith("templates/default")
