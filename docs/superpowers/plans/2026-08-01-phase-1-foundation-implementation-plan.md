# 公司级 DevOps 平台阶段 1 实施计划

- 日期：2026-08-01
- 范围：平台底座与项目管理黄金闭环
- 黄金样板：`project-service`
- 技术栈：Python 3 + Flask、Vue 3 + TypeScript、PostgreSQL、Redis、RabbitMQ、Celery、Docker

## 1. 阶段目标

阶段 1 不追求一次上线全部微服务，而是交付一条可运行、可测试、可观测、可部署的底座闭环：

```text
企业用户登录
→ 创建项目
→ 分配项目成员和角色
→ 创建版本/迭代
→ 创建任务
→ 记录计划时间与 Worklog
→ 工作流驱动任务状态
→ 发布领域事件
→ 记录审计
→ 展示项目基础效能统计
```

阶段完成后，需求、TP、TD 等后续服务直接复制黄金样板的工程基线，不重新发明配置、错误、日志、权限、Outbox 和流水线。

## 2. 实施边界

### 2.1 本阶段交付

- `devops-portal`：Vue 3 门户、登录回调、项目与任务页面、主题切换。
- `devops-api-gateway`：认证、路由、限流、Trace、项目上下文。
- `iam-service`：企业 SSO 适配、本地开发身份、用户组织同步骨架、角色与项目授权。
- `project-service`：项目、成员、迭代、版本、任务、Worklog、基础统计。
- `workflow-service`：任务状态模板、实例和流转校验。
- `audit-service`：统一审计事件接收、查询和归档接口骨架。
- `notification-service`：站内通知基础能力。
- RabbitMQ、Redis、PostgreSQL、OpenTelemetry、Prometheus、Grafana 和日志采集。
- 公共契约与轻量 SDK：身份上下文、Problem Details、事件信封、Outbox、Trace。
- Docker 开发/测试环境和生产多主机部署基线。

### 2.2 本阶段不交付

- 需求、TP、TD 正式业务功能。
- AI 模型和 XMind。
- GitLab MR/CI/CD 深度治理、Nexus/Harbor 晋级、发布服务。
- OpenSearch 全局搜索和完整管理驾驶舱。
- Kubernetes 编排。

可预留接口和事件 Schema，但不建立空壳微服务。

## 3. 架构决策

| 决策 | 选择 | 原因 |
|---|---|---|
| 代码结构 | Feature-first + API/Service/Repository | 控制 Flask 服务规模，便于复制 |
| API 客户端 | OpenAPI 生成 TypeScript 客户端 | Python/Vue 跨语言保持契约一致 |
| 认证 | OIDC 授权码 + PKCE；本地开发身份适配器 | 企业统一身份且便于开发测试 |
| 实时能力 | SSE 用于通知和任务状态；普通数据按需刷新 | 当前主要是服务端到客户端通知 |
| 错误处理 | 类型化错误 + 全局 Problem Details | 统一跨服务和前端错误体验 |
| 一致性 | 本地事务 + Outbox + RabbitMQ | 不引入分布式事务 |
| 数据隔离 | 项目 ID + 服务端对象级校验 | 满足项目级隔离 |
| 前端状态 | Pinia 管客户端状态；查询状态由 API composables 管理 | 避免把所有服务器数据塞进全局 Store |

## 4. 仓库与依赖顺序

建议按独立仓库实施，但阶段初期需统一模板：

```text
platform-contracts
platform-python-sdk
project-service
workflow-service
iam-service
audit-service
notification-service
devops-api-gateway
devops-portal
platform-deployment
```

依赖顺序：

1. `platform-contracts` 定义基础契约。
2. `platform-python-sdk` 实现无业务逻辑的通用能力。
3. `project-service` 作为黄金样板验证 SDK 和契约。
4. `iam-service`、`workflow-service`、`audit-service` 接入闭环。
5. 网关和门户完成端到端集成。
6. 部署仓库固化多环境和发布标准。

## 5. 工作包 A：工程基础与契约

### A1. 统一开发基线

交付：

- Python 项目模板和 `pyproject.toml`。
- 统一 Ruff、mypy/Pyright、pytest、Bandit、pip-audit 配置。
- Vue 3 模板和 ESLint、TypeScript、Vitest、Playwright 配置。
- GitLab MR 模板、CODEOWNERS、分支保护和流水线基线。
- `.env.example`，不包含真实密钥。

验收：新服务可在 10 分钟内从模板创建并通过空项目 CI。

### A2. 公共契约

交付：

- RFC 9457 Problem Details Schema。
- 身份上下文和项目上下文 Schema。
- 事件信封 JSON Schema。
- 审计事件 Schema。
- OpenAPI 公共参数、分页和错误组件。
- 契约版本和兼容性策略。

验收：OpenAPI lint、breaking-change 检查和 JSON Schema 兼容性检查进入 CI。

### A3. Python SDK

仅包含：

- 配置加载和启动校验。
- Request/Trace ID 中间件。
- 结构化日志。
- 类型化错误和全局处理器。
- 身份上下文解析接口。
- Outbox 基础设施。
- OpenTelemetry 初始化。
- 健康检查和优雅停机。

不得包含项目、任务、需求等业务实体。

## 6. 工作包 B：黄金样板 project-service

### B1. 工程结构

```text
project-service/
  src/project_service/
    app.py
    config.py
    extensions.py
    shared/
      auth/
      database/
      errors/
      events/
      observability/
    projects/
      api.py
      schemas.py
      service.py
      repository.py
      models.py
      events.py
      policies.py
      tests/
    memberships/
    iterations/
    versions/
    tasks/
    worklogs/
    outbox/
  migrations/
  tests/integration/
  tests/contract/
  Dockerfile
  pyproject.toml
```

### B2. 数据模型

核心表：

- `projects`
- `project_memberships`
- `iterations`
- `release_versions`
- `tasks`
- `task_assignees`
- `worklogs`
- `outbox_events`
- `processed_commands`

通用字段：UUIDv7/ULID、业务编号、`project_id`、审计时间和人员、`version` 乐观锁。Worklog 不允许覆盖原始记录；更正通过反向记录或修正记录实现。

索引重点：

- `projects(status, updated_at)`
- `project_memberships(project_id, user_id)` 唯一
- `tasks(project_id, status, assignee_id, planned_end_at)`
- `tasks(iteration_id, status)`
- `tasks(release_version_id, status)`
- `worklogs(task_id, work_date)`
- `outbox_events(status, available_at)`

### B3. API

第一批 API：

```text
POST   /api/v1/projects
GET    /api/v1/projects
GET    /api/v1/projects/{project_id}
POST   /api/v1/projects/{project_id}/members
DELETE /api/v1/projects/{project_id}/members/{user_id}
POST   /api/v1/projects/{project_id}/iterations
POST   /api/v1/projects/{project_id}/versions
POST   /api/v1/projects/{project_id}/tasks
GET    /api/v1/projects/{project_id}/tasks
GET    /api/v1/tasks/{task_id}
PATCH  /api/v1/tasks/{task_id}
POST   /api/v1/tasks/{task_id}/transitions
POST   /api/v1/tasks/{task_id}/worklogs
GET    /api/v1/projects/{project_id}/metrics/summary
```

要求：

- 所有写接口支持 `Idempotency-Key`。
- 更新和流转校验 `version`。
- 项目 ID 同时从路径和身份上下文校验。
- 状态只通过 `transitions` 修改。
- 列表使用游标分页。

### B4. 领域规则

- 任务必须关联迭代或版本之一。
- 计划结束时间不得早于计划开始时间。
- 实际结束后任务必须处于完成/关闭状态。
- Worklog 必须大于 0，单日和单次上限可配置。
- 非项目成员不能访问项目对象。
- 项目归档后业务对象只读。
- 任务状态流转由工作流服务/本地缓存的模板快照校验。
- 工时修正必须记录原因并产生审计事件。

### B5. 事件

首批事件：

- `Project.Created.v1`
- `Project.MemberAdded.v1`
- `Project.MemberRemoved.v1`
- `Iteration.Created.v1`
- `ReleaseVersion.Created.v1`
- `Task.Created.v1`
- `Task.Assigned.v1`
- `Task.StatusChanged.v1`
- `Worklog.Recorded.v1`
- `Project.Archived.v1`

每个事件必须具备 Schema、Outbox 测试、重复消费测试和 Trace 传播测试。

### B6. 测试

- 单元：状态机、时间规则、Worklog、权限策略。
- 集成：PostgreSQL 事务、迁移、唯一约束、Outbox。
- API 契约：OpenAPI 请求/响应和 Problem Details。
- 安全：跨项目访问、角色越权、ID 枚举。
- 性能：任务列表、工时汇总和批量事件。
- E2E：创建项目 → 成员 → 版本/迭代 → 任务 → 工时 → 状态完成 → 指标。

## 7. 工作包 C：IAM 与权限

交付顺序：

1. 开发环境身份适配器，支持固定测试用户和角色。
2. OIDC 授权码 + PKCE。
3. 用户、组织和不可变主体 ID 映射。
4. LDAP/AD 同步任务骨架和失败补偿。
5. 项目角色、权限动作、数据范围接口。
6. 服务身份和短期令牌。
7. 本地应急管理员的 MFA、IP 白名单和审计接口。

验收：普通成员不能跨项目；项目管理员只能管理本项目；平台管理员无额外授权不能查看敏感业务数据。

## 8. 工作包 D：工作流、审计与通知

### D1. 工作流

阶段 1 只实现任务工作流模板：

```text
待处理 → 进行中 → 已完成 → 已关闭
   └────────→ 已取消
```

交付模板版本、实例、显式流转、角色条件、必填字段和乐观锁。不实现可视化任意编排和脚本动作。

### D2. 审计

接收身份、权限、项目、任务、Worklog 和流程事件。支持按 Trace、项目、资源、操作者和时间查询。审计数据追加写入，业务服务无修改权限。

### D3. 通知

支持站内通知、已读状态和 SSE 推送。首批通知：成员加入、任务分配、任务超期、工作流驳回/完成。邮件和企业通信渠道保留适配器接口。

## 9. 工作包 E：网关与 Vue 3 门户

### E1. API Gateway/BFF

- OIDC 回调与会话/令牌转发。
- Request ID、Trace、结构化访问日志。
- CORS 白名单、限流和请求大小限制。
- 项目上下文注入。
- `/health` 和 `/ready`。
- 只为必要详情做 2～3 服务并行聚合。

### E2. Vue 3 门户

页面：

- 登录和身份错误页。
- 项目列表、创建项目、项目概览。
- 成员管理。
- 迭代和版本管理。
- 任务列表、看板、详情和流转。
- Worklog 登记。
- 基础效能统计。
- 通知中心。

工程要求：

- Light/Dark/System 主题切换。
- OpenAPI 生成客户端，不手写重复 DTO。
- 加载、空状态、错误和无权限状态完整。
- 核心页面满足 WCAG 2.1 AA。
- 大列表虚拟化或游标加载。
- 使用 SSE 接收通知，不引入 WebSocket。

## 10. 工作包 F：部署与可观测性

### F1. 环境

- 本地：Docker Compose，仅开发依赖和联调。
- CI：临时 PostgreSQL、Redis、RabbitMQ，执行迁移和集成测试。
- 测试：多服务集成环境。
- 生产：Docker 多主机，网关与核心服务双实例。

### F2. 可观测性

- 指标：请求量、P95、错误率、连接池、队列、Outbox、业务指标。
- 日志：JSON，包含服务、环境、Trace、项目和主体摘要。
- Trace：HTTP、RabbitMQ、Celery 和数据库关键跨度。
- 告警：服务不可用、错误率、延迟、连接池、队列积压、死信和审计高风险事件。

### F3. 数据保护

- PostgreSQL 每日全量 + WAL，验证时间点恢复。
- Redis 不作为事实唯一来源。
- RabbitMQ 使用持久化和仲裁队列。
- 密钥使用受控加密挂载，禁止进入 Git 和镜像。

## 11. GitLab CI 流水线阶段

```text
validate
→ lint
→ type-check
→ unit-test
→ integration-test
→ contract-test
→ security-scan
→ build-image
→ image-scan
→ deploy-test
→ e2e
→ publish
```

MR 阶段至少执行至安全扫描；主分支执行镜像构建、测试环境部署和 E2E；正式发布才推送受信任标签。

门禁：

- Ruff/ESLint/TypeScript 零错误。
- 核心 mypy/Pyright 零错误。
- 测试全部通过。
- 新增 Blocker/Critical 为零。
- Gitleaks 无有效密钥。
- OpenAPI/事件契约无未批准破坏性变更。
- 镜像 Critical 漏洞为零，High 按例外流程。

## 12. 里程碑与依赖

### M1：工程基线可用

完成模板、契约、SDK、CI 和本地开发环境。阻断条件：公共契约未稳定时不得并行复制多个服务。

### M2：project-service 黄金闭环

完成项目、版本、迭代、任务、Worklog、Outbox、审计事件和完整测试。阻断条件：跨项目权限测试或 Outbox 重复测试失败。

### M3：IAM/工作流/审计集成

完成真实身份、任务流转、审计查询和通知。阻断条件：权限绕过、高风险审计丢失。

### M4：门户与端到端闭环

完成 Vue 3 页面、生成客户端、SSE 通知和黄金链路 E2E。阻断条件：关键页面无加载/错误/无权限状态。

### M5：生产基线验收

完成容量、故障、恢复和安全验证。阻断条件：RPO/RTO 未演练、数据库连接预算不成立、严重漏洞未处理。

## 13. 团队分工建议

| 小组 | 职责 |
|---|---|
| 架构/资深开发 | ADR、黄金模板、关键建模、MR 与质量签核 |
| IAM/网关 | SSO、权限、项目上下文、安全 |
| 项目服务 | 项目、版本、迭代、任务、Worklog、事件 |
| 工作流/审计 | 模板、流转、审计和通知 |
| 前端 | 门户、生成客户端、项目与任务体验 |
| QA/测试架构 | 测试策略、契约、E2E、容量和安全验证 |
| DevOps/SRE | GitLab CI、Docker、多环境、监控和恢复演练 |

每个工作包至少有一名主责和一名备份维护者。

## 14. 阶段验收标准

功能：

- 企业账号可登录，项目成员和角色可管理。
- 可创建项目、版本、迭代、任务并登记工时。
- 任务状态按模板流转，非法流转被拒绝。
- 非项目成员无法访问项目数据。
- 操作产生审计和领域事件。
- 门户显示项目概览和基础效能指标。

质量：

- 黄金链路 E2E 稳定通过。
- API/事件契约进入 CI。
- 核心规则具备风险导向测试，核心分支覆盖率不低于 80%。
- 无未处理 Critical/High 安全风险（High 仅允许正式例外审批）。
- 所有核心服务具备健康检查、结构化日志、Trace 和优雅停机。

性能与可靠性：

- 普通查询 P95 ≤ 500 ms，写入 P95 ≤ 800 ms。
- 事件正常 P95 ≤ 5 秒。
- 目标并发下数据库连接池无耗尽。
- PostgreSQL 切换、消息重复/积压和服务重启演练通过。
- 备份恢复演练满足 RPO ≤ 15 分钟、RTO ≤ 2 小时。

## 15. 实施风险

| 风险 | 处理 |
|---|---|
| 同时开发过多服务 | 先稳定 project-service 和契约，再复制 |
| 公共 SDK 膨胀 | 只放基础设施，不放业务实体 |
| IAM 阻塞开发 | 先提供开发身份适配器，再接真实 OIDC |
| 工作流过度设计 | 阶段 1 只支持任务模板和受控规则 |
| 指标口径争议 | 先交基础统计，口径版本化并留数据证据 |
| Docker 生产运维复杂 | 标准镜像、双实例、健康检查、自动发布和恢复演练 |
| 测试环境不稳定 | CI 临时依赖 + 测试环境基线 + 可重置测试数据 |

## 16. 完成定义

阶段 1 只有在以下条件同时满足时完成：

1. 黄金闭环可由用户通过门户完整操作。
2. API、事件、数据库迁移和权限契约有自动测试。
3. project-service 被评审为可复制的黄金样板。
4. 质量门禁不能被普通开发者绕过。
5. 监控、告警、审计、备份和恢复经过实际验证。
6. 运行手册、ADR、接口文档和服务所有权齐全。
7. 团队至少完成一次结对开发、代码门诊和故障演练。
