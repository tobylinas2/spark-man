"""
GitHub Source 插件 — 通过 `gh` CLI 轮询仓库的 Issue、PR、Discussion、评论。

配置: ~/.claude-man/sources/github/config.yaml
状态: ~/.claude-man/sources/github/state.json

依赖: gh CLI (需已认证: gh auth status)

Source 插件不知道下游有哪些 Claude Man。
轮询到新事件后直接调用 dispatch()，由 dispatcher 按订阅规则路由。
"""

import json
import os
import re
import subprocess
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import yaml

from .dispatcher import dispatch
from .config import CLAUDE_MAN_HOME

log = logging.getLogger("source.github")

SOURCE_DIR = os.path.join(CLAUDE_MAN_HOME, "sources", "github")
CONFIG_FILE = "config.yaml"
STATE_FILE = "state.json"


# ─── 工具函数 ────────────────────────────────────────────────


def _gh(api_path: str) -> list | dict:
    """调用 gh api 并返回解析后的 JSON。"""
    result = subprocess.run(
        ["gh", "api", api_path, "--jq", "."],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "403" in stderr or "429" in stderr:
            log.warning("gh api 限流: %s → %s", api_path, stderr)
        else:
            log.warning("gh api 失败: %s → %s", api_path, stderr)
        return []
    if not result.stdout.strip():
        return []
    return json.loads(result.stdout)


def _gh_graphql(query: str, variables: Optional[dict] = None) -> dict:
    """调用 gh api graphql。"""
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    if variables:
        for k, v in variables.items():
            if isinstance(v, bool):
                args.extend(["-F", f"{k}={str(v).lower()}"])
            elif isinstance(v, (int, float)):
                args.extend(["-F", f"{k}={v}"])
            else:
                args.extend(["-f", f"{k}={v}"])
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "403" in stderr or "429" in stderr:
            log.warning("gh graphql 限流: %s", stderr)
        else:
            log.warning("gh graphql 失败: %s", stderr)
        return {}
    return json.loads(result.stdout)


def _since_param(since: str) -> str:
    """将 ISO 时间转成 GitHub API 需要的 ISO8601 格式。"""
    if not since:
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return since


# ─── 配置/状态读写 ──────────────────────────────────────────


from .source_github_common import ensure_source_dir, ensure_list as _ensure_list
def _ensure_source_dir():
    return ensure_source_dir(SOURCE_DIR)


def load_config() -> dict:
    _ensure_source_dir()
    path = os.path.join(SOURCE_DIR, CONFIG_FILE)
    if not os.path.exists(path):
        return {"repos": []}
    with open(path) as f:
        raw = yaml.safe_load(f)
    return raw or {"repos": []}


def save_config(cfg: dict) -> None:
    _ensure_source_dir()
    path = os.path.join(SOURCE_DIR, CONFIG_FILE)
    with open(path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)


def load_state() -> dict:
    _ensure_source_dir()
    path = os.path.join(SOURCE_DIR, STATE_FILE)
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def save_state(state: dict) -> None:
    _ensure_source_dir()
    path = os.path.join(SOURCE_DIR, STATE_FILE)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


# ─── 事件轮询 ────────────────────────────────────────────────


def _repo_full(repo: dict) -> str:
    return f"{repo['owner']}/{repo['name']}"


def _should_poll(repo: dict, event_type: str) -> bool:
    events = repo.get("events", [])
    return event_type in events


def _fetch_issues_since(full: str, since: str) -> list:
    """获取指定仓库的 issues（含 PR），供 poll_issues 和 poll_prs 共享。"""
    return _gh(f"/repos/{full}/issues?state=all&sort=created&direction=desc&since={since}")




def poll_issues(repo: dict, state: dict, items: list | None = None) -> None:
    """轮询 Issue 和 PR（GitHub Issues API 同时返回二者，PR 带 pull_request 字段）。"""
    full = _repo_full(repo)
    repostate = state.setdefault(full, {})

    # ── Issue ──
    if _should_poll(repo, "issue.opened") or _should_poll(repo, "issue.comment"):
        since = _since_param(repostate.get("last_poll", ""))
        if items is None:
            items = _gh(f"/repos/{full}/issues?state=all&sort=created&direction=desc&since={since}")
        known_ids = set(_ensure_list(repostate.get("known_issues", [])))

        for item in _ensure_list(items):
            if item.get("pull_request"):
                continue
            node_id = item.get("node_id", "")
            if node_id and node_id in known_ids:
                continue
            if node_id:
                known_ids.add(node_id)

            body = item.get("body", "") or ""
            title = item.get("title", "") or ""
            user = (item.get("user") or {}).get("login", "")
            body_preview = body[:500].replace("\n", " ").strip()
            summary = f"[{user}] {title}" + (f"\n{body_preview}" if body_preview else "")

            dispatch(
                type_name="github.issue",
                props={
                    "repo": full,
                    "number": item["number"],
                    "summary": summary,
                },
                data={
                    "action": "opened",
                    "title": title,
                    "body": body,
                    "state": item.get("state", "open"),
                    "user": user,
                    "url": item.get("html_url", ""),
                    "created_at": item.get("created_at", ""),
                },
            )

        repostate["known_issues"] = list(known_ids)

    # ── Issue 评论 ──
    if _should_poll(repo, "issue.comment"):
        since = _since_param(repostate.get("last_comment_poll", ""))
        comments = _gh(f"/repos/{full}/issues/comments?since={since}&sort=created&direction=desc")
        known_cids = set(_ensure_list(repostate.get("known_comments", [])))

        for c in _ensure_list(comments):
            node_id = c.get("node_id", "")
            if node_id and node_id in known_cids:
                continue
            if node_id:
                known_cids.add(node_id)

            issue_url = c.get("issue_url", "")
            issue_number = None
            if issue_url:
                m = re.search(r"/issues/(\d+)$", issue_url)
                if m:
                    issue_number = int(m.group(1))

            body = c.get("body", "") or ""
            user = (c.get("user") or {}).get("login", "")
            body_preview = body[:500].replace("\n", " ").strip()
            summary = f"[{user}] 评论于 #{issue_number}" + (f"\n{body_preview}" if body_preview else "")

            dispatch(
                type_name="github.issue_comment",
                props={
                    "repo": full,
                    "issue_number": str(issue_number) if issue_number else "",
                    "summary": summary,
                },
                data={
                    "issue_number": issue_number,
                    "body": body,
                    "user": user,
                    "url": c.get("html_url", ""),
                    "created_at": c.get("created_at", ""),
                },
            )

        repostate["known_comments"] = list(known_cids)


def poll_prs(repo: dict, state: dict, items: list | None = None) -> None:
    """轮询 PR（含 review）。"""
    full = _repo_full(repo)
    repostate = state.setdefault(full, {})

    if not (_should_poll(repo, "pr.opened") or _should_poll(repo, "pr.comment") or _should_poll(repo, "pr.review")):
        return

    since = _since_param(repostate.get("last_pr_poll", ""))
    if items is None:
        items = _gh(f"/repos/{full}/issues?state=all&sort=created&direction=desc&since={since}")
    known_ids = set(_ensure_list(repostate.get("known_prs", [])))

    for item in _ensure_list(items):
        if not item.get("pull_request"):
            continue
        node_id = item.get("node_id", "")
        if node_id and node_id in known_ids:
            continue
        if node_id:
            known_ids.add(node_id)

        title = item.get("title", "") or ""
        user = (item.get("user") or {}).get("login", "")
        body = item.get("body", "") or ""
        draft = item.get("draft", False)
        body_preview = body[:500].replace("\n", " ").strip()
        draft_tag = " [DRAFT]" if draft else ""
        summary = f"[{user}] PR #{item['number']}{draft_tag}: {title}"
        if body_preview:
            summary += f"\n{body_preview}"

        dispatch(
            type_name="github.pr",
            props={"repo": full, "number": item["number"], "summary": summary},
            data={
                "action": "opened",
                "title": title,
                "body": body,
                "state": item.get("state", "open"),
                "user": user,
                "url": item.get("html_url", ""),
                "created_at": item.get("created_at", ""),
                "draft": draft,
            },
        )

    repostate["known_prs"] = list(known_ids)


def poll_discussions(repo: dict, state: dict) -> None:
    """通过 GraphQL 轮询 Discussion。"""
    if not _should_poll(repo, "discussion.created") and not _should_poll(repo, "discussion.comment"):
        return

    full = _repo_full(repo)
    owner, name = repo["owner"], repo["name"]
    repostate = state.setdefault(full, {})

    known_ids = set(_ensure_list(repostate.get("known_discussions", [])))
    since = repostate.get("last_discussion_poll", "")

    query = """
    query($owner: String!, $repo: String!, $first: Int!) {
      repository(owner: $owner, name: $repo) {
        discussions(first: $first, orderBy: {field: CREATED_AT, direction: DESC}) {
          nodes {
            id
            number
            title
            body
            url
            createdAt
            author { login }
            category { name }
          }
        }
      }
    }
    """
    result = _gh_graphql(query, {"owner": owner, "repo": name, "first": 20})
    try:
        nodes = result["data"]["repository"]["discussions"]["nodes"]
    except (KeyError, TypeError):
        return

    for node in nodes:
        node_id = node.get("id", "")
        created = node.get("createdAt", "")
        if node_id and node_id in known_ids:
            continue
        if since and created <= since:
            continue
        if node_id:
            known_ids.add(node_id)

        title = node.get("title", "") or ""
        user = (node.get("author") or {}).get("login", "")
        body = node.get("body", "") or ""
        category = (node.get("category") or {}).get("name", "")
        body_preview = body[:500].replace("\n", " ").strip()
        summary = f"[{user}] [{category}] {title}" + (f"\n{body_preview}" if body_preview else "")

        dispatch(
            type_name="github.discussion",
            props={"repo": full, "number": node["number"], "summary": summary},
            data={
                "action": "opened",
                "title": title,
                "body": body,
                "category": category,
                "user": user,
                "url": node.get("url", ""),
                "created_at": created,
            },
        )

    repostate["known_discussions"] = list(known_ids)


def poll_discussion_comments(repo: dict, state: dict) -> None:
    """轮询 Discussion 评论。"""
    if not _should_poll(repo, "discussion.comment"):
        return

    full = _repo_full(repo)
    owner, name = repo["owner"], repo["name"]
    repostate = state.setdefault(full, {})

    known_cids = set(_ensure_list(repostate.get("known_discussion_comments", [])))
    # 取已知 discussions 列表（若没有则跳过）
    known_disc_ids = _ensure_list(repostate.get("known_discussions", []))
    if not known_disc_ids:
        return

    for disc_id in known_disc_ids:
        # 用 GraphQL 取每个 discussion 的评论
        query = """
        query($owner: String!, $repo: String!, $number: Int!) {
          repository(owner: $owner, name: $repo) {
            discussion(number: $number) {
              comments(first: 20, orderBy: {field: UPDATED_AT, direction: DESC}) {
                nodes {
                  id
                  body
                  url
                  createdAt
                  author { login }
                }
              }
            }
          }
        }
        """
        result = _gh_graphql(query, {"owner": owner, "repo": name, "number": disc_id})
        try:
            nodes = result["data"]["repository"]["discussion"]["comments"]["nodes"]
        except (KeyError, TypeError):
            continue

        for node in nodes:
            node_id = node.get("id", "")
            if node_id and node_id in known_cids:
                continue
            if node_id:
                known_cids.add(node_id)

            body = node.get("body", "") or ""
            user = (node.get("author") or {}).get("login", "")
            body_preview = body[:500].replace("\n", " ").strip()
            summary = f"[{user}] 评论于 Discussion #{disc_id}" + (f"\n{body_preview}" if body_preview else "")

            dispatch(
                type_name="github.discussion_comment",
                props={
                    "repo": full,
                    "discussion_number": str(disc_id),
                    "summary": summary,
                },
                data={
                    "discussion_number": disc_id,
                    "body": body,
                    "user": user,
                    "url": node.get("url", ""),
                    "created_at": node.get("createdAt", ""),
                },
            )

    repostate["known_discussion_comments"] = list(known_cids)


# ─── 轮询主循环 ──────────────────────────────────────────────


def poll_once() -> dict:
    """执行一轮轮询，返回统计。"""
    cfg = load_config()
    state = load_state()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stats = {"repos": 0, "events": 0}

    for repo in cfg.get("repos", []):
        stats["repos"] += 1
        full = _repo_full(repo)
        repostate = state.setdefault(full, {})
        # 共享一次 API 调用给 issues 和 PRs
        need_issues = (_should_poll(repo, "issue.opened") or _should_poll(repo, "issue.comment")
                       or _should_poll(repo, "pr.opened") or _should_poll(repo, "pr.comment")
                       or _should_poll(repo, "pr.review"))
        shared_items = None
        if need_issues:
            since = _since_param(repostate.get("last_poll", ""))
            shared_items = _gh(f"/repos/{full}/issues?state=all&sort=created&direction=desc&since={since}")
        poll_issues(repo, state, shared_items)
        poll_prs(repo, state, shared_items)
        poll_discussions(repo, state)
        poll_discussion_comments(repo, state)
        # full/repostate 已在上面定义，直接使用
        
        repostate["last_poll"] = now
        if _should_poll(repo, "issue.comment"):
            repostate["last_comment_poll"] = now
        if _should_poll(repo, "pr.opened") or _should_poll(repo, "pr.comment") or _should_poll(repo, "pr.review"):
            repostate["last_pr_poll"] = now
        if _should_poll(repo, "discussion.created") or _should_poll(repo, "discussion.comment"):
            repostate["last_discussion_poll"] = now
        if _should_poll(repo, "discussion.comment"):
            repostate["last_discussion_comment_poll"] = now

    save_state(state)
    return stats


def main_loop(interval: int = 60) -> None:
    """持续轮询循环。"""
    log.info("GitHub Source 启动, interval=%ds", interval)
    while True:
        try:
            stats = poll_once()
            log.info("轮询完成: %d repos", stats["repos"])
        except KeyboardInterrupt:
            log.info("GitHub Source 收到中断，退出。")
            break
        except Exception as e:
            log.error("轮询异常: %s", e)
        time.sleep(interval)


# ─── CLI ─────────────────────────────────────────────────────


def cli_main():
    import argparse
    parser = argparse.ArgumentParser(prog="claude-man-source-github", description="GitHub Source 插件")
    parser.add_argument("--interval", type=int, default=60, help="轮询间隔（秒，默认 60）")
    parser.add_argument("--once", action="store_true", help="只执行一轮轮询，不持续循环")
    parser.add_argument("--poll", action="store_true", help="单轮轮询的别名")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    if args.once or args.poll:
        stats = poll_once()
        print(f"轮询完成: {stats['repos']} repos")
        return

    main_loop(interval=args.interval)


if __name__ == "__main__":
    cli_main()
