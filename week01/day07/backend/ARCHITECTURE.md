# Backend 架构设计

## 技术选型

| 类别 | 方案 |
|------|------|
| 框架 | FastAPI |
| ORM | SQLAlchemy 2.0 |
| 数据校验 | Pydantic v2 |
| 数据库迁移 | Alembic |
| 认证 | JWT (python-jose) |
| 密码 | bcrypt (passlib) |
| AI | Anthropic SDK（对话审核、记录补齐、预警分析） |
| 定时任务 | APScheduler（每晚上报分析） |
| CORS | fastapi.middleware.cors |

## 模块分层

```
backend/
├── main.py                # FastAPI 入口，注册路由/中间件/定时任务
├── config.py              # 配置（JWT密钥、DB路径、AI Key 等，从 env 读取）
├── dependencies.py         # 依赖注入（get_db、get_current_user 等）
├── routers/               # 路由层 — 仅做参数解析和响应封装，不含业务逻辑
│   ├── auth.py            # 登录/退出/获取当前用户
│   ├── worker.py          # 护工 CRUD + 排班
│   ├── patient.py         # 病人 CRUD
│   ├── approval.py        # 病人审核
│   ├── record.py          # 护理记录
│   ├── complaint.py       # 投诉管理
│   ├── schedule.py        # 排班相关
│   ├── alert.py           # 预警设置
│   └── checkin.py         # 打卡（护工端）
├── models/                # SQLAlchemy 模型（一个文件一个模型）
│   ├── user.py            # 用户（管理员/护工）
│   ├── worker.py          # 护工信息
│   ├── patient.py         # 病人信息
│   ├── special_cond.py    # 病人特殊情况
│   ├── care_record.py     # 护理记录
│   ├── schedule.py        # 排班表
│   ├── checkin.py         # 打卡记录
│   ├── complaint.py       # 投诉
│   ├── alert_config.py    # 预警配置
│   └── session.py         # Agent 对话 session
├── schemas/               # Pydantic 请求/响应模型
│   ├── common.py          # ApiResponse[T], PageResult[T], PageParams
│   ├── auth.py            # LoginRequest, LoginResponse
│   ├── worker.py          # WorkerCreate, WorkerUpdate, WorkerOut
│   ├── patient.py         # PatientCreate, PatientUpdate, PatientOut
│   ├── record.py          # RecordCreate, RecordOut
│   ├── schedule.py        # ScheduleOut, ScheduleAssign
│   ├── checkin.py         # CheckinSubmit
│   ├── complaint.py       # ComplaintCreate, ComplaintOut
│   ├── alert.py           # AlertConfigUpdate
│   └── session.py         # SessionCreate, MessageAdd
├── services/              # 业务逻辑层
│   ├── auth.py            # 登录校验、JWT 签发/验证
│   ├── worker.py          # 护工业务
│   ├── patient.py         # 病人业务
│   ├── approval.py        # 审核流程
│   ├── record.py          # 护理记录业务
│   ├── schedule.py        # 排班算法
│   ├── complaint.py       # 投诉处理
│   └── alert.py           # 预警逻辑
├── ai/                    # AI Agent 模块
│   ├── client.py          # Anthropic SDK 封装
│   ├── review.py          # 病人数据审核 → 标准格式入库
│   ├── complete.py        # 护理记录完整性判断 → 缺失补齐
│   ├── analyze.py         # 批量分析病人身体情况 → 预警判断
│   └── prompts/           # 各场景 System Prompt 模板
│       ├── review.md
│       ├── complete.md
│       └── analyze.md
├── scheduler/             # 定时任务
│   └── jobs.py            # 每晚批量分析任务
└── utils/
    ├── response.py        # 统一响应封装 ok() / fail()
    └── security.py        # JWT 工具、密码哈希
```

## API 路由总览

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 登录，返回 JWT token |
| POST | `/api/auth/logout` | 退出 |
| GET | `/api/auth/me` | 获取当前用户信息 |

### 护工管理（机构端）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/workers` | 护工列表（分页） |
| GET | `/api/workers/:id` | 护工详情 |
| POST | `/api/workers` | 新增护工 |
| PUT | `/api/workers/:id` | 编辑护工 |
| DELETE | `/api/workers/:id` | 删除护工 |

### 病人管理（机构端）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/patients` | 病人列表（分页） |
| GET | `/api/patients/:id` | 病人详情（含特殊情况） |
| POST | `/api/patients` | 新增病人 |
| PUT | `/api/patients/:id` | 编辑病人 |

### 病人审核（机构端）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/approvals` | 待审核列表 |
| POST | `/api/approvals/:id/approve` | 通过审核 |
| POST | `/api/approvals/:id/reject` | 驳回（含驳回原因） |

### 护理记录

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/records` | 记录列表（机构端全量/护工端自己） |
| GET | `/api/records/:id` | 记录详情 |

### 投诉管理（机构端）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/complaints` | 投诉列表 |
| POST | `/api/complaints` | 新增投诉 |
| PUT | `/api/complaints/:id` | 处理投诉 |

### 排班管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/schedules` | 排班列表（按日期筛选） |
| POST | `/api/schedules/auto` | 自动排班 |
| POST | `/api/schedules/adjust` | 临时调整（加钟） |
| GET | `/api/schedules/my` | 我的排班（护工端） |

### 预警设置（机构端）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/alerts/config` | 获取预警参数 |
| PUT | `/api/alerts/config` | 更新预警参数 |

### 护工端 — Agent 对话

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sessions` | 我的病人对话列表 |
| POST | `/api/sessions` | 新建对话（新增病人入口） |
| GET | `/api/sessions/:id` | 获取对话消息 |
| POST | `/api/sessions/:id/messages` | 发送消息 |
| POST | `/api/sessions/:id/confirm` | 确认记录完成 → 触发 AI 审核 |

### 护工端 — 打卡

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/checkin` | 服务打卡（开始记录） |
| POST | `/api/checkin/:id/submit` | 提交护理记录 → 触发 AI 完整性检查 |
| GET | `/api/checkin/:id/status` | 打卡状态查询 |

## 中间件设计

```
请求 → CORS → AuthMiddleware(白名单放行) → Router → 响应封装
```

- **CORS**：开发阶段允许 localhost:5173
- **AuthMiddleware**：从 Header 取 token → 解码 → 注入 request.state.user
- 路由白名单：`/api/auth/login`，其他全部需鉴权

## 数据库模型关系

```
User (id, username, password_hash, role[admin|worker], created_at)
  ↓ 1:1
Worker (id, user_id FK, name, phone, id_card, avatar, status, created_at)

Patient (id, name, age, gender, address, phone, status[active|pending], created_at)
  ↓ 1:N
SpecialCondition (id, patient_id FK, type, description, recorded_at)

CareRecord (id, patient_id FK, worker_id FK, content, ai_score, created_at)

Schedule (id, worker_id FK, patient_id FK, start_time, end_time, status)

Checkin (id, worker_id FK, patient_id FK, session_id FK, start_time, end_time, content, status)

Complaint (id, patient_id FK, worker_id FK, content, status, created_at, resolved_at)

AlertConfig (id, key, value, description)   // 键值对存配置，如 heart_rate_min=60

Session (id, patient_id FK, worker_id FK, status[active|pending_review|approved|rejected], created_at)
  ↓ 1:N
ChatMessage (id, session_id FK, role[user|assistant], content, created_at)
```

## AI 模块流程

### 病人审核（review）
```
护工确认提交 → 取 session 全部消息 → 拼装 prompt →
AI 解析病人信息 → 输出标准 JSON → Pydantic 校验 →
审核状态改为 pending_review → 通知管理员
```

### 记录补齐（complete）
```
护工提交打卡内容 → AI 逐项检查完整性（必填项列表） →
有缺失 → 返回缺失项 + 追问 → 护工补充后再次提交 →
无缺失 → 统计入库
```

### 预警分析（analyze）
```
定时任务触发 → 拉取所有 active 病人 + 近期 CareRecord →
批量提交 AI → 逐人输出风险等级 + 依据 →
高风险项 → 生成 Alert 记录 → 通知管理员和对应护工
```

## 统一响应格式

```json
{
  "code": 200,
  "message": "success",
  "data": { }
}
```

分页响应：

```json
{
  "code": 200,
  "message": "success",
  "data": [ ],
  "total": 100,
  "page": 1,
  "pageSize": 20
}
```

## 错误码

| code | 含义 |
|------|------|
| 200 | 成功 |
| 400 | 参数校验失败 |
| 401 | 未登录 / token 过期 |
| 403 | 无权限（护工访问机构接口） |
| 404 | 资源不存在 |
| 409 | 状态冲突（重复打卡等） |
| 500 | 服务端内部错误 |

## 安全规范

- 密码 bcrypt 加盐存储，禁止明文
- JWT 有效期 24h，过期需重新登录
- 护工只能访问自己的 session/排班/记录
- 管理员可访问全量，路由层用 `Depends(get_current_admin)` 控制
