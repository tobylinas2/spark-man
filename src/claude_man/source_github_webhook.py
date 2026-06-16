"""
GitHub Source 插件 — Webhook 版本。

通过 smee.io (SSE) 或直接 HTTP 接收 GitHub Webhook 事件，
解析后调用 dispatch() 投递到各 Claude Man 的消息队列。

两种运行模式:
  1. SSE 模式（默认）: 直连 smee.io，无需 smee CLI
     设置 SMEE_URL 环境变量或 webhook.yaml 中的 smee_url
  2. HTTP 模式: 配合 smee CLI 使用
     smee --url https://smee.io/XXXX --port 8080
     claude-man-source-github-webhook --http --port 8080

数据流:
  GitHub → smee.io → (SSE) → 本插件 → dispatch() → Claude Man

配置:
  ~/.claude-man/sources/github/config.yaml  (仓库/事件配置，与轮询版本共享)
  ~/.claude-man/sources/github/webhook.yaml (webhook 特有配置)

依赖: 纯标准库，无额外依赖
"""

import json
import logging
import os
import signal
import sys
import time
import hmac
import hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.error import URLError

import yaml

from .dispatcher import dispatch
from .config import CLAUDE_MAN_HOME

log = logging.getLogger("source.github-webhook")

SOURCE_DIR = os.path.join(CLAUDE_MAN_HOME, "sources", "github")
WEBHOOK_CONFIG_FILE = "webhook.yaml"

# ─── GitHub 事件 → claude-man 消息类型映射 ────────────────

_EVENT_MAP = {
    "issues": {
        "opened": "github.issue",
        "reopened": "github.issue",
        "closed": "github.issue",
        "edited": None,      # 跳过编辑事件（不产生新消息）
        "deleted": None,
        "labeled": None,
        "unlabeled": None,
        "assigned": None,
        "unassigned": None,
    },
    "issue_comment": {
        "created": "github.issue_comment",
        "edited": None,
        "deleted": None,
    },
    "pull_request": {
        "opened": "github.pr",
        "reopened": "github.pr",
        "closed": "github.pr",
        "ready_for_review": "github.pr",
        "edited": None,
        "review_requested": None,
        "review_request_removed": None,
        "synchronize": None,
        "labeled": None,
        "unlabeled": None,
    },
    "pull_request_review": {
        "submitted": None,   # TODO: 未来可添加 github.pr_review 类型
        "edited": None,
        "dismissed": None,
    },
    "discussion": {
        "created": "github.discussion",
        "edited": None,
        "deleted": None,
        "answered": None,
    },
    "discussion_comment": {
        "created": "github.discussion_comment",
        "edited": None,
        "deleted": None,
    },
}


# ─── 配置 ──────────────────────────────────────────────────


from .source_github_common import ensure_source_dir, ensure_list as _ensure_list
def _ensure_source_dir():
    return ensure_source_dir(SOURCE_DIR)


def load_shared_config() -> dict:
    """加载与轮询版本共享的 config.yaml。"""
    path = os.path.join(SOURCE_DIR, "config.yaml")
    if not os.path.exists(path):
        return {"repos": []}
    with open(path) as f:
        raw = yaml.safe_load(f)
    return raw or {"repos": []}


def load_webhook_config() -> dict:
    """加载 webhook 特有配置。"""
    _ensure_source_dir()
    path = os.path.join(SOURCE_DIR, WEBHOOK_CONFIG_FILE)
    if not os.path.exists(path):
        return {"port": 8080, "secret": "", "smee_url": ""}
    with open(path) as f:
        raw = yaml.safe_load(f)
    cfg = raw or {}
    cfg.setdefault("port", 8080)
    cfg.setdefault("secret", "")
    cfg.setdefault("smee_url", "")
    return cfg


def save_webhook_config(cfg: dict) -> None:
    _ensure_source_dir()
    path = os.path.join(SOURCE_DIR, WEBHOOK_CONFIG_FILE)
    with open(path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)


def _get_smee_url() -> str | None:
    """获取 smee.io URL，优先级: 环境变量 > webhook.yaml。"""
    env_url = os.environ.get("SMEE_URL", "").strip()
    if env_url:
        return env_url
    cfg = load_webhook_config()
    return cfg.get("smee_url", "").strip() or None


def _get_secret() -> str:
    cfg = load_webhook_config()
    return cfg.get("secret", "") or ""


def _is_repo_tracked(full_name: str) -> bool:
    """检查仓库是否在配置列表中。空列表表示接受所有仓库。"""
    cfg = load_shared_config()
    repos = cfg.get("repos", [])
    if not repos:
        return True  # 无配置则接受全部
    for repo in repos:
        if f"{repo['owner']}/{repo['name']}" == full_name:
            return True
    return False


def _normalize_event_name(gh_event: str) -> str:
    """将 GitHub webhook event 名转为 config.yaml 中的事件名。"""
    mapping = {
        "issues": "issue",
        "issue_comment": "issue",
        "pull_request": "pr",
        "pull_request_review": "pr",
        "discussion": "discussion",
        "discussion_comment": "discussion",
    }
    return mapping.get(gh_event, gh_event)


def _is_event_tracked(full_name: str, gh_event: str, action: str) -> bool:
    """检查事件类型是否在配置列表中。"""
    cfg = load_shared_config()
    repos = cfg.get("repos", [])
    norm_event = _normalize_event_name(gh_event)
    for repo in repos:
        if f"{repo['owner']}/{repo['name']}" != full_name:
            continue
        tracked = repo.get("events", [])
        # 构造类似 "issue.opened" 的格式与配置匹配
        event_key = f"{norm_event}.{action}"
        for t in tracked:
            if t == event_key:
                return True
            if t == norm_event:
                return True  # 简写 "issue" 匹配所有 issues 子事件
            # 兼容轮询时代的 config 事件名:
            #   "issue.comment" → gh_event "issue_comment"
            #   "pr.comment"    → gh_event "pull_request_review"
            if "." in t:
                cfg_cat, cfg_sub = t.split(".", 1)
                if cfg_cat == norm_event and f"{norm_event}_{cfg_sub}" == gh_event:
                    return True
                # pr.comment → pull_request_review
                if cfg_cat == "pr" and cfg_sub == "comment" and gh_event == "pull_request_review":
                    return True
        return False
    return False  # 仓库不在列表中应拒绝（防御性编程）


# ─── Webhook 签名验证 ──────────────────────────────────────


def verify_signature(payload_body: bytes, signature_header: str, secret: str) -> bool:
    """验证 x-hub-signature-256。"""
    if not secret:
        return True
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), payload_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


# ─── 事件处理 ──────────────────────────────────────────────


def _get_repo_full(payload: dict) -> str:
    repo = payload.get("repository") or {}
    return repo.get("full_name", "")





def handle_webhook_event(gh_event: str, payload_body: bytes) -> int:
    """处理单个 webhook 事件，返回投递的消息数。"""
    payload = json.loads(payload_body)
    action = payload.get("action", "")
    full_name = _get_repo_full(payload)

    if not full_name:
        log.warning("无法获取仓库信息，跳过")
        return 0

    # 检查仓库是否被跟踪
    if not _is_repo_tracked(full_name):
        log.debug("仓库 %s 未配置，跳过", full_name)
        return 0

    # 检查事件类型是否被跟踪
    if not _is_event_tracked(full_name, gh_event, action):
        log.debug("事件 %s.%s 未订阅，跳过", gh_event, action)
        return 0

    # 查找映射
    action_map = _EVENT_MAP.get(gh_event, {})
    msg_type = action_map.get(action)
    if msg_type is None:
        log.debug("未映射的事件类型: %s.%s，跳过", gh_event, action)
        return 0

    # 根据事件类型构建 props 和 data
    handler = _HANDLERS.get(gh_event)
    if handler is None:
        log.warning("无处理器: %s", gh_event)
        return 0

    result = handler(payload, action, full_name)
    if result is None:
        return 0

    props, data = result
    dispatch(type_name=msg_type, props=props, data=data)
    log.info("已投递 %s (%s.%s): %s/%s", msg_type, gh_event, action, full_name, props.get("number", ""))
    return 1


def _handle_issue(payload: dict, action: str, full_name: str):
    issue = payload.get("issue") or {}
    number = issue.get("number", "")
    title = issue.get("title", "") or ""
    body = issue.get("body", "") or ""
    user = (issue.get("user") or {}).get("login", "")
    body_preview = body[:500].replace("\n", " ").strip()
    summary = f"[{user}] {title}" + (f"\n{body_preview}" if body_preview else "")

    props = {"repo": full_name, "number": number, "summary": summary}
    data = {
        "action": action,
        "title": title,
        "body": body,
        "state": issue.get("state", "open"),
        "user": user,
        "url": issue.get("html_url", ""),
        "created_at": issue.get("created_at", ""),
    }
    return props, data


def _handle_issue_comment(payload: dict, action: str, full_name: str):
    issue = payload.get("issue") or {}
    comment = payload.get("comment") or {}
    issue_number = issue.get("number", "")
    body = comment.get("body", "") or ""
    user = (comment.get("user") or {}).get("login", "")
    body_preview = body[:500].replace("\n", " ").strip()
    summary = f"[{user}] 评论于 #{issue_number}" + (f"\n{body_preview}" if body_preview else "")

    props = {"repo": full_name, "issue_number": str(issue_number), "summary": summary}
    data = {
        "issue_number": issue_number,
        "body": body,
        "user": user,
        "url": comment.get("html_url", ""),
        "created_at": comment.get("created_at", ""),
    }
    return props, data


def _handle_pr(payload: dict, action: str, full_name: str):
    pr = payload.get("pull_request") or {}
    number = pr.get("number", "")
    title = pr.get("title", "") or ""
    body = pr.get("body", "") or ""
    user = (pr.get("user") or {}).get("login", "")
    draft = pr.get("draft", False)
    body_preview = body[:500].replace("\n", " ").strip()
    draft_tag = " [DRAFT]" if draft else ""
    summary = f"[{user}] PR #{number}{draft_tag}: {title}"
    if body_preview:
        summary += f"\n{body_preview}"

    props = {"repo": full_name, "number": number, "summary": summary}
    data = {
        "action": action,
        "title": title,
        "body": body,
        "state": pr.get("state", "open"),
        "user": user,
        "url": pr.get("html_url", ""),
        "created_at": pr.get("created_at", ""),
        "draft": draft,
        "merged": pr.get("merged", False),
    }
    return props, data


def _handle_discussion(payload: dict, action: str, full_name: str):
    disc = payload.get("discussion") or {}
    number = disc.get("number", "")
    title = disc.get("title", "") or ""
    body = disc.get("body", "") or ""
    user = (disc.get("author") or {}).get("login", "") or (disc.get("user") or {}).get("login", "")
    category = (disc.get("category") or {}).get("name", "")
    body_preview = body[:500].replace("\n", " ").strip()
    summary = f"[{user}] [{category}] {title}" + (f"\n{body_preview}" if body_preview else "")

    props = {"repo": full_name, "number": number, "summary": summary}
    data = {
        "action": action,
        "title": title,
        "body": body,
        "category": category,
        "user": user,
        "url": disc.get("html_url", ""),
        "created_at": disc.get("created_at", ""),
    }
    return props, data


def _handle_discussion_comment(payload: dict, action: str, full_name: str):
    disc = payload.get("discussion") or {}
    comment = payload.get("comment") or {}
    disc_number = disc.get("number", "")
    body = comment.get("body", "") or ""
    user = (comment.get("author") or {}).get("login", "") or (comment.get("user") or {}).get("login", "")
    body_preview = body[:500].replace("\n", " ").strip()
    summary = f"[{user}] 评论于 Discussion #{disc_number}" + (f"\n{body_preview}" if body_preview else "")

    props = {"repo": full_name, "discussion_number": str(disc_number), "summary": summary}
    data = {
        "discussion_number": disc_number,
        "body": body,
        "user": user,
        "url": comment.get("html_url", ""),
        "created_at": comment.get("created_at", ""),
    }
    return props, data


_HANDLERS = {
    "issues": _handle_issue,
    "issue_comment": _handle_issue_comment,
    "pull_request": _handle_pr,
    "discussion": _handle_discussion,
    "discussion_comment": _handle_discussion_comment,
}


# ─── 去重缓存 ──────────────────────────────────────────────

class DedupCache:
    """简单的内存去重缓存，基于 x-github-delivery ID。"""

    def __init__(self, max_size: int = 1000):
        self._seen = set()
        self._max_size = max_size

    def check_and_add(self, delivery_id: str) -> bool:
        """返回 True 表示已见过（重复）。"""
        if delivery_id in self._seen:
            return True
        self._seen.add(delivery_id)
        if len(self._seen) > self._max_size:
            # 简单裁剪：清空一半
            self._seen = set(list(self._seen)[-self._max_size // 2:])
        return False


_dedup = DedupCache()


# ─── HTTP 服务器模式（配合 smee CLI）───────────────────────


class WebhookHandler(BaseHTTPRequestHandler):
    """接收 smee CLI 转发的 POST 请求。"""

    # 类级别引用，避免线程/实例问题
    server_secret = ""

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        payload_body = self.rfile.read(content_length)

        # 签名验证
        sig = self.headers.get("X-Hub-Signature-256", "")
        if not verify_signature(payload_body, sig, self.server_secret):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"signature mismatch")
            log.warning("签名验证失败")
            return

        gh_event = self.headers.get("X-GitHub-Event", "")
        delivery_id = self.headers.get("X-GitHub-Delivery", "")

        # 去重
        if delivery_id and _dedup.check_and_add(delivery_id):
            log.debug("重复事件 %s，跳过", delivery_id)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"duplicate")
            return

        if not gh_event:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"missing X-GitHub-Event header")
            return

        try:
            count = handle_webhook_event(gh_event, payload_body)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(f"ok ({count})".encode())
        except Exception as e:
            log.error("处理 webhook 事件异常: %s", e)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"error: {e}".encode())

    def log_message(self, fmt, *args):
        log.debug("HTTP: %s", fmt % args)


def run_http_server(port: int, secret: str) -> None:
    """启动 HTTP 服务器（供 smee CLI 转发）。"""
    WebhookHandler.server_secret = secret
    server = HTTPServer(("127.0.0.1", port), WebhookHandler)

    # 优雅退出
    stop = False

    def _shutdown(signum, frame):
        nonlocal stop
        log.info("收到信号，正在关闭 HTTP 服务器...")
        stop = True
        server.shutdown()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info("HTTP 服务器启动: http://127.0.0.1:%d", port)
    log.info("请运行: smee --url <SMEE_URL> --port %d", port)
    if secret:
        log.info("Webhook 签名验证已启用")

    while not stop:
        server.handle_request()


# ─── SSE 客户端（直连 smee.io）─────────────────────────────


def _parse_sse_event(lines: list[str]) -> tuple[str, str, str]:
    """解析一组 SSE 行，返回 (event_type, data_str, id)。"""
    event_type = ""
    data_str = ""
    eid = ""
    for line in lines:
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_str = line[5:].strip()
        elif line.startswith("id:"):
            eid = line[3:].strip()
    return event_type, data_str, eid


def _sse_connect(smee_url: str, last_id: str = ""):
    """建立到 smee.io 的 SSE 连接，返回 response 对象。"""
    headers = {"Accept": "text/event-stream", "Cache-Control": "no-cache"}
    if last_id:
        headers["Last-Event-ID"] = last_id
    req = Request(smee_url, headers=headers)
    return urlopen(req, timeout=None)  # 长连接，无超时


def _read_sse_line(stream) -> str | None:
    """从 SSE 流读取一行。返回 None 表示连接已关闭。"""
    chars = []
    while True:
        c = stream.read(1)
        if not c:
            # 连接关闭
            return None if not chars else "".join(chars)
        if c == b"\r":
            next_c = stream.read(1)
            if next_c != b"\n" and next_c:
                # 单独的 \r 后跟有效字符：该字符属于下一行
                pass
            break  # \r\n 或单独的 \r 都算行结束
        elif c == b"\n":
            break
        chars.append(chr(c[0]))
    return "".join(chars)


def run_sse_client(smee_url: str, secret: str) -> None:
    """SSE 模式：直连 smee.io 接收事件。"""
    log.info("SSE 客户端启动: %s", smee_url)
    if secret:
        log.info("Webhook 签名验证已启用")

    last_id = ""
    reconnect_delay = 1

    while True:
        try:
            log.info("正在连接 smee.io...")
            resp = _sse_connect(smee_url, last_id)
            log.info("已连接 smee.io")
            reconnect_delay = 1  # 重置重连延迟

            # 读取 SSE 事件
            current_lines = []
            while True:
                line = _read_sse_line(resp)
                if line is None:
                    break
                if line == "":
                    # 空行 = 事件结束
                    if current_lines:
                        event_type, data_str, eid = _parse_sse_event(current_lines)
                        current_lines = []
                        log.debug("SSE 事件: event=%r eid=%r data_len=%d",
                                  event_type, eid, len(data_str))
                        if eid:
                            last_id = eid
                        # smee.io 发送的 SSE 没有 event: 字段（event_type=""），
                        # 所以只要有 data 就处理，不限制 event_type
                        if data_str and event_type != "ready":
                            _process_smee_event(data_str, secret)
                else:
                    current_lines.append(line)

        except URLError as e:
            log.warning("连接 smee.io 失败: %s (%ds 后重试)", e, reconnect_delay)
        except Exception as e:
            log.error("SSE 异常: %s (%ds 后重试)", e, reconnect_delay)

        time.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, 60)


def _process_smee_event(data_str: str, secret: str) -> None:
    """处理从 smee.io 收到的一个事件。"""
    try:
        smee_data = json.loads(data_str)
    except json.JSONDecodeError:
        log.warning("无法解析 smee 事件数据")
        return

    body_raw = smee_data.get("body", "")

    # smee.io 的 SSE data 是扁平 JSON，头信息和 body 在同一层。
    # 从顶层直接提取 GitHub 事件头。
    gh_event = str(smee_data.get("x-github-event", "") or "")
    delivery_id = str(smee_data.get("x-github-delivery", "") or "")
    sig = str(smee_data.get("x-hub-signature-256", "") or "")

    # body 可能是字符串或对象
    if isinstance(body_raw, str):
        try:
            payload_body = body_raw.encode("utf-8")
        except (UnicodeEncodeError, ValueError):
            log.warning("无法编码 payload body")
            return
    else:
        payload_body = json.dumps(body_raw).encode("utf-8")

    # 去重
    if delivery_id and _dedup.check_and_add(delivery_id):
        log.debug("重复事件 %s，跳过", delivery_id)
        return

    # 签名验证
    if not verify_signature(payload_body, sig, secret):
        log.warning("签名验证失败，跳过事件 %s", delivery_id)
        return

    if not gh_event:
        log.warning("缺少 X-GitHub-Event 头，跳过")
        return

    try:
        handle_webhook_event(gh_event, payload_body)
    except Exception as e:
        log.error("处理事件异常: %s", e)


# ─── CLI ──────────────────────────────────────────────────


def cli_main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="claude-man-source-github-webhook",
        description="GitHub Source 插件 (Webhook 版本)",
    )
    parser.add_argument("--http", action="store_true",
                        help="HTTP 服务器模式（配合 smee CLI），默认 SSE 模式")
    parser.add_argument("--port", type=int, default=0,
                        help="监听端口（默认从 webhook.yaml 读取，否则 8080）")
    parser.add_argument("--secret",
                        help="Webhook secret（默认从 webhook.yaml 读取）")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    wh_cfg = load_webhook_config()
    secret = args.secret or wh_cfg.get("secret", "") or ""

    if args.http:
        port = args.port or wh_cfg.get("port", 8080)
        run_http_server(port, secret)
    else:
        smee_url = _get_smee_url()
        if not smee_url:
            print(
                "错误: 未设置 SMEE_URL。请设置环境变量或配置 webhook.yaml。\n"
                "  export SMEE_URL=https://smee.io/XXXX\n"
                "  或: claude-man-source-github-webhook --http",
                file=sys.stderr,
            )
            sys.exit(1)
        run_sse_client(smee_url, secret)


if __name__ == "__main__":
    cli_main()
