import os
import re
import yaml

from .config import load_config

ME_DIR_NAME = ".me"
SUBSCRIBE_FILE = "message.yaml"


def get_me_dir(work_dir: str) -> str:
    return os.path.join(work_dir, ME_DIR_NAME)


def get_subscribe_path(work_dir: str) -> str:
    return os.path.join(get_me_dir(work_dir), SUBSCRIBE_FILE)


def ensure_me_dir(work_dir: str) -> str:
    path = get_me_dir(work_dir)
    os.makedirs(path, exist_ok=True)
    return path


def load_subscribes(work_dir: str) -> list[dict]:
    path = get_subscribe_path(work_dir)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        raw = yaml.safe_load(f)
    if not raw or "subscribe_messages" not in raw:
        return []
    return raw["subscribe_messages"]


def save_subscribes(work_dir: str, rules: list[dict]) -> None:
    ensure_me_dir(work_dir)
    path = get_subscribe_path(work_dir)
    data = {"subscribe_messages": rules}
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def match_subscribe(type_name: str, props: dict, rules: list[dict]) -> bool:
    for rule in rules:
        if rule.get("type") != type_name:
            continue
        rule_props = rule.get("props", {})
        if not rule_props:
            return True
        match = True
        for key, pattern in rule_props.items():
            val = props.get(key, "")
            if not pattern or not re.search(pattern, str(val)):
                match = False
                break
        if match:
            return True
    return False


def add_subscribe(work_dir: str, type_name: str, props: dict[str, str]) -> None:
    rules = load_subscribes(work_dir)
    rules.append({"type": type_name, "props": props})
    save_subscribes(work_dir, rules)


def remove_subscribe(work_dir: str, index: int) -> dict | None:
    rules = load_subscribes(work_dir)
    if index < 0 or index >= len(rules):
        return None
    removed = rules.pop(index)
    save_subscribes(work_dir, rules)
    return removed
