import os
import sys
import time
import uuid
import subprocess
import logging

from .config import load_config
from .db import init_db, get_popup_messages, count_pending, count_by_level
from .preview import format_brief

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("worker")


from .worker_common import calc_delay, load_or_create_session_id, build_system_prompt


def build_brief(config) -> str:
    """构建所有 pending popup 消息的简报。"""
    rows = get_popup_messages(config.db_path, limit=config.preview.max_messages_per_turn)
    counts = count_by_level(config.db_path)
    return format_brief(
        rows,
        max_preview_length=config.preview.max_preview_length,
        total_popup_pending=counts["popup"]["pending"],
        total_silent=counts["silent"],
    )


def load_prompt_template(config) -> str:
    """加载 prompt 模板，按优先级：工作目录 → 全局模板目录 → 内建。"""
    # 1. 工作目录下自定义模板
    local_path = os.path.join(config.work_dir, ".claude", "prompt_new_message.md")
    if os.path.exists(local_path):
        with open(local_path) as f:
            return f.read()

    # 2. 全局模板目录
    templates_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
    global_path = os.path.join(templates_dir, "prompt_new_message.md.template")
    if os.path.exists(global_path):
        with open(global_path) as f:
            return f.read()

    # 3. 内建模板
    return """## 新消息简报

{{MAN_NAME}} 检测到以下新增弹出消息：

{{PREVIEW}}

---
*以上为新增的弹出消息简报，与工具执行结果无关。请使用 msg_list / msg_show / msg_mark 管理消息。*
"""


def render_prompt(template: str, brief: str, man_name: str) -> str:
    return template.replace("{{PREVIEW}}", brief).replace("{{MAN_NAME}}", man_name)








def run_claude(config, brief: str, system_prompt: str) -> int:
    session_id, session_is_new = load_or_create_session_id(config.work_dir)
    template = load_prompt_template(config)
    prompt = render_prompt(template, brief, config.name)

    if session_is_new:
        cmd = [
            "claude",
            "--session-id", session_id,
            "-p", prompt,
            "--append-system-prompt", system_prompt,
            "--name", config.name,
        ]
    else:
        cmd = [
            "claude",
            "--resume", session_id,
            "-p", prompt,
            "--name", config.name,
        ]

    log.info(
        "启动 Claude (name=%s, work_dir=%s, session=%s, mode=%s)",
        config.name, config.work_dir, session_id,
        "new" if session_is_new else "resume",
    )
    result = subprocess.run(cmd, capture_output=False, text=True, cwd=config.work_dir)
    return result.returncode


def worker_loop(config_name: str) -> None:
    config = load_config(config_name)
    init_db(config.db_path)
    log.info("Worker 启动: %s (work_dir=%s)", config.name, config.work_dir)

    fail_count = 0

    while True:
        try:
            pending = count_pending(config.db_path)
            if pending == 0:
                time.sleep(1)
                continue

            log.info("检测到 %d 条未处理弹出消息", pending)
            brief = build_brief(config)

            system_prompt = build_system_prompt(config.tools_dir, config.name)
            rc = run_claude(config, brief, system_prompt)

            if rc == 0:
                log.info("Claude 正常退出")
                fail_count = 0
            else:
                fail_count += 1
                log.warning(
                    "Claude 退出码 %d (第 %d 次失败), 保持 session ID 不变",
                    rc, fail_count,
                )
                delay = calc_delay(fail_count - 1, config)
                log.warning("%ds 后重试", delay)
                time.sleep(delay)

        except KeyboardInterrupt:
            log.info("Worker 收到中断信号，退出。")
            break
        except Exception as e:
            fail_count += 1
            delay = calc_delay(fail_count - 1, config)
            log.error("Worker 异常: %s, %ds 后重试", e, delay)
            time.sleep(delay)


def main():
    if len(sys.argv) < 2:
        print("用法: claude-man-worker <man-name>", file=sys.stderr)
        sys.exit(1)
    worker_loop(sys.argv[1])


if __name__ == "__main__":
    main()
