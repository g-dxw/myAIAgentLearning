# 项目开发步骤

## 总原则

- **后端优先**：先有 API 再有前端页面，前端不做 mock 数据
- **自底向上**：每个模块按 Model → Schema → Service → Router 顺序构建
- **每步可验证**：每个 Phase 结束后后端可启动、接口可 curl、前端页面可交互
- **增量不重构**：后续 Phase 只在前一步基础上追加，不推翻已有代码

---

## Phase 0：项目脚手架

### 0.1 前端项目初始化
1. `npm create vite@latest frontend -- --template react-ts` 创建 Vite + React + TS 项目
2. 安装依赖：`react-router-dom`
3. 按 [frontend/ARCHITECTURE.md](frontend/ARCHITECTURE.md) 创建目录结构（空目录 + 占位文件）
4. 创建 `src/types/api.ts` 定义 `ApiResponse<T>`、`PageResult<T>`、`PageParams`
5. 创建 `src/services/request.ts` 封装 fetch（baseURL、token 注入、code 判断）

### 0.2 后端项目初始化
1. 创建 `backend/requirements.txt`，依赖清单：
   ```
   fastapi
   uvicorn
   sqlalchemy>=2.0
   alembic
   pydantic>=2.0
   python-jose[cryptography]
   passlib[bcrypt]
   anthropic
   apscheduler
   ```
2. 创建 `backend/config.py`，从环境变量读取：`DATABASE_URL`、`JWT_SECRET`、`ANTHROPIC_API_KEY`
3. 创建 `backend/main.py` 最小入口：CORS 配置 + `app = FastAPI()` + `uvicorn.run()`
4. 确认 `backend/models/` 下 11 个模型文件可正常 import（已完成）
5. 初始化 Alembic：`alembic init migrations`
6. 配置 `alembic.ini` 和 `env.py`，指向 models.Base 的 metadata
7. 生成初始迁移：`alembic revision --autogenerate -m "init"` → `alembic upgrade head`

### 0.3 验证
- 前端 `npm run dev` 可启动
- 后端 `uvicorn main:app --reload` 可启动
- `GET /docs` 可看到 Swagger 页面
- SQLite 数据库文件已生成，表结构正确

---

## Phase 1：认证系统

这是所有功能的入口，必须先做。

### 1.1 后端 — Auth
1. 创建 `backend/utils/security.py`：
   - `hash_password(pwd: str) -> str`
   - `verify_password(pwd: str, hash: str) -> bool`
   - `create_token(user_id: int, role: str) -> str`
   - `decode_token(token: str) -> dict`
2. 创建 `backend/schemas/auth.py`：`LoginRequest`、`LoginResponse`（含 token + user 信息）
3. 创建 `backend/schemas/common.py`：`ApiResponse[T]`、`PageResult[T]`
4. 创建 `backend/utils/response.py`：`ok(data)`、`fail(code, msg)`
5. 创建 `backend/services/auth.py`：`login()`、`get_current_user()`
6. 创建 `backend/dependencies.py`：`get_db`、`get_current_user`（Depends 注入）
7. 创建 `backend/routers/auth.py`：`POST /api/auth/login`、`GET /api/auth/me`
8. 在 `main.py` 注册 auth router

### 1.2 数据库种子
1. 创建 `backend/seed.py`，插入默认管理员账号（admin/admin123）
2. 确保密码经过 bcrypt 哈希

### 1.3 前端 — Login
1. 创建 `src/types/auth.ts`：`User`、`LoginForm`
2. 创建 `src/services/auth.ts`：`login()`、`getMe()`
3. 创建 `src/contexts/AuthContext.tsx`：`AuthProvider` + `useAuth` hook
4. 创建 `src/pages/LoginPage.tsx`：用户名密码表单
5. 创建 `src/components/RoleGuard.tsx`：按角色渲染 AdminLayout 或 WorkerLayout
6. 在 `App.tsx` 接入路由：`/login` → LoginPage，受保护路由由 RoleGuard 包裹

### 1.4 验证
- `POST /api/auth/login` 返回 token
- 前端登录后 token 存入 localStorage，刷新页面保持登录
- 访问无 token 的受保护路由自动跳转 `/login`

---

## Phase 2：机构端 — 护工管理

### 2.1 后端 — Worker CRUD
1. `backend/schemas/worker.py`：`WorkerCreate`、`WorkerUpdate`、`WorkerOut`
2. `backend/services/worker.py`：`list_workers()`、`get_worker()`、`create_worker()`、`update_worker()`、`delete_worker()`
3. `backend/routers/worker.py`：`GET/POST/PUT/DELETE /api/workers`
4. 创建 Worker 时自动创建关联 User（角色=worker，默认密码），在一个事务中完成

### 2.2 前端 — Worker 页面
1. `src/types/worker.ts`
2. `src/services/worker.ts`
3. `src/pages/admin/AdminLayout.tsx`：Sidebar + Header + Outlet
4. `src/pages/admin/WorkerList.tsx`：表格 + 分页 + 搜索
5. `src/pages/admin/WorkerDetail.tsx`：新建/编辑表单（抽屉或新页）
6. 配置路由：`/admin/workers`、`/admin/workers/:id`

### 2.3 验证
- 管理员可新增、编辑、删除护工
- 新增护工时可登录（默认密码）

---

## Phase 3：机构端 — 病人管理

### 3.1 后端 — Patient CRUD
1. `backend/schemas/patient.py`：`PatientCreate`、`PatientUpdate`、`PatientOut`（含 special_conditions）
2. `backend/services/patient.py`：标准 CRUD + 特殊情况增删
3. `backend/routers/patient.py`：`GET/POST/PUT /api/patients`、`GET /api/patients/:id`

### 3.2 前端 — Patient 页面
1. `src/pages/admin/PatientList.tsx`
2. `src/pages/admin/PatientDetail.tsx`：基本信息 + 特殊情况列表（子表增删）
3. 路由：`/admin/patients`、`/admin/patients/:id`

---

## Phase 4：护工端 — Agent 对话（新增病人流程）

这是项目的核心功能之一。

### 4.1 后端 — Session + ChatMessage
1. `backend/schemas/session.py`：`SessionCreate`、`MessageAdd`、`SessionOut`（含 messages）
2. `backend/services/session.py`：
   - `create_session()`：护工发起新对话，创建 Patient（status=pending），创建 Session，创建初始消息
   - `get_my_sessions()`：护工只能查自己的
   - `get_session()`：含权限校验（护工只能看自己的）
   - `add_message()`：添加消息到 session
   - `confirm_session()`：标记为 pending_review，触发 AI 审核
3. `backend/routers/session.py`：对应 REST 路由
4. 在 `dependencies.py` 新增 `get_current_worker`（限制角色=worker）

### 4.2 前端 — Session 页面
1. `src/types/session.ts`
2. `src/services/session.ts`
3. `src/pages/worker/WorkerLayout.tsx`：底部导航栏
4. `src/pages/worker/SessionList.tsx`：病人对话列表
5. `src/pages/worker/SessionChat.tsx`：聊天界面 + 确认按钮
6. 路由：`/worker/sessions`、`/worker/sessions/:id`

### 4.3 验证
- 护工可创建新对话（= 新增病人申请）
- 对话中可发送消息
- 点击"确认完成"后 session 状态变为 pending_review

---

## Phase 5：AI 审核 + 管理员审核

### 5.1 后端 — AI Review
1. 创建 `backend/ai/client.py`：封装 Anthropic SDK，输入 messages + system prompt → 返回结构化 JSON
2. 创建 `backend/ai/prompts/review.md`：System prompt，要求 AI 从对话中提取病人姓名/年龄/性别/地址/电话/特殊情况
3. 创建 `backend/ai/review.py`：
   - 取出 session 全部 messages
   - 调用 AI 解析为 `PatientCreate` schema
   - 用 Pydantic 校验 AI 返回的 JSON
   - 校验失败 → 返回原始 AI 输出 + 错误信息（供护工修正）
   - 校验通过 → 更新 Patient 数据，session 状态 → `pending_review`

### 5.2 后端 — 管理员审核
1. `backend/schemas/approval.py`
2. `backend/services/approval.py`：
   - `list_approvals()`：`pending_review` 的 session 列表
   - `approve()`：Patient.status → active，Session.status → approved
   - `reject()`：Session.status → rejected，附驳回原因，护工可重新提交
3. `backend/routers/approval.py`

### 5.3 前端 — 审核页面
1. `src/pages/admin/PatientApproval.tsx`：待审核列表
2. 每条记录展示：AI 提取的病人信息（预览）+ 原始对话记录
3. 操作按钮：通过 / 驳回（填原因）
4. 护工端 SessionList 显示驳回状态和原因，可点击重新编辑

### 5.4 验证
- 护工提交 → AI 自动解析为病人信息
- 管理员可查看 AI 提取结果和原始对话
- 通过后病人正式入库，驳回后护工可重提

---

## Phase 6：护工端 — 打卡 + AI 补齐

### 6.1 后端 — Checkin
1. `backend/schemas/checkin.py`
2. `backend/services/checkin.py`：
   - `start_checkin()`：打卡开始，Checkin(status=STARTED)
   - `submit_checkin(content)`：提交护理内容 → 调用 AI 完整性检查
   - `complete_checkin()`：补齐后再次提交
3. 创建 `backend/ai/prompts/complete.md`：System prompt，定义护理记录必填项（体温/血压/饮食/精神状态/用药等）
4. 创建 `backend/ai/complete.py`：
   - AI 逐项检查 content
   - 有缺失 → 返回缺失列表 + 追问，Checkin(status=INCOMPLETE)
   - 无缺失 → Checkin(status=COMPLETED) + 生成 CareRecord
5. `backend/routers/checkin.py`

### 6.2 定时提醒
- 在 `backend/scheduler/jobs.py` 创建定时任务
- 服务时间到达 1 小时后，检查 Checkin 是否已提交
- 未提交 → 推送提醒（暂用数据库记录 + 前端轮询，后续可接推送）

### 6.3 前端 — 打卡页面
1. `src/pages/worker/CheckinForm.tsx`：
   - 选择病人 → 点击"开始服务"打卡 → 服务中计时显示
   - 填写护理记录 → 提交
   - AI 判定缺失时显示追问项 → 补齐 → 再次提交
2. `src/pages/worker/MyRecordList.tsx`：自己的护理记录
3. 服务时间到 1 小时提醒通知

### 6.4 验证
- 打卡 → 填写记录 → AI 检查 → 缺失提示 → 补齐 → 入库
- 管理员可在护理记录管理页看到

---

## Phase 7：排班系统

### 7.1 后端 — Schedule
1. `backend/schemas/schedule.py`
2. `backend/services/schedule.py`：
   - **自动排班算法**：
     - 输入：日期、活跃护工列表、活跃病人列表
     - 以 1 小时为单位，分配护工→病人，避免冲突
     - 优先均匀分配工作负载
   - **临时调整**：将某病人某时段换到空闲护工
   - `get_my_schedule()`：护工端看自己排班
3. `backend/routers/schedule.py`

### 7.2 前端 — 排班页面
1. `src/pages/admin/WorkerSchedule.tsx`：日历/时间轴视图，拖拽或表单调整
2. `src/pages/admin/SettingsPage.tsx` 中自动排班设置 Tab
3. `src/pages/worker/MySchedule.tsx`：今日排班卡片

---

## Phase 8：预警系统

### 8.1 后端 — Alert
1. `backend/services/alert.py`：
   - `get_config()` / `update_config()`
   - `run_analysis()`：拉取所有 active 病人 + 近期 CareRecord → 批提交 AI
2. 创建 `backend/ai/prompts/analyze.md`：逐病人分析，判断风险等级（正常/关注/危险），给出依据
3. 创建 `backend/ai/analyze.py`：AI 返回 JSON 列表 → 高危/危险项入库 AlertNotification 表
4. 在 `backend/scheduler/jobs.py` 注册每晚定时任务（如凌晨 2 点）
5. Alert 通知关联 worker_id 和 patient_id，方便查询

> 注：需新增 `AlertNotification` 模型（id, worker_id, patient_id, level, reason, created_at, is_read），可在 Phase 8 追加

### 8.2 前端
1. `src/pages/admin/SettingsPage.tsx`：预警参数配置
2. `src/pages/worker/AlertList.tsx`：预警通知列表

---

## Phase 9：投诉 + 护理记录管理

### 9.1 后端 — Complaint
1. `backend/services/complaint.py`：创建投诉、列表、处理
2. `backend/routers/complaint.py`

### 9.2 后端 — Record（机构端视角）
1. 已有 CareRecord 模型，补充 service 和 router
2. 支持按病人、护工、日期筛选

### 9.3 前端
1. `src/pages/admin/ComplaintList.tsx`
2. `src/pages/admin/RecordList.tsx`

---

## Phase 10：收尾完善

1. **错误处理统一**：所有 router 异常由全局 exception handler 捕获，返回统一格式
2. **前端 Loading/Empty/Error 状态**：每个列表页补充三态渲染
3. **表单校验**：前端校验（必填、格式）+ 后端 Pydantic 兜底
4. **权限边界**：检查所有 worker 端接口是否有 `get_current_worker` 守卫，admin 端接口是否有 admin 守卫
5. **数据库索引**：检查高频查询字段是否建索引（worker_id、patient_id、status、created_at）
6. **API 文档**：FastAPI 自动生成的 `/docs` 确认所有接口标注清晰

---

## 依赖关系图

```
Phase 0（脚手架）
  └─→ Phase 1（认证）← 所有功能的前置
       └─→ Phase 2（护工管理）
            └─→ Phase 3（病人管理）
                 └─→ Phase 4（Agent 对话）
                      └─→ Phase 5（AI 审核 + 管理员审核）
                           └─→ Phase 6（打卡 + AI 补齐）
                                ├─→ Phase 7（排班）
                                ├─→ Phase 8（预警）
                                └─→ Phase 9（投诉 + 记录管理）
                                     └─→ Phase 10（收尾）
```

Phase 7、8、9 不互相依赖，可并行开发。

---

## 每个 Phase 的开发顺序（固化模板）

1. 后端 Model（如需新增表）
2. 后端 Schema（Pydantic 入参/出参）
3. 后端 Service（业务逻辑）
4. 后端 Router（挂载路由 + 依赖注入）
5. `curl` / Swagger 验证后端接口
6. 前端 types（对接后端 Schema）
7. 前端 service（API 调用封装）
8. 前端 page + 路由注册
9. 浏览器验证完整链路
