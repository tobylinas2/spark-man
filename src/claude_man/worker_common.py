"""Worker 公共函数 — worker.py 和 worker_tui.py 共享。"""
import os
import uuid


def calc_delay(attempt: int, config) -> int:
    """退避延迟计算。"""
    delay = config.retry.initial_delay * (config.retry.backoff_factor ** attempt)
    return min(delay, config.retry.max_delay)


def load_or_create_session_id(work_dir: str) -> tuple[str, bool]:
    """返回 (session_id, is_new)。is_new=True 表示首次生成。"""
    path = os.path.join(work_dir, ".me", "session_id")
    try:
        with open(path) as f:
            sid = f.read().strip()
            if sid:
                return sid, False
    except OSError:
        pass
    sid = str(uuid.uuid4())
    os.makedirs(os.path.join(work_dir, ".me"), exist_ok=True)
    with open(path, "w") as f:
        f.write(sid)
    return sid, True


def build_system_prompt(tools_dir: str, name: str = "") -> str:
    """构建 system prompt，包含工具列表。"""
    return f"""你是一个 Claude Man Worker，正在处理消息队列中的消息。

你有以下工具可用：
  python3 {tools_dir}/msg_list.py              # 列出未处理消息
  python3 {tools_dir}/msg_show.py <id>         # 查看消息全文
  python3 {tools_dir}/msg_mark.py <id> [... ]  # 标记已处理
  python3 {tools_dir}/msg_mark.py --all        # 标记全部
  python3 {tools_dir}/sub_list.py              # 查看订阅规则
  python3 {tools_dir}/sub_add.py <type> <key=regex> [key=regex ...]  # 添加订阅规则
  python3 {tools_dir}/sub_remove.py <index>    # 删除订阅规则
  python3 {tools_dir}/gh_config.py list        # 查看 GitHub 源配置
  python3 {tools_dir}/gh_config.py add <owner/name> [--events ...]  # 添加 GitHub 仓库
  python3 {tools_dir}/gh_config.py remove <index>  # 移除仓库

流程：
1. 先用 msg_list.py 查看未处理消息列表
2. 用 msg_show.py 查看每条消息的完整内容
3. 处理完毕后用 msg_mark.py 标记已处理
4. 如需调整订阅规则，用 sub_* 工具

请开始处理。"""
