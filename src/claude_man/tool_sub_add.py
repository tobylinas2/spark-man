import argparse
import sys
import re

from .config import load_config
from .subscribe import add_subscribe


def main():
    parser = argparse.ArgumentParser(description="添加订阅规则")
    parser.add_argument("--man")
    parser.add_argument("type_name", help="消息类型，如 wexin.group_message")
    parser.add_argument("props", nargs="*", help="props 匹配规则，格式 key=regex")
    args = parser.parse_args()

    if not args.man:
        print("请指定 --man", file=sys.stderr)
        sys.exit(1)

    props = {}
    for p in args.props:
        if "=" not in p:
            print(f"无效格式: {p}，应为 key=regex", file=sys.stderr)
            sys.exit(1)
        key, _, pattern = p.partition("=")
        try:
            re.compile(pattern)
        except re.error as e:
            print(f"无效正则 {pattern!r}: {e}", file=sys.stderr)
            sys.exit(1)
        props[key] = pattern

    cfg = load_config(args.man)
    add_subscribe(cfg.work_dir, args.type_name, props)
    props_str = ", ".join(f"{k}={v}" for k, v in props.items())
    print(f"已添加订阅: {args.type_name} ({props_str})")
