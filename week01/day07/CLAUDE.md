# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

养老管理系统，分两端：机构端（管理护工/病人/护理记录/排班/预警）和护工端（AI Agent 驱动的上门护理记录）。
技术栈：React + Ant Design 5 + FastAPI + SQLite。

## 目录结构

```
frontend/src/       — React 前端
  components/       — 通用组件
  pages/            — 页面组件
    admin/          — 机构端页面
    worker/         — 护工端页面
  services/         — API 请求封装
  hooks/            — 自定义 hooks
  types/            — TS 类型定义
  utils/            — 工具函数
backend/
  main.py           — FastAPI 入口
  routers/          — 路由模块
  models/           — SQLAlchemy 模型
  schemas/          — Pydantic 请求/响应 schema
  services/         — 业务逻辑
  utils/            — 工具函数
  ai/               — AI Agent 相关（对话、审核、补齐、预警分析）
  migrations/       — 数据库迁移（Alembic）
database/
  db.sqlite         — SQLite 数据库文件（开发环境）
```

## 常用命令

### 前端

```bash
cd frontend
npm install           # 含 antd @ant-design/icons
npm run dev           # 启动开发服务器
npm run build        # 生产构建
npm run lint         # ESLint 检查
npx tsc --noEmit     # TypeScript 类型检查
```

### 后端

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000   # 启动开发服务器
ruff check .                             # Python 代码检查
pytest                                   # 运行测试
alembic upgrade head                     # 执行数据库迁移
alembic revision --autogenerate -m "描述"  # 生成迁移文件
```

## 数据库规范

- 使用 SQLAlchemy ORM 操作 SQLite
- 所有建表/改表操作通过 Alembic 迁移管理
- 模型文件放在 `backend/models/`，每个模型一个文件
- 外键和索引必须在迁移中显式定义
- 字段命名：数据库用 snake_case，Pydantic 响应用 camelCase（统一转换）

## 接口规范

- 统一请求格式：`{ code, message, data }`，分页响应额外包含 `total, page, pageSize`
- 状态码：200 成功，400 参数错误，401 未登录，403 无权限，404 不存在，500 服务端错误
- 分页参数：`page`（默认1）, `pageSize`（默认20）

## 编码规范

- 前端 TS 强类型，所有函数必须声明参数和返回值类型
- UI 组件使用 antd 5，图标使用 @ant-design/icons
- 表单统一 antd Form + useForm，表格使用 antd Table
- 消息提示使用 App.useApp().message/modal（不用静态方法）
- 命名：小驼峰变量/函数，大驼峰组件/类
- 函数单一职责，单个函数不超过 80 行
- 关键逻辑必须加注释
- 统一错误捕获，统一返回格式
- 所有入参做校验，处理空值异常

## 开发原则

1. 优先复用项目已有工具、常量、枚举
2. 只做增量开发，不重构已稳定运行业务代码
3. 不确定逻辑先询问，不擅自修改
4. 代码简洁优先，拒绝过度设计
5. 不私自新增第三方依赖
6. 输出可直接运行的完整代码，不输出片段
7. 遇到冲突优先沿用项目原有写法

## 功能模块（需求概览）

### 机构端
- **护工管理**：护工基础信息、排班管理
- **客户管理**：病人基础信息/特殊情况记录、新增病人审核
- **护理记录管理**
- **投诉管理**
- **系统管理**：预警设置、自动排班设置

### 护工端（AI Agent 驱动）
- 每个病人一个独立 session 对话
- 新增病人通过 Agent 添加消息 → AI 格式入库审核 → 管理员审核 → 正式入库（护工不可删除，驳回可重提）
- 上门服务打卡 → AI 判断记录完整性 → 缺失补全后入库
- 每晚 AI 批量分析病人身体情况 → 预警通知管理员和护工（参数可在预警设置中调整）
- 排班以 1 小时为单位，支持加钟临时调整至空闲人员
- 服务时间结束提醒护工上传护理记录
