# project-service 项目协作能力增量 PRD

- 文档日期：2026-08-02
- 文档状态：待架构评审
- PRD 类型：增量 / 简洁执行版
- Project Name：`project_collaboration_increment`
- Language：中文
- Programming Language：Python 3.13 + Flask + SQLAlchemy 2 + PostgreSQL + Alembic；前端预留 Vue 3 API 契约，本轮不开发前端

## 1. 原始需求与范围

在已完成总体设计与 `project-service` 黄金服务的基础上，增量交付三组后端能力：

1. 项目成员与项目角色；
2. 版本与迭代；
3. 任务与 Worklog 工时记录。

任务可挂载版本或迭代，记录预估工时，并由不可覆盖的 Worklog 汇总实际工时，为后续效能统计提供可信数据源。用户默认只能访问其参与项目；一期采用固定模板化工作流。本轮不实现 IAM 登录、Vue 门户、需求、TP、TD。

## 2. 产品目标

1. **建立项目内协作边界**：以项目成员和项目角色控制对象级访问，跨项目越权访问拦截率必须为 100%。
2. **形成可执行的计划—任务闭环**：支持项目按版本、迭代组织任务，P0 流程可完成“成员 → 版本/迭代 → 任务 → 状态流转”。
3. **沉淀可信效能数据**：预估工时可追踪，实际工时仅由 Worklog 明细净额汇总，所有修正可审计，为后续计划准确度、投入分布等统计提供数据源。

## 3. 角色定义

| 角色 | 定义 |
|---|---|
| 项目所有者（Owner） | 项目责任人；唯一，拥有项目内最高管理权限，可移交所有权 |
| 项目管理员（Admin） | 管理成员、角色、版本、迭代及全部任务，但不能移交项目所有权 |
| 项目成员（Member） | 创建和参与任务，登记本人 Worklog，查看项目内协作数据 |
| 项目只读成员（Viewer） | 只读查看项目、版本、迭代、任务及工时汇总，不可查看非必要审计敏感详情 |
| 平台调用方 | 本轮通过可信请求头传入 `actor_id`；不等同于平台管理员，不自动获得业务数据权限 |

> Owner、Admin、Member、Viewer 为一期内置角色模板；本轮不提供自定义角色和权限点编辑器。

## 4. 用户故事

1. As a 项目所有者, I want 添加成员并分配项目角色 so that 项目数据只对授权参与者开放。
2. As a 项目管理员, I want 创建版本和迭代并维护生命周期 so that 团队可按发布目标和时间盒组织工作。
3. As a 项目成员, I want 创建任务并挂载版本或迭代 so that 工作范围可被计划、分派和追踪。
4. As a 任务参与者, I want 登记和修正本人 Worklog so that 实际投入准确且保留完整修正链。
5. As a 项目管理者, I want 获取预估与实际工时的结构化数据 so that 后续效能服务可计算团队趋势和计划准确度。

## 5. 需求池

### P0 — Must Have

- 项目成员新增、列表、角色变更、移除；Owner 唯一且不可直接移除。
- 内置 Owner/Admin/Member/Viewer 权限校验；业务服务执行最终对象级鉴权。
- 用户项目列表仅返回其有效参与项目，项目内所有资源强制按 `project_id` 隔离。
- 版本、迭代的创建、查询、列表、更新及显式生命周期转换。
- 任务创建、详情、游标分页列表、基础字段更新、负责人/参与人维护、显式状态转换。
- 任务必须至少关联一个有效版本或迭代；允许同时关联二者，但二者必须属于任务所在项目。
- 任务记录预估工时；实际工时为有效 Worklog 净额汇总，禁止直接写入。
- Worklog 新增、列表和修正；原始记录不可覆盖、不可物理删除。
- 所有写接口支持幂等键；更新/流转使用乐观锁；错误遵循 RFC 9457 Problem Details。
- 成员、角色、版本、迭代、任务、Worklog 的关键变更产生审计记录；正式业务资产不物理删除。
- OpenAPI 3.1 契约、Alembic 迁移、单元/集成/契约/越权测试同步交付。

### P1 — Should Have

- 版本/迭代/任务按状态、负责人、时间范围筛选与排序。
- 批量调整任务版本或迭代，单批上限 100 条，整体事务成功或失败。
- 项目工时汇总 API：按任务、成员、版本、迭代和日期范围返回预估/实际分钟数。
- 任务剩余工时、标签、参与人及阻塞原因。
- 版本发布日期、迭代容量与任务超期标识。
- 领域事件通过 Outbox 可靠发布，至少覆盖成员变更、任务创建/分派/流转、Worklog 记录/修正。

### P2 — Nice to Have

- 版本/迭代复制与任务批量导入。
- 任务层级（父子任务）与任务依赖。
- 个人工时草稿、定时提醒和缺报提示。
- 可配置工时上限及项目日历；一期先用平台统一配置。

## 6. 核心业务规则

### 6.1 成员与角色

1. `(project_id, user_id)` 在有效成员关系中必须唯一；重复新增返回原结果或明确冲突，不产生重复成员。
2. 项目创建者自动成为 Owner；每个活动项目必须且只能有一个有效 Owner。
3. Owner 移交必须使用显式动作 API，在同一事务中将新 Owner 升级、原 Owner 降为 Admin；新 Owner 必须是有效项目成员。
4. Owner 不可被直接移除或降级；必须先完成所有权移交。
5. 移除成员采用关系终止（记录 `removed_at/removed_by`），不得删除历史任务、Worklog 或审计记录。
6. 被移除成员立即失去项目访问权；其历史任务分派和 Worklog 保留。其未完成任务允许暂时保留原负责人快照，但必须支持 Admin 后续改派。
7. 任务负责人及参与人必须是当前有效 Member/Admin/Owner；Viewer 不可被分配为负责人。

### 6.2 版本与迭代

1. 版本业务编号/名称在项目内唯一；迭代名称在项目内唯一。
2. 迭代 `end_date` 不得早于 `start_date`；同一项目可存在多个规划中迭代，但同一时间最多一个进行中迭代（一期规则）。
3. 已发布版本、已完成迭代不可再接受新任务挂载；既有任务关系保留。
4. 存在未关闭任务时，版本不得发布、迭代不得完成；Admin/Owner 可使用带原因的受控强制动作，必须审计。
5. 已被任务引用的版本/迭代不得删除，只能取消或归档。

### 6.3 任务

1. 任务创建时必须关联 `release_version_id` 或 `iteration_id` 至少一项；关联对象必须同项目且非取消/归档状态。
2. `planned_end_at >= planned_start_at`；`actual_end_at >= actual_start_at`。
3. `estimated_minutes` 为非负整数；实际工时 `actual_minutes` 只读，等于有效 Worklog `minutes_delta` 之和，最小为 0。
4. 状态不可通过普通 PATCH 修改，只能调用显式 `transitions` API。
5. 任务进入“进行中”时，如 `actual_start_at` 为空则由服务端写入当前时间；进入“已完成”时写入 `actual_end_at`；重开时保留历史时间并清空当前完成时间。
6. 已关闭/已取消任务不可新增 Worklog；已完成但未关闭任务允许补录完成日及以前的 Worklog。
7. 项目归档后，成员、版本、迭代、任务和 Worklog 全部只读。

### 6.4 Worklog

1. 每条 Worklog 归属一个任务、项目和登记人，`work_date` 为项目业务日期，`minutes_delta` 为整数且不等于 0。
2. 普通登记 `minutes_delta > 0`；一期单条上限 1,440 分钟，同一用户同一自然日跨任务有效净工时上限默认 1,440 分钟。
3. Worklog 不允许 PATCH/DELETE。更正必须新增一条修正记录，引用 `corrects_worklog_id`，填写非空 `correction_reason`，以正/负差额调整。
4. 普通成员只能登记/修正本人 Worklog；Admin/Owner 可代录或修正，但必须填写 `on_behalf_of_user_id`/原因并强化审计。
5. 修正后任务实际工时不得小于 0；一条记录可被多次差额修正，但完整链必须可查询。
6. 工时用于团队资源规划与过程改进，不应作为个人单一绩效排名依据。

## 7. 权限矩阵

符号：✓ 允许；△ 受限；— 禁止。

| 操作 | Owner | Admin | Member | Viewer |
|---|:---:|:---:|:---:|:---:|
| 查看项目及项目内对象 | ✓ | ✓ | ✓ | ✓ |
| 管理成员（新增/移除） | ✓ | ✓ | — | — |
| 调整 Admin/Member/Viewer 角色 | ✓ | ✓* | — | — |
| 移交 Owner | ✓ | — | — | — |
| 创建/更新/流转版本、迭代 | ✓ | ✓ | — | — |
| 创建任务 | ✓ | ✓ | ✓ | — |
| 编辑任意任务基础字段 | ✓ | ✓ | △* | — |
| 分派任意任务 | ✓ | ✓ | — | — |
| 流转任务状态 | ✓ | ✓ | △* | — |
| 登记/修正本人 Worklog | ✓ | ✓ | ✓ | — |
| 代录/修正他人 Worklog | ✓ | ✓ | — | — |
| 查看工时明细 | ✓ | ✓ | ✓* | △* |
| 强制完成迭代/发布版本 | ✓ | ✓ | — | — |

限制说明：

- Admin 不得授予/撤销 Owner，也不得移除或降级 Owner。
- Member 仅可编辑自己创建或负责/参与的任务；仅可执行模板允许 Member 执行的转换。
- Member 可查看项目内 Worklog 明细；Viewer 默认只看任务及聚合工时，不看工作内容与修正原因。

## 8. 状态与生命周期

### 8.1 成员关系

`active → removed`；移除后不可原记录复活，再次加入生成新成员关系或新任期记录。

### 8.2 版本

```text
planned → active → released → archived
   └────────────→ canceled
active ─────────→ canceled
```

- `released` 必须有 `release_date`，默认要求关联任务均为 `closed/canceled`。
- `released/canceled/archived` 为终态；归档只用于收敛展示，不删除关系。

### 8.3 迭代

```text
planned → active → completed
   └────────────→ canceled
active ─────────→ canceled
```

- 同一项目最多一个 `active` 迭代。
- `completed` 默认要求关联任务均为 `done/closed/canceled`。

### 8.4 任务模板化工作流

```text
todo → in_progress → done → closed
  └───────────────→ canceled
in_progress ──────→ canceled
done → in_progress（重开）
```

- 允许转换由服务端固定模板版本校验；任务实例保存 `workflow_template_key` 与 `workflow_version`。
- 非法转换返回 `409 INVALID_STATE_TRANSITION`；并发版本冲突返回 `412 VERSION_CONFLICT`。
- 一期不支持项目自定义状态、任意脚本或可视化流程编排。

## 9. 字段级规则

所有核心对象使用 UUID；API JSON 使用 `snake_case`；时间戳使用带时区 ISO 8601 UTC；日期使用 `YYYY-MM-DD`。所有可变聚合包含从 1 起始的 `version` 乐观锁字段。

### 9.1 ProjectMembership

| 字段 | 规则 |
|---|---|
| `id` | UUID，服务端生成，不可变 |
| `project_id` | 必填、不可变，必须为当前路径项目 |
| `user_id` | 必填，1~255 字符；一期视为上游不可变主体 ID |
| `role` | 必填，枚举 `owner/admin/member/viewer` |
| `status` | 只读，`active/removed` |
| `joined_at/joined_by` | 服务端生成 |
| `removed_at/removed_by` | 移除时生成，未移除为空 |
| `version` | 更新角色或移除时校验并递增 |

### 9.2 ReleaseVersion

| 字段 | 规则 |
|---|---|
| `id/business_no` | 服务端生成；业务编号项目内唯一，建议 `VER-{sequence}` |
| `project_id` | 必填、不可变 |
| `name` | 必填，1~120 字符，去首尾空格后项目内唯一 |
| `description` | 可选，最大 5,000 字符 |
| `status` | 只读，通过 transition 修改 |
| `planned_release_date` | 可选日期 |
| `release_date` | `released` 时必填，可由动作请求或服务端当天生成 |
| `version` | 乐观锁 |

### 9.3 Iteration

| 字段 | 规则 |
|---|---|
| `id/business_no` | 服务端生成；建议 `ITR-{sequence}` |
| `project_id` | 必填、不可变 |
| `name` | 必填，1~120 字符，项目内唯一 |
| `goal` | 可选，最大 2,000 字符 |
| `start_date/end_date` | 必填日期，结束不早于开始 |
| `status` | 只读，通过 transition 修改 |
| `capacity_minutes` | 可选，非负整数 |
| `version` | 乐观锁 |

### 9.4 Task

| 字段 | 规则 |
|---|---|
| `id/business_no` | 服务端生成；业务编号格式建议 `TSK-{sequence}`，全局唯一 |
| `project_id` | 必填、不可变 |
| `title` | 必填，1~200 字符 |
| `description` | 可选，最大 20,000 字符 |
| `task_type` | 一期枚举 `development/test/documentation/operation/other`；与 TP 测试任务无关 |
| `priority` | 枚举 `p0/p1/p2/p3`，默认 `p2` |
| `status` | 只读，默认 `todo` |
| `assignee_id` | 可选；必须为有效 Owner/Admin/Member |
| `participant_ids` | 可选去重数组；均须为有效 Owner/Admin/Member |
| `release_version_id/iteration_id` | 至少一项非空，同项目且可接收任务 |
| `planned_start_at/planned_end_at` | 可选，成对或单独填写均可；同时存在时校验顺序 |
| `actual_start_at/actual_end_at` | 服务端随状态维护，普通 PATCH 不可写 |
| `estimated_minutes` | 必填，整数，0~10,000,000 |
| `actual_minutes` | 只读，Worklog 有效净额汇总 |
| `remaining_minutes` | P1，可选非负整数 |
| `workflow_template_key/version` | 服务端写入且实例期内不可变 |
| `version` | PATCH/transition 必须校验 |

### 9.5 Worklog

| 字段 | 规则 |
|---|---|
| `id` | UUID，服务端生成，不可变 |
| `project_id/task_id` | 必填、不可变，任务必须属于路径项目 |
| `user_id` | 实际工时归属人；普通成员只能为自己 |
| `recorded_by` | 服务端取当前 actor，不可伪造 |
| `work_date` | 必填，不得晚于项目当前业务日期；是否允许跨期补录见待确认事项 |
| `minutes_delta` | 必填整数；普通记录 1~1,440，修正可为 -1,440~1,440 且不为 0 |
| `description` | 普通记录必填，1~2,000 字符 |
| `corrects_worklog_id` | 修正记录必填且须同任务、同工时归属人 |
| `correction_reason` | 修正或代录时必填，1~1,000 字符 |
| `created_at` | 服务端生成；无 `updated_at` 语义 |

## 10. 项目级隔离

1. 所有领域表必须持有 `project_id`；所有 Repository 查询必须显式包含 `project_id` 条件，禁止先按资源 ID 查询后在应用层过滤。
2. 列表接口仅返回当前 actor 的有效成员项目；被移除成员不可继续读取历史项目。
3. 路径 `project_id`、资源自身 `project_id`、请求身份可访问项目三者必须一致；请求体中的 `project_id` 不作为授权依据。
4. 非项目成员访问项目或项目内对象统一返回 `404 RESOURCE_NOT_FOUND`，避免枚举；项目成员因角色不足返回 `403 FORBIDDEN`。
5. 关联版本、迭代、任务、成员的写操作必须在数据库事务内再次校验同项目归属，防止 TOCTOU 和跨项目 ID 注入。
6. 项目归档后除审计读取外全部业务写操作返回 `409 PROJECT_ARCHIVED`。
7. 本轮 `X-Actor-Id` 仅为开发/受信网关身份适配；生产不得直接信任公网客户端该请求头。

## 11. 审计要求

- 审计范围：成员新增/移除/角色变更/Owner 移交；版本和迭代创建、字段变更、状态转换及强制动作；任务创建、分派、关联范围变更、预估工时变更、状态转换；Worklog 新增、代录与修正；越权和非法流转失败。
- 每条审计至少包含：`occurred_at`、`trace_id`、`actor_id`、`project_id`、`resource_type`、`resource_id`、`action`、`result`、`before`、`after`、`reason`、`source`、`idempotency_key`（如有）。
- `before/after` 记录字段差异；不得记录凭据、Token 或不必要的个人敏感信息。
- 审计采用追加写入，业务服务无修改/删除权限；审计投递失败不得静默丢失，应通过同事务 Outbox 重试。
- Worklog 修正必须能从当前有效净额追溯到全部原始及修正记录。
- 最低保留期由公司审计制度确定；本轮先保证不随业务归档删除。

## 12. API 级验收标准

### 12.1 建议 API 范围

```text
GET    /api/v1/projects/{project_id}/members
POST   /api/v1/projects/{project_id}/members
PATCH  /api/v1/projects/{project_id}/members/{membership_id}
DELETE /api/v1/projects/{project_id}/members/{membership_id}
POST   /api/v1/projects/{project_id}/owner-transfers

GET    /api/v1/projects/{project_id}/versions
POST   /api/v1/projects/{project_id}/versions
GET    /api/v1/projects/{project_id}/versions/{version_id}
PATCH  /api/v1/projects/{project_id}/versions/{version_id}
POST   /api/v1/projects/{project_id}/versions/{version_id}/transitions

GET    /api/v1/projects/{project_id}/iterations
POST   /api/v1/projects/{project_id}/iterations
GET    /api/v1/projects/{project_id}/iterations/{iteration_id}
PATCH  /api/v1/projects/{project_id}/iterations/{iteration_id}
POST   /api/v1/projects/{project_id}/iterations/{iteration_id}/transitions

GET    /api/v1/projects/{project_id}/tasks
POST   /api/v1/projects/{project_id}/tasks
GET    /api/v1/projects/{project_id}/tasks/{task_id}
PATCH  /api/v1/projects/{project_id}/tasks/{task_id}
POST   /api/v1/projects/{project_id}/tasks/{task_id}/transitions
GET    /api/v1/projects/{project_id}/tasks/{task_id}/worklogs
POST   /api/v1/projects/{project_id}/tasks/{task_id}/worklogs
POST   /api/v1/projects/{project_id}/tasks/{task_id}/worklogs/{worklog_id}/corrections

GET    /api/v1/projects/{project_id}/worklogs/summary   # P1
```

### 12.2 通用契约验收

1. 所有写接口必须接收 `Idempotency-Key`；同 actor、同 key、同规范化请求重放返回首次结果且不重复写库/审计/事件；同 key 不同请求返回 `409 IDEMPOTENCY_KEY_CONFLICT`。
2. PATCH 与 transition 必须使用 `If-Match` 或请求 `version`；版本不一致返回 `412 VERSION_CONFLICT`，不得产生部分更新。
3. 成功响应包含 `data` 和 `meta.trace_id`，并回传 `X-Trace-Id`；JSON 字段为 `snake_case`。
4. 校验失败返回 `422 VALIDATION_ERROR`；角色不足返回 403；不可见或不存在资源返回 404；业务状态冲突返回 409；错误体符合 RFC 9457。
5. 列表使用游标分页，默认 50、最大 200；相同游标和筛选条件结果顺序稳定，不重复、不漏项。
6. OpenAPI 3.1 必须覆盖全部请求、响应、枚举、错误码和示例，并通过契约 lint 与破坏性变更检查。

### 12.3 关键场景验收

| 场景 | 可验收结果 |
|---|---|
| 成员隔离 | A 项目 Member 请求 B 项目任一成员/版本/迭代/任务/Worklog，均返回 404，且无数据泄露 |
| Owner 约束 | 直接移除/降级 Owner 返回 409；Owner 移交后项目始终恰有一个 Owner |
| 任务范围 | 创建时版本与迭代均为空，或任一关联对象属于其他项目，返回 422/404 且不落库 |
| 工作流 | `todo → done` 等模板未允许转换返回 409；合法转换仅递增一次版本并记录审计 |
| 工时汇总 | 新增 120 分钟 Worklog 后 `actual_minutes=120`；新增 -30 分钟合法修正后为 90，原记录仍可查询 |
| Worklog 不可变 | 对 Worklog 执行 PATCH/DELETE 无接口或返回 405；数据库无覆盖更新路径 |
| 项目归档 | 对归档项目任一业务写接口返回 409，读取仍按成员权限执行 |
| 并发一致性 | 两个请求以同一资源版本更新，仅一个成功，另一个返回 412 |
| 事务原子性 | 业务写入与 Outbox/审计投递记录同事务提交；任一失败均不留下半成品 |
| 指标数据源 | 可按项目和日期范围稳定取得任务预估分钟、Worklog 实际净分钟及版本/迭代维度，汇总值与明细一致 |

### 12.4 质量与性能门槛

- 必须覆盖领域规则单元测试、PostgreSQL/Alembic 集成测试、OpenAPI 契约测试、跨项目/角色越权测试和完整 E2E 黄金链路。
- 权限策略、状态机、Worklog 修正、幂等及并发更新关键分支测试覆盖率应达到 90% 以上。
- 在总体容量基线下，普通单对象查询 P95 ≤ 500 ms、写操作 P95 ≤ 800 ms；性能验收使用生产等价 PostgreSQL 环境。
- Alembic 必须支持从当前 `0001` 正向升级；回滚策略至少在测试环境验证，不得破坏既有项目与幂等数据。

## 13. UI Design Draft（未来 Vue 3，非本轮交付）

- 项目设置：成员表格、角色选择、移除与 Owner 移交入口。
- 项目计划：版本列表与迭代列表，展示状态、日期、任务数、预估/实际工时。
- 任务页：筛选列表/看板、任务详情抽屉、版本/迭代选择、负责人、预估工时、状态动作。
- Worklog：任务详情内按日期展示不可变明细和修正链；只读角色仅见聚合。

本轮仅保证 API 能支持上述页面，不实现 Vue 组件或 BFF 聚合。

## 14. 非目标

- IAM 登录、OIDC/LDAP/AD、用户目录同步及真实 Token 校验；仅保留可信身份上下文接口。
- Vue 3 门户、移动端、通知中心和可视化统计大盘。
- 需求管理、TP 测试管理、TD 缺陷管理及其关联字段/追溯关系。
- GitLab、CI/CD、Nexus、Harbor、发布门禁集成。
- 自定义角色、自定义权限点、可视化工作流、任意脚本/SQL 动作。
- 个人绩效排名、薪酬核算、考勤或计费系统。
- 完整 metric-service；本轮仅提供可信明细及必要汇总数据源。
- 任务父子层级、依赖图、评论、附件、标签体系和全文检索（除非提升至 P1/P2 后另立范围）。

## 15. 待确认事项

1. **任务挂载规则**：沿用总体设计“至少关联迭代或版本之一”；是否允许项目级临时任务两者均不挂载？本 PRD 默认不允许。
2. **工时补录窗口**：是否限制只能补录最近 30 天，以及跨月修正是否需要审批？本 PRD 暂不设跨期限制，仅保留审计。
3. **单日工时上限**：1,440 分钟是数据完整性上限；是否另设 8/12/24 小时业务告警阈值？
4. **完成/发布强制动作**：未关闭任务情况下，Admin/Owner 是否可强制完成迭代或发布版本？本 PRD 默认允许但必须填写原因并审计。
5. **成员移除后的任务处理**：是否要求移除前强制完成批量改派？本 PRD 默认不阻塞移除，保留历史负责人并提示待改派。
6. **任务可见性**：是否存在项目内私密任务？本 PRD 默认项目成员可见全部任务，不做行级私密范围。
7. **Viewer 工时可见粒度**：本 PRD 默认仅可见聚合，不可见 Worklog 内容；需确认是否符合管理报表需要。
8. **角色来源演进**：未来 IAM 接入后，项目角色由 project-service 持有还是 IAM 持有授权主数据，需要架构确认边界与迁移方案。
9. **业务编号规则**：版本、迭代、任务编号采用项目内序列还是全局序列，需统一平台规范；技术 ID 仍使用 UUIDv7/ULID。
10. **事件交付边界**：若本轮 Outbox 尚未具备 RabbitMQ 发布能力，至少必须同事务落 Outbox；发布器可作为后续工程任务，但不得以同步直发替代。

## 16. 交付完成定义（DoD）

- P0 API、数据模型、Alembic 迁移、OpenAPI 3.1、权限策略、状态机和审计/Outbox 接口全部实现。
- “项目 → 成员/角色 → 版本/迭代 → 任务 → Worklog → 状态完成 → 工时数据校验”自动化黄金链路通过。
- 跨项目访问、角色越权、ID 注入、幂等冲突、乐观锁冲突和 Worklog 篡改测试全部通过。
- 不引入 IAM 登录、Vue 页面、需求/TP/TD 空壳功能；代码继续遵守 Feature-first、API/Service/Repository 分层。
