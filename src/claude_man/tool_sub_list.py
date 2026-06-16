import argparse
import sys

from .config import load_config
from .subscribe import load_subscribes


def main():
    parser = argparse.ArgumentParser(description="查看订阅规则")
    parser.add_argument("--man")
    args = parser.parse_args()

    if not args.man:
        print("请指定 --man", file=sys.stderr)
        sys.exit(1)

    cfg = load_config(args.man)
    rules = load_subscribes(cfg.work_dir)
    if not rules:
        print("没有订阅规则。\n")
        print("用 sub_add.py <type> <key=regex> [key=regex ...] 添加规则。")
        print("例如: sub_add.py wexin.group_message group_name=^项目")
        return

    print(f"共 {len(rules)} 条订阅规则:\n")
    for i, rule in enumerate(rules):
        props_str = ", ".join(f"{k}={v}" for k, v in rule.get("props", {}).items())
        print(f"[{i}] {rule['type']}  ({props_str})")
