"""
Worker TUI — 只读仪表盘，实时展示 Worker 状态和 Claude 输出。
"""

import json
import os
import sys
import time
import subprocess
import logging
import threading
import pty
import uuid
from datetime import datetime, timezone
from typing import Optional
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.live import Live
from rich.console import Console
from rich import box

from .worker_common import calc_delay, load_or_create_session_id, build_system_prompt
from .config import load_config
from .db import init_db, count_pending, count_by_level, get_popup_messages
from .preview import format_brief
from .worker import load_prompt_template, render_prompt

log = logging.getLogger("worker.tui")

console = Console()


class WorkerTUI:
    def __init__(self, config_name: str):
        self.config = load_config(config_name)
        self.work_dir = self.config.work_dir
        init_db(self.config.db_path)

        self.status = "idle"
        self.start_time = time.time()
        self.fail_count = 0
        self.total_runs = 0
        self.total_success = 0
        self.total_fail = 0
        self.claude_pid: Optional[int] = None
        self.claude_output: list[str] = []
        self.activity_log: list[str] = []
        self.last_gh_poll: Optional[str] = None

    @property
    def uptime(self) -> str:
        elapsed = int(time.time() - self.start_time)
        h, r = divmod(elapsed, 3600)
        m, s = divmod(r, 60)
        if h:
            return f"{h}h{m:02d}m{s:02d}s"
        return f"{m:02d}m{s:02d}s"

    def _add_activity(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.activity_log.insert(0, f"[{ts}] {msg}")
        if len(self.activity_log) > 50:
            self.activity_log.pop()

    def _add_claude_output(self, text: str) -> None:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                self.claude_output.append(stripped)
        if len(self.claude_output) > 200:
            self.claude_output = self.claude_output[-200:]

    def _render_header(self) -> Panel:
        info = Table.grid(padding=(0, 2))
        info.add_column()
        info.add_row(Text(f"Claude Man Worker · {self.config.name}", style="bold cyan"))
        info.add_row(Text(f"工作目录: {self.work_dir}", style="dim"))
        info.add_row(Text(f"运行时间: {self.uptime}", style="dim"))
        return Panel(info, box=box.ROUNDED)

    def _render_stats(self) -> Panel:
        counts = count_by_level(self.config.db_path)
        popup_pending = counts["popup"]["pending"]
        popup_processed = counts["popup"]["processed"]
        silent = counts["silent"]

        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold")
        table.add_column()

        table.add_row(
            "弹出 pending:",
            Text(str(popup_pending), style="yellow" if popup_pending > 0 else "green"),
        )
        table.add_row("弹出 processed:", str(popup_processed))
        table.add_row("静默:", str(silent))
        table.add_row("", "")
        table.add_row("总运行次数:", str(self.total_runs))
        table.add_row("成功:", Text(str(self.total_success), style="green"))
        table.add_row("失败:", Text(str(self.total_fail), style="red" if self.total_fail > 0 else ""))

        return Panel(table, title="📊 消息状态", box=box.ROUNDED)

    def _render_source_status(self) -> Panel:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold")
        table.add_column()

        table.add_row("GitHub 轮询:", self.last_gh_poll or "未启动")

        from .config import CLAUDE_MAN_HOME
        gh_state_path = os.path.join(CLAUDE_MAN_HOME, "sources", "github", "state.json")
        # 兼容旧路径（man 目录下 .me/github.state.json）
        old_path = os.path.join(self.work_dir, ".me", "github.state.json")
        if not os.path.exists(gh_state_path) and os.path.exists(old_path):
            gh_state_path = old_path
        if os.path.exists(gh_state_path):
            import json

            try:
                with open(gh_state_path) as f:
                    gh_state = json.load(f)
                for repo, st in gh_state.items():
                    last = st.get("last_poll", "")
                    if last:
                        try:
                            dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                            ago = int((datetime.now(timezone.utc) - dt).total_seconds())
                            table.add_row(f"  {repo}:", f"{ago}s ago")
                        except ValueError:
                            table.add_row(f"  {repo}:", last)
            except (json.JSONDecodeError, OSError):
                pass

        return Panel(table, title="🔌 源状态", box=box.ROUNDED)

    def _render_claude_output(self) -> Panel:
        if self.status == "idle" and not self.claude_output:
            return Panel(Text("等待消息...", style="dim"), title="🤖 Claude 输出", box=box.ROUNDED)

        if self.status == "running" and not self.claude_output:
            return Panel(
                Text("⏳ Claude 正在启动...", style="yellow"),
                title="🤖 Claude 输出",
                box=box.ROUNDED,
                border_style="yellow",
            )

        lines = self.claude_output[-30:]
        lines.reverse()
        text = "\n".join(lines)

        if not text.strip():
            text = "⏳ Claude 正在处理..."

        return Panel(
            Text(text, style="green"),
            title=f"🤖 Claude 输出 (PID: {self.claude_pid or '?'})",
            box=box.ROUNDED,
            border_style="yellow" if self.status == "running" else "green",
        )

    def _render_activity(self) -> Panel:
        if not self.activity_log:
            return Panel(Text("暂无活动", style="dim"), title="📋 最近活动", box=box.ROUNDED)
        lines = self.activity_log[:12]
        text = "\n".join(lines)
        return Panel(Text(text, style="dim"), title="📋 最近活动", box=box.ROUNDED)

    def _render_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=6),
            Layout(name="body", ratio=1),
            Layout(name="footer", size=1),
        )
        layout["body"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=2),
        )
        layout["left"].split_column(
            Layout(name="stats", ratio=1),
            Layout(name="source", ratio=1),
        )
        layout["right"].split_column(
            Layout(name="claude", ratio=3),
            Layout(name="activity", ratio=2),
        )

        layout["header"].update(self._render_header())
        layout["stats"].update(self._render_stats())
        layout["source"].update(self._render_source_status())
        layout["claude"].update(self._render_claude_output())
        layout["activity"].update(self._render_activity())
        layout["footer"].update(Text(" Ctrl+C 退出  |  仅监控模式 - 系统自动管理 Worker", style="dim"))

        return layout

    def _get_session(self) -> tuple[str, bool]:
        return load_or_create_session_id(self.work_dir)

    def run(self):
        with Live(self._render_layout(), refresh_per_second=4, screen=True) as live:
            self._add_activity("Worker 启动")
            while True:
                try:
                    pending = count_pending(self.config.db_path)
                    if pending == 0:
                        self.status = "idle"
                        live.update(self._render_layout())
                        time.sleep(1)
                        continue

                    self.status = "running"
                    self.total_runs += 1
                    self._add_activity(f"检测到 {pending} 条未处理弹出消息")

                    rows = get_popup_messages(self.config.db_path, limit=self.config.preview.max_messages_per_turn)
                    counts = count_by_level(self.config.db_path)
                    brief = format_brief(
                        rows,
                        total_popup_pending=counts["popup"]["pending"],
                        total_silent=counts["silent"],
                    )

                    template = load_prompt_template(self.config)
                    prompt = render_prompt(template, brief, self.config.name)
                    tools_dir = self.config.tools_dir
                    system_prompt = build_system_prompt(tools_dir, self.config.name)

                    session_id, session_is_new = self._get_session()

                    cmd = [
                        "claude",
                        "--resume", session_id,
                        "-p", prompt,
                        "--name", self.config.name,
                    ]
                    if session_is_new:
                        cmd = [
                            "claude",
                            "--session-id", session_id,
                            "-p", prompt,
                            "--append-system-prompt", system_prompt,
                            "--name", self.config.name,
                        ]

                    self._add_activity(f"启动 Claude (name={self.config.name})")
                    self.claude_output = []

                    # 用 PTY 捕获输出（claude 在非 TTY 下可能不输出内容）
                    master_fd, slave_fd = pty.openpty()
                    proc = subprocess.Popen(
                        cmd,
                        stdout=slave_fd,
                        stderr=slave_fd,
                        cwd=self.config.work_dir,
                        close_fds=True,
                    )
                    os.close(slave_fd)
                    self.claude_pid = proc.pid

                    # 在单独线程中读取 PTY 输出
                    def reader_pty(fd, tui):
                        try:
                            while True:
                                data = os.read(fd, 4096)
                                if not data:
                                    break
                                tui._add_claude_output(data.decode("utf-8", errors="replace"))
                        except OSError:
                            pass
                        finally:
                            try:
                                os.close(fd)
                            except OSError:
                                pass

                    t_pty = threading.Thread(target=reader_pty, args=(master_fd, self), daemon=True)
                    t_pty.start()

                    # 轮询等待进程结束，同时刷新 UI
                    while proc.poll() is None:
                        live.update(self._render_layout())
                        time.sleep(0.15)

                    log.debug("Poll loop ended: poll()=%s, returncode=%s", proc.poll(), proc.returncode)
                    t_pty.join(timeout=2)
                    rc = proc.returncode
                    log.debug("Process exited: rc=%d", rc)

                    if rc == 0:
                        self.total_success += 1
                        self.fail_count = 0
                        self._add_activity("Claude 正常退出")
                        self.status = "idle"
                    else:
                        self.total_fail += 1
                        self.fail_count += 1
                        self._add_activity(f"Claude 退出码 {rc} (第 {self.fail_count} 次失败)")
                        delay = calc_delay(self.fail_count - 1, self.config)
                        self._add_activity(f"{delay}s 后重试")
                        self.status = "retrying"
                        live.update(self._render_layout())
                        time.sleep(delay)
                        self.status = "running"

                except KeyboardInterrupt:
                    self._add_activity("Worker 收到中断")
                    break
                except Exception as e:
                    self.fail_count += 1
                    delay = calc_delay(self.fail_count - 1, self.config)
                    self._add_activity(f"异常: {e}, {delay}s 后重试")
                    self.status = "error"
                    live.update(self._render_layout())
                    time.sleep(delay)
                    self.status = "running"








def main():
    if len(sys.argv) < 2:
        print("用法: claude-man-worker-tui <man-name>", file=sys.stderr)
        sys.exit(1)
    tui = WorkerTUI(sys.argv[1])
    tui.run()


if __name__ == "__main__":
    main()
