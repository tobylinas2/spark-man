import argparse
import json
import sys

from .config import load_config
from .db import get_popup_messages, search_messages, count_by_level


def main():
    parser = argparse.ArgumentParser(description="列出消息")
    parser.add_argument("--db-path", help="messages.db 路径")
    parser.add_argument("--man", help="Claude Man 名称")
    parser.add_argument("--level", choices=["popup", "silent"])
    parser.add_argument("--type")
    parser.add_argument("--search")
    args = parser.parse_args()

    db_path = args.db_path
    if not db_path and args.man:
        cfg = load_config(args.man)
        db_path = cfg.db_path
    if not db_path:
        print("请指定 --db-path 或 --man", file=sys.stderr)
        sys.exit(1)

    counts = count_by_level(db_path)

    # 默认列出最新 10 条 popup；有筛选参数时使用 search
    if args.level or args.type or args.search:
        rows = search_messages(
            db_path,
            level=args.level,
            type_name=args.type,
            search=args.search,
        )
    else:
        rows = get_popup_messages(db_path, limit=10)

    # 打印统计
    popup_pending = counts["popup"]["pending"]
    popup_processed = counts["popup"]["processed"]
    silent = counts["silent"]
    if popup_pending > 0:
        print(f"弹出 {popup_pending} 条 (已处理 {popup_processed}) / 静默 {silent} 条\n")
    elif rows:
        print(f"弹出 {popup_pending} 条 (已处理 {popup_processed}) / 静默 {silent} 条\n")
    else:
        print(f"弹出 {popup_pending} 条 (已处理 {popup_processed}) / 静默 {silent} 条")

    if not rows:
        if not (args.level or args.type or args.search):
            print("\n提示: 用 --level silent 查看静默消息，--type xxx 按类型筛选")
        return

    header = f"{'ID':<6} {'Level':<7} {'Type':<25} {'Preview':<45} {'Created'}"
    print(header)
    print("-" * len(header))
    for row in rows:
        # 优先使用 props.summary 作为预览
        props_raw = row["props"]
        summary = ""
        if props_raw and props_raw != "{}":
            try:
                parsed = json.loads(props_raw) if isinstance(props_raw, str) else props_raw
                summary = parsed.get("summary", "")
            except (json.JSONDecodeError, TypeError):
                pass
        preview_text = summary if summary else row["data"]
        max_len = 45
        preview = (preview_text[:max_len - 3] + "...") if len(preview_text) > max_len else preview_text
        print(f"{row['id']:<6} {row['level']:<7} {row['type_name']:<25} {preview:<45} {row['created_at']}")
