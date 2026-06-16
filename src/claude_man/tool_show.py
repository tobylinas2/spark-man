import json
import argparse
import sys

from .config import load_config
from .db import get_message


def _pretty(obj):
    if isinstance(obj, str):
        try:
            return json.dumps(json.loads(obj), ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, TypeError):
            return obj
    return json.dumps(obj, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="查看消息全文")
    parser.add_argument("--db-path")
    parser.add_argument("--man")
    parser.add_argument("id", type=int, help="消息 ID")
    args = parser.parse_args()

    db_path = args.db_path
    if not db_path and args.man:
        cfg = load_config(args.man)
        db_path = cfg.db_path
    if not db_path:
        print("请指定 --db-path 或 --man", file=sys.stderr)
        sys.exit(1)

    row = get_message(db_path, args.id)
    if not row:
        print(f"消息 #{args.id} 不存在。")
        return

    print(f"Message #{row['id']}")
    print("─" * 40)
    print(f"Type:   {row['type_name']}")
    print(f"Level:  {row['level']}")
    print(f"Status: {row['status']}")
    print(f"Created: {row['created_at']}")
    if row["processed_at"]:
        print(f"Processed: {row['processed_at']}")
    print()
    print("Props:")
    print(_pretty(row["props"]))
    # 如果 props 中有 summary，单独高亮显示
    try:
        parsed = json.loads(row["props"]) if isinstance(row["props"], str) else row["props"]
        if isinstance(parsed, dict) and "summary" in parsed:
            print()
            print("Summary:")
            print(parsed["summary"])
    except (json.JSONDecodeError, TypeError):
        pass
    print()
    print("Data:")
    print(_pretty(row["data"]))
