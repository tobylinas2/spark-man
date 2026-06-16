"""数据库模块测试"""
from claude_man.db import init_db, add_message, count_pending, get_popup_messages, mark_processed
import tempfile, os


def test_init_db():
    """测试数据库初始化"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        init_db(db_path)
        assert os.path.exists(db_path)
    finally:
        os.unlink(db_path)


def test_add_message():
    """测试添加消息"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        init_db(db_path)
        msg_id = add_message(db_path, "test.type", {"key": "val"}, "hello", level="popup")
        assert msg_id > 0
        assert count_pending(db_path) == 1
        rows = get_popup_messages(db_path)
        assert len(rows) == 1
        assert rows[0]["type_name"] == "test.type"
    finally:
        os.unlink(db_path)


def test_mark_processed():
    """测试标记已处理"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        init_db(db_path)
        msg_id = add_message(db_path, "test.type", {}, "data", level="popup")
        assert count_pending(db_path) == 1
        mark_processed(db_path, [msg_id])
        assert count_pending(db_path) == 0
    finally:
        os.unlink(db_path)


def test_add_message_bytes():
    """测试 bytes 类型 data"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        init_db(db_path)
        msg_id = add_message(db_path, "test.type", {}, b"bytes data", level="popup")
        assert msg_id > 0
        rows = get_popup_messages(db_path)
        assert rows[0]["data"] == "bytes data"
    finally:
        os.unlink(db_path)


def test_silent_message_not_pending():
    """测试 silent 消息不计入 pending"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        init_db(db_path)
        add_message(db_path, "silent.type", {}, "silent", level="silent")
        assert count_pending(db_path) == 0
    finally:
        os.unlink(db_path)
