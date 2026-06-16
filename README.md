# Spark Man

星火的 AI Agent 编排系统。

基于 claude-man，让 Claude Code 以非交互、常驻 Worker 模式持续运行。

## 功能

- **消息编排** — Source → Dispatcher → Worker 的消息处理流水线
- **GitHub 集成** — 轮询/Webhook 两种方式接收 Issue、PR、Discussion 事件
- **订阅规则** — 灵活的消息类型匹配，自动路由到对应 Man
- **Worker 循环** — 常驻进程，自动处理消息队列
- **Webhook 支持** — 通过 smee.io SSE 直连 GitHub 事件

## 快速开始

```bash
# 安装
pip install ./src

# 初始化
claude-man init my-man

# 启动 Worker
claude-man-worker my-man
```

## 项目状态

开发中，基于 tobyprime/claude-man。

## 目录

```
├── src/claude_man/    # 核心模块
├── templates/         # 配置模板
├── notes/             # 学习笔记
└── tests/             # 测试
```
