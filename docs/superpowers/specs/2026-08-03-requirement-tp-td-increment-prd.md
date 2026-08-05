# 需求、TP 测试与 TD 缺陷管理增量 PRD

- 文档日期：2026-08-03
- 文档状态：待架构评审
- PRD 类型：增量 / P0 裁决版
- Project Name：`requirement_tp_td_increment`
- Language：中文
- Programming Language：后端 Python 3.12/3.13 + Flask + SQLAlchemy 2 + PostgreSQL + Alembic（3.12 调试、3.13 生产默认）；前端 Vue 3 + TypeScript + Vite + Pinia + Vuetify 3
- 上游基线：公司级 DevOps 总体设计、平台底座 PRD/架构、project-service 协作 PRD/架构及当前 OpenAPI/事件/门户代码

## 1. 原始需求、范围与默认裁决

本轮在项目、成员角色、版本、迭代、任务、Worklog、IAM、工作流、审计、通知和 Vue 门户底座之上，增量交付：

1. `requirement-service`：需求分层、评审、基线、变更和验收标准；
2. `tp-service`：完整测试管理域的 P0 核心闭环，包括测试资产生产链、用例库、计划、执行、环境、报告及自动化治理接口；
3. `td-service`：Bug 提交、分派、修复、验证、关闭、重开和质量字段；
4. 三域与项目、版本、迭代、任务、Worklog、工作流、审计、通知的双向追溯；
5. Vue 门户对应 P0 页面。

不逐项等待确认，P0 采用以下裁决：

- 需求层级固定为 `epic → feature → user_story → fr|nfr|ac`；`ac` 是可独立编号、可追溯的验收标准型需求，普通需求同时可有结构化验收条目。
- 需求评审采用内置状态机和人工结论；工作流服务保存可选治理实例/通知，不把三域核心写路径改造成跨服务强事务。
- 基线是已批准需求版本集合的不可变快照；基线后正文、验收标准、父子、版本/迭代范围变化必须走变更申请，批准后生成新需求版本和新基线版本。
- TP 所有 AI 输出均为草稿，人工门禁不可跳过；AI 模型网关、XMind 处理器为可替换端口，P0 使用确定性受控 Mock，禁止伪称真实 AI 能力。
- P0 自动化仅治理资产、套件、计划、任务和结果摄取；不触发真实 GitLab Runner。摄取支持受信 Mock/JUnit XML/受限 JSON，Allure 原始包和真实 CI 触发为 P1。
- TD 的“已修复”进入“待验证”前，P0 因 GitLab 尚未交付，接受 `fix_evidence` 占位（外部类型、引用、摘要、修复版本）；真实已合并 MR 校验在 GitLab 增量替换该端口后生效。
- 统一追溯采用各服务私有 `traceability_links` + 领域事件构建的只读投影；关系创建由“关系拥有方”服务校验本域端点并通过端口校验远端存在/项目一致，绝不共享数据库或建跨库外键。
- 前端延续同站 BFF、HttpOnly Cookie、Vuetify 3、`light/dark/system`、WCAG 2.2 AA 与响应式基线。

## 2. 产品目标与成功标准

1. **建立受控需求事实源**：100% 已基线需求具有不可变版本快照、评审证据和变更链；跨项目越权拦截率 100%。
2. **跑通可信测试资产生产与执行闭环**：可自动化完成“选择需求 → 分析 → XMind 设计 → XMind 用例 → 人工门禁 → 导入用例库 → 计划/执行/报告”，正式用例被 AI 静默覆盖为 0 次。
3. **形成端到端质量追溯**：P0 黄金链中任一需求、用例、执行或缺陷均能在统一视图查询正反向链路；事件投影正常延迟 P95 ≤ 5 秒，缺失/过期关系有明确标识。

## 3. 用户角色

| 角色 | 说明 |
|---|---|
| Owner | 项目最高业务管理者；管理范围、基线、质量例外和全部三域对象 |
| Admin | 项目管理员；除 Owner 专属例外审批外管理三域对象 |
| Member | 项目执行成员；创建/编辑授权对象、参与评审、执行测试、处理本人缺陷 |
| Viewer | 项目只读成员；只读查看非敏感业务信息与追溯 |
| 需求负责人/评审人 | Member 之上的对象关系；负责需求内容或提交评审结论，不是新增项目角色 |
| 测试负责人/测试人员 | 计划、设计会话、执行任务的负责人/参与人；须为有效非 Viewer 成员 |
| 缺陷处理人/验证人 | 负责修复和验证；须为有效非 Viewer 成员且受状态动作限制 |
| 服务身份 | BFF、事件消费者、Mock AI/XMind/自动化结果摄取调用方；最小 scope、不可交互登录 |

## 4. 用户故事

1. As a 产品负责人, I want 分层编写需求并经评审形成不可变基线 so that 开发与测试使用同一批准范围。
2. As a 测试负责人, I want 从需求快照经 AI 草稿和人工门禁生成 XMind 设计及用例并导入指定文件夹 so that 测试资产生产高效且可审计。
3. As a 测试人员, I want 建立计划、执行用例、记录证据并生成报告 so that 版本质量状态可判断。
4. As a 开发/测试成员, I want 提交并流转 Bug，关联需求、用例、执行、任务和修复证据 so that 缺陷闭环可验证。
5. As a 项目成员, I want 从任一对象查看需求到发布占位的正反向链路 so that 我能快速判断影响、覆盖与阻塞。
6. As a 管理者, I want 接收评审、变更、执行失败、SLA 和重开通知 so that 风险及时处置。

## 5. 需求池

### 5.1 P0 — Must Have

#### requirement-service

- 需求 CRUD、层级、类型、来源、优先级、负责人、版本/迭代归属、验收条目、标签和附件引用。
- 需求版本不可变；显式提交评审、批准、驳回、激活、完成、取消、重开。
- 评审轮次、评审人结论和意见；批准前至少 1 名非提交人批准，Owner/Admin 可配置评审人但不可伪造结论。
- 基线创建、详情、范围校验和不可变快照；变更申请、影响说明、批准/拒绝、应用并生成新版本。
- 父子关系校验：同项目、合法层级、无环、单一直接父节点；需求关联项目版本/迭代和 project-service 任务/发布占位。
- 基线变化发布事件，使关联测试设计和用例投影标记 `needs_impact_review`。

#### tp-service

- 测试库根、文件夹树、移动/归档；项目内文件夹同父名称唯一且禁止循环移动。
- 测试用例创建、版本化、步骤/预期、前置条件、优先级、类型、状态、需求追溯；正式版本不可覆盖。
- 测试设计会话完整链：选择需求及版本快照 → 需求分析草稿 → 人工批准 → 测试设计 XMind 草稿 → 人工批准 → 测试用例 XMind 草稿 → 校验/人工批准 → 选择目标文件夹及冲突策略 → 导入正式用例。
- 每阶段保存模型/提示词/适配器版本、输入 hash/快照引用、参数摘要、输出版本、耗时、评审人/意见/结论；Mock 结果明确标记 `provider=mock`。
- XMind 端口支持受控 `.xmind` 导入/导出、解析节点、节点—用例映射；P0 Mock 生成确定性安全文件，不实现任意宏/外链。
- 测试计划关联项目版本、迭代（可空）、需求范围、用例版本、环境、负责人、准入/准出标准；计划冻结后范围形成快照。
- 测试执行按计划轮次产生用例运行项，结果 `passed/failed/blocked/skipped`；记录执行人、时间、实际结果、证据附件引用；失败可显式创建/关联 TD。
- 环境记录名称、类型、版本、配置摘要和密级；不得保存明文密码/Token/Secret。
- 报告以冻结快照生成，至少给出总数、通过/失败/阻塞/未执行、通过率、需求覆盖和关联未关闭缺陷。
- 自动化资产/套件/计划/任务治理；P0 提供任务创建和 Mock 结果摄取接口，支持 JUnit XML 与受限 JSON，结果映射到用例版本/运行项；重复摄取幂等。

#### td-service

- 缺陷提交、列表、详情、基础字段修改；分派、开始处理、拒绝、标记修复、提交验证、验证关闭、验证失败重开、手工重开、重复关闭均走显式动作。
- 字段覆盖严重性、优先级、类型、标题/描述、复现步骤、预期/实际、环境、影响/发现/修复版本、发现阶段、引入阶段、根因、负责人、报告人、验证人、SLA 及附件引用。
- 关联需求、用例版本、测试执行/运行项、project-service 任务、修复证据；所有关联必须同项目。
- 重复缺陷必须指向同项目非自身主缺陷，不得成环；重复关闭保留原记录和反向关系。
- SLA 保存策略快照、响应/解决截止时间、暂停累计、首次响应/解决时间和 breach 状态；P0 只提示与通知，不自动处分。
- 已修复进入待验证必须有修复版本和 fix evidence；关闭必须有验证环境、结论和证据；重开计数达到 2 次通知 Owner/Admin。

#### 跨域、门户和通用

- 统一链路：需求 → 任务 → `code_change` 占位 → 测试设计 → 用例 → 执行 → 缺陷 → 修复/验证 → 版本 → `release` 占位，支持反向查询。
- 三服务私有 PostgreSQL、独立账号/迁移；跨域只存稳定引用和来源版本，无共享表、跨服务 ORM/FK。
- 所有写 API 强制 `Idempotency-Key`；可变聚合 PATCH/动作强制 `If-Match`；RFC 9457；游标分页；OpenAPI 3.1。
- 所有成功关键变更与 Outbox 同本地事务；消费按 `(consumer_name,event_id)` 幂等；RabbitMQ 契约兼容现有 envelope。
- 项目级隔离和 Owner/Admin/Member/Viewer 最终授权；门户导航/动作只做 UX 收敛，后端仍最终授权。
- 交付第 14 节全部 Vue P0 页面、统一追溯视图、主题/响应式/WCAG 验收。

### 5.2 P1 — Should Have

- 需求批量导入/导出、评论/提及、基线差异与可视化影响分析、项目级可配置评审人数。
- TP 参数化用例、共享步骤、数据集、用例批量编辑、计划复制、Allure 包摄取、真实 XMind 适配器、真实 AI 网关沙箱接入。
- GitLab CI/CD 触发和专用 Runner 状态同步、API/Web UI/Android/Android TV 执行适配器；失败重试策略与定时计划。
- TD SLA 工作日历/暂停规则、批量流转、相似缺陷建议、质量趋势与根因分析面板。
- 追溯完整性门禁 API、异步 CSV/XMind 导出审批、水印/过期下载、搜索索引。

### 5.3 P2 — Nice to Have

- 可配置需求类型/状态/字段、电子签名审批、跨项目需求依赖。
- AI 多模型对比、知识库检索、覆盖率智能评价、自愈测试建议。
- 测试实验室/设备池、容量排期、实时协作设计、性能与安全专项模型。
- 缺陷聚类预测、逃逸风险预测、自动根因推荐。

## 6. 核心对象、字段与状态

通用：技术 ID 为 UUID；业务号建议 `REQ/TPD/TC/TP/TE/TD-{sequence}`；`project_id` 必填；时间 ISO 8601 UTC；日期 `YYYY-MM-DD`；可变对象 `version≥1`；正文默认纯文本/受控 Markdown，单字段上限 20,000 字符。

### 6.1 Requirement

| 字段 | P0 规则 |
|---|---|
| `business_no/title/description` | 项目内业务号唯一；标题 1~200；描述 ≤20,000 |
| `type` | `epic/feature/user_story/fr/nfr/ac` |
| `source` | `customer/market/internal/compliance/operation/technical/other` |
| `priority` | `p0/p1/p2/p3`，默认 p2 |
| `status` | 只读，见状态机 |
| `owner_id` | 有效 Owner/Admin/Member |
| `parent_id` | 合法层级、同项目、无环；Epic 为空 |
| `release_version_id/iteration_id` | 至少版本必填；迭代可空；均属同项目 |
| `acceptance_criteria` | 1~100 条 `{id,given,when,then,notes}`；提交评审至少 1 条（Epic 可豁免） |
| `current_revision` | 最新不可变 RequirementRevision 号 |
| `baseline_status` | `unbaselined/baselined/change_pending` 投影值 |
| `tags/attachment_refs` | 标签 ≤20；附件仅 MinIO 引用与安全元数据 |

Requirement 状态：

```text
draft → in_review → approved → active → completed
  ↑       └→ rejected → draft       └→ canceled
  └──────── approved/active 经变更申请生成新 revision，不回写旧版本
completed → active（Owner/Admin 带原因重开）
```

- `draft→in_review`：范围/负责人/版本/AC 校验通过。
- `in_review→approved`：至少一名指定、非提交人评审批准且无未解决拒绝结论。
- `approved→active`：已纳入有效基线；`active→completed`：关联 P0 任务完成且 AC 有验收结论或 Owner/Admin 明示豁免理由。

### 6.2 RequirementReview / Baseline / ChangeRequest

- Review：`round_no,status(open/approved/rejected/canceled),reviewer_ids,decisions,submitted_by/at,closed_at,version`；每位评审人每轮一条最新结论，历史追加保留。
- Baseline：`name,baseline_no,status(draft/active/superseded),release_version_id,requirement_revision_refs,created_by/approved_by/at`；激活后集合和快照不可变，新基线 supersede 旧基线。
- ChangeRequest：`reason,urgency(low/medium/high/emergency),impact_summary,proposed_patch,affected_refs,status(draft/in_review/approved/rejected/applied/canceled),review evidence`；`approved→applied` 原子生成新 revision，本地事务不跨服务修改远端资产。

### 6.3 TestFolder / TestCase

- TestFolder：`id,project_id,parent_id,name,path,status(active/archived),version`；同父规范化名称唯一，归档文件夹只读。
- TestCase：`business_no,folder_id,title,type(functional/api/ui/android/android_tv/other),priority,status(draft/active/deprecated),owner_id,current_case_version,requirement_refs,automation_mode(manual/automated/candidate),version`。
- TestCaseVersion 不可变：`preconditions,steps[{sequence,action,expected,test_data}],postconditions,source(design/manual/import/automation),source_design_node_ref,created_by/at`；激活新版本不会篡改计划/执行已冻结版本。
- 用例状态：`draft→active→deprecated`；deprecated 可读、不可加入新计划。

### 6.4 TestDesignSession / StageRun / ImportBatch

- Session：`business_no,requirement_snapshot_refs,target_folder_id,status,created_by,version`。
- 状态：`draft → analyzing → analysis_review → designing → design_review → generating_cases → cases_review → ready_to_import → imported`；任一异步阶段可 `failed→上一人工可恢复状态`；未 imported 可取消。
- 每一门禁只能由有效非 Viewer 人工执行；生成者允许评审，但 P0 对 Owner/Admin 之外默认要求另一名成员评审。
- StageRun：`stage,attempt,input_snapshot_ref/input_hash,adapter_key,provider,model,model_version,prompt_key/prompt_version,parameters,output_ref/output_hash,result_version,status,started/finished_at,usage_summary,error_code`。
- ReviewGate：`stage_run_id,decision(approved/changes_requested/rejected),reviewer_id,comments,created_at`，追加式。
- ImportBatch：`source_case_xmind_version,target_folder_id,conflict_strategy(create_new/update_if_same_source/skip),validation_summary,mappings,status`；人工编辑后的 active 用例只有显式 `update_if_same_source` + 再评审才可新建版本，绝不覆盖。

### 6.5 TestPlan / Execution / Environment / Report

- TestPlan：`business_no,name,release_version_id,iteration_id,requirement_snapshot_refs,case_version_refs,environment_ids,owner_id,entry_criteria,exit_criteria,status,scope_frozen_at,version`。
- 状态：`draft→ready→in_progress→completed→closed`；`draft|ready|in_progress→canceled`；ready 时冻结范围；in_progress 后变更须创建新轮次而非改历史。
- TestExecution：`plan_id,round_no,status(not_started/in_progress/completed/canceled),started/finished_by/at,version`。
- CaseRun：`case_version_ref,assignee_id,status(not_run/running/passed/failed/blocked/skipped),actual_result,evidence_refs,executed_at,linked_defect_refs,version`；仅 `not_run→running→终态`，终态更正须追加 rerun attempt。
- TestEnvironment：`name,type(dev/test/staging/device_lab/other),status(active/inactive),version_summary,configuration_summary,classification,secret_ref_count,version`；禁止秘密正文。
- TestReport：`plan/execution snapshot,metrics,coverage,open_defect_summary,generated_by/at,revision,status(draft/published)`；published 不可变。

### 6.6 AutomationAsset / Task / Result

- Asset：`name,type(api/web_ui/android/android_tv/other),repository_ref,path_ref,framework,owner_id,status(active/deprecated),version`；P0 repository_ref 可为占位，不验证 GitLab。
- Suite/Plan：引用 asset 与 case version；保存环境和受限参数 schema，不存秘密。
- AutomationTask：`trigger_source(manual/mock/external),suite/plan_ref,status(queued/running/succeeded/failed/canceled),external_run_ref,requested_by,timestamps,version`。
- ResultIngestion：`source,external_run_ref,format(junit_xml/json),payload_hash,received_at,mapping_summary,status`；相同来源+运行引用+hash 幂等，相同运行不同 hash 返回 409。

### 6.7 Defect

| 字段 | P0 规则 |
|---|---|
| `business_no/title/description` | 标题 1~200；描述 ≤20,000 |
| `severity` | `blocker/critical/major/minor/trivial` |
| `priority` | `p0/p1/p2/p3` |
| `defect_type` | `functional/performance/security/compatibility/usability/data/configuration/other` |
| `status` | 只读，见状态机 |
| `reporter_id/assignee_id/verifier_id` | 有效项目成员；assignee/verifier 不可为 Viewer |
| `reproduction_steps` | 1~50 个有序步骤；blocker/critical 提交时必填 |
| `expected_result/actual_result` | 提交必填 |
| `environment_ref/snapshot` | TP 环境引用或受控快照 |
| `affected/found/fix_version_id` | 同项目；进入待验证 fix_version 必填 |
| `requirement/test_case_version/execution/case_run/task refs` | 稳定跨域引用，可多值但设上限 100 |
| `root_cause/introduction_stage/discovery_stage` | 关闭前 root_cause 必填（重复/拒绝除外） |
| `fix_evidence` | `{type:mr|commit|patch|other,external_ref,summary}`；P0 可 mock |
| `duplicate_of_id` | 同项目主缺陷；无环 |
| `reopen_count` | 服务端递增 |
| SLA 字段 | `policy_key/version,response_due_at,resolution_due_at,first_responded_at,resolved_at,paused_seconds,response/resolution_breached` |

TD 状态机：

```text
new → assigned → in_progress → fixed → pending_verification → closed
  └→ rejected                       └→ reopened → assigned
new|assigned|in_progress → duplicate → closed
pending_verification → reopened
closed → reopened（Owner/Admin/原验证人，带原因）
```

- `new→assigned` 需 assignee；`assigned→in_progress` 由 assignee 或 Owner/Admin。
- `in_progress→fixed` 需修复摘要、fix evidence、fix version；`fixed→pending_verification` 指定 verifier。
- `pending_verification→closed` 需验证通过、环境、证据、root cause；验证失败走 reopened。
- rejected/duplicate 必须有原因；duplicate 指向主缺陷。所有终态保留且不物理删除。

## 7. 权限矩阵

符号：✓ 允许；△ 条件允许；— 禁止。对象级关系、项目归档和状态机可进一步收窄。

| 操作 | Owner | Admin | Member | Viewer |
|---|:---:|:---:|:---:|:---:|
| 查看三域对象与追溯 | ✓ | ✓ | ✓ | ✓* |
| 创建/编辑草稿需求 | ✓ | ✓ | ✓ | — |
| 配置评审人/批准需求 | ✓ | ✓ | △* | — |
| 激活基线/批准变更 | ✓ | △* | — | — |
| 创建/编辑文件夹、用例 | ✓ | ✓ | ✓ | — |
| 发起设计会话/运行 Mock 阶段 | ✓ | ✓ | ✓ | — |
| 人工门禁批准 | ✓ | ✓ | △* | — |
| 导入正式用例 | ✓ | ✓ | △* | — |
| 管理计划/环境/自动化治理 | ✓ | ✓ | △* | — |
| 执行获分配用例 | ✓ | ✓ | △* | — |
| 发布测试报告 | ✓ | ✓ | △*（计划负责人） | — |
| 提交缺陷 | ✓ | ✓ | ✓ | — |
| 分派/拒绝/重复关闭 | ✓ | ✓ | — | — |
| 修复/提交验证 | ✓ | ✓ | △*（assignee） | — |
| 验证关闭/验证失败 | ✓ | ✓ | △*（verifier） | — |
| 手工重开已关闭缺陷 | ✓ | ✓ | △*（原验证人/报告人） | — |
| 删除正式资产/历史 | — | — | — | — |

限制：Viewer 不读取 AI 提示词正文、内部评审敏感意见、环境敏感配置或附件下载 URL；Member 不得自批自己提交的需求评审或默认 AI 门禁，除非另有一名批准人；Admin 可批准普通基线，Owner 专属批准紧急变更和质量例外。

## 8. 核心业务规则

1. 所有对象路径 `project_id`、对象项目、当前有效成员关系必须一致；非成员/跨项目引用统一 404，成员角色不足 403。
2. 项目归档后三服务只读；运行中异步任务可完成并落审计，但不得自动写入正式资产。
3. 需求、用例、报告、基线、设计输出均采用版本/快照；历史执行永远引用当时版本。
4. 基线变更不直接修改 TP；发布 `Requirement.BaselineChanged` 后 TP 将相关会话、用例、计划范围投影标记待影响评估，由人工确认更新。
5. AI/XMind 阶段异步受理目标 ≤2 秒；输出只能进入草稿区。任何适配器失败不得绕过人工门禁或降级到未获准模型。
6. 导入前必须通过结构、必填、最大节点数、重复、追溯完整性校验；部分失败默认整体不导入。单批最多 1,000 用例/10,000 节点/50 MiB `.xmind`。
7. 附件单文件默认 100 MiB、每对象 50 个；通过 MinIO 预签名上传、MIME/扩展/恶意内容扫描，未通过扫描不可下载或参与处理。
8. 计划 ready 后冻结 case version；用例更新不静默改变计划。需要新版本时复制计划范围或新增轮次。
9. CaseRun 失败不自动创建 TD；用户确认后显式创建，保证标题、严重性、复现与关联完整。
10. TD SLA 默认策略：blocker 15 分钟响应/8 小时解决，critical 1 小时/24 小时，major 4 小时/72 小时，minor 1 工作日/10 工作日，trivial 2/20 工作日；P0 按 UTC 连续时间计算，工作日历 P1。rejected/duplicate/closed 停止计时，pending_verification 不暂停解决计时直至 closed。
11. 统一追溯 link 类型白名单，禁止任意类型和循环爆炸；查询默认深度 4、最大深度 8、节点 500，超过返回截断标识。
12. 远端校验不可用时，创建强关联失败关闭 `503 DEPENDENCY_UNAVAILABLE`；事件投影可保持 last-known 数据并显示 `stale_at`，不得把投影当授权依据。

## 9. 跨域追溯模型

### 9.1 TraceabilityLink

`id,project_id,source{service,type,id,version},target{service,type,id,version},link_type,origin(manual/system/import/event),status(active/superseded/broken),created_by/at,verified_at,metadata,version`。

允许的 P0 关系：

- `requirement parent_of requirement`
- `requirement implemented_by task`
- `task evidenced_by code_change`（占位引用）
- `requirement analyzed_by test_design_session`
- `requirement covered_by test_case_version`
- `test_case_version included_in test_plan|executed_as case_run`
- `case_run found defect`
- `defect affects requirement|detected_by case_run|fixed_by task|fixed_by code_change|verified_by case_run`
- `requirement|task|test_plan|defect targeted_to version`
- `version released_by release`（占位引用）

每个领域服务只拥有从本域聚合发出的权威关系；BFF/traceability query projection 合并三服务与 project-service 事件。关系删除采用 supersede，不物理删除。

### 9.2 完整性判定

- 已基线 active/completed 需求至少关联 1 个任务、1 个 active 用例版本；NFR 可由 Owner/Admin 记录“无需用例”例外。
- ready 测试计划内每个需求至少 1 个用例；每个用例版本必须可追到需求或注明 exploratory。
- failed CaseRun 若未关联 TD，报告显示“待确认失败”；blocker/critical 失败关闭计划前必须关联缺陷或有 Owner 例外。
- closed TD 必须可追到验证 CaseRun 或人工验证证据、修复版本和修复证据。
- P0 提供查询/提示，不阻塞 project-service 版本发布；正式发布门禁在发布域增量实现。

## 10. API 清单与验收

通用前缀 `/api/v1/projects/{project_id}`；GET 列表游标默认 50、最大 200。以下写接口均要求 Idempotency-Key；PATCH/transition/gate/review 等可变聚合动作要求 If-Match。

### 10.1 Requirement API

```text
GET/POST   /requirements
GET/PATCH  /requirements/{requirement_id}
GET        /requirements/{id}/revisions
POST       /requirements/{id}/transitions
POST       /requirements/{id}/reviews
POST       /requirements/{id}/reviews/{review_id}/decisions
GET/POST   /requirement-baselines
GET        /requirement-baselines/{baseline_id}
POST       /requirement-baselines/{id}/activate
GET/POST   /requirements/{id}/change-requests
POST       /requirements/{id}/change-requests/{cr_id}/transitions
GET/POST   /requirements/{id}/traceability-links
```

### 10.2 TP API

```text
GET/POST   /test-folders
GET/PATCH  /test-folders/{folder_id}
POST       /test-folders/{folder_id}/move
GET/POST   /test-cases
GET/PATCH  /test-cases/{case_id}
GET        /test-cases/{case_id}/versions
POST       /test-cases/{case_id}/versions
POST       /test-cases/{case_id}/transitions
GET/POST   /test-design-sessions
GET        /test-design-sessions/{session_id}
POST       /test-design-sessions/{id}/stage-runs
POST       /test-design-sessions/{id}/stage-runs/{run_id}/review-gates
POST       /test-design-sessions/{id}/imports
GET        /test-design-sessions/{id}/exports/{artifact_id}
GET/POST   /test-environments
GET/PATCH  /test-environments/{environment_id}
GET/POST   /test-plans
GET/PATCH  /test-plans/{plan_id}
POST       /test-plans/{plan_id}/transitions
GET/POST   /test-plans/{plan_id}/executions
GET        /test-executions/{execution_id}
POST       /test-executions/{id}/case-runs/{run_id}/transitions
GET/POST   /test-reports
POST       /test-reports/{report_id}/publish
GET/POST   /automation-assets
GET/POST   /automation-suites
GET/POST   /automation-tasks
POST       /automation-tasks/{task_id}/mock-transitions
POST       /automation-result-ingestions
```

### 10.3 TD 与追溯 API

```text
GET/POST   /defects
GET/PATCH  /defects/{defect_id}
POST       /defects/{defect_id}/transitions
GET        /defects/{defect_id}/history
GET/POST   /defects/{defect_id}/traceability-links
GET        /traceability?root_type=&root_id=&direction=&depth=
GET        /traceability/completeness?release_version_id=
```

内部端口：

```text
POST /internal/api/v1/references/check             # 服务身份；批量存在性/项目一致性
POST /internal/api/v1/automation-results           # automation:ingest
POST /internal/api/v1/traceability-events/replay   # 运维受控，P1 可开放实现
```

### 10.4 API 可验收标准

1. 同 actor、operation、Idempotency-Key、规范化请求重放只产生一次业务记录/历史/Outbox；同键不同请求返回 409。
2. 同版本并发更新仅一个成功，另一个返回 RFC 9457 `412 VERSION_CONFLICT`；非法状态返回 409。
3. OpenAPI 3.1 覆盖所有 P0 路由、权限、枚举、错误和示例；生成 TypeScript 客户端无未批准 diff。
4. 跨项目注入需求/版本/迭代/任务/用例/缺陷引用返回 404 且不落库；角色不足返回 403。
5. 基线激活后其快照无法 PATCH/DELETE；批准变更产生新 revision，旧 revision hash 不变。
6. 跳过任一 TP 人工门禁直接进入下一阶段/导入返回 409；Mock 输出带 provider 标识；正式用例不会被覆盖。
7. 重复自动化结果摄取不重复 CaseRun；同 external_run_ref 不同 payload hash 返回 409 并审计。
8. TD 无修复版本/证据不能进入 fixed/pending_verification；无验证证据/root cause 不能关闭。
9. 追溯查询正反向一致；投影延迟或远端删除时返回 `stale/broken/truncated`，不伪造完整链。

## 11. 事件、审计与通知

### 11.1 事件

沿用 envelope：`event_id,event_type,event_version,occurred_at,producer,trace_id,project_id,actor,aggregate,data,security.classification`；topic exchange `platform.domain.v1`；Outbox 同事务、RabbitMQ 独立 quorum queue、幂等消费、5s/30s/5m 重试和 DLQ。

P0 事件：

- Requirement：`Requirement.Created/ReviewSubmitted/Approved/Baselined/BaselineChanged/ChangeApplied/Completed`。
- TP：`TestDesign.SessionCreated/StageCompleted/GateDecided/CasesImported`，`TestCase.VersionActivated`，`TestPlan.Ready/Started/Completed`，`TestExecution.CaseRunCompleted`，`TestReport.Published`，`Automation.TaskCreated/ResultIngested`。
- TD：`Defect.Created/Assigned/Fixed/PendingVerification/Closed/Reopened/SlaBreached/DuplicateLinked`。
- Traceability：`Traceability.LinkCreated/LinkSuperseded/ProjectionUpdated`；ProjectionUpdated 不回流生成业务通知。

事件只含必要引用/摘要，不含需求全文、提示词正文、测试数据、复现敏感信息、附件 URL 或秘密。

### 11.2 审计

必须审计：所有创建/字段变化/状态动作；评审和门禁结论；基线/变更；AI/XMind 调用元数据及失败；导入冲突决策；计划范围冻结、CaseRun 更正、报告发布；自动化结果摄取；TD 分派/修复/验证/重开/重复/SLA；追溯关系；权限拒绝、导出和管理员例外。

审计包含主体、项目、资源、动作、前后差异、理由、结果、trace、幂等键、适配器/模型/提示词版本；追加式投递 audit-service，禁止凭据和大正文。

### 11.3 通知

站内 P0 通知收件人：

- 需求提交评审/结论/变更影响：评审人、负责人、受影响测试负责人；
- TP 门禁待办/阶段失败/执行分派/失败与阻塞/报告发布：会话、计划负责人和执行人；
- TD 新分派、状态退回、验证待办、SLA 预警/超时、第二次及以上重开：assignee/verifier/Owner/Admin；
- 安全或权限拒绝不向业务用户广播，只进审计/安全渠道。

重复事件按 `(recipient_id,source_event_id,template_key)` 去重；目标 URL 必须为 `/app/` 内部白名单路由；用户可关闭普通提醒，评审待办、SLA breach 和安全类不可关闭。

## 12. 非功能、隔离与安全

- 容量沿用 5,000 用户/1,500 在线；普通查询 P95 ≤500ms、写 P95 ≤800ms；追溯/报告普通查询 P95 ≤2s；事件可见 P95 ≤5s；AI/XMind 异步受理 ≤2s。
- 三服务分别私有 DB/账号/Alembic；所有 Repository 查询以 `project_id` 为首要条件；投影库只读，不作为授权事实源。
- Python 代码在 3.12、3.13 的 Ruff、类型检查、pytest 通过；3.13 生产镜像为默认，3.12 仅本地调试/兼容矩阵。
- 输入执行 JSON Schema/Pydantic 边界校验；HTML/脚本按文本处理；CSV 公式注入防护；XMind ZIP 防 Zip Slip/Zip Bomb，解压后上限 200 MiB、压缩比上限 100:1、节点深度 ≤20。
- AI 输入按项目数据密级路由；P0 Mock 不联网。未来外部模型不得接收 restricted 数据，且不可用时失败关闭，不降级绕策略。
- 环境/自动化参数只保存 Secret 引用；日志、事件、审计禁止 Token、Cookie、密码、OTP、Secret、完整测试数据。
- 导出必须重新鉴权；P0 单对象即时导出上限 50 MiB/1,000 用例，仅 XMind/JSON；CSV/批量异步审批为 P1。下载 URL 短期有效且不得跨项目复用。
- 正式资产不物理删除；草稿取消后保留审计。备份/RPO≤15 分钟、RTO≤2 小时沿用总体基线。
- 单元、PostgreSQL/RabbitMQ 集成、OpenAPI/事件契约、权限/安全、E2E、前端可访问性测试同步交付；关键状态机/权限/幂等分支覆盖率 ≥90%。

## 13. Vue 门户信息架构

```text
/app/projects/:project_id
  /requirements                     需求列表
  /requirements/new                 新建/编辑
  /requirements/:id                 详情：版本、AC、评审、基线、变更、追溯
  /requirements/:id/review          评审工作台
  /testing/library                  文件夹树 + 用例列表
  /testing/cases/:id                用例详情/版本
  /testing/design                   设计会话列表
  /testing/design/:id               分阶段 Stepper、草稿预览、门禁、导入
  /testing/plans                    计划列表
  /testing/plans/:id                范围、环境、轮次、准入/准出
  /testing/executions/:id           执行工作台
  /testing/reports/:id              报告
  /defects                          缺陷列表
  /defects/new                      提交缺陷
  /defects/:id                      详情、动作、历史、SLA、追溯
  /traceability                     项目统一追溯视图
```

### UI 交互验收

1. 列表具备服务端分页、关键词/状态/负责人/版本筛选、稳定 URL 查询参数；加载、空、错误、无权状态可区分。
2. 需求编辑有 AC 行编辑、父级/版本/迭代选择；已基线内容进入只读并引导创建变更申请。
3. 评审页展示 revision diff、AC、关联范围和历史；批准/拒绝对话框要求意见规则，版本冲突提示刷新。
4. 测试库桌面为树+表格，窄屏改抽屉/卡片；移动文件夹或导入前展示目标路径和影响数量。
5. 设计会话使用可键盘操作的 Stepper；未满足门禁的下一步禁用并给出后端原因；Mock 能力有显著标识，不冒充真实 AI。
6. 用例步骤表支持键盘新增/排序并具有程序化标签；版本切换不会丢失未保存草稿。
7. 计划/执行页显示冻结版本；执行结果不能只靠颜色，失败/阻塞要求实际结果，附件上传有扫描状态。
8. 报告数值与执行快照一致；链接可下钻到用例/CaseRun/TD，发布后只读。
9. 缺陷详情仅显示当前用户可执行动作；动作表单按状态要求修复/验证证据，SLA 超时同时用文字/图标表达。
10. 追溯视图默认展示有向分组链和可访问的表格替代视图；支持正反向、深度、类型筛选，断链/陈旧/截断清晰提示。
11. 直接访问无权路由返回 403/安全 404；隐藏导航不能替代 API 授权。
12. `light/dark/system` 三模式、360/768/1280 px、200% 缩放可完成核心链；WCAG 2.2 AA，键盘、焦点、对比度、ARIA、reduced motion 自动检查无 serious/critical 问题。

## 14. 非目标

- 真实外部/公司 AI 模型接入、知识库 RAG、成本结算；本轮仅可替换端口和受控 Mock。
- 真实 GitLab CI/CD/Runner 触发、浏览器/移动设备执行、Nexus/Harbor、Commit/MR 强校验与正式发布；仅稳定占位引用/端口。
- 任意 XMind 特性完整兼容、在线脑图协同编辑；仅约定模板的安全导入导出。
- 自定义字段/状态/脚本工作流/跨服务强事务；三域使用内置版本化状态机。
- 全文搜索、管理驾驶舱、预测分析、个人绩效排名。
- 邮件/企业通信真实投递、SSE/WebSocket；延续站内通知轮询。
- 大规模历史数据迁移、跨项目资产共享、匿名/外部客户访问。

## 15. 端到端黄金链

```text
Owner 创建版本/迭代
→ Member 创建 user_story + AC 并提交评审
→ Reviewer 批准，Owner 激活需求基线
→ 测试负责人选择需求 revision 创建设计会话
→ Mock 需求分析 → 人工批准
→ Mock XMind 测试设计 → 人工批准
→ Mock XMind 测试用例 → 人工批准
→ 选择文件夹导入正式用例并建立追溯
→ 创建并 ready 测试计划，冻结用例版本
→ 创建执行，CaseRun 失败并上传证据
→ 显式创建 TD 并关联需求/用例/执行/任务
→ 分派 → 处理中 → 修复（Mock fix evidence + 修复版本）
→ 待验证 → 回归 CaseRun 通过 → TD 关闭
→ 发布测试报告
→ 从需求和 TD 双向查询完整追溯
→ audit-service 可见关键动作，notification-service 可见待办/结果
```

自动化还必须覆盖：跨项目 ID 注入、Viewer 写入、同键重放、并发 If-Match、基线不可变、跳门禁、恶意 XMind、AI Mock 失败恢复、正式用例防覆盖、重复结果摄取、TD 非法关闭、重复缺陷环、追溯断链/陈旧。

## 16. Definition of Done

- `requirement-service`、`tp-service`、`td-service` 可独立启动；私有 PostgreSQL、空库 Alembic 正向升级、健康/就绪、配置示例齐备。
- P0 对象、字段、权限、状态机、业务规则、API 和事件全部实现；OpenAPI 3.1/JSON Schema 可校验并生成前端类型。
- AI 模型、XMind、自动化执行均经可替换端口；确定性 Mock 有清晰标识、无外网依赖，且不能绕过人工门禁。
- 需求基线/变更、测试资产链/计划/执行/报告、TD 修复验证闭环和统一追溯黄金链全自动通过。
- 所有成功写入与历史/Outbox 同本地事务；RabbitMQ 重投去重、DLQ、审计、通知可重复验证。
- 项目隔离、角色越权、状态机、幂等、并发、文件/输入安全测试全部通过；关键分支覆盖率 ≥90%。
- Vue P0 页面不是占位页；三主题、响应式、WCAG 2.2 AA、错误/空/冲突态和后端最终授权通过 Playwright/axe 验收。
- Python 3.12/3.13 双兼容门禁通过，生产默认 3.13；不得以 3.12 调试成功替代 3.13 生产验收。
- 未引入真实模型、Runner、GitLab/制品/发布实现或共享数据库；所有占位/Mock 在 UI、API 和审计中明确可识别。
