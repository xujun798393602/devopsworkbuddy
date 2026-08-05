# wkDEVOPS 当前执行概览

## 最新状态（2026-08-03）

- 本地 Requirement、TP、TD、Traceability 与 Portal 核心门禁已通过；Python 全仓 201 passed / 3 PostgreSQL skipped，Portal 类型检查、测试、连续生产构建及发布目录安全回归通过。
- 远程 PostgreSQL 集成部署已完成并经独立 QA 验收：`IS_PASS: YES / ROUTE_TO: NoOne`。
- 当前远程 Release：`/project/devops-platform/releases/20260803T200000Z-task68`；`current` 指向 Task68，`previous` 指向 Task66，回滚切换已验证。
- PostgreSQL 容器：`wkDEVOPS-platform-postgres-debug`，使用远程已有 `postgres:16-alpine`，绑定 `127.0.0.1:25432`，状态 healthy。
- 已建立 8 个服务私有数据库；Project Service 真实 Alembic head 为 `0002`，真实 PostgreSQL 集成测试为 3 passed / 2 非阻断弃用警告。
- 共享测试运行时：`/project/devops-platform/shared/test-runtimes/project-service-py312-v1`，Python 3.12.12、pytest 8.4.2，root-owned、全树只读、45 包 Manifest 校验通过。
- Task68 Release：93 个 Manifest 文件、15 个目录、5 个可执行入口，0 cache、0 writable、0 non-root；Task64 Audit 4076 条记录可独立重算并一致。
- 受保护的旧 `devops-project-service-golden:18080` 与 `auto-test-postgres:5432` 未改变。


## 本轮完成

### 离线部署工具链

- 完成 `project-service/scripts/download_docker_image.py` 的安全加固。
- 离线镜像归档改为同目录临时文件写入，校验成功后通过 `os.replace` 原子发布。
- 下载、校验或替换失败时不会留下半成品，也不会破坏已有归档。
- `--force-ipv4` 仅在下载生命周期生效，正常和异常退出都会恢复网络解析函数。
- 网络异常采用固定错误码输出，不泄露代理账号、密码、URL、Token 或 Authorization。
- 固化 Windows 下载 Linux x86_64 / CPython 3.13 wheels，再上传 Linux 离线安装和容器构建的交付模式。

### project-service P0 协作增量

- 产品经理完成增量 PRD：项目成员与角色、版本与迭代、任务与 Worklog。
- 架构师完成增量架构：数据模型、API、权限、迁移、任务分解和 Mermaid 类图/时序图。
- 工程师批量实现并补齐本地可验证缺口：
  - 通用写幂等闭环（成员/版本/迭代/任务/Worklog/Owner 移交）。
  - 版本发布与迭代完成门禁（未关闭任务拒绝、force=true 必填 reason）。
  - 任务游标分页（稳定排序、after、limit、跨项目 cursor 422）。
  - OpenAPI 3.1 精化（35 个具体 schema、枚举、必填、If-Match/Idempotency-Key、Problem Details）。
  - Alembic 0002 静态结构修复（pgcrypto 前置、FK 顺序、upgrade/downgrade 对称）。
- QA 第 1 轮独立验证通过，测试代码缺陷已由 QA 自行修复，源码无缺陷。

## QA 结果

### 离线下载脚本

- 专项测试：11/11 通过，通过率 100%。
- Ruff：通过。
- compileall：通过。
- Routing Decision：NoOne。
- IS_PASS：YES。

### P0 协作增量

- pytest：130 passed / 3 skipped / 0 failed。
- Ruff（src/scripts/migrations/tests）：通过。
- compileall：通过。
- OpenAPI 3.1 validator：通过。
- Routing Decision：NoOne。
- IS_PASS：YES。
- 3 个 skip 为 PostgreSQL 实时集成测试，需真实数据库，不伪造。

## 当前阻塞

- 当前 Windows 命令执行环境访问 `auth.docker.io`、`registry-1.docker.io` 和 `mirror.gcr.io` 的 IPv4 443 均在 TCP 建连阶段超时。
- 尚未生成 `python:3.13-slim` Docker-load 离线归档，因此尚未继续远程镜像加载和 wkDEVOPS 持久化部署。
- 现有 18 个 Linux x86_64 / CPython 3.13 wheels 及 SHA-256 清单保持可用。
- PostgreSQL 真实迁移和集成测试需远程基础镜像恢复后执行。

## 继续条件

满足以下任一条件即可恢复远程部署：

1. 提供当前执行进程可用、能够访问 Docker Hub 的 HTTPS forward proxy，并通过临时 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量配合 `--proxy-env --force-ipv4` 使用；或
2. 提供来源可信、可校验 manifest/config/layer digest 的官方 `python:3.13-slim` Docker-save 归档。

恢复后将继续：归档校验 -> 上传 `/project` 版本化 release -> `docker load/inspect` -> wheelhouse 离线构建 -> 部署 `wkDEVOPS` PostgreSQL/migration/API -> 持久化、幂等、并发、多 worker 和故障恢复验收。

## 本地后续增量

远程部署恢复前，本地可继续推进的增量（不依赖公网和远程容器）：

1. IAM 与登录（本地代码 + 测试）。
2. Vue 3 门户骨架（本地构建）。
3. 工作流、审计和通知服务的本地骨架。
4. 需求、TP、TD 服务的本地骨架。
5. GitLab CI/CD 集成与制品发布的本地契约和 mock 测试。
