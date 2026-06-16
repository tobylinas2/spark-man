import argparse
import sys

from .config import load_config
from .db import mark_processed, mark_all_popup_processed


def main():
    parser = argparse.ArgumentParser(description="标记消息已处理")
    parser.add_argument("--db-path")
    parser.add_argument("--man")
    parser.add_argument("ids", type=int, nargs="*", help="消息 ID")
    parser.add_argument("--all", action="store_true", help="标记所有弹出消息为已处理")
    args = parser.parse_args()

    db_path = args.db_path
    if not db_path and args.man:
        cfg = load_config(args.man)
        db_path = cfg.db_path
    if not db_path:
        print("请指定 --db-path 或 --man", file=sys.stderr)
        sys.exit(1)

    if args.all:
        count = mark_all_popup_processed(db_path)
        print(f"已标记 {count} 条弹出消息为已处理。")
    elif args.ids:
        count = mark_processed(db_path, args.ids)
        print(f"已标记 {count} 条消息为已处理。")
    else:
        print("请指定消息 ID 或使用 --all", file=sys.stderr)
        sys.exit(1)
