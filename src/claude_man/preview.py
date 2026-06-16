import json
from typing import Sequence


def truncate(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


def _parse_props(msg) -> dict:
    """安全解析 props 字段。"""
    props_raw = msg.get("props", "")
    if not props_raw or props_raw == "{}":
        return {}
    try:
        return json.loads(props_raw) if isinstance(props_raw, str) else props_raw
    except (json.JSONDecodeError, TypeError):
        return {}


def format_preview(
    messages: Sequence,
    max_preview_length: int = 200,
    total_popup_pending: int = 0,
    total_silent: int = 0,
) -> str:
    if not messages and total_popup_pending == 0:
        return "没有未处理的消息。"

    lines = []
    if total_popup_pending > 0:
        lines.append(f"弹出消息 {total_popup_pending} 条 / 静默消息 {total_silent} 条\n")
    else:
        lines.append(f"静默消息 {total_silent} 条（无弹出消息）\n")

    for i, msg in enumerate(messages, start=1):
        parsed_props = _parse_props(msg)

        # 优先使用 props.summary 作为预览（简短可读）
        summary = parsed_props.get("summary", "")
        if summary:
            content_preview = truncate(summary, max_preview_length)
        else:
            data_raw = msg["data"]
            data_text = data_raw if isinstance(data_raw, str) else json.dumps(data_raw, ensure_ascii=False)
            content_preview = truncate(data_text, max_preview_length)

        meta = ""
        for key in ("number", "sender", "repo", "group_name"):
            if key in parsed_props:
                meta = f" {parsed_props[key]}"
                break

        lines.append(
            f"[{i}] {msg['type_name']}{meta}: "
            f'"{content_preview}"'
        )

    lines.append("")
    lines.append("用 msg_list/msg_show/msg_mark 管理消息。")
    return "\n".join(lines)


def format_brief(
    messages: Sequence,
    total_popup_pending: int = 0,
    total_silent: int = 0,
) -> str:
    """生成简洁的新增消息简报，与 format_preview 输出格式明确区分。

    简报不含 "用 msg_list 管理" 等指令，仅呈现新增消息概览。
    使用 ━ 框线将简报与工具执行结果明确分隔。
    """
    if not messages:
        return ""

    lines = []
    lines.append("")
    lines.append("━" * 54)
    lines.append(f"  新消息简报 ({len(messages)} 条新增, 共 {total_popup_pending} 条待处理 / 静默 {total_silent})")
    lines.append("━" * 54)

    for i, msg in enumerate(messages, 1):
        parsed = _parse_props(msg)
        summary = parsed.get("summary", "")
        preview = summary if summary else str(msg["data"])[:80]
        meta = ""
        for key in ("number", "sender", "repo", "group_name"):
            if key in parsed:
                meta = f" {parsed[key]}"
                break

        lines.append(f"  [{i}] {msg['type_name']}{meta}: {preview}")

    lines.append("━" * 54)
    lines.append("")
    return "\n".join(lines)
