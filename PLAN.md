# Claude Man — 项目规划

## 概述

Claude Man 是一个让 Claude Code 以非交互、常驻 Worker 模式持续运行的编排系统。每个 Claude Man 拥有独立的工作目录、独立的 `--session` 上下文，以及一个 SQLite Message Box 作为消息队列。外部 Source 插件通过 Dispatcher 向指定的 Claude Man 投递消息，Worker 循环检测到未处理消息后，以预览形式唤醒 Claude 进行处理。

## 核心概念

| 概念 | 说明 |
|------|------|
| **Claude Man** | 一个常驻 Worker 进程，持有独立的 `--session`，循环消费自身 Message Box 中的消息 |
| **Message Box** | 每个 Claude Man 的 SQLite 数据库，存储所有消息（pending / processed 状态） |
| **Dispatcher** | Python 库 / CLI，Source 插件通过它向指定 Claude Man 投递消息 |
| **Source 插件** | 外部消息源（GitHub 轮询、QQ 机器人等），调用 Dispatcher 写入消息 |
| **Preview** | 唤醒 Claude 时给的摘要，包含未处理消息的数量和简短预览 |
| **Tool** | 每个 Claude Man 工作目录下的 Python 脚本，供 Claude 检索/操作自己的 Message Box |

## 目录结构

```
~/.claude-man/
├── <man-name>/                # 每个 Claude Man 一个目录
│   ├── .claude_man            # YAML 配置
│   ├── messages.db            # SQLite Message Box
│   └── tools/
│       ├── msg_list.py        # 列出/搜索消息
│       ├── msg_mark.py        # 标记消息已处理
│       └── msg_show.py        # 查看消息全文
├── src/
│   ├── claude_man/
│   │   ├── __init__.py
│   │   ├── dispatcher.py      # Dispatcher 核心库
│   │   ├── worker.py          # Worker 循环
│   │   ├── db.py              # SQLite 操作
│   │   ├── preview.py         # 预览格式化
│   │   ├── config.py          # .claude_man 解析
│   │   └── cli.py             # CLI 入口
│   └── pyproject.toml
├── PLAN.md
└── README.md
```

## 配置文件 `.claude_man`

```yaml
name: github-reviewer           # Claude Man 名称
work_dir: /home/user/.claude-man/github-reviewer

preview:
  max_preview_length: 200       # 每条消息预览最大字符数
  max_messages_per_turn: 10     # 每轮唤醒最多展示消息数

retry:
  initial_delay: 60             # 初始失败等待（秒）
  max_delay: 3600               # 最大等待（秒）
  backoff_factor: 5
```

## Dispatcher API

### Python 调用

```python
from claude_man.dispatcher import dispatch

dispatch(
    target="github-reviewer",     # Claude Man 名称
    source="github",              # 消息来源
    type="issue",                 # 消息类型
    content="Issue body text...",
    metadata={"repo": "a/b", "number": 42}
)
```

### CLI 调用

```bash
claude-man dispatch \
  --target github-reviewer \
  --source github \
  --type issue \
  --content "message text" \
  --metadata '{"repo": "a/b", "number": 42}'
```

## 数据库结构 `messages.db`

```sql
CREATE TABLE messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,       -- 消息来源（github, qq 等）
    type        TEXT NOT NULL,       -- 消息类型（issue, pr, mention 等）
    content     TEXT NOT NULL,       -- 消息全文
    metadata    TEXT DEFAULT '{}',   -- JSON 元数据
    status      TEXT DEFAULT 'pending',  -- pending | processed
    created_at  TEXT DEFAULT (datetime('now')),
    processed_at TEXT
);

CREATE INDEX idx_status ON messages(status);
CREATE INDEX idx_source_type ON messages(source, type);
```

## Worker 循环流程

```
┌─────────────────────────────────────┐
│  启动 Worker                         │
│  - 加载 .claude_man 配置             │
│  - 打开 messages.db                  │
└─────────────┬───────────────────────┘
              ▼
┌─────────────────────────────────────┐
│  查询 pending 消息                   │
│  SELECT * FROM messages              │
│  WHERE status='pending'              │
│  ORDER BY created_at                 │
│  LIMIT max_messages_per_turn         │
└─────────────┬───────────────────────┘
              ▼
    ┌──── 有消息？────┐
    │                 │
    │ 是              │ 否
    ▼                 ▼
┌──────────────┐  ┌──────────────┐
│ 格式化预览     │  │ sleep(1)    │
│ 调用 Claude   │  │ 继续循环     │
│ 等待退出       │  └──────────────┘
│ 继续循环       │       │
└──────────────┘        │
              ▲         │
              └─────────┘
```

### 失败重试序列

Claude 进程退出码非 0 或超时：
- 第 1 次失败 → 等待 60s 后重试
- 第 2 次失败 → 等待 300s（5m）后重试
- 第 3 次失败 → 等待 1500s（25m）后重试
- 第 4+ 次失败 → 等待 3600s（1h）后重试
- 每次重试成功则重置失败计数

## Claude 侧工具

每个工具 Claude 通过 `python3 tools/<script>` 调用：

### msg_list.py

```bash
# 列出未处理消息
python3 tools/msg_list.py
python3 tools/msg_list.py --status processed
python3 tools/msg_list.py --source github --type issue
python3 tools/msg_list.py --search "keyword"
```

输出格式：
```
ID   Source   Type      Preview            Created
42   github   issue     Fix login bug...   2026-06-15 10:00
43   github   pr        Add dark mode...   2026-06-15 10:05
```

### msg_show.py

```bash
# 查看消息全文
python3 tools/msg_show.py 42
```

输出格式：
```
Message #42
────────────────────────────────
Source: github
Type:   issue
Status: pending
Created: 2026-06-15 10:00:00

[完整消息内容]
```

### msg_mark.py

```bash
# 标记已处理
python3 tools/msg_mark.py 42
python3 tools/msg_mark.py 42 43 44  # 批量
python3 tools/msg_mark.py --all     # 全部标记
```

## 预览格式

```
你有 3 条未处理消息：

[1] github/issue  #42: "Fix login bug on mobile..." (200 chars)
[2] github/pr     #43: "Add dark mode support..."   (200 chars)
[3] qq/mention    张三: "这个功能什么时候上线？"    (85 chars)

用 msg_list/msg_show/msg_mark 管理消息。
```

## Source 插件示例

### GitHub Issue 轮询

```python
# 独立进程，cron 或 while True
from claude_man.dispatcher import dispatch

def poll_issues(repo):
    for issue in fetch_new_issues(repo):
        dispatch(
            target="github-reviewer",
            source="github",
            type="issue",
            content=issue.body,
            metadata={"repo": repo, "number": issue.number}
        )
```

### QQ 机器人

```python
# 长连接
from claude_man.dispatcher import dispatch

@qq_bot.on_message
def handle(msg):
    dispatch(
        target="qq-helper",
        source="qq",
        type="message",
        content=msg.text,
        metadata={"sender": msg.sender, "group": msg.group_id}
    )
```

## 实现阶段

### Phase 1 — 基础设施
- [x] 项目规划
- [x] `claude_man/db.py` — SQLite 建表、CRUD
- [x] `claude_man/config.py` — `.claude_man` 解析
- [x] `claude_man/dispatcher.py` — 向指定 Claude Man 投递消息
- [x] `claude_man/preview.py` — 预览格式化
- [x] `claude_man/cli.py` — `claude-man` CLI 入口

### Phase 2 — Worker 循环
- [x] `claude_man/worker.py` — 常驻循环、Claude 调用、重试逻辑
- [x] 工具脚本 `tools/msg_list.py`
- [x] 工具脚本 `tools/msg_show.py`
- [x] 工具脚本 `tools/mark_list.py`

### Phase 3 — 集成与测试
- [ ] 完整端到端测试：dispatch → worker → claude → mark
- [ ] 示例 Source 插件：GitHub 轮询
- [ ] 错误处理与日志

### Phase 4 — 可选增强
- [ ] HTTP Server（远程 webhook 支持）
- [ ] 监控/健康检查
- [ ] 消息去重
- [ ] 优先级队列
