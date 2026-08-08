# 613 Coding 设计文档

- 日期：2026-08-07
- 状态：已由用户逐节确认
- 项目类型：Coding Agent Harness
- 主要贡献：确定性反馈闭环

## 1. 项目概述

613 Coding 是一个面向本地 Git 仓库的任务驱动 Coding Agent Harness。用户提供自然语言任务和仓库路径，系统读取项目上下文，通过自研 agent loop 调用 LLM、执行受控工具、运行验证并把客观反馈回灌给模型，直到任务完成、需要人工审批或满足停止条件。

项目参考 Claude Code 可观察到的工具调用、权限审批、上下文组织和任务状态体验，但不调用 Claude Code 或任何现成 agent 框架的高层 agent loop。主循环、工具分发、治理、反馈、记忆、沙箱和多 agent 编排均由本项目代码实现。

产品以 CLI 为完整入口，并提供共享同一内核的 FastAPI WebUI。公网 WebUI 只运行示例仓库或隔离沙箱，不访问用户本机文件系统。

## 2. 问题与目标用户

目标用户是希望让 coding agent 在本地代码仓库内自主完成小到中型开发任务，同时仍能获得确定性验证、安全边界、运行审计和人工审批能力的软件开发者。

现有的“让 LLM 直接修改代码”方案常见问题包括：

- 模型用自然语言宣称完成，但没有客观验证证据；
- 测试失败日志没有结构化分类，模型容易重复无效修复；
- 工具和 shell 权限缺少确定性边界；
- 历史上下文无限增长或完全丢失；
- 多个 agent 共享工作区时产生覆盖和冲突；
- 执行未信任代码时影响宿主机；
- 使用真实 LLM 的演示难以稳定复现。

613 Coding 的目标是把这些问题落实为可以在移除真实 LLM 后独立测试的工程机制。

## 3. 用户故事

1. 作为开发者，我希望提交自然语言任务和本地仓库路径，以便 agent 自动读取、修改并验证代码。
2. 作为开发者，我希望看到测试、lint 和类型检查的结构化失败分类，以便理解 agent 为什么继续、暂停或结束。
3. 作为安全敏感用户，我希望切换 strict、balanced 和 autonomous 权限模式，以便控制自动化程度。
4. 作为开发者，我希望危险动作在执行前被确定性拦截或请求审批，以便保护仓库和宿主机。
5. 作为开发者，我希望任务在隔离容器中执行，以便限制未信任代码和命令的影响面。
6. 作为开发者，我希望多个专职 agent 可以拆分、执行、测试和评审任务，同时避免直接覆盖彼此的工作。
7. 作为回访用户，我希望系统记住项目约定、验证命令和历史失败模式，以便后续任务获得相关上下文。
8. 作为评审者，我希望在无网络、无真实 API Key 的环境中重复运行核心机制演示，以便验证 Harness 的真实工程能力。

## 4. 设计原则

- LLM 只决定下一步，Harness 负责执行、治理、验证和停机。
- 客观信号优先于模型自述。
- 所有核心依赖都通过接口注入，以支持 mock 和离线测试。
- SQLite 是结构化状态和记忆原文的唯一事实来源。
- LanceDB 是可删除、可重建的向量索引，不保存权威状态。
- worker 不直接修改宿主机原始仓库，只输出结构化工件。
- 权限模式不能绕过硬性拒绝规则。
- 真实 LLM 演示是补充，确定性 mock 演示是验收基础。

## 5. 总体架构

系统采用分层架构：

### 5.1 领域层

定义不依赖基础设施的核心模型和规则：

- `RunState`
- `IterationRecord`
- `ActionEnvelope`
- `ToolCall`
- `ToolResult`
- `Feedback`
- `ApprovalRequest`
- `StopReason`
- `TaskGraph`
- `TaskNode`
- `WorkArtifact`
- `Event`
- `MemoryEntry`

### 5.2 应用层

- `AgentLoop`：执行单 agent 的完整状态机。
- `RunService`：创建、暂停、恢复、取消和查询运行。
- `Supervisor`：拆分和调度多 agent 任务图。
- `ArtifactIntegrator`：应用 worker 工件、处理冲突并重新验证。
- `ContextAssembler`：组织项目说明、记忆、事件摘要和反馈。
- `CredentialService`：管理供应商凭据状态。

### 5.3 端口接口

- `LLMProvider`
- `EmbeddingProvider`
- `ToolExecutor`
- `PolicyEngine`
- `Validator`
- `FeedbackClassifier`
- `MemoryStore`
- `VectorIndex`
- `EventStore`
- `SandboxRuntime`
- `ArtifactStore`

### 5.4 基础设施适配器

- OpenAI-compatible LLM 和 embedding 适配器；
- 脚本化 mock LLM 和 deterministic mock embedding；
- 本地文件、搜索、Git diff 和子进程工具；
- SQLite 状态存储；
- LanceDB 向量索引；
- 系统钥匙串；
- Docker Engine API 沙箱；
- CLI；
- FastAPI WebUI。

## 6. Agent Loop

Agent loop 是项目的核心交付物，状态包括：

- `RUNNING`
- `WAITING_MODEL`
- `WAITING_APPROVAL`
- `COMPLETED`
- `PAUSED`
- `FAILED`
- `CANCELLED`

每轮循环执行：

1. 检查取消、审批、重试预算和停机条件。
2. 加载任务、项目说明、`harness.toml`、相关记忆、当前状态和最近事件。
3. 调用 `LLMProvider`，并提供允许的工具 schema。
4. 解析模型文本和一个或多个 tool call。
5. 对每个 tool call 执行参数 schema 校验。
6. 调用 `PolicyEngine` 返回 `allow`、`ask` 或 `deny`。
7. 对允许动作执行工具；需审批动作进入 `WAITING_APPROVAL`；禁止动作生成反馈。
8. 将工具结果、资源使用和变更摘要写入事件日志。
9. 在需要时运行 test、lint 和 typecheck 验证。
10. 由确定性分类器把结果转换为结构化反馈。
11. 更新记忆、任务状态、无进展计数和上下文摘要。
12. 若未满足停机条件，将反馈注入下一轮。

只读且互不依赖的 tool call 可以并行执行。写入、命令和审批相关调用按顺序执行。

`finish` 不是成功证据。仅当最近一次要求的验证全部通过、没有待审批动作且不存在未解决反馈时，`finish` 才能转为 `COMPLETED`。

## 7. 工具协议

第一版内置工具：

- `list_files`
- `search_files`
- `read_file`
- `edit_file`
- `git_diff`
- `run_validation`
- `request_approval`
- `finish`

工具输入使用版本化 schema，禁止模型拼接未校验的内部对象。每次调用记录调用 ID、参数摘要、治理判定、开始/结束时间、结果摘要和错误分类。

验证命令在 `harness.toml` 中使用 argv 数组声明，避免不必要的 shell 字符串解析。任意 shell、网络、依赖安装和 Git 写操作受权限模式控制。

## 8. 反馈闭环

反馈闭环是主要贡献维度。分类器不调用 LLM，而是根据命令类型、退出码、超时、资源状态和输出解析器生成：

- `pass`
- `test_failure`
- `lint_failure`
- `type_failure`
- `environment_failure`
- `timeout`
- `resource_exhausted`
- `policy_blocked`
- `tool_error`
- `invalid_action`
- `merge_conflict`
- `no_progress`

反馈包含分类、简短摘要、相关诊断、命令、文件、可重试性和停止建议。反馈不包含 API Key、完整环境变量或未脱敏日志。

交互模式不设置“最多 5 轮”之类的低固定上限。循环持续到客观完成条件、用户操作或安全预算触发。`harness.toml` 可以分别配置 `max_model_turns`、`max_total_model_calls`、`max_wall_time_seconds` 和 `max_cost_usd`；无人值守或 CI 运行必须设置至少一个有限的模型调用或费用预算。确定性机制演示显式使用 5 轮预算，以稳定验证预算耗尽行为。

以下情况提前暂停或结束：

- 连续重复同一失败且无文件变化；
- 连续产生非法动作；
- 环境或权限错误不可恢复；
- 资源预算耗尽；
- 用户取消；
- 审批被拒绝；
- worker 工件无法安全集成。

## 9. 治理与审批

判定优先级：

1. 硬性安全规则；
2. 项目 `harness.toml`；
3. 当前权限模式；
4. 当前会话的具体审批。

权限模式：

- `strict`：写入、命令和外部访问默认审批。
- `balanced`：仓库内编辑和声明式验证自动执行；依赖安装、网络、仓库外路径和 Git 写操作审批。
- `autonomous`：已声明范围内自动执行，但硬性路径和破坏性规则仍不可绕过。

硬性拒绝至少覆盖：

- 仓库外写入和符号链接逃逸；
- 访问 Docker socket、SSH agent、系统密钥目录和用户凭据；
- 明显破坏性磁盘、数据库或系统命令；
- 未声明的特权容器配置；
- 将真实凭据传入 worker 容器或日志。

审批仅适用于一个具体动作，记录动作、原因、请求时间、用户决定和恢复结果。

## 10. 上下文与记忆

每轮上下文按固定顺序组装：

1. 用户任务；
2. 仓库约定文件，如 `AGENTS.md`、`CLAUDE.md` 和 README；
3. `harness.toml`；
4. 当前运行和任务图状态；
5. 与当前任务相关的项目记忆；
6. 最近事件、工具结果和反馈；
7. 压缩后的早期历史摘要。

SQLite 保存：

- 项目；
- 运行；
- 迭代；
- 事件；
- 审批；
- 任务图；
- 工件元数据；
- 记忆原文；
- embedding 状态。

记忆类型：

- `project_convention`
- `validation_config`
- `governance_decision`
- `task_summary`
- `failure_pattern`

LanceDB 保存脱敏后的向量和关联 `memory_id`。检索流程为 query embedding、项目和类型过滤、top-k 搜索、SQLite 恢复原文、再次权限过滤、限制数量后注入。

真实 embedding 通过可注入供应商适配器获得。测试使用固定维度的 deterministic mock embedding。embedding 不可用时降级到 SQLite 全文或关键词检索。

## 11. 容器级 Sandbox Runtime

每个 worker 使用独立临时容器和独立任务工作副本。原始仓库不直接作为可写挂载暴露给 worker。

默认容器策略：

- 非 root 用户；
- 只读根文件系统；
- 丢弃全部 Linux capabilities；
- 工作区是唯一持久可写位置；
- 默认无网络；
- CPU、内存、PID、磁盘、命令时长和输出大小限制；
- 固定基础镜像和镜像 digest；
- 不挂载 Docker socket、SSH agent、用户 home 或凭据目录；
- 任务结束后销毁容器和临时卷。

Supervisor 通过 Docker Engine API 管理容器，但 Docker socket 不进入 worker。只有结构化工件可以离开容器：补丁、文件摘要、测试结果、日志摘要和交接消息。

安全边界明确为限制普通工具误操作和未信任代码的影响面，不承诺抵御宿主机内核或容器运行时漏洞。

## 12. 多 Agent 编排

采用 Supervisor + 专职 worker：

- `planner`：只读分析，输出 `TaskGraph`；
- `coder`：在独立沙箱内修改代码；
- `tester`：复现失败、补充测试、验证补丁；
- `reviewer`：检查规约、范围、证据和质量；
- `security`：检查危险动作、依赖、敏感信息和沙箱策略。

每个 worker 内部运行同一套 `AgentLoop`，但拥有独立角色策略、上下文预算、权限和记忆范围。

任务图节点包含：目标、输入工件、允许路径、验证命令、依赖、重试预算和状态。依赖满足后才可调度；独立只读任务可以并行；修改重叠文件的任务必须串行。

worker 输出 `WorkArtifact`，包含补丁、文件列表、摘要、验证证据、假设和后续请求。Supervisor 在集成沙箱应用补丁并重新验证。冲突自动基于最新状态重放一次，仍冲突则产生 `merge_conflict` 并暂停审批。

## 13. 配置

目标仓库可提交 `harness.toml`，声明：

- 治理模式；
- 可读写路径；
- test、lint、typecheck argv；
- 命令超时和输出限制；
- 最大轮数和 worker 数；
- 是否允许网络；
- 容器镜像和资源限制；
- 启用的 worker 角色；
- 记忆检索数量。

配置通过 schema 校验。无效配置阻止运行，不采用模型猜测值。

## 14. 凭据安全

LLM 和 embedding API Key 使用系统钥匙串保存。CLI 支持隐藏录入、状态、更新和清除，状态不回显明文。

`.env` 仅作为显式开发回退，必须被 Git 忽略，并在 README 中说明明文、进程环境和误提交风险。

真实凭据不得：

- 提交到 Git；
- 写入 SQLite 或 LanceDB；
- 写入日志、事件或错误报告；
- 传入 worker 容器；
- 出现在命令行参数和 shell history。

## 15. CLI 与 WebUI

CLI 至少支持：

- 创建任务运行；
- 选择权限模式；
- 查看状态和事件；
- 审批、拒绝、恢复和取消；
- 查看记忆和清除索引；
- 管理凭据；
- 启动 WebUI；
- 运行确定性机制演示。

WebUI 展示：

- 任务创建；
- Supervisor 和 worker 状态；
- 任务图；
- 事件时间线；
- tool call 和反馈分类；
- 审批；
- 修改文件和补丁摘要；
- 验证结果和最终停止原因。

本地 WebUI 可以使用本地仓库。公网 WebUI 只运行内置示例或隔离上传副本。

## 16. 错误处理与可观测性

所有错误转换为领域错误和事件，不把原始异常直接展示给 LLM。事件采用版本化 JSON schema，包含时间、运行、worker、任务节点、动作、结果、反馈和状态转换。

日志、事件、数据库写入和 UI 展示共用脱敏器。敏感字段在持久化前处理，而不是只在显示层隐藏。

系统为每次运行生成最终摘要：完成状态、停止原因、修改文件、验证证据、审批记录、资源使用和未解决风险。

## 17. 测试策略

### 17.1 单元测试

- Agent loop 状态转移；
- tool schema 和分发；
- 三档治理和硬性拒绝；
- 审批恢复；
- 反馈分类和无进展检测；
- 上下文预算和摘要；
- SQLite 记忆；
- LanceDB 检索和降级；
- Sandbox 配置生成和生命周期；
- TaskGraph 调度；
- 工件集成和冲突处理；
- 凭据服务的 mock keyring 行为。

### 17.2 集成测试

使用临时 Git 仓库和临时数据库验证真实文件、Git diff、子进程、超时、脱敏、容器生命周期和补丁集成。测试默认无网络、无真实 LLM。

“测试默认无网络”指依赖已经通过 `uv sync --all-extras --frozen` 预置后的运行阶段，而不是声称一个没有 pytest、Pydantic 或 wheel cache 的全新离线环境可以自动完成首次安装。首次安装可使用 registry；气隙环境必须提供预置 uv cache 或 wheelhouse，并使用 `uv sync --all-extras --frozen --offline`。第一个包结构测试只使用标准库 `unittest`，用来验证第三方开发依赖安装前的源目录和版本导出。

### 17.3 确定性机制演示

mock 场景固定复现：

1. planner 生成任务图；
2. coder 产生错误补丁；
3. tester 返回 `test_failure`；
4. coder 根据反馈修正；
5. reviewer 批准；
6. Supervisor 集成并验证通过；
7. 危险动作被护栏拦截；
8. 三档权限产生预期差异；
9. 向量记忆命中相关历史。

真实 LLM 修复真实缺陷作为补充演示，不作为唯一验收证据。

## 18. 分发与 CI

- Python 使用 `uv` 管理依赖、环境、测试和构建。
- 提供 Python 包安装和 `uv tool install` 路径。
- 提供 Dockerfile 和可复现的 WebUI/演示镜像。
- GitLab CI 必须包含名为 `unit-test` 的 job。
- CI 运行离线测试、确定性机制演示和镜像构建。
- README 说明获取、运行、钥匙串配置、Docker 前提、平台限制和安全边界。

## 19. 开发过程与交付证据自动记录

交付记录不是项目结束时补写的材料，而是每个开发 task 的状态输出。开发 agent 必须在同一 task 内维护以下文件：

- `AGENT_LOG.md`：按 Asia/Shanghai 时间顺序追加 task、Superpowers 技能、关键 prompt/context、subagent 结果、commit hash、人工干预和经验。
- `PLAN.md`：task 完成时写入状态、实际验证命令、结果和 commit hash；没有新鲜验证证据不得标记完成。
- `SPEC_PROCESS.md`：记录 brainstorming、陌生 agent 冷启动和 spec/plan 修订，包括暴露的问题和关键 diff。
- `DELIVERY_STATUS.md`：汇总课程交付清单、当前状态、最后验证时间、负责人和证据链接，并记录最新 CI/CD pipeline/job 的结果。

失败、暂停、审批拒绝、用户修改、流程偏离和外部依赖故障都必须记录。`DELIVERY_STATUS.md` 只是索引，不能替代 `AGENT_LOG.md`、`PLAN.md` 或 `SPEC_PROCESS.md` 的原始证据。任何命令只有实际执行并读取结果后才能被记录为通过。

## 20. 验收标准

- 自研 agent loop 可以在 mock LLM 下完成闭环。
- 失败分类能改变下一轮预设动作。
- 核心机制不依赖网络和真实模型即可测试。
- 三档权限、审批和硬性拒绝可确定性验证。
- 每个 worker 在独立受限容器中运行并被清理。
- Supervisor 可以调度、交接、评审和集成工件。
- SQLite 和 LanceDB 持久化与检索行为可测试。
- CLI 和 WebUI 共享相同服务和状态。
- API Key 不进入仓库、数据库、日志或容器。
- `uv` 测试命令和 GitLab CI 的 `unit-test` job 通过。
- Docker 镜像可以启动演示 WebUI。
- `AGENT_LOG.md`、`PLAN.md`、`SPEC_PROCESS.md` 和 `DELIVERY_STATUS.md` 能将每个完成 task 追溯到 commit 与验证证据。

## 21. 非目标

- 不使用现成 agent 框架的高层循环；
- 不自动创建远程 PR 或执行发布；
- 不让公网服务直接读取用户本机路径；
- 不承诺抵御内核级容器逃逸；
- 第一版不为所有语言提供专用语法分析器；
- 第一版不实现层级式 supervisor 树。

## 22. 风险与对策

- 真实模型输出差异：统一内部 tool-call schema，非法响应不执行。
- 通用命令风险：结构化 argv、白名单、审批、超时和容器隔离。
- 双数据库一致性：SQLite 为事实来源，LanceDB 可重建。
- 多 agent 冲突：独立副本、结构化工件、集成沙箱和冲突反馈。
- Docker daemon 权限：socket 仅由受信任 Supervisor 使用，不进入 worker；README 明确宿主风险。
- 上下文膨胀：相关记忆检索、最近事件窗口和结构化摘要。
- 范围过大：反馈闭环保持主要贡献；沙箱和编排通过明确接口和独立测试控制边界。
