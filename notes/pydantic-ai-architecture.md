# pydantic-ai 架构学习笔记

> 学习时间: 2026-06-16

## 整体架构

pydantic-ai 是一个 AI Agent 框架，核心设计模式：

### 1. Agent 分层体系

AgentSpec (规格定义) → AbstractAgent (抽象基类) → Agent (具体实现) / WrapperAgent (装饰器包装)

### 2. ToolManager（工具管理）

工具验证与执行分离的设计：
- ToolCallPart → ValidatedToolCall (args_valid + validated_args) → execute_tool
- 支持并行/串行/有序并行三种执行模式
- 每次 run step 创建新的 ToolManager，携带 retry 计数

### 3. RunContext（运行上下文）

统一的运行上下文对象，承载：
- deps: 外部依赖注入
- usage: LLM 用量统计
- messages: 对话消息历史
- retries: 每个工具的已重试次数
- tool_manager: 当前 step 的工具管理器

### 4. Capability 系统（能力扩展）

插件式能力链：AbstractCapability → CombinedCapability → AgentCapability
- 分层组合，每个 capability 可以包装/修改 agent 的行为
- 支持事件流处理

## 可借鉴的设计

1. ToolManager 的验证/执行分离 — 可应用到 claude-man 的工具脚本管理
2. RunContext 统一上下文 — 替代 claude-man 目前的分散传参
3. Capability 链式扩展 — 可用来设计 claude-man 的 Plugin 系统
4. 并行执行模式 — claude-man 的 Source 轮询可受益
