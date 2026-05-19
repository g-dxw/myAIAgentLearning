# 养老管理系统 — 开发架构设计文档

| 字段 | 内容 |
|------|------|
| 文档版本 | v1.0 |
| 最后更新 | 2026-05-18 |
| 依据 PRD | prd-v1.md (Final) |
| 状态 | 已定稿 |

---

## 目录

1. [总体架构概览](#1-总体架构概览)
2. [数据库完整设计](#2-数据库完整设计)
3. [后端架构设计](#3-后端架构设计)
4. [前端架构设计](#4-前端架构设计)
5. [AI Agent 模块设计](#5-ai-agent-模块设计)
6. [认证与权限设计](#6-认证与权限设计)
7. [排班管理双入口设计](#7-排班管理双入口设计)
8. [打卡与护理记录流程设计](#8-打卡与护理记录流程设计)
9. [缺勤统计设计](#9-缺勤统计设计)
10. [路由总览](#10-路由总览)
11. [实施顺序](#11-实施顺序)

---

## 1. 总体架构概览

### 1.1 系统分层

```
┌──────────────────────────────────────────────────────────────┐
│                    前端 (React + TypeScript)                  │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌───────────┐  │
│  │ 机构端    │  │ 护工端   │  │  共享组件  │  │ 工具/服务 │  │
│  │ (Admin)  │  │ (Worker) │  │           │  │           │  │
│  └────┬─────┘  └────┬─────┘  └────────────┘  └───────────┘  │
│       │             │                                        │
│       └──────┬──────┘                                        │
│              │ HTTP (fetch)                                  │
│        JWT in Authorization Header                           │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                  后端 (FastAPI + Python)                      │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌───────────┐  │
│  │ Routers  │→ │ Services │→ │   Models   │→ │ Database  │  │
│  │ (路由层) │  │ (业务层) │  │  (ORM)     │  │ (SQLite)  │  │
│  └──────────┘  └────┬─────┘  └────────────┘  └───────────┘  │
│                     │                                         │
│              ┌──────▼──────┐                                  │
│              │  AI Agent   │  (Anthropic SDK)                  │
│              │ 模块        │                                  │
│              └─────────────┘                                  │
└───────────────────────────────────────────────────────────────┘
```

### 1.2 技术选型

| 层级 | 方案 | 说明 |
|------|------|------|
| 前端框架 | React 18 + TypeScript | SPA |
| 构建工具 | Vite | 开发服务器 + 生产构建 |
| 路由 | React Router v6 | 嵌套路由 + 角色守卫 |
| 状态管理 | React Context + useReducer | 仅 Auth 全局，其余页面级 |
| HTTP 请求 | fetch + 自定义封装 | 无 axios |
| UI 组件库 | Ant Design 5 | antd + @ant-design/icons，全局化配置中文 |
| 后端框架 | FastAPI | Python async web 框架 |
| ORM | SQLAlchemy 2.0 | 声明式映射 |
| 数据校验 | Pydantic v2 | 请求/响应模型 |
| 数据库迁移 | Alembic | 版本化管理 |
| 认证 | JWT (python-jose) | 24h 有效期，无 refresh token |
| 密码哈希 | bcrypt (passlib) | |
| AI | Anthropic SDK | Claude API |
| CORS | fastapi.middleware.cors | |

### 1.3 目录结构（完整）

```
day07/
├── CLAUDE.md                      # 项目指导文件
├── DEVELOPMENT_PLAN.md            # 开发步骤计划
├── docs/
│   └── architecture.md            # 本文档
│
├── backend/
│   ├── main.py                    # FastAPI 入口
│   ├── config.py                  # 配置（环境变量读取）
│   ├── dependencies.py            # 依赖注入（get_db, get_current_user, get_current_admin, get_current_worker）
│   ├── seed.py                    # 种子数据（默认管理员账号）
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── auth.py                # 认证（登录/获取当前用户）
│   │   ├── worker.py              # 护工 CRUD
│   │   ├── patient.py             # 病人 CRUD + 分配护工
│   │   ├── approval.py            # 病人审核（自提自审）
│   │   ├── schedule.py            # 排班管理 + 双入口视图
│   │   ├── checkin.py             # 打卡 + 护理记录提交
│   │   ├── record.py              # 护理记录查询（管理端/护工端）
│   │   ├── absenteeism.py         # 出勤统计 + 旷工纠正
│   │   ├── session.py             # AI Agent 对话
│   │   └── settings.py            # 系统管理（密码重置等）
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py                # Base + TimestampMixin
│   │   ├── user.py                # 用户表（管理员 + 护工账号）
│   │   ├── worker.py              # 护工信息
│   │   ├── patient.py             # 病人信息
│   │   ├── special_cond.py        # 病人特殊情况
│   │   ├── care_record.py         # 护理记录
│   │   ├── schedule.py            # 排班表
│   │   ├── schedule_log.py        # 排班变更日志（新增）
│   │   ├── checkin.py             # 打卡记录
│   │   ├── absenteeism.py         # 缺勤记录（新增，含预留绩效字段）
│   │   ├── patient_version.py     # 病人档案版本追踪（新增）
│   │   ├── reminder.py            # 提醒记录（新增）
│   │   ├── session.py             # AI 对话 session
│   │   └── chat_message.py        # 对话消息
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── common.py              # ApiResponse[T], PageResult[T], PageParams
│   │   ├── auth.py                # LoginRequest, LoginResponse, UserOut
│   │   ├── worker.py              # WorkerCreate, WorkerUpdate, WorkerOut, WorkerStatusUpdate
│   │   ├── patient.py             # PatientCreate, PatientUpdate, PatientOut, PatientAssign
│   │   ├── special_cond.py        # SpecialConditionCreate, SpecialConditionOut
│   │   ├── schedule.py            # ScheduleCreate, ScheduleUpdate, ScheduleOut, ScheduleLogOut
│   │   ├── checkin.py             # CheckinStart, CheckinSubmit, CheckinMakeup, CheckinOut
│   │   ├── record.py              # CareRecordOut
│   │   ├── absenteeism.py         # AbsenteeismOut, AbsenteeismCorrect
│   │   ├── session.py             # SessionCreate, MessageAdd, SessionOut, MessageOut, ExtractResult, ConfirmSubmit
│   │   ├── patient_version.py     # PatientVersionOut
│   │   ├── reminder.py            # ReminderOut
│   │   └── settings.py            # PasswordReset
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth.py                # 登录校验、JWT 签发/验证
│   │   ├── worker.py              # 护工 CRUD 业务（含自动创建 User）
│   │   ├── patient.py             # 病人 CRUD 业务
│   │   ├── approval.py            # 审核流程业务
│   │   ├── schedule.py            # 排班业务（含冲突检测）
│   │   ├── checkin.py             # 打卡业务（含补卡、旷工自动标记）
│   │   ├── record.py              # 护理记录查询业务
│   │   ├── absenteeism.py         # 出勤统计业务
│   │   ├── session.py             # AI 对话业务
│   │   ├── reminder.py            # 提醒业务
│   │   └── settings.py            # 系统管理业务
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── client.py              # Anthropic SDK 封装
│   │   ├── extract.py             # 从护工对话提取病人信息
│   │   └── prompts/
│   │       ├── extract.md         # 信息提取 System Prompt
│   │       └── completeness.md    # 完整性校验 System Prompt
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── response.py            # 统一响应封装 ok() / fail()
│   │   └── security.py            # JWT 工具、密码哈希
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── jobs.py                # 定时任务（旷工自动标记、服务结束提醒）
│   └── migrations/                # Alembic 迁移文件目录
│       ├── env.py
│       ├── script.py.mako
│       └── versions/
│           └── 001_init.py        # 初始迁移
│
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── main.tsx               # 入口
│   │   ├── App.tsx                # 根组件 + 路由注册
│   │   ├── App.css
│   │   ├── contexts/
│   │   │   └── AuthContext.tsx     # AuthProvider + useAuth
│   │   ├── components/
│   │   │   ├── RoleGuard.tsx       # 按角色渲染 AdminLayout / WorkerLayout
│   │   │   └── StatusBadge.tsx     # 状态标签组件（封装 antd Tag）
│   │   ├── pages/
│   │   │   ├── LoginPage.tsx       # 登录页
│   │   │   ├── admin/
│   │   │   │   ├── AdminLayout.tsx     # 机构端布局（侧边栏+顶栏）
│   │   │   │   ├── AdminDashboard.tsx  # 机构端首页
│   │   │   │   ├── WorkerList.tsx      # 护工列表
│   │   │   │   ├── WorkerDetail.tsx    # 护工详情/编辑
│   │   │   │   ├── PatientList.tsx     # 病人列表
│   │   │   │   ├── PatientDetail.tsx   # 病人详情（含特殊情况、版本历史）
│   │   │   │   ├── PatientApproval.tsx # 病人审核列表
│   │   │   │   ├── ScheduleView.tsx    # 排班管理（双入口视图）
│   │   │   │   ├── RecordList.tsx      # 护理记录全量查询
│   │   │   │   ├── AbsenteeismList.tsx # 出勤统计列表
│   │   │   │   └── SettingsPage.tsx    # 系统设置（密码重置等）
│   │   │   └── worker/
│   │   │       ├── WorkerLayout.tsx    # 护工端布局（底部导航）
│   │   │       ├── WorkerDashboard.tsx # 护工端首页
│   │   │       ├── MySchedule.tsx      # 我的排班（卡片列表）
│   │   │       ├── ScheduleDetail.tsx  # 排班详情（含开始服务按钮）
│   │   │       ├── MyPatientList.tsx   # 我的病人列表
│   │   │       ├── SessionChat.tsx     # AI 对话页（核心功能）
│   │   │       ├── CheckinForm.tsx     # 打卡/护理记录表单
│   │   │       ├── MakeupCheckin.tsx   # 补卡页面
│   │   │       ├── MyRecordList.tsx    # 我的护理记录
│   │   │       └── ReminderList.tsx    # 提醒列表
│   │   ├── services/
│   │   │   ├── request.ts          # 统一请求封装
│   │   │   ├── auth.ts             # 认证 API
│   │   │   ├── worker.ts           # 护工 API
│   │   │   ├── patient.ts          # 病人 API
│   │   │   ├── schedule.ts         # 排班 API
│   │   │   ├── checkin.ts          # 打卡 API
│   │   │   ├── record.ts           # 护理记录 API
│   │   │   ├── absenteeism.ts      # 出勤统计 API
│   │   │   ├── session.ts          # AI 对话 API
│   │   │   ├── reminder.ts         # 提醒 API
│   │   │   └── settings.ts         # 系统管理 API
│   │   ├── types/
│   │   │   ├── api.ts              # ApiResponse, PageResult, PageParams
│   │   │   ├── auth.ts             # User, LoginForm
│   │   │   ├── worker.ts           # Worker, WorkerFormData
│   │   │   ├── patient.ts          # Patient, PatientFormData, SpecialCondition
│   │   │   ├── schedule.ts         # Schedule, ScheduleLog
│   │   │   ├── checkin.ts          # CheckinRecord
│   │   │   ├── record.ts           # CareRecord
│   │   │   ├── absenteeism.ts      # AbsenteeismRecord
│   │   │   ├── session.ts          # Session, ChatMessage, ExtractResult
│   │   │   ├── reminder.ts         # Reminder
│   │   │   └── settings.ts         # PasswordReset
│   │   └── utils/
│   │       ├── constants.ts        # 常量（状态枚举、角色等）
│   │       ├── format.ts           # 格式化工具（日期、状态文案）
│   │       └── storage.ts          # localStorage 封装
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── .eslintrc.cjs
│
└── database/
    └── db.sqlite                   # SQLite 数据库文件
```

---

## 2. 数据库完整设计

### 2.1 完整 ER 关系

```
User ──1:1──> Worker ──1:N──> Checkin
                              │
Worker ──1:N──> Schedule ──N:1──> Patient
              │
Schedule ──1:N──> ScheduleLog
Schedule ──1:1──> Reminder
Schedule ──1:1──> Absenteeism

Patient ──1:N──> SpecialCondition
Patient ──1:N──> CareRecord
Patient ──1:N──> PatientVersion
Patient ──1:N──> Session ──1:N──> ChatMessage

Worker ──1:N──> Session
Worker ──1:N──> Absenteeism
Worker ──1:N──> Reminder
Worker ──1:N──> CareRecord
```

### 2.2 各表完整定义

#### 2.2.1 User（用户账号表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | |
| username | String(50) | UNIQUE, NOT NULL | 登录用户名 |
| password_hash | String(128) | NOT NULL | bcrypt 哈希后密码 |
| role | String(10) | NOT NULL, default='worker' | admin / worker |
| created_at | DateTime | NOT NULL, default=now | |

关系：
- Worker: 1:1 关联（worker 角色必有对应 Worker 记录；admin 角色无 Worker 记录）

种子数据：
- admin / bcrypt("fd7105203322") / role='admin'

#### 2.2.2 Worker（护工信息表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | |
| user_id | Integer | FK→user.id, UNIQUE, NOT NULL | 关联 User 账号 |
| name | String(50) | NOT NULL | 姓名 |
| phone | String(20) | NOT NULL | 手机号 |
| id_card | String(18) | NOT NULL | 身份证号（不可修改） |
| avatar | String(255) | NULLABLE | 头像 URL |
| status | String(10) | NOT NULL, default='active' | active / inactive / deleted |
| created_at | DateTime | NOT NULL, default=now | |

索引：
- `ix_worker_status` ON (status)
- `ix_worker_name` ON (name)

业务规则：
- 新增时自动创建关联 User（username=phone, password=id_card 后 6 位）
- 停用时自动取消所有待执行排班（status=assigned 的 Schedule → cancelled）
- 删除时：有历史关联数据则逻辑删除（status=deleted），无关联数据则物理删除

#### 2.2.3 Patient（病人信息表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | |
| name | String(50) | NOT NULL | 姓名 |
| age | Integer | NOT NULL | 年龄 |
| gender | String(4) | NOT NULL | 男/女 |
| insurance_type | String(20) | NOT NULL | 医保类型：城镇职工/城乡居民/自费/其他 |
| phone | String(20) | NOT NULL | 联系电话 |
| address | String(200) | NOT NULL | 居住地址 |
| emergency_contact | String(100) | NOT NULL | 紧急联系人（姓名+关系+电话） |
| guardian_info | Text | NULLABLE | 监护人情况（护工补充） |
| disease_info | Text | NULLABLE | 基础疾病信息（护工补充） |
| care_requirements | Text | NULLABLE | 照护要求（护工补充） |
| personality | Text | NULLABLE | 性格特点（护工补充） |
| status | String(10) | NOT NULL, default='pending' | active / pending |
| assigned_worker_id | Integer | FK→worker.id, NULLABLE | 所属护工 |
| last_updater_id | Integer | NULLABLE | 最后更新人 ID |
| update_method | String(20) | NULLABLE | admin_manual / ai_supplement |
| updated_at | DateTime | NULLABLE | 最后更新时间 |
| created_at | DateTime | NOT NULL, default=now | |

索引：
- `ix_patient_status` ON (status)
- `ix_patient_assigned_worker` ON (assigned_worker_id)
- `ix_patient_name` ON (name)

关系：
- assigned_worker → Worker: N:1
- special_conditions: 1:N → SpecialCondition
- care_records: 1:N → CareRecord
- schedules: 1:N → Schedule
- checkins: 1:N → Checkin
- sessions: 1:N → Session
- versions: 1:N → PatientVersion

版本追踪（3 个字段直接在 Patient 表上）：
- last_updater_id: 最后更新人 ID（可能是 worker_id 或 admin_id）
- update_method: admin_manual（管理员手动）/ ai_supplement（AI 补充）
- updated_at: 最后更新时间

#### 2.2.4 SpecialCondition（病人特殊情况表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | |
| patient_id | Integer | FK→patient.id, NOT NULL | |
| type | String(50) | NOT NULL | 固定 4 值：死亡/就医/外出/其他 |
| description | String(500) | NOT NULL | 具体情况描述 |
| recorded_at | DateTime | NOT NULL, default=now | |

#### 2.2.5 Schedule（排班表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | |
| worker_id | Integer | FK→worker.id, NOT NULL | |
| patient_id | Integer | FK→patient.id, NOT NULL | |
| start_time | DateTime | NOT NULL | 排班开始时间 |
| end_time | DateTime | NOT NULL | 排班结束时间 |
| status | String(15) | NOT NULL, default='assigned' | assigned / in_progress / completed / cancelled |

索引：
- `ix_schedule_date` ON (start_time, end_time)
- `ix_schedule_worker_date` ON (worker_id, start_time)
- `ix_schedule_patient_date` ON (patient_id, start_time)
- `ix_schedule_status` ON (status)

关系：
- worker → Worker: N:1
- patient → Patient: N:1
- schedule_logs: 1:N → ScheduleLog

冲突检测规则：
- 同一护工在同一时间段不可有多个排班
- 同一病人在同一时间段不可有多个排班
- 已停用/删除的护工不可参与排班
- 已开始的排班不可修改
- 进行中的排班不可取消

#### 2.2.6 ScheduleLog（排班变更日志表 — 新增）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | |
| schedule_id | Integer | FK→schedule.id, NOT NULL | |
| action | String(20) | NOT NULL | created / cancelled / substituted |
| operator_id | Integer | FK→user.id, NOT NULL | 操作人（管理员） |
| original_worker_id | Integer | FK→worker.id, NULLABLE | 原护工（代班时记录） |
| new_worker_id | Integer | FK→worker.id, NULLABLE | 新护工（代班时记录） |
| remark | Text | NULLABLE | 操作说明 |
| created_at | DateTime | NOT NULL, default=now | |

#### 2.2.7 Checkin（打卡记录表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | |
| worker_id | Integer | FK→worker.id, NOT NULL | |
| patient_id | Integer | FK→patient.id, NOT NULL | |
| schedule_id | Integer | FK→schedule.id, NULLABLE | 关联排班（可为空，补卡可不关联） |
| start_time | DateTime | NOT NULL | 打卡开始时间 |
| end_time | DateTime | NULLABLE | 打卡结束时间 |
| content | String(2000) | NULLABLE | 护理记录内容 |
| status | String(15) | NOT NULL, default='started' | started / completed / absent |
| is_makeup | Boolean | NOT NULL, default=false | 是否为补卡 |
| created_at | DateTime | NOT NULL, default=now | |

索引：
- `ix_checkin_worker` ON (worker_id)
- `ix_checkin_patient` ON (patient_id)
- `ix_checkin_date` ON (start_time)
- `ix_checkin_status` ON (status)

变更说明：
- 移除旧状态：submitted, incomplete（Phase 1 不做 AI 完整性评分）
- 新增：absent（旷工状态）
- 新增：is_makeup 标记
- schedule_id 改为可空（支持补卡不关联排班）

#### 2.2.8 CareRecord（护理记录表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | |
| patient_id | Integer | FK→patient.id, NOT NULL | |
| worker_id | Integer | FK→worker.id, NOT NULL | |
| content | String(2000) | NOT NULL | 护理记录内容 |
| created_at | DateTime | NOT NULL, default=now | |

变更说明：
- 移除 ai_score 字段（Phase 1 不做 AI 评分）
- Phase 1 提交后不可修改

#### 2.2.9 Absenteeism（缺勤记录表 — 新增）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | |
| schedule_id | Integer | FK→schedule.id, NOT NULL | 关联排班 |
| worker_id | Integer | FK→worker.id, NOT NULL | |
| patient_id | Integer | FK→patient.id, NOT NULL | |
| status | String(20) | NOT NULL, default='absent' | absent / corrected |
| auto_marked_at | DateTime | NOT NULL | 系统自动标记时间 |
| corrected_at | DateTime | NULLABLE | 管理员纠正时间 |
| corrected_by | Integer | FK→user.id, NULLABLE | 纠正人（管理员） |
| correction_reason | Text | NULLABLE | 纠正原因 |
| score | Integer | NULLABLE | **预留**：绩效扣分，Phase 1 不使用 |
| performance_level | String(20) | NULLABLE | **预留**：考核等级，Phase 1 不使用 |
| created_at | DateTime | NOT NULL, default=now | |

索引：
- `ix_absenteeism_worker` ON (worker_id)
- `ix_absenteeism_date` ON (auto_marked_at)
- `ix_absenteeism_status` ON (status)

业务规则：
- 排班结束 1 小时后未提交护理记录 → 自动创建 Absenteeism 记录
- 管理员可纠正（status → corrected），需填写纠正原因
- 预留 score 和 performance_level 供 Phase 2+ 使用

#### 2.2.10 PatientVersion（病人档案版本表 — 新增）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | |
| patient_id | Integer | FK→patient.id, NOT NULL | |
| updater_id | Integer | NOT NULL | 更新人 ID |
| update_method | String(20) | NOT NULL | admin_manual / ai_supplement |
| changed_fields | Text | NOT NULL | JSON，记录变更的字段名和前后值 |
| created_at | DateTime | NOT NULL, default=now | |

索引：
- `ix_patient_version_patient` ON (patient_id)
- `ix_patient_version_created` ON (created_at)

#### 2.2.11 Reminder（提醒记录表 — 新增）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | |
| worker_id | Integer | FK→worker.id, NOT NULL | |
| schedule_id | Integer | FK→schedule.id, NOT NULL | |
| type | String(20) | NOT NULL | 未提交提醒 |
| message | Text | NOT NULL | 提醒内容 |
| is_read | Boolean | NOT NULL, default=false | 是否已读 |
| created_at | DateTime | NOT NULL, default=now | |

索引：
- `ix_reminder_worker` ON (worker_id)
- `ix_reminder_read` ON (is_read)

#### 2.2.12 Session（AI 对话 Session 表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | |
| patient_id | Integer | FK→patient.id, NOT NULL | |
| worker_id | Integer | FK→worker.id, NOT NULL | |
| status | String(15) | NOT NULL, default='ongoing' | ongoing / completed |
| summary | Text | NULLABLE | AI 自动生成的历史摘要 |
| created_at | DateTime | NOT NULL, default=now | |

索引：
- `ix_session_patient` ON (patient_id)
- `ix_session_worker` ON (worker_id)

变更说明（相对于旧架构）：
- 移除 PENDING_REVIEW, APPROVED, REJECTED 状态
- 改为 ONGOING（持续累积）/ COMPLETED（已归档）
- 新增 summary 字段用于存储 AI 自动历史摘要
- 每个病人对每个护工至多有一个 ONGOING 的 Session

#### 2.2.13 ChatMessage（对话消息表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | |
| session_id | Integer | FK→session.id, NOT NULL | |
| role | String(10) | NOT NULL | user / assistant |
| content | String(2000) | NOT NULL | 消息内容 |
| created_at | DateTime | NOT NULL, default=now | |

### 2.3 表间关系汇总

```
User (1) ──→ (1) Worker (1) ──→ (N) Schedule
                                    │
Worker (1) ──→ (N) Checkin          │
Worker (1) ──→ (N) Session          ├── (1) ScheduleLog
Worker (1) ──→ (N) CareRecord       ├── (1) Reminder
Worker (1) ──→ (N) Absenteeism      └── (1) Absenteeism
Worker (1) ──→ (N) Reminder
                                    Patient (1) ──→ (N) SpecialCondition
Session (1) ──→ (N) ChatMessage     Patient (1) ──→ (N) CareRecord
Patient (1) ──→ (N) Session         Patient (1) ──→ (N) PatientVersion
Patient (N) ──→ (1) Worker          Patient (N) ──→ (1) Worker (assigned_worker_id)
```

### 2.4 迁移注意事项

Alembic 初始迁移（001_init.py）需包含：

1. 旧表：user, worker, patient, special_condition, care_record, schedule, checkin, session, chat_message
   - patient 表需包含所有新增字段（insurance_type, emergency_contact, guardian_info, disease_info, care_requirements, personality, assigned_worker_id, last_updater_id, update_method, updated_at）
   - checkin 表需使用最终设计（schedule_id 可空，is_makeup 字段，status 枚举简化）
   - session 表需使用最终设计（summary 字段，status 改为 ongoing/completed）
   - care_record 表不包含 ai_score 字段

2. 新增表：schedule_log, absenteeism, patient_version, reminder

3. 所有索引在迁移中显式定义

---

## 3. 后端架构设计

### 3.1 模块分层与职责

```
请求 → Router（参数解析+权限校验） → Service（业务逻辑） → Model（ORM操作） → Database
                                                                     ↓
                                                              AI Agent（Anthropic）
```

**Router 层**职责：
- HTTP 方法、路径、参数定义
- Pydantic 入参校验
- 角色权限守卫（Depends(get_current_admin) / Depends(get_current_worker)）
- 调用 Service 层并封装统一响应

**Service 层**职责：
- 所有业务逻辑
- 事务管理
- 调用 AI Agent
- 异常处理和校验

**Model 层**职责：
- SQLAlchemy ORM 定义
- 表关系、索引

### 3.2 依赖注入设计 (`backend/dependencies.py`)

```python
# 数据库 Session
def get_db() -> Generator[Session, None, None]

# 当前登录用户（任意角色）
def get_current_user(token: str = Header(...), db: Session = Depends(get_db)) -> User

# 当前管理员
def get_current_admin(user: User = Depends(get_current_user)) -> User

# 当前护工
def get_current_worker(user: User = Depends(get_current_user)) -> Worker
```

### 3.3 路由模块一览

见第 [10 章](#10-路由总览)。

### 3.4 常用工具函数

#### `backend/utils/response.py`

```python
def ok(data: Any = None, message: str = "success") -> dict:
    """统一成功响应"""
    return {"code": 200, "message": message, "data": data}

def ok_page(data: list, total: int, page: int, page_size: int) -> dict:
    """分页成功响应"""
    return {
        "code": 200, "message": "success",
        "data": data, "total": total,
        "page": page, "pageSize": page_size
    }

def fail(code: int = 400, message: str = "error", data: Any = None) -> dict:
    """统一失败响应"""
    return {"code": code, "message": message, "data": data}
```

#### `backend/utils/security.py`

```python
def hash_password(password: str) -> str
def verify_password(password: str, hashed: str) -> bool
def create_access_token(user_id: int, role: str, expires_delta: timedelta = timedelta(hours=24)) -> str
def decode_token(token: str) -> dict
```

### 3.5 异常处理

FastAPI 全局异常处理器：

```python
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": "服务器内部错误", "data": None}
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "message": exc.detail, "data": None}
    )
```

常见的 HTTPException 场景：

| HTTP 状态码 | 触发场景 |
|-------------|---------|
| 400 | 参数校验失败、逻辑校验失败（如冲突检测） |
| 401 | Token 缺失/过期/无效 |
| 403 | 角色权限不足（护工访问管理接口） |
| 404 | 资源不存在 |
| 409 | 状态冲突（重复打卡、排班冲突） |
| 500 | 服务端内部错误 |

### 3.6 关键 Service 实现要点

#### Worker Service
- `create_worker()`: 在一个事务中完成 Worker 创建 + User 创建（username=phone, password=id_card[-6:]）
- `delete_worker()`: 先检查关联数据，有关联则逻辑删除（status=deleted），无则物理删除
- `update_status()`: 停用时自动取消该护工所有 assigned 状态的 Schedule

#### Patient Service
- `create_patient()`: 管理员直接新增，status=pending，同时创建一条 PatientVersion 记录
- `approve()`: status → active，记录操作日志
- `reject()`: 记录驳回原因，病人状态保持 pending 或改为 rejected
- `assign_worker()`: 重新分配护工
- `update_patient()`: 记录变更到 PatientVersion 表

#### Schedule Service
- `create_schedule()`: 检查冲突（worker 和 patient 在同一时间段），通过后创建 + 写 ScheduleLog
- `cancel_schedule()`: 仅允许 assigned 状态，写 ScheduleLog
- `get_schedule_view()`: 根据参数返回护工视角或病人视角的排班矩阵数据
- 双入口视图数据格式：

**护工视角返回格式**：
```json
{
  "workers": [
    {
      "id": 1, "name": "张三",
      "slots": [
        {"hour": 8, "patient_name": "李四", "patient_id": 1, "schedule_id": 10},
        {"hour": 9, "patient_name": null, "patient_id": null, "schedule_id": null},
        ...
      ]
    }
  ]
}
```

**病人视角返回格式**：
```json
{
  "patients": [
    {
      "id": 1, "name": "李四",
      "slots": [
        {"hour": 8, "worker_name": "张三", "worker_id": 1, "schedule_id": 10},
        {"hour": 9, "worker_name": null, "worker_id": null, "schedule_id": null},
        ...
      ]
    }
  ]
}
```

#### Checkin Service
- `start_checkin()`: 从排班详情页触发，创建 Checkin 记录，Schedule 状态 → in_progress
- `submit_checkin()`: 填写护理记录 → 创建 CareRecord → Checkin 状态 → completed → Schedule 状态 → completed
- `makeup_checkin()`: 当天补卡，schedule_id 可为空，需校验时间边界（不允许跨日）
- 旷工自动标记：scheduler/jobs.py 定时检查排班结束 1 小时后未提交记录的排班

#### Session Service
- `get_or_create_session()`: 每个 worker + patient 组合至多一个 ONGOING session
- `add_message()`: 添加消息，调用 AI 获取回复
- `extract_info()`: 调用 AI 从对话中提取结构化病人信息 → 返回给护工编辑
- `confirm_submit()`: 护工二次确认后，调用 AI 做完整性校验 → 通过则更新 Patient 表 + 创建 PatientVersion

---

## 4. 前端架构设计

### 4.1 路由设计

```
/login                         → LoginPage（公开）
/                              → RoleGuard 重定向

/admin                         → AdminLayout（需 admin 角色）
  /admin                       → redirect to /admin/dashboard
  /admin/dashboard             → AdminDashboard（首页看板）
  /admin/workers               → WorkerList
  /admin/workers/new           → WorkerDetail（新增模式）
  /admin/workers/:id           → WorkerDetail（编辑模式）
  /admin/patients              → PatientList
  /admin/patients/new          → PatientDetail（新增模式）
  /admin/patients/:id          → PatientDetail（详情模式）
  /admin/patients/approvals    → PatientApproval（审核列表）
  /admin/schedules             → ScheduleView（排班管理）
  /admin/records               → RecordList（护理记录）
  /admin/absenteeism           → AbsenteeismList（出勤统计）
  /admin/settings              → SettingsPage（系统设置）

/worker                        → WorkerLayout（需 worker 角色）
  /worker                      → redirect to /worker/dashboard
  /worker/dashboard            → WorkerDashboard（工作台首页）
  /worker/schedules            → MySchedule（我的排班列表）
  /worker/schedules/:id        → ScheduleDetail（排班详情，含开始服务）
  /worker/patients             → MyPatientList（我的病人列表）
  /worker/patients/:id/chat    → SessionChat（AI 对话）
  /worker/checkin/makeup       → MakeupCheckin（补卡）
  /worker/records              → MyRecordList（我的护理记录）
  /worker/reminders            → ReminderList（提醒列表）
```

### 4.2 组件树

```
App
├── AuthProvider (Context)
│   ├── LoginPage
│   └── RoleGuard
│       ├── AdminLayout
│       │   ├── Sidebar (导航菜单: 护工/病人/排班/记录/出勤/设置)
│       │   ├── Header (用户信息/退出)
│       │   └── <Outlet>
│       │       ├── AdminDashboard
│       │       ├── WorkerList → antd Table + SearchBar + Modal(WorkerForm)
│       │       ├── PatientList → antd Table + SearchBar
│       │       ├── PatientDetail → PatientForm + SpecialConditionList + VersionTimeline
│       │       ├── PatientApproval → antd Table + Modal(ApproveDialog)
│       │       ├── ScheduleView → ViewToggle + DatePicker + ScheduleMatrix
│       │       │   └── Modal(ScheduleForm)
│       │       ├── RecordList → antd Table + Filters
│       │       ├── AbsenteeismList → antd Table + CorrectDialog
│       │       └── SettingsPage → antd Form(PasswordReset)
│       │
│       └── WorkerLayout
│           ├── BottomNav (排班/病人/记录/提醒)
│           └── <Outlet>
│               ├── WorkerDashboard → antd Card + Statistic
│               ├── MySchedule → antd Card(ScheduleCardList)
│               ├── ScheduleDetail → PatientInfo + StartServiceBtn + RecordForm
│               ├── MyPatientList → antd Card(PatientCard) + 信息完整度进度
│               ├── SessionChat → Header + MessageList + InputArea + ExtractBtn
│               │   └── Modal(ExtractPreview): AI 提取结果 + 编辑 + 二次确认
│               ├── MakeupCheckin → antd Form(PatientSelect + TimeInput + ContentForm)
│               ├── MyRecordList → antd List(RecordCardList)
│               └── ReminderList → antd List(ReminderItem[])
│
└── ErrorBoundary
```

### 4.3 全局状态设计

```typescript
// AuthContext — 唯一全局状态
interface AuthContextValue {
  user: User | null;           // { id, username, name, role, avatar? }
  token: string | null;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  loading: boolean;
}
```

原则：Token 存储在 localStorage，页面刷新时从 localStorage 恢复 token 并调用 `/api/auth/me` 验证。

### 4.4 统一请求封装 (`src/services/request.ts`)

```typescript
// 自动注入:
// - baseURL: 从环境变量读取 VITE_API_BASE
// - Authorization: Bearer token (从 localStorage 读取)
// - Content-Type: application/json

// 统一错误处理:
// - 401 → 清除 token → 跳转 /login
// - 500 → 显示"服务端错误"
// - 非 200 → 从 message 字段读取错误信息

interface RequestConfig {
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  url: string;
  params?: Record<string, any>;  // query 参数
  body?: any;                     // JSON body
}

function request<T>(config: RequestConfig): Promise<T>;
```

### 4.5 组件通用状态规范

每个列表页必须处理三种状态，使用 antd 内置组件：

```typescript
// 每个数据获取页面遵循以下模式：
interface PageState<T> {
  loading: boolean;
  error: string | null;
  data: T[];
  total: number;
  page: number;
  pageSize: number;
}
```

对应渲染逻辑：
- `loading === true` → antd `<Spin />` 包裹内容区
- `error !== null` → antd `<Result status="error" />` 含重试按钮
- `data.length === 0` → antd `<Empty description="暂无数据" />`
- 正常 → antd `<Table>` 内置分页 / `<List>` + `<Pagination>`
- 弹窗二次确认 → antd `<Modal>` + 确认按钮，危险操作用 `<Popconfirm>`

### 4.6 护工端自适应适配

护工端采用移动优先的响应式设计，基于 antd 组件：
- 底部固定导航栏（4 个 Tab）：排班、病人、记录、提醒
- 全屏宽度适配（320px - 768px），使用 antd Grid 响应式布局
- 大字号、大按钮（antd Button size="large"）
- 卡片式布局（antd Card）替代表格
- antd ConfigProvider 全局设置中文语言包

### 4.7 机构端布局

使用 antd Layout 组件：
- 左侧固定 Sider（宽度 220px，可折叠），antd Menu 导航
- 顶部 Header（面包屑 + 用户信息 + 退出按钮）
- 主内容区 Content（右侧，min-width: 800px）

侧边栏菜单项：

```
📋 基础数据
  ├── 护工管理        /admin/workers
  └── 病人管理        /admin/patients
📅 排班中心
  └── 排班管理        /admin/schedules
📝 护理记录
  └── 护理记录        /admin/records
📊 出勤统计
  └── 出勤统计        /admin/absenteeism
⚙️ 系统设置
  └── 系统设置        /admin/settings
```

### 4.8 Ant Design 全局配置

`main.tsx` 入口：

```typescript
import { ConfigProvider, App } from 'antd';
import zhCN from 'antd/locale/zh_CN';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <ConfigProvider
    locale={zhCN}
    theme={{
      token: {
        colorPrimary: '#1677ff',  // 主题色，可按需调整
        borderRadius: 6,
      },
    }}
  >
    <App>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </App>
  </ConfigProvider>
);
```

antd 组件用法约定：
- 表单统一使用 `antd Form` + `useForm`，校验规则在 `rules` 中声明
- 表格统一使用 `antd Table`，内置分页（`pagination={{ pageSize: 20 }}`）
- 消息提示使用 `App.useApp().message` / `App.useApp().modal`（静态方法通过 App 组件注入，避免 ConfigProvider 上下文丢失）
- 图标使用 `@ant-design/icons`（如 `UserOutlined`, `PlusOutlined`, `ExclamationCircleOutlined`）
- 日期处理使用 antd `DatePicker`
- 所有文案为中文（zhCN 语言包）

---

## 5. AI Agent 模块设计

### 5.1 架构概览

```
护工消息 → Session Service → 历史摘要 + 近期消息 → AI Client → AI 回复
    ↓
护工点击"查看提取结果" → AI Client (提取 prompt) → 结构化 JSON
    ↓
护工编辑确认 → 二次确认 → AI Client (完整性校验 prompt) → 校验结果
    ↓
校验通过 → 更新 Patient 表 + 创建 PatientVersion
校验不通过 → 返回缺失列表 → 护工继续补充
```

### 5.2 模块文件结构

```
backend/ai/
├── __init__.py
├── client.py              # Anthropic SDK 封装
│   ├── chat(messages, system_prompt) → str          # 普通对话
│   └── extract_json(messages, system_prompt) → dict  # 提取结构化 JSON
├── extract.py             # 信息提取 + 完整性校验
│   ├── extract_patient_info(session_id, db) → dict   # 从对话提取病人信息
│   └── check_completeness(patient_id, db) → list     # 完整性校验
└── prompts/
    ├── extract.md         # 信息提取 System Prompt
    └── completeness.md    # 完整性校验 System Prompt
```

### 5.3 AI Client (`backend/ai/client.py`)

```python
class AIClient:
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)

    def chat(self, messages: list, system_prompt: str, max_tokens: int = 1024) -> str:
        """通用对话接口"""
        response = self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            system=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
        )
        return response.content[0].text

    def extract_json(self, messages: list, system_prompt: str) -> dict:
        """提取结构化 JSON，自动处理格式错误"""
        response = self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            system=system_prompt + "\n请只输出 JSON，不要包含其他文字。",
            messages=messages,
            max_tokens=1024,
        )
        text = response.content[0].text
        # 尝试从 markdown 代码块中提取 JSON
        # 尝试直接解析 JSON
        # 失败则抛异常
```

### 5.4 会话上下文策略

采用"保留全部历史 + AI 自动摘要"策略：

1. **存储**：所有 ChatMessage 保存在数据库
2. **摘要生成**：每次对话结束后（护工点击确认提交后），AI 自动生成本轮对话的摘要
3. **上下文构建**：护工进入同一病人的新对话轮次时
   - 先加载 session.summary（历史摘要）
   - 再加载最近 N 条消息（如最近 20 条）
   - 拼接后发给 AI

上下文构建伪代码：

```python
def build_context(session_id: str, db: Session) -> list:
    session = db.query(Session).get(session_id)

    context_messages = []

    # 1. 如果有历史摘要，以 system 消息形式注入
    if session.summary:
        context_messages.append({
            "role": "user",
            "content": f"[历史对话摘要]: {session.summary}"
        })
        context_messages.append({
            "role": "assistant",
            "content": "我已了解历史情况，请继续。"
        })

    # 2. 加载近期消息
    recent_messages = db.query(ChatMessage)\
        .filter(ChatMessage.session_id == session_id)\
        .order_by(ChatMessage.created_at.desc())\
        .limit(20)\
        .all()

    # 反转时间顺序
    for msg in reversed(recent_messages):
        context_messages.append({
            "role": msg.role,
            "content": msg.content
        })

    return context_messages
```

### 5.5 AI 信息提取流程

```
Step 1: 护工与 AI 对话补充病人信息（多轮）
Step 2: 护工点击「查看提取结果」
Step 3: 后端调用 extract_json()，system prompt 要求输出:
         {
           "guardian_info": "监护人情况描述",
           "disease_info": "基础疾病信息",
           "care_requirements": "照护要求",
           "personality": "性格特点"
         }
Step 4: 返回结构化数据给前端
Step 5: 护工在前端编辑各字段
Step 6: 护工点击「确认提交」→ 二次确认弹窗
Step 7: 后端调用完整性校验:
         - 检查 disease_info 是否非空
         - 检查 care_requirements 是否非空
         - 不强制要求一次完成所有字段
Step 8: 校验通过 → 更新 Patient 表字段 + 创建 PatientVersion
        校验不通过 → 返回缺失列表 → 护工继续补充
```

### 5.6 System Prompt 设计

#### `extract.md` — 信息提取

```
你是一个养老护理系统的 AI 助手。护工正在通过对话补充病人的详细信息。

请从对话中提取以下信息（以 JSON 格式输出）：
1. guardian_info（监护人情况）：监护人与病人的关系、联系方式等
2. disease_info（基础疾病信息）：病人患有的基础疾病
3. care_requirements（照护要求）：需要哪些照护服务
4. personality（性格特点）：病人的性格特征

注意：
- 只提取对话中明确提到的信息，不要编造
- 对于未提到的字段，输出空字符串
- 信息描述要详细完整
- 使用中文输出
```

#### `completeness.md` — 完整性校验

```
你是一个养老护理系统的数据校验 AI。

请检查以下病人信息是否完整：

必填字段：
1. 基础疾病信息（disease_info）
2. 照护要求（care_requirements）

如果所有必填字段都已填写，输出：{"is_complete": true, "missing_fields": []}
如果有字段缺失，输出：{"is_complete": false, "missing_fields": ["字段1", "字段2"]}

注意：
- 空字符串视为未填写
- 字段内容应合理且有实质信息
```

### 5.7 Session 生命周期

```
护工分配给病人（管理员操作）
  → Session 创建（status=ongoing）
    → 护工进入对话
      → 多轮对话补充信息
        → 查看提取结果 → 编辑 → 二次确认
          → 完整性校验
            → 通过 → 更新 Patient → 创建 PatientVersion
                     → AI 生成 summary → 更新 Session.summary
                     → Session 保持 ongoing（继续累积）
            → 不通过 → 返回缺失项 → 继续对话
```

生命周期图示：

```
时间线 →
┌─────────────────────────────────────────────────────────────┐
│ Session（ONGOING）持续累积                                    │
│                                                              │
│ 对话轮次 1 ──→ 提取+确认 ──→ 更新档案 ──→ AI 生成 summary     │
│                                                              │
│ 对话轮次 2（加载 summary + 近期消息）                          │
│     ──→ 提取+确认 ──→ 更新档案 ──→ AI 更新 summary             │
│                                                              │
│ ...（持续累积）                                               │
│                                                              │
│ 护工/管理员认为信息已完善 ──→ Session 标记为 COMPLETED         │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. 认证与权限设计

### 6.1 管理员账号

| 属性 | 值 |
|------|-----|
| 用户名 | admin |
| 初始密码 | fd7105203322 |
| 角色 | admin |
| 存储 | bcrypt 哈希后通过 seed.py 写入数据库 |
| 限制 | 不可删除、不可停用 |

### 6.2 护工账号

| 属性 | 值 |
|------|-----|
| 用户名 | phone（手机号） |
| 初始密码 | id_card 最后 6 位 |
| 角色 | worker |
| 创建 | 新增护工时在事务中自动创建 |
| 重置 | 管理员重置，密码恢复为身份证后 6 位 |

### 6.3 JWT 认证流程

```
登录请求 (POST /api/auth/login)
  ├── 查询 User (username)
  ├── 校验密码 (bcrypt)
  ├── 生成 JWT token (payload: { user_id, role }, exp: 24h)
  └── 返回 { token, user: { id, username, name, role, avatar } }

后续请求
  ├── Header: Authorization: Bearer <token>
  ├── get_current_user 依赖注入解码 token
  └── 根据角色限制访问

Token 过期
  └── 前端 401 拦截 → 清除 token → 跳转 /login
```

### 6.4 角色权限矩阵

| 接口 | admin | worker | 公开 |
|------|-------|--------|------|
| POST /api/auth/login | - | - | yes |
| GET /api/auth/me | yes | yes | - |
| 护工 CRUD | yes | - | - |
| 病人 CRUD | yes | - | - |
| 病人审核 | yes | - | - |
| 排班管理 | yes | - | - |
| 排班查看（我的） | - | yes | - |
| 护理记录全量 | yes | - | - |
| 护理记录（我的） | - | yes | - |
| 出勤统计 | yes | - | - |
| 旷工纠正 | yes | - | - |
| AI 对话 | - | yes | - |
| 打卡 | - | yes | - |
| 补卡 | - | yes | - |
| 密码重置 | yes | - | - |
| 提醒列表 | - | yes | - |

---

## 7. 排班管理双入口设计

### 7.1 排班视图数据结构

#### 护工视角（默认）

```
行 = 护工列表
列 = 当天 24 小时（0:00-23:00，共 24 列）

        0   1   2   3   4   5   6   7   8   9  10  11  ...  23
张三    │   │   │   │   │   │   │   │李四│李四│   │   │   │   │
李四    │   │   │   │   │   │   │   │   │   │王五│王五│   │   │
...
```

API 返回格式：

```json
GET /api/schedules?date=2026-05-18&view=worker

{
  "code": 200,
  "message": "success",
  "data": {
    "view": "worker",
    "date": "2026-05-18",
    "hours": [0, 1, 2, ..., 23],
    "rows": [
      {
        "worker_id": 1,
        "worker_name": "张三",
        "slots": [
          {"hour": 7, "schedule_id": null, "patient_id": null, "patient_name": null, "status": null},
          {"hour": 8, "schedule_id": 10, "patient_id": 5, "patient_name": "李四", "status": "assigned"},
          {"hour": 9, "schedule_id": 10, "patient_id": 5, "patient_name": "李四", "status": "assigned"},
          {"hour": 10, "schedule_id": null, ...},
          ...
        ]
      }
    ]
  }
}
```

#### 病人视角

```
行 = 病人列表
列 = 当天 24 小时

        0   1   2   3   4   5   6   7   8   9  10  11  ...  23
李四    │   │   │   │   │   │   │   │张三│张三│   │   │   │   │
王五    │   │   │   │   │   │   │   │   │   │李四│李四│   │   │
...
```

API 返回格式：

```json
GET /api/schedules?date=2026-05-18&view=patient

{
  "code": 200,
  "message": "success",
  "data": {
    "view": "patient",
    "date": "2026-05-18",
    "hours": [0, 1, 2, ..., 23],
    "rows": [
      {
        "patient_id": 5,
        "patient_name": "李四",
        "slots": [
          {"hour": 8, "schedule_id": 10, "worker_id": 1, "worker_name": "张三", "status": "assigned"},
          {"hour": 9, "schedule_id": 10, "worker_id": 1, "worker_name": "张三", "status": "assigned"},
          ...
        ]
      }
    ]
  }
}
```

### 7.2 排班操作

#### 新增排班（带冲突检测）

```json
POST /api/schedules
Body: {
  "worker_id": 1,
  "patient_id": 5,
  "start_time": "2026-05-18T08:00:00",
  "end_time": "2026-05-18T10:00:00"
}

成功响应: { "code": 200, "message": "success", "data": { "id": 10, ... } }

冲突响应: { "code": 409, "message": "排班冲突：护工张三在 08:00-10:00 已有排班", "data": null }
```

#### 取消排班

```json
DELETE /api/schedules/10

成功响应: { "code": 200, "message": "排班已取消", "data": null }
```

### 7.3 前端排班视图组件设计

`ScheduleView.tsx` 组件结构：

```
ScheduleView
├── ViewToggle (护工视角/病人视角 切换按钮)
├── DateNavigator (前一天/今天/后一天)
├── SearchFilter (按护工/病人姓名搜索过滤行)
├── ScheduleMatrix (核心排班矩阵)
│   ├── 左侧固定列：行标题（护工/病人姓名）
│   └── 右侧滚动区域：24 小时列
│       ├── 单元格：有排班 → 显示姓名（高亮背景）+ 点击弹出操作菜单
│       └── 单元格：空闲 → 显示为空白 + 点击弹出新增排班对话框
└── ScheduleDialog (新增/编辑排班弹窗)
    ├── WorkerSelect / PatientSelect（根据视图自动切换）
    ├── TimeRangePicker
    └── SaveButton + 冲突提示区
```

---

## 8. 打卡与护理记录流程设计

### 8.1 完整操作流

```
排班列表页（护工端）
  └── 点击排班卡片
       └── 排班详情页
            ├── 显示：病人信息、服务时间、地址
            ├── 状态：待服务（蓝色）/ 服务中（绿色）/ 已完成（灰色）/ 旷工（红色）
            ├── 按钮：开始服务（仅在 assigned 状态显示）
            └── 点击「开始服务」
                 ├── 创建 Checkin 记录 (status=started)
                 ├── Schedule 状态 → in_progress
                 └── 页面进入服务中模式
                      ├── 显示计时器
                      ├── 护理内容文本输入框
                      └── 提交按钮
                           └── 提交护理记录
                                ├── 创建 CareRecord
                                ├── Checkin 状态 → completed
                                ├── Schedule 状态 → completed
                                └── 页面恢复正常模式
```

### 8.2 补卡流程

```
护工端补卡入口（底部导航或首页快捷入口）
  └── 补卡页面
       ├── 病人选择（下拉列表：已分配的病人）
       ├── 服务开始时间（手动输入）
       ├── 服务结束时间（手动输入）
       ├── 护理记录内容（文本输入）
       ├── schedule_id = null（不关联排班）
       └── 提交
            ├── 校验：补卡时间是否跨日（不允许）
            ├── 创建 Checkin (is_makeup=true, schedule_id=null)
            ├── 创建 CareRecord
            └── 补卡记录在管理端标记为「补卡」
```

### 8.3 旷工自动标记

```python
# backend/scheduler/jobs.py

def auto_mark_absent():
    """每小时运行一次，检查排班结束1小时后未提交的记录"""
    one_hour_ago = datetime.now() - timedelta(hours=1)

    # 查询排班结束时间 > 1小时前，且状态为 assigned 的排班
    overdue_schedules = db.query(Schedule).filter(
        Schedule.end_time <= one_hour_ago,
        Schedule.status == ScheduleStatus.ASSIGNED,
        Schedule.status != ScheduleStatus.CANCELLED,
    ).all()

    for schedule in overdue_schedules:
        # 检查是否有对应的 completed Checkin
        checkin = db.query(Checkin).filter(
            Checkin.schedule_id == schedule.id,
            Checkin.status == CheckinStatus.COMPLETED,
        ).first()

        if not checkin:
            # 标记为旷工
            schedule.status = ScheduleStatus.COMPLETED  # 排班结束
            absent = Absenteeism(
                schedule_id=schedule.id,
                worker_id=schedule.worker_id,
                patient_id=schedule.patient_id,
                status="absent",
                auto_marked_at=datetime.now(),
            )
            db.add(absent)

            # 创建提醒
            reminder = Reminder(
                worker_id=schedule.worker_id,
                schedule_id=schedule.id,
                type="未提交提醒",
                message=f"您于 {schedule.start_time} 至 {schedule.end_time} 的服务未提交护理记录",
            )
            db.add(reminder)

    db.commit()
```

### 8.4 提醒机制

- 定时任务检查到未提交后 → 创建 Reminder 记录
- 护工端通过轮询（1 分钟间隔）获取未读提醒数量
- 底部导航栏显示红点标记
- 提醒列表页面展示所有未读和已读提醒

---

## 9. 缺勤统计设计

### 9.1 管理端出勤统计页面

**筛选条件**：
- 护工（必选，下拉列表）
- 日期范围（必选，开始日期 + 结束日期）

**统计展示**：

| 字段 | 说明 |
|------|------|
| 护工姓名 | |
| 应出勤次数 | 日期范围内排班总数 |
| 实际出勤次数 | 已提交护理记录的排班数 |
| 旷工次数 | Absenteeism 记录数 |
| 出勤率 | 实际出勤 / 应出勤 * 100% |

**操按钮**：
- 查看详情：点击某条记录展开该护工在日期范围内的每日出勤明细
- 纠正旷工：点击纠正按钮 → 弹出对话框填写纠正原因 → 提交

### 9.2 旷工纠正 API

```json
PATCH /api/absenteeism/:id/correct
Body: {
  "correction_reason": "护工当日请假已批准，因系统未提前取消排班导致误标记"
}

成功响应: { "code": 200, "message": "旷工状态已纠正", "data": null }
```

注意事项：
- 纠正后 absenteeism.status → corrected
- 记录 corrected_at, corrected_by, correction_reason
- 前端列表中的"旷工"状态更新为"已纠正"
- 保留纠正前的原始记录（不删除）

---

## 10. 路由总览

### 10.1 认证

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| POST | /api/auth/login | 公开 | 登录，返回 token + user |
| GET | /api/auth/me | admin/worker | 获取当前用户信息 |

### 10.2 护工管理

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /api/workers | admin | 护工列表（分页+筛选） |
| GET | /api/workers/:id | admin | 护工详情 |
| POST | /api/workers | admin | 新增护工（含自动创建 User） |
| PUT | /api/workers/:id | admin | 编辑护工 |
| PATCH | /api/workers/:id/status | admin | 启用/停用护工 |
| DELETE | /api/workers/:id | admin | 删除护工（逻辑/物理删除） |
| PATCH | /api/workers/:id/reset-password | admin | 重置护工密码 |

### 10.3 病人管理

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /api/patients | admin | 病人列表（分页+筛选） |
| GET | /api/patients/:id | admin | 病人详情（含完整字段） |
| POST | /api/patients | admin | 新增病人（status=pending，自审批） |
| PUT | /api/patients/:id | admin | 编辑病人 |
| POST | /api/patients/:id/assign | admin | 重新分配护工 |

### 10.4 病人审核

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /api/approvals | admin | 待审核病人列表（status=pending） |
| POST | /api/approvals/:id/approve | admin | 审核通过（status→active） |
| POST | /api/approvals/:id/reject | admin | 驳回（需填写原因） |

### 10.5 病人补充信息

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /api/patients/:id/versions | admin | 病人档案版本历史 |
| GET | /api/patients/:id/special-conditions | admin | 特殊情况列表 |
| POST | /api/patients/:id/special-conditions | admin | 新增特殊情况 |
| GET | /api/patients/:id/history | worker | 病人历史补充记录 |

### 10.6 排班管理

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /api/schedules | admin | 排班列表（按日期筛选，支持 view=worker\|patient） |
| POST | /api/schedules | admin | 新增排班（含冲突检测） |
| PUT | /api/schedules/:id | admin | 编辑排班 |
| DELETE | /api/schedules/:id | admin | 取消排班 |
| GET | /api/schedules/logs | admin | 排班变更日志 |
| GET | /api/schedules/my | worker | 我的排班（按日期） |

### 10.7 AI 对话

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /api/worker/patients | worker | 我的病人列表（含信息完整度） |
| POST | /api/sessions | worker | 创建/获取 session（每个病人唯一 ongoing） |
| GET | /api/sessions/:id | worker | 对话详情（含 messages） |
| POST | /api/sessions/:id/messages | worker | 发送消息（含 AI 回复） |
| POST | /api/sessions/:id/extract | worker | AI 提取病人信息 |
| POST | /api/sessions/:id/confirm | worker | 护工二次确认并提交（含完整性校验） |

### 10.8 打卡

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| POST | /api/checkin | worker | 开始服务（关联排班详情页） |
| POST | /api/checkin/:id/submit | worker | 提交护理记录（结束打卡） |
| POST | /api/checkin/makeup | worker | 补卡（schedule_id 可空） |
| GET | /api/checkin/my | worker | 我的打卡记录 |

### 10.9 护理记录

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /api/records | admin | 护理记录全量列表（筛选） |
| GET | /api/records/my | worker | 我的护理记录 |
| GET | /api/records/:id | admin/worker | 护理记录详情 |

### 10.10 出勤统计

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /api/absenteeism | admin | 出勤统计列表（分页+筛选） |
| PATCH | /api/absenteeism/:id/correct | admin | 纠正旷工状态（需填写原因） |

### 10.11 提醒

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| GET | /api/reminders | worker | 提醒列表 |
| PATCH | /api/reminders/:id/read | worker | 标记提醒为已读 |

### 10.12 系统管理

| 方法 | 路径 | 角色 | 说明 |
|------|------|------|------|
| PATCH | /api/workers/:id/reset-password | admin | 重置护工密码 |

---

## 11. 实施顺序

### 11.1 推荐的开发阶段

| 阶段 | 内容 | 前置依赖 |
|------|------|----------|
| 0-1 | 项目脚手架 + 认证系统 | 无 |
| 2 | 护工管理（CRUD + 账号自动创建） | 阶段 1 |
| 3 | 病人管理（CRUD + 审核 + 特殊情况 + 版本追踪） | 阶段 2 |
| 4 | 排班管理（双入口视图 + 冲突检测 + 变更日志） | 阶段 2 + 3 |
| 5 | AI Agent 对话（Session + 消息 + AI 提取 + 完整性校验） | 阶段 3 |
| 6 | 打卡 & 护理记录（正常打卡 + 补卡 + CareRecord） | 阶段 4 |
| 7 | 缺勤统计 + 旷工纠正 + 定时任务 | 阶段 6 |
| 8 | 提醒机制 + 系统管理 | 阶段 6 |
| 9 | 收尾（错误处理、空状态、权限审查、性能优化） | 全部完成 |

### 11.2 每个阶段的开发顺序（每个阶段按此模板执行）

1. **后端 Model**（如需新增表或修改字段）→ 生成 Alembic 迁移 → upgrade
2. **后端 Schema**（Pydantic 入参/出参）
3. **后端 Service**（业务逻辑）
4. **后端 Router**（挂载路由 + 依赖注入）
5. **验证**：后端启动 + Swagger 调试接口
6. **前端 types**（对接后端 Schema）
7. **前端 service**（API 调用封装）
8. **前端 page + 路由注册**
9. **验证**：浏览器完整链路

---

## 附录 A：新旧架构差异清单

| 项目 | 旧架构（ARCHITECTURE.md 旧版） | 新架构（本文档） |
|------|-------------------------------|------------------|
| Session 状态 | ACTIVE / PENDING_REVIEW / APPROVED / REJECTED | ONGOING / COMPLETED |
| Session 用途 | 新增病人入口 | 长期记忆，信息补充 |
| 护工新增病人 | 支持（AI 对话 → 审核 → 入库） | 不支持（管理员录入） |
| AI 补充信息审核 | 需要管理员审核 | 无需审核，直接更新档案 |
| Patient 字段 | 基本信息 | 扩展含医保/监护人/疾病/照护/性格等 |
| Patient 版本追踪 | 无 | last_updater_id, update_method, updated_at |
| Checkin 状态 | STARTED / SUBMITTED / INCOMPLETE / COMPLETED | STARTED / COMPLETED / ABSENT |
| Checkin.schedule_id | 必填 | 可空 |
| Checkin.is_makeup | 无 | 新增 |
| CareRecord.ai_score | 存在 | 移除（Phase 1 不做） |
| ScheduleLog 表 | 无 | 新增 |
| Absenteeism 表 | 无 | 新增（含预留绩效字段） |
| PatientVersion 表 | 无 | 新增 |
| Reminder 表 | 无 | 新增 |
| Complaint 模块 | 存在 | 移除（Phase 2+） |
| Alert 模块 | 存在 | 移除（Phase 2+） |
| 自动排班 API | 存在 | 移除 |
| 临时调整排班 API | 存在 | 移除 |
| 排班视图 | 单一视图 | 双入口（护工视角/病人视角） |
| 前端前端 | 部分目录结构 | 完整的目录 + 组件树 + 路由 |

---

## 附录 B：关键决策记录

| 编号 | 决策 | 选择 | 理由 |
|------|------|------|------|
| AD-1 | 每个病人一个 Session | 长期记忆模式 | 护工持续累积信息，避免 Session 碎片化 |
| AD-2 | AI 补充信息直接更新档案 | 无需管理员审核 | 减少审核延迟，提升护工效率；质量问题 Phase 2 引入抽审 |
| AD-3 | 补卡 schedule_id 可空 | 自由填写 | 护工补卡时不强制关联排班，简化操作 |
| AD-4 | 排班矩阵布局 | 行=人员，列=24小时 | 直观展示全天排班，支持双入口切换 |
| AD-5 | Session 上下文策略 | 全部历史 + AI 自动摘要 | 保留上下文连续性，同时控制 token 长度 |
| AD-6 | 前端无全局状态管理 | 仅 AuthContext | 项目规模有限，Context 足够，避免引入 redux 等重方案 |
| AD-7 | 无 refresh token | 仅 access token（24h） | Phase 1 复杂度控制，简化实现 |
| AD-8 | 旷工自动标记 | 排班结束 1 小时后 | 给护工留出合理的时间窗口提交记录 |
| AD-9 | UI 组件库 | Ant Design 5 | 国内后台系统事实标准，组件齐全，中文生态好，减少自行封装 |
