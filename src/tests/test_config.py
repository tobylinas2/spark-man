"""配置模块测试"""
from claude_man.config import PreviewConfig, RetryConfig, Config


def test_preview_config_defaults():
    """测试 PreviewConfig 默认值"""
    cfg = PreviewConfig()
    assert cfg.max_preview_length == 200
    assert cfg.max_messages_per_turn == 10


def test_retry_config_defaults():
    """测试 RetryConfig 默认值"""
    cfg = RetryConfig()
    assert cfg.initial_delay == 60
    assert cfg.max_delay == 3600
    assert cfg.backoff_factor == 5


def test_config_properties():
    """测试 Config 属性"""
    cfg = Config(name="test", work_dir="/tmp/test-man")
    assert cfg.db_path == "/tmp/test-man/messages.db"
    assert cfg.tools_dir == "/tmp/test-man/tools"
