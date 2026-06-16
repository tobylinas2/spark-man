# AI Agent 编排框架对比

> 学习时间: 2026-06-16

## pydantic-ai

**定位**: AI Agent 框架
**语言**: Python
**Star**: ~17k

### 核心设计
- Agent 分层：Spec → Abstract → Wrapper
- ToolManager：验证/执行分离，并行/串行模式
- RunContext：统一运行上下文
- Capability：插件式能力链
- 内建 MCP 支持

### 可借鉴
- 工具验证与执行分离设计
- 统一运行上下文模式
- 能力链式扩展

## Microsoft agent-framework

**定位**: 企业级 Agent 编排平台
**语言**: Python / .NET
**Star**: ~11k

### 核心设计
- 30+ 包模块化架构
- 多模型支持（OpenAI、Anthropic、Ollama、Gemini...）
- 内置 Workflow 引擎
- 会话管理
- 遥测/可观测性
- MCP 集成

### 可借鉴
- 模块化分包设计
- 多模型抽象层
- 遥测系统

## claude-man 当前架构

**定位**: Claude Code Worker 编排系统
**语言**: Python

### 核心模块
- dispatcher.py：自动路由
- worker.py：Worker 循环
- db.py：消息队列（SQLite）
- source_github.py：GitHub 事件轮询
- subscribe.py：订阅规则
- preview.py：消息简报

### 改进方向（基于学习）
1. 引入 ToolManager 模式管理工具脚本
2. 统一运行上下文（RunContext）
3. 模块化分包
4. 添加遥测/日志系统
5. 支持更多 Source 类型
