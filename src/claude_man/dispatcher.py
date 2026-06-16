import os
from typing import Optional

from .config import load_config, MANS_DIR
from .db import add_message as db_add_message, init_db
from .subscribe import load_subscribes, match_subscribe


def _discover_men() -> list[str]:
    """扫描 ~/.claude-man/mans/ 下所有已注册的 Claude Man。"""
    men = []
    if not os.path.isdir(MANS_DIR):
        return men
    for entry in os.listdir(MANS_DIR):
        man_dir = os.path.join(MANS_DIR, entry)
        config_path = os.path.join(man_dir, ".claude_man")
        if os.path.isdir(man_dir) and os.path.exists(config_path):
            men.append(entry)
    return sorted(men)


def dispatch(
    type_name: str,
    props: Optional[dict] = None,
    data: object = "",
) -> dict[str, int]:
    """按订阅规则自动路由消息到所有匹配的 Claude Man。

    Source 插件只需调用 dispatch(type, props, data)，
    不需要知道下游有哪些 Man、不需要指定 target。

    返回 {man_name: msg_id} 映射。
    """
    props = props or {}
    men = _discover_men()
    if not men:
        raise RuntimeError(
            "没有找到已注册的 Claude Man。先用 'claude-man init <name>' 初始化。"
        )

    result = {}
    for name in men:
        try:
            config = load_config(name)
        except (FileNotFoundError, ValueError):
            continue
        work_dir = config.work_dir
        if not os.path.isdir(work_dir):
            continue
        init_db(config.db_path)
        rules = load_subscribes(work_dir)
        level = "popup" if match_subscribe(type_name, props, rules) else "silent"
        msg_id = db_add_message(config.db_path, type_name, props, data, level)
        result[name] = msg_id

    return result


def dispatch_to(
    target: str,
    type_name: str,
    props: Optional[dict] = None,
    data: object = "",
) -> int:
    """显式投递消息到指定 Claude Man（CLI 等场景用）。"""
    config = load_config(target)
    init_db(config.db_path)
    rules = load_subscribes(config.work_dir)
    level = "popup" if match_subscribe(type_name, props or {}, rules) else "silent"
    return db_add_message(config.db_path, type_name, props or {}, data, level)
