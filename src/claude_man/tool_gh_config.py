import argparse
import sys

from .source_github import load_config as gh_load, save_config as gh_save


def main():
    parser = argparse.ArgumentParser(description="管理 GitHub Source 配置")
    parser.add_argument("--man")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ls = sub.add_parser("list", help="列出已配置的仓库")
    p_ls.set_defaults(func=cmd_list)

    p_add = sub.add_parser("add", help="添加仓库")
    p_add.add_argument("repo", help="owner/name")
    p_add.add_argument("--events", nargs="*",
                       default=["issue.opened", "issue.comment", "pr.opened",
                                "pr.comment", "discussion.created"])
    p_add.set_defaults(func=cmd_add)

    p_rm = sub.add_parser("remove", help="移除仓库")
    p_rm.add_argument("index", type=int, help="序号")
    p_rm.set_defaults(func=cmd_remove)

    args = parser.parse_args()
    args.func(args, parser)


def cmd_list(args, parser):
    ghcfg = gh_load()
    repos = ghcfg.get("repos", [])
    if not repos:
        print("没有配置的仓库。")
        print("用: gh_config.py add <owner/name>")
        return
    print(f"共 {len(repos)} 个仓库:\n")
    for i, repo in enumerate(repos):
        events = ", ".join(repo.get("events", []))
        print(f"[{i}] {repo['owner']}/{repo['name']}  ({events})")


def cmd_add(args, parser):
    parts = args.repo.split("/")
    if len(parts) != 2:
        print("repo 格式应为 owner/name", file=sys.stderr)
        sys.exit(1)

    ghcfg = gh_load()
    ghcfg.setdefault("repos", []).append({
        "owner": parts[0],
        "name": parts[1],
        "events": args.events,
    })
    gh_save(ghcfg)
    print(f"已添加仓库 {args.repo}（{len(args.events)} 个事件类型）")


def cmd_remove(args, parser):
    ghcfg = gh_load()
    repos = ghcfg.get("repos", [])
    if args.index < 0 or args.index >= len(repos):
        print(f"序号 {args.index} 不存在", file=sys.stderr)
        sys.exit(1)
    removed = repos.pop(args.index)
    gh_save(ghcfg)
    print(f"已移除仓库 {removed['owner']}/{removed['name']}")
