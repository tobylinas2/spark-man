"""Worker 公共函数测试"""
from claude_man.worker_common import calc_delay, build_system_prompt
from types import SimpleNamespace


def test_calc_delay():
    """测试退避延迟计算"""
    config = SimpleNamespace(retry=SimpleNamespace(
        initial_delay=60, backoff_factor=5, max_delay=3600
    ))
    assert calc_delay(0, config) == 60
    assert calc_delay(1, config) == 300
    assert calc_delay(2, config) == 1500
    assert calc_delay(3, config) == 3600  # capped


def test_build_system_prompt():
    """测试 system prompt 生成"""
    prompt = build_system_prompt("/tmp/tools")
    assert "/tmp/tools/msg_list.py" in prompt
    assert "/tmp/tools/msg_show.py" in prompt
    assert "/tmp/tools/sub_list.py" in prompt
    assert "/tmp/tools/gh_config.py" in prompt
