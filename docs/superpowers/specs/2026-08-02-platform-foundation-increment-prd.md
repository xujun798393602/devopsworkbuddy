# DevOps 平台底座增量 PRD

- 文档日期：2026-08-02
- 文档状态：待架构评审
- PRD 类型：增量 / 简洁执行版
- Project Name：`platform_foundation_increment`
- Language：中文
- Programming Language：后端 Python 3.13 + Flask + SQLAlchemy 2 + PostgreSQL + Alembic；前端 Vue 3 + TypeScript + Vite + Pinia

## 1. 原始需求与范围

在 `project-service` 已具备项目、成员/角色、版本/迭代、任务/Worklog P0，以及项目级隔离、RFC 9457、持久化幂等、审计/Outbox 基线的基础上，本轮仅交付五项**可运行骨架与核心闭环**：

1. IAM 与登录骨架；
2. Vue 3 统一门户骨架；
3. 工作流服务骨架；
4. 审计服务骨架；
5. 通知服务骨架。

身份策略为企业统一身份优先，采用 OIDC/OAuth 2.1，兼容 LDAP/AD 用户与组织同步；项目角色和细粒度业务权限由平台维护。本轮提供标准适配接口、本地开发认证和隔离的本地应急管理员，不接真实企业 IdP/LDAP。门户默认支持 `light/dark/system` 主题。不进入需求、TP、TD、GitLab、制品与发布域。

## 2. 产品目标

1. **建立安全可替换的身份入口**：完成登录、登出、Token 刷新和会话失效闭环；认证提供者可由本地开发实现平滑替换为 OIDC/LDAP 适配器，未授权请求拦截率 100%。
2. **建立可扩展的统一工作台**：用户登录后可在 Vue 门户访问首页、项目、工作流、通知和个人设置；路由、导航和操作按权限收敛，`light/dark/system` 均可用。
3. **建立跨域治理最小闭环**：工作流实例可按版本化模板启动与流转，关键行为形成追加式审计，业务事件可产生站内通知并维护偏好与已读状态；黄金链路自动化通过。

## 3. 用户角色

| 角色 | 定义 |
|---|---|
| 普通用户 | 企业目录或本地开发身份映射的平台主体，仅访问本人有权项目及个人资源 |
| 项目成员 | 沿用 `project-service` 的 Owner/Admin/Member/Viewer；其项目权限由业务服务最终判定 |
| 平台安全管理员 | 管理用户启停、平台权限与会话；默认无权查看全部项目业务数据 |
| 审计员 | 按授权范围只读查询审计，不可修改、删除或伪造记录 |
| 工作流管理员 | 管理平台级工作流模板草稿、发布与停用，不因此获得业务对象权限 |
| 本地应急管理员 | 与企业身份隔离的 break-glass 账号，仅用于身份系统故障处置，强认证、受限来源、全量审计 |
| 服务身份 | 服务间调用主体，使用独立凭据和最小权限，不具备交互式登录能力 |

## 4. 用户故事

1. As a 普通用户, I want 通过统一入口登录并安全刷新会话 so that 我能持续访问获授权的平台功能而无需频繁重新认证。
2. As a 普通用户, I want 在统一门户按权限看到项目、工作流和通知入口 so that 我能从一个工作台完成日常操作且不会看到无权功能。
3. As a 项目成员, I want 从已发布模板启动并推进工作流实例 so that 状态变化遵循一致、可追溯的规则。
4. As an 审计员, I want 按时间、主体、项目、动作和结果查询追加式审计 so that 我能调查关键变更且无法篡改证据。
5. As a 普通用户, I want 查看站内通知、标记已读并设置通知偏好 so that 我能聚焦需要处理的信息。
6. As a 本地应急管理员, I want 在企业身份不可用时通过隔离入口登录 so that 我能恢复服务且所有操作均被强化审计。

## 5. 需求池

### P0 — Must Have

#### 5.1 IAM 与会话

- 必须提供本地开发认证适配器和标准 OIDC/OAuth 2.1、LDAP/AD 同步适配接口；生产配置不得误启开发认证。
- 必须完成登录、当前主体查询、Access Token 刷新、登出、会话撤销；Token 不得写入 URL、日志或 `localStorage`。
- 必须以短期 Access Token + 可轮换 Refresh Token 实现会话；刷新时执行 refresh token rotation，旧 Token 再用须撤销该会话族。
- 必须区分认证与授权：网关验证身份，业务服务执行最终资源/项目级鉴权；平台管理员不自动获得业务数据权限。
- 必须提供本地应急管理员隔离入口；账号不得与企业身份自动合并，强制 MFA 接口、来源 IP/CIDR 白名单、凭据过期/轮换、显著应急标识和全量审计。
- 必须支持用户状态 `active/disabled/locked`；禁用或锁定后不得新建/刷新会话，已有会话须在可控时限内撤销。
- 必须为认证成功/失败、刷新、登出、撤销、应急登录和权限拒绝产生安全审计，审计中不得保存密码、验证码或 Token。

#### 5.2 Vue 3 统一门户

- 必须提供登录页、应急登录页、门户壳、首页、项目入口、工作流实例页、通知中心、个人设置、403、404 和会话失效页。
- 必须提供顶部栏、可折叠侧边导航、面包屑、用户菜单和主内容区；桌面与移动宽度下可用。
- 必须使用 Vue Router 路由守卫和 Pinia 管理主体、会话元信息、权限、主题与通知未读数；前端隐藏不代表授权，后端仍须校验。
- 必须支持 `light/dark/system`；默认 `system`，个人选择持久化，首次渲染避免明显主题闪烁。
- 必须提供统一 API 客户端、RFC 9457 错误映射、401 单次刷新与请求重放、刷新失败统一退出；并发 401 只能触发一次刷新。
- 必须提供全局加载、空态、错误态、无权态和 Toast/内联反馈基础组件。

#### 5.3 工作流服务

- 必须支持工作流模板创建草稿、查看、列表、发布、停用，以及版本不可变；仅已发布版本可启动实例。
- 必须支持实例启动、详情、列表、获取可用转换、执行显式转换；实例保存模板版本快照引用。
- 模板最小定义必须包含状态、初始状态、终态、转换、允许执行的权限点/角色、必填原因标志。
- 转换必须校验当前状态、执行权限、项目数据范围、乐观锁和幂等键；禁止客户端直接 PATCH `current_state`。
- 必须发布 `Workflow.InstanceStarted`、`Workflow.Transitioned` 事件并产生审计/Outbox；失败不得留下半完成状态。
- 必须至少内置并发布一个与现有任务状态兼容的只读系统模板：`todo → in_progress → done → closed`，含取消与重开路径；本轮不要求改造 `project-service` 由工作流服务实时驱动。

#### 5.4 审计服务

- 必须接收标准审计事件并追加保存，提供详情和条件查询；业务调用方不得更新或删除审计记录。
- 必须支持按时间范围、`trace_id`、`actor_id`、`project_id`、资源、动作、结果和来源筛选，使用游标分页和稳定排序。
- 必须记录认证/授权、IAM 管理、工作流、通知偏好及来自现有服务的关键审计事件；敏感字段按规则脱敏/拒收。
- 必须明确“不可篡改边界”：应用层 append-only、审计服务数据库独立账号、写入账号仅 INSERT、查询账号只读、无公开 UPDATE/DELETE API；P0 不宣称达到 WORM/密码学不可抵赖。
- 必须保留摄取幂等键/事件 ID，重复投递不产生重复审计；记录摄取时间与原事件发生时间。

#### 5.5 通知服务

- 必须支持站内通知列表、详情、单条已读/未读、全部已读、未读数。
- 必须支持用户级通知偏好查询和更新，最小维度为事件类别 × 站内渠道；安全类通知不得被用户关闭。
- 必须支持由领域事件或受信 API 创建通知，按 `(recipient_id, source_event_id, template_key)` 幂等去重。
- 通知必须区分通知本体与用户送达/已读状态；用户只能访问自己的通知。
- 必须提供最小通知模板键与变量渲染，变量需转义，禁止将未经处理的 HTML 直接渲染到门户。

#### 5.6 通用交付

- 所有服务必须提供 OpenAPI 3.1、Alembic 迁移、健康检查、结构化日志、Trace、RFC 9457、持久化幂等和 Outbox/消费幂等基线。
- 必须交付单元、集成、契约、权限越权和 E2E 黄金链路测试；不得用内存数据库代替 PostgreSQL 作为最终集成验收。

### P1 — Should Have

- OIDC 授权码 + PKCE 适配器的模拟提供者契约测试；LDAP/AD 用户与组织增量同步任务、停用传播和对账报告。
- 会话设备/客户端列表、单会话撤销与“退出所有设备”。
- 权限点目录查询和平台角色绑定；支持用户与组织组主体，保留 ABAC 属性接口。
- 门户项目切换器、最近访问、导航搜索、页面级错误边界和前端埋点。
- 工作流模板 JSON Schema 校验、版本对比、实例按状态/项目/发起人筛选。
- 审计详情前后差异展示、CSV 异步导出（带权限、数量限制、水印和过期下载）。
- 通知按类别筛选、批量选中已读、偏好中的免打扰时段；邮件/企业通信渠道仅提供适配接口和模拟实现。

### P2 — Nice to Have

- WebAuthn/Passkey、风险登录检测、管理员临时授权审批。
- 门户收藏、自定义首页卡片、全局命令面板。
- 工作流审批节点、多人会签、超时、待办、补偿动作和可视化编排。
- 审计哈希链、可信时间戳、对象存储不可变归档/WORM 和 SIEM 适配。
- 通知摘要、聚合、定时发送、多语言模板和跨端实时推送。

## 6. 权限矩阵

符号：✓ 允许；△ 按数据范围/附加条件允许；— 禁止。

| 操作 | 普通用户 | 项目 Owner/Admin | 平台安全管理员 | 工作流管理员 | 审计员 | 应急管理员 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| 登录/刷新/登出本人会话 | ✓ | ✓ | ✓ | ✓ | ✓ | △* |
| 查看/维护本人通知与偏好 | ✓ | ✓ | ✓ | ✓ | ✓ | △* |
| 查看本人有权项目 | △ | △ | △* | △* | △* | △* |
| 管理用户状态/平台角色/会话 | — | — | ✓ | — | — | △* |
| 创建模板草稿 | — | — | — | ✓ | — | △* |
| 发布/停用工作流模板 | — | — | — | ✓ | — | △* |
| 启动/流转项目工作流 | △ | △ | △* | △* | — | △* |
| 查询审计 | — | △* | △* | — | ✓ | △* |
| 修改/删除审计 | — | — | — | — | — | — |

限制说明：

- 所有项目数据访问仍以 `project-service` 成员关系和业务权限为最终依据；平台角色不自动扩大项目数据范围。
- 项目 Owner/Admin 仅可查询本项目授权范围内的审计摘要，且不含敏感安全字段；若 P0 不实现此视图则默认禁止。
- 应急管理员仅在企业身份故障或安全处置窗口使用，要求 MFA、来源限制、明确原因/工单号和强化审计；其能力不等于全库读权限。
- 工作流管理员可管理模板，但启动/流转业务实例仍需对应项目与对象权限。

## 7. 核心字段与状态

通用规则：技术 ID 使用 UUIDv7/ULID；API JSON 使用 `snake_case`；时间为 ISO 8601 UTC；可变聚合含从 1 起始的 `version`；跨服务仅存 ID，不建跨库外键。

### 7.1 User / Identity

| 字段 | 规则 |
|---|---|
| `id` | 平台不可变主体 ID |
| `subject` | 身份提供者内不可变主体标识；与 `identity_provider_id` 联合唯一 |
| `identity_provider_id/type` | 提供者 ID；`oidc/ldap/local_dev/break_glass` |
| `username/display_name/email` | 用户资料；邮件不得作为跨系统不可变主键 |
| `organization_unit_ids/group_ids` | 同步的组织/组引用 |
| `status` | `active/disabled/locked` |
| `last_synced_at` | 企业目录最近同步时间，可空 |
| `created_at/updated_at/version` | 服务端维护 |

状态：`active → disabled`、`active → locked`；管理员可按策略恢复至 `active`，每次转换必须审计并撤销相关会话。

### 7.2 Session / Credential

| 字段 | 规则 |
|---|---|
| `id/user_id` | 会话及所属主体 |
| `auth_method` | `oidc/local_dev/break_glass`；生产不得使用 `local_dev` |
| `refresh_token_hash/family_id` | 仅保存不可逆摘要；用于轮换与重用检测 |
| `issued_at/expires_at/last_seen_at` | 服务端维护 |
| `ip/user_agent` | 按安全与隐私策略记录/脱敏 |
| `mfa_verified_at` | 应急管理员必填 |
| `status/revoked_reason` | `active/revoked/expired` |

状态：`active → revoked|expired`，终态不可恢复。Access Token 建议 10～15 分钟；Refresh Token 生命周期与空闲超时由安全策略配置，不在代码写死。

### 7.3 WorkflowTemplate / Version

| 字段 | 规则 |
|---|---|
| `template_key/name/scope` | 稳定键、名称；范围 `system/project`，P0 以 system 为主 |
| `version_no/status` | 版本号；`draft/published/deprecated` |
| `definition` | 状态与转换的结构化 JSON，经 Schema 校验 |
| `created_by/published_by/created_at/published_at` | 服务端记录 |

状态：`draft → published → deprecated`。发布后内容不可改；变更必须复制为新草稿版本。

### 7.4 WorkflowInstance

| 字段 | 规则 |
|---|---|
| `id/project_id` | 实例 ID；项目级实例必填 `project_id` |
| `business_object_type/id` | 外部业务对象引用，不建跨库外键 |
| `template_key/template_version` | 启动时锁定，不随模板升级 |
| `current_state/status` | 当前模板状态；实例状态 `active/completed/canceled` |
| `started_by/started_at/completed_at` | 服务端维护 |
| `context` | 受限 JSON，禁止秘密与大对象，设大小上限 |
| `version` | 转换时乐观锁 |

转换记录必须追加保存 `from_state/to_state/action/actor_id/reason/occurred_at/idempotency_key`，不得覆盖历史。

### 7.5 AuditRecord

| 字段 | 规则 |
|---|---|
| `id/event_id` | 审计 ID；`event_id` 全局幂等唯一 |
| `occurred_at/ingested_at` | 业务发生时间与摄取时间 |
| `trace_id/actor_id/actor_type` | 调用链与主体 |
| `project_id` | 可空；项目级事件必填 |
| `resource_type/resource_id/action` | 被操作资源和动作 |
| `result/source` | `success/failure/denied`；来源服务/入口 |
| `before/after/reason/metadata` | 差异与必要上下文，需脱敏和限额 |
| `classification` | 数据密级/审计类别 |

AuditRecord 无更新、删除和业务生命周期状态。

### 7.6 Notification / Delivery

| 字段 | 规则 |
|---|---|
| `id/recipient_id` | 通知与收件人 |
| `source_event_id/template_key/category` | 来源事件、模板键和类别 |
| `title/body/target_url` | 渲染后安全文本及平台内白名单链接 |
| `severity` | `info/success/warning/critical` |
| `created_at/expires_at` | 服务端维护；过期不等于物理删除 |
| `status/read_at` | `unread/read/archived`；P0 UI 暂不要求归档入口 |

状态：`unread ↔ read`，可进入 `archived`；用户状态变更只影响本人 Delivery，不修改共享事件事实。

### 7.7 NotificationPreference

| 字段 | 规则 |
|---|---|
| `user_id/category/channel` | 联合唯一；P0 渠道为 `in_app` |
| `enabled` | 安全强制类别只读为 true |
| `quiet_hours/timezone` | P1；按用户时区解释 |
| `version/updated_at` | 乐观锁与更新时间 |

## 8. 登录、会话与安全规则

1. **常规登录**：门户跳转认证入口；本地开发环境可提交受控测试账号，模拟 OIDC 回调后由 IAM 建立平台会话。生产环境若检测到开发认证开启必须启动失败或健康检查失败。
2. **登出**：撤销服务端 Refresh Token 会话并清除浏览器会话材料；即使上游 IdP 登出失败，本地会话也必须失效。是否联动 IdP 单点登出列为待确认。
3. **刷新**：Access Token 过期前或 API 401 时由受控客户端刷新；每次成功刷新同时轮换 Refresh Token；旧 Token 重用触发会话族撤销与安全审计。
4. **Token 保存**：优先采用 BFF/同站 `HttpOnly + Secure + SameSite` Cookie；若架构采用浏览器持有 Token，Refresh Token 仍不得进入 Web Storage，并必须完成威胁评审。
5. **CSRF/XSS**：Cookie 会话写请求必须带 CSRF 防护；所有用户可控内容默认文本渲染并执行 CSP，禁止 `v-html` 渲染通知正文。
6. **会话失效**：禁用用户、撤销会话、Refresh Token 重用及应急账号策略不满足时禁止刷新；短期 Access Token 的即时撤销方案由架构在黑名单/版本号/短 TTL 中选择。
7. **应急管理员**：使用独立路由、独立账号命名空间和凭据存储；禁止 OIDC/LDAP 自动创建；必须 MFA、IP/CIDR 限制、强制填写原因/工单号，登录后门户持续展示应急会话警示。
8. **密码策略**：本地开发账号仅用于非生产。应急凭据采用高强度、轮换和密钥托管；P0 不自行实现通用企业密码登录体系。

## 9. 门户信息架构与 UI 草案

### 9.1 页面与导航

```text
/login                    常规登录
/emergency-login          隔离的应急登录
/app                      门户壳
  /home                   首页：欢迎、我的项目、我的待办占位、通知摘要
  /projects               有权项目列表；进入既有项目能力
  /workflows              我的/有权工作流实例列表与详情
  /notifications          通知中心
  /settings/profile       个人资料只读摘要
  /settings/appearance    light/dark/system
  /settings/notifications 通知偏好
  /admin/identity         P1 平台安全管理入口
  /admin/workflows        工作流模板管理
  /audit                  审计查询
/403 /404 /session-expired
```

主导航默认显示：首页、项目、工作流、通知；“管理”和“审计”仅在具有对应权限时显示。顶部栏包含侧栏开关、项目上下文（进入项目后）、主题快捷切换、通知未读徽标和用户菜单。移动端侧栏改为可关闭抽屉，主操作不得仅依赖悬停。

### 9.2 页面最小行为

- 登录页：单一主按钮“使用企业身份登录”（本地开发时为“开发环境登录”）；应急入口不作为醒目默认操作。
- 首页：加载失败可独立重试；无项目时给出明确空态，不展示无权数据。
- 工作流：列表展示对象、当前状态、模板版本、更新时间；详情展示转换历史与当前可执行动作。
- 审计：筛选区 + 结果表 + 详情抽屉；默认要求时间范围，敏感字段按权限隐藏。
- 通知：未读优先视觉提示但不只依赖颜色；支持单条和全部已读；目标链接仅允许平台内部安全路由。
- 设置：主题三选一；通知偏好即时保存或显式保存须全局一致，失败可恢复原值。

## 10. API 骨架与验收标准

### 10.1 建议 API 范围

```text
# IAM
POST   /api/v1/auth/login                    # 本地开发/适配入口
GET    /api/v1/auth/oidc/authorize           # 适配契约
GET    /api/v1/auth/oidc/callback            # 适配契约
POST   /api/v1/auth/refresh
POST   /api/v1/auth/logout
GET    /api/v1/me
GET    /api/v1/me/permissions
GET    /api/v1/me/sessions                   # P1
DELETE /api/v1/me/sessions/{session_id}      # P1
POST   /api/v1/emergency-auth/login

# Workflow
GET    /api/v1/workflow-templates
POST   /api/v1/workflow-templates
GET    /api/v1/workflow-templates/{template_key}/versions/{version_no}
POST   /api/v1/workflow-templates/{template_key}/versions/{version_no}/publish
POST   /api/v1/workflow-templates/{template_key}/versions/{version_no}/deprecate
GET    /api/v1/workflow-instances
POST   /api/v1/workflow-instances
GET    /api/v1/workflow-instances/{instance_id}
GET    /api/v1/workflow-instances/{instance_id}/available-transitions
POST   /api/v1/workflow-instances/{instance_id}/transitions

# Audit
POST   /internal/api/v1/audit-records         # 受信服务/事件消费者
GET    /api/v1/audit-records
GET    /api/v1/audit-records/{audit_id}

# Notification
POST   /internal/api/v1/notifications         # 受信服务/事件消费者
GET    /api/v1/me/notifications
GET    /api/v1/me/notifications/{notification_id}
POST   /api/v1/me/notifications/{notification_id}/read
POST   /api/v1/me/notifications/{notification_id}/unread
POST   /api/v1/me/notifications/read-all
GET    /api/v1/me/notifications/unread-count
GET    /api/v1/me/notification-preferences
PUT    /api/v1/me/notification-preferences
```

### 10.2 通用 API 验收

1. 所有写接口支持 `Idempotency-Key`；同主体、同键、同规范化请求重放不重复写库/审计/事件，不同请求返回 `409 IDEMPOTENCY_KEY_CONFLICT`。
2. 可变聚合更新/转换使用 `If-Match` 或 `version`；冲突返回 `412 VERSION_CONFLICT`。
3. 错误体符合 RFC 9457；校验 422、认证失败 401、权限不足 403、不可见资源 404、状态冲突 409。
4. 成功响应包含 `data` 和 `meta.trace_id` 并回传 `X-Trace-Id`；列表使用游标分页，默认 50、最大 200。
5. OpenAPI 3.1 覆盖请求、响应、权限、枚举、错误码和示例，并生成/校验 TypeScript 客户端。
6. 服务间接口必须认证并限制调用方权限；不得因使用 `/internal` 路径而默认可信。

### 10.3 关键 API 场景验收

| 场景 | 可验收结果 |
|---|---|
| 登录闭环 | 有效开发身份可登录并访问 `/me`；无效凭据返回统一 401，响应与日志不泄露凭据 |
| 刷新轮换 | 刷新成功后旧 Refresh Token 立即失效；重用旧 Token 撤销会话族并产生安全审计 |
| 登出 | 登出后 Refresh Token 不可再用；重复登出幂等成功，不重复产生副作用 |
| 用户禁用 | 用户被禁用后无法登录或刷新；已有会话在约定窗口内失效 |
| 应急登录 | 非白名单来源、未通过 MFA 或无原因/工单号均失败；成功操作全量标记 `break_glass=true` |
| 模板不可变 | 已发布模板无法 PATCH；变更只能创建新版本，旧实例仍引用旧版本 |
| 工作流并发 | 两请求以同一实例版本流转，仅一个成功，另一个返回 412；非法转换返回 409 |
| 工作流越权 | 无项目访问权或无转换权限的主体不可启动/流转实例，且无状态变化 |
| 审计追加 | 公开 API 无 UPDATE/DELETE；数据库写入角色不能修改/删除既有记录；重复事件仅一条记录 |
| 审计隔离 | 无审计权限用户查询返回 403；项目范围查询不会返回其他项目记录 |
| 通知隔离 | 用户 A 以任意 ID 读取或改写用户 B 通知均返回 404，B 状态不变 |
| 通知去重 | 同来源事件、收件人和模板重复消费只产生一条 Delivery |
| 偏好生效 | 关闭可选类别后不生成后续站内 Delivery；安全强制类别不可关闭并返回明确校验错误 |

## 11. UI 验收标准

1. 未登录访问 `/app/**` 必须进入登录流程；登录后返回原安全路由，外部任意 URL 不得作为重定向目标。
2. 401 并发请求只触发一次 Token 刷新；成功后各请求最多自动重放一次；失败后清理会话并进入会话失效页，不形成刷新循环。
3. 用户只看到有权导航和动作；直接输入无权路由显示 403 或安全 404，且后端请求仍被拒绝。
4. `light/dark/system` 可即时切换；刷新后保留选择；`system` 随操作系统偏好变化；登录页与门户均适配三种模式。
5. 工作流合法动作执行后，实例状态、版本和历史同步更新；冲突时提示刷新最新状态，不误报成功。
6. 通知中心显示稳定分页、未读数、单条/全部已读；已读操作失败时 UI 不永久保留错误乐观状态。
7. 审计筛选可组合时间、主体、项目、动作和结果；空结果、无权限、加载失败表现不同且可理解。
8. 在 360 px、768 px、1280 px 典型宽度下无关键内容横向溢出；数据表在窄屏可滚动或转为卡片，不裁掉主要操作。

## 12. 可访问性、主题与响应式要求

- P0 以 WCAG 2.2 AA 为目标：文本/背景对比度至少 4.5:1，大文本至少 3:1；焦点指示清晰且不被遮挡。
- 所有功能可用键盘完成；导航、对话框、菜单和 Toast 使用正确语义/ARIA；打开对话框后焦点进入，关闭后返回触发点。
- 表单控件必须有程序化标签、必填/错误说明；错误不得只用颜色表达。通知未读状态同时使用文字或图标语义。
- 支持浏览器缩放 200% 后核心任务可完成；尊重 `prefers-reduced-motion`，非必要动画可关闭。
- 主题使用语义化 Design Token，不允许业务组件硬编码只适配亮色的颜色；三种主题需通过视觉回归与对比度检查。
- 桌面采用固定/可折叠侧栏，平板与手机采用抽屉；触控目标建议不小于 44×44 CSS px。
- 页面标题层级、Landmark、跳至主内容链接和动态页面标题必须正确；异步结果使用不过度打扰的 live region。

## 13. 非功能与交付门槛

- 容量沿用平台注册用户 5000、峰值在线 1500；普通查询 P95 ≤ 500 ms、写操作 P95 ≤ 800 ms，审计/通知正常事件可见延迟 P95 ≤ 5 秒。
- 登录与刷新接口必须具备按账号、IP/来源和客户端维度限流；错误信息不得支持账号枚举。
- 关键安全/权限/状态机/幂等分支测试覆盖率应达到 90% 以上；前端必须有 Vitest 组件/Store 测试和 Playwright 黄金链路。
- 数据库账号按服务和读写职责隔离；秘密来自外部 Secret 配置，不进入仓库、镜像和前端产物。
- 各服务提供存活/就绪检查；依赖不可用时就绪失败但进程不应反复破坏数据。
- Alembic 支持从空库正向升级；审计数据迁移不得通过常规回滚删除既有记录。

## 14. 端到端黄金链路

```text
开发用户登录
→ 获取本人主体与权限
→ 进入 Vue 门户并看到本人项目
→ 从已发布模板启动一个项目工作流实例
→ 执行一次合法状态转换
→ audit-service 查询到登录、启动与转换记录
→ notification-service 生成本人站内通知
→ 门户未读数增加并可标记已读
→ 修改通知偏好和 light/dark/system 主题
→ 登出后刷新令牌不可再用
```

自动化测试还必须覆盖：跨项目工作流越权、重复事件去重、并发转换、Refresh Token 重用、应急登录拒绝与强化审计。

## 15. 非目标

- 真实企业 IdP、LDAP/AD 服务器连接、生产级目录迁移与组织主数据治理；本轮只实现标准接口、模拟契约和本地开发认证。
- 需求、TP、TD、GitLab、CI/CD、Nexus、Harbor、制品、发布与门禁功能或空壳页面。
- 自研通用身份提供者、企业密码找回、短信/邮件 MFA 服务；应急 MFA 可通过标准适配接口或开发模拟完成。
- 项目自定义角色/权限点可视化编辑器、复杂 ABAC 策略语言和跨企业多租户。
- 可视化工作流编排、脚本/SQL 动作、审批会签、定时器、补偿和跨服务 Saga 编排。
- 邮件、短信、企业微信等真实渠道投递；仅保留适配接口和模拟实现。
- 审计记录的密码学签名、哈希链、WORM 合规存储、SIEM 全量集成和无限期在线查询。
- 统一搜索、指标驾驶舱、移动原生应用与离线模式。
- 本轮不强制将 `project-service` 既有任务状态机迁移为对 `workflow-service` 的同步依赖；只保证模板语义兼容和未来集成契约。

## 16. 待确认问题

1. **门户会话形态**：是否确定由 Gateway/BFF 使用同站 HttpOnly Cookie，还是 SPA 直接持有短期 Access Token？本 PRD 推荐前者。
2. **上游单点登出**：平台登出是否必须同时触发 OIDC RP-Initiated Logout；上游失败时的平台提示与重试策略需确认。
3. **Token 时限**：Access Token、Refresh Token 绝对时限和空闲时限，以及用户禁用后 Access Token 最大残留有效窗口需安全团队确认。
4. **应急 MFA 实现**：一期采用 TOTP、WebAuthn 还是外部 MFA 适配？密钥托管、恢复码和双人领用流程需确认；不得因未确认而退化为单因素生产账号。
5. **应急网络边界**：允许的 IP/CIDR、VPN/堡垒机要求及工单号校验来源需运维确认。
6. **IAM 与 project-service 边界**：项目角色主数据继续由 `project-service` 持有；IAM 只提供平台权限点/主体上下文，这一边界需架构确认。
7. **工作流一期所有权**：工作流服务 P0 是仅验证独立实例，还是需要 `project-service` 任务流转同步接入？本 PRD 默认不改造既有任务写路径。
8. **模板管理范围**：P0 是否仅允许系统模板，还是允许项目管理员复制系统模板为项目版本？本 PRD 默认仅工作流管理员管理系统模板。
9. **审计保留期与可见范围**：在线保留期、归档期、项目 Owner 可查询的字段集合及安全审计的访问审批需合规确认。
10. **审计不可篡改等级**：P0 明确为应用与数据库权限层 append-only；何时升级哈希链/WORM/可信时间戳需确定合规里程碑。
11. **通知偏好默认值**：各事件类别默认开启策略、安全强制类别清单及通知过期/归档期限需产品与安全确认。
12. **实时通知方式**：P0 采用轮询还是 SSE/WebSocket？本 PRD 默认轮询未读数，实时推送列 P1/P2。
13. **前端组件体系**：总体技术栈未指定组件库和 CSS 方案；需在架构阶段确认，避免同时引入相互重叠的 UI/CSS 框架。
14. **组织同步删除语义**：目录用户消失时立即禁用还是宽限期禁用，以及重命名/调组冲突处理需后续企业接入方案确认。

## 17. 交付完成定义（DoD）

- 五项 P0 骨架均可独立启动，数据库迁移、OpenAPI、健康检查、配置示例和测试齐备。
- Vue 门户完成登录—导航—工作流—审计（有权角色）—通知—主题—登出页面闭环，`light/dark/system` 全部可验收。
- 本地开发认证可支持自动化测试，但生产配置可证明无法误启；应急管理员具备隔离、强认证接口、来源限制和强化审计。
- 工作流发布版本不可变、实例转换具备幂等与乐观锁；审计应用/数据库权限层不可修改删除；通知具备隔离、去重、偏好和已读状态。
- API/UI/权限/可访问性/响应式关键验收全部自动化或形成可重复验证脚本；黄金链路通过。
- 不引入需求、TP、TD、GitLab/发布域，不以空壳页面或伪集成扩大本轮范围。
