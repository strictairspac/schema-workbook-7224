# 实验委托模型拆解册

南麓材料实验室（9人）把委托单上的业务依赖整理为可验证的3NF关系，并保留候选键、闭包、最小覆盖和无损校验证据。

## 业务工作流

原先设计员在Excel里堆叠委托号、客户、检测项、方法与结果，再手工画表结构。痛点：依赖口径难确认、复合键容易漏判、拆表后无法证明无损。上游为委托单和已确认业务规则，本项目承接关系草案登记、函数依赖编辑、3NF合成、验证报告导出，下游为实验数据录入系统的数据库设计人员。

核心实体：关系草案 Relation、函数依赖 Dependency、分解报告 Report、索引试验 IndexTrial/IndexTrialCombo。5业务页（关系草案、依赖编辑、分解任务、校验详情含索引试验录入、索引试验）和独立登录页；管理员另有审计页。业务规则不执行为SQL，属性名是纯数据；索引试验仅在隔离库内对冻结样本执行DDL/DML。

## 快速启动

```sh
cp .env.example .env
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```

前端 http://localhost:18243 ，后端 http://localhost:19243/docs ，MySQL localhost:17743。

|角色|账号|密码|权限|
|---|---|---|---|
|admin|admin@nanlu.test|Demo2026!|草案/依赖写入、运行、审计|
|operator|operator@nanlu.test|Demo2026!|草案/依赖写入、运行、导出|
|viewer|viewer@nanlu.test|Demo2026!|只读与导出，写API403|

## 一天的工作剧本

09:00 operator登录；09:05打开 `NL-1117-A` 材料检测委托单；09:10查看五属性 `委托号,客户,检测项,方法,结果`；09:15确认 `委托号→客户`、`检测项→方法`、`委托号,检测项→结果`；09:20执行 `shift-20261117` 分解任务；09:25候选键为 `{委托号,检测项}`，拆出委托客户、检测项方法、委托检测结果3个关系；09:30导出 `report-1.json`；09:40 viewer复核3NF/依赖保持/无损均通过；10:00 admin审计。

另有 `NL-1117-B` 的循环依赖 A→B/B→A与独立属性C，候选键AC/BC；`NL-1117-C` 没有确认依赖，完整属性集作为唯一候选键，不凭空猜测业务规则。

## 算法说明

Python真算，MySQL保存草案/依赖与结果，Redis传递任务，独立worker执行。

1. 属性闭包：迭代应用所有X→a，直到不再增加属性。
2. 候选键：先取不出现在RHS的必需属性，再按大小枚举其余属性子集；若闭包覆盖全集且不含已知候选键，加入结果。**最多10个属性/64条依赖**，最多1024个子集；超限API422/算法ValueError，避免指数搜索失控。
3. 最小覆盖：RHS拆成单属性，去平凡依赖；逐一删除左侧多余属性、移除冗余依赖。
4. 3NF合成：按最小覆盖左侧分组，删除被包含关系；若无关系含候选键，补入候选键关系。无依赖时保留全属性关系。
5. 验证：精确生成F+在各分解关系上的投影，枚举局部候选键，逐非平凡投影依赖检查3NF；所有原始依赖须可由投影并集推出。tableau追赶法依据FD合并符号，出现全a符号行则无损，报告包含见证行、合并步骤与最终表。

复合、循环、空决定项、无依赖均支持。不在任何RHS中的属性强制进入候选键。输入入队时冻结快照，后续修改不会改变已有报告。结果JSON含SHA256，固定输入应有固定输出。失败态包括引用关系外属性、重复/空属性、属性超过10、依赖超过64、队列错误；页面可恢复并重新执行。

这是小型关系模型设计辅助工具，FD由人工提供，不能从脏数据自动推断业务规则；不连接生产数据或自动执行DDL。精确投影在10属性内有界，仍可能随依赖复杂度增加耗时。单worker串行队列，不带生产任务重试/崩溃续跑。

## 索引选型试验（报告页）

拆解报告定了分表之后，在**报告详情页（校验详情）**直接录入索引试验，数据冻结后实测，不碰任何生产库：

- **委托样本**：CSV 粘贴（首行表头即属性列，最多 20 万行）；**常用查询**：1–20 条只读 SELECT（禁 DDL/DML/分号，后端校验）；**候选索引**：1–12 个，列必须来自样本表头。
- 空组合作为**无候选索引基线**，其余 `2^n-1` 个非空子集（上限 256 个）各自在**独立隔离的 MySQL schema** 中用**同一批数据**真实建表、建索引、回放查询。
- 每个组合：`EXPLAIN` + `EXPLAIN FORMAT=JSON` 取执行计划与查询总估算成本；回放结果做 SHA256 校验，**与基线结果不一致即拒绝**；`information_schema` 实测占用（DATA_LENGTH+INDEX_LENGTH），**超过容量上限即拒绝**。
- 只推荐**比基线省**（总估算成本严格更低）且容量内、结果一致的组合，按总估算成本最低择优；全部不合格时结论为「无可用组合」，页面可回看每个组合的执行计划 JSON 与实测占用。
- **隔离**：schema 名 `trial_{试验id}_{时间戳}_{随机}`，按试验 id 前缀区分，组合间库互不影响，试验结束即清理，中断残留库在下次同试验运行开头自动回收。worker 用独立的最小权限账号 `trial_admin`（仅对 `trial%` 库有权限，见 `migrations/003_trial_admin.sql`）做隔离库的全部 DDL/回放，跨库读取业务库或 `mysql` 系统表直接 1142 拒绝；Web 应用账号 `schemaworkbook` 不持有任何 `trial%` 权限。
- **可恢复**：组合按 `pending/running/measured/skipped/failed` 落库，已 `measured` 的（含基线）重试时直接复用、**不重复计入**；每次恢复换新 `run_token`，旧 worker 的迟到写入自动失效。中断后在试验详情页「恢复原试验」，仍回到同一条试验记录。
- 前端路径 `#/trials`（列表）与 `#/trials/{id}`（详情）；写接口仅 operator/admin，viewer 只读 403。所有入队、推荐、无可用组合、恢复动作写审计日志。

## 工程结构

|服务|技术|职责|
|---|---|---|
|frontend|原生HTML/CSS/JS + Nginx|5业务页、登录、共享业务表格/报告/试验组件|
|backend|Python3.11/FastAPI/SQLAlchemy/PyJWT|校验、权限、审计、快照与导出|
|worker|Python3.11|闭包、候选键、3NF与chase；索引试验隔离库实测与恢复|
|db|MySQL8.0|JSON属性与依赖、任务报告、索引试验与逐组合实测结果|
|redis|Redis7|持久任务队列（分解队列 + 索引试验队列）|

目录：`frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}`；`backend/src/{routes,controllers,services,models,schemas,middlewares,utils,constants,config}`；`backend/scripts/seed_demo.py`；`backend/migrations/001_initial.sql`、`002_index_trials.sql`。每核心实体贯穿模型/schema/service/route/API/store/page。组件table/badge/frame复用，hooks/session/feedback和utils/forms/html共用；request_id/errors双后端中间件。索引试验实体 IndexTrial/IndexTrialCombo 对应 `src/services/index_trials.py`、`src/routes/index_trials.py`、`src/schemas/index_trial.py` 与 `frontend/src/pages/trials.js`。

枚举：角色admin/operator/viewer、任务queued/running/completed/failed；前后端定义位于 `backend/src/constants/enums.py` 和 `frontend/src/constants/enums.js`，security/reports、frame/badge消费；worker持久化状态。

环境变量见.env.example：COMPOSE_PROJECT_NAME、FRONTEND_PORT/BACKEND_PORT/DB_PORT、DB_PASSWORD、JWT_SECRET、SEED_DEMO。默认密码仅本地演示，JWT8小时。seed按自然键只补缺失关系及初始依赖，不覆盖用户修改。schema由SQLAlchemy metadata.create_all初始化，无在线迁移引擎。

本地开发：Python3.11安装backend/requirements.txt，配置DATABASE_URL/REDIS_URL后从backend运行 `uvicorn src.main:app --reload`、`python -m src.worker`；前端用Nginx同源代理/api。5服务均有健康检查和健康依赖，数据库/Redis/worker产物为独立命名卷。停止清空：`docker compose down -v --remove-orphans`。

UI为酒红档案册，双字体由Google Fonts加载，离线有回退且业务不依赖字体网络。

## License

MIT。真实测试脚本与结果在仓库内 `tests/`：`e2e_index_trials.py`（同数据回放一致性、超容量拒绝、成本择优、校验422）、`e2e_trial_resume.py`（中断恢复、重试不重复计入已测组合）、`e2e_trial_concurrency.py`（并发试验隔离）、`smoke_frontend.mjs`（页面分支渲染）；源码外截图产物保存在 `../../test-artifacts/gb-4104/`。
