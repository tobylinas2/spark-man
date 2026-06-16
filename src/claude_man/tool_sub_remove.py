import argparse
import sys

from .config import load_config
from .subscribe import remove_subscribe, load_subscribes
from .db import exclude_pending_by_type


def main():
    parser = argparse.ArgumentParser(description="删除订阅规则，并排除相关 pending 消息")
    parser.add_argument("--man")
    parser.add_argument("index", type=int, help="规则序号（从 sub_list 查看）")
    args = parser.parse_args()

    if not args.man:
        print("请指定 --man", file=sys.stderr)
        sys.exit(1)

    cfg = load_config(args.man)

    rules = load_subscribes(cfg.work_dir)
    if args.index < 0 or args.index >= len(rules):
        print(f"序号 {args.index} 不存在，共 {len(rules)} 条规则", file=sys.stderr)
        sys.exit(1)

    removed_type = rules[args.index].get("type", "")
    removed = remove_subscribe(cfg.work_dir, args.index)
    if not removed:
        print("删除失败", file=sys.stderr)
        sys.exit(1)

    if removed_type:
        count = exclude_pending_by_type(cfg.db_path, removed_type)
        if count > 0:
            print(f"已排除 {count} 条 {removed_type} 类型的 pending 消息（降级为静默）")

    print(f"已删除订阅: {removed['type']}")
