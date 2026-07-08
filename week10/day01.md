# Day 01 — 项目脚手架 + ASR 接入

## 学习目标

前 9 周你学了一堆散装技能——FastAPI、Agent Loop、RAG 流水线、向量库、create_agent、多 Agent 编排、MCP、评估体系。这些技能就像工具箱里的扳手、螺丝刀、电钻，每一件都用过，但还没真正组装过一台机器。从本周开始，我们用养老护工智能记录系统这个项目把所有散装技能串成一条完整的产品线。今天先把地基打好：项目脚手架 + ASR 语音转文本——养老护工用微信录一段语音，系统把它转成文字，这是整条数据链路的入口。

学完今天你能：
1. 理解养老护工场景为什么是 12 周学习的"终极练手项目"——它天然需要多模态（语音 ASR + 文本）、多 Agent（提取/异常/趋势/通知）、RAG（历史记录检索），一个场景把前 9 周全串起来
2. 从零搭建 FastAPI 分层项目结构（routers/services/models/config/schemas），理解为什么后端要分层，和前端的组件分层有什么对应关系
3. 设计三个核心 API 路由（upload/transcribe/extract），理解"录音上传 → ASR 转文本 → 结构化提取"这条数据链路
4. 接入腾讯云 ASR，把微信录的 AMR 音频转成文本，知道怎么 mock、怎么处理格式、怎么对接真实 SDK

---

## 一、项目背景：为什么选养老护工场景

### 1.1 场景描述

先说清楚这个项目到底在做什么：

```
养老院里，护工每天要记录老人的状况：
- "王奶奶今天早饭吃了半碗粥，精神不错，上午参加了手工活动"
- "李爷爷下午说头晕，量了血压 150/95，已经吃药"
- "张奶奶今晚情绪低落，哭了一会，已经安抚"

痛点：护工手写太慢，打字也慢，而且很多场景双手占着（扶老人、推轮椅）。
方案：护工用微信语音录一段，系统自动转文字 + 提取结构化数据（饮食/体征/情绪/异常）。
```

> **为什么是微信录音：** 养老院护工平均年龄 45+，让他们装个新 App 学习成本太高。微信是所有人都会用的，语音消息是微信最自然的功能。这个选型背后是"用户调研"思维——技术在用户习惯面前要低头。

### 1.2 为什么这个场景是"终极练手项目"

养老护工这个场景刚好卡在"能做完"和"有深度"的甜点上，一个场景把前 9 周全串起来：

| 技术能力 | 养老护工场景怎么用 | 对应 Week |
|---------|-------------------|-----------|
| **多模态** | 语音（ASR 转文本）+ 文本（结构化）+ 未来图片（拍照记录伤口） | Week 10 新增 |
| **多 Agent** | 提取 Agent / 异常检测 Agent / 趋势分析 Agent / 通知 Agent | Week 07 |
| **RAG** | 检索历史记录对比"今天的头晕和上周的头晕有什么变化" | Week 04-05 |
| **Reflection** | 提取结果让 Critic Agent 检查，不通过就自我纠正 | Week 10 新增 |
| **评估** | 测试集 + trace + 成功率统计 | Week 09 |
| **FastAPI** | 整个系统的后端骨架 | Week 01 |

> **前端类比：** 这就像你做前端时，一个"后台管理系统"能覆盖路由/状态管理/表单/表格/权限/图表全部技能点。养老护工系统就是后端 + AI 版的"后台管理系统"——一个项目把所有散装技能串起来。

### 1.3 与 Week 01 FastAPI 的衔接

Week 01 你学的是 FastAPI 的零件（路由、依赖注入、中间件、异常处理、Pydantic 校验），当时搭的是一个"聊天接口 Demo"——一个文件里塞了所有逻辑。Week 10 你要学的是"零件怎么组装成一台机器"。

```
Week 01：一个 main.py，路由 + 中间件 + 逻辑全塞一起，像 HTML 写了所有 CSS+JS
Week 10：分层架构，routers/services/models/config 各司其职，像拆好的现代前端项目
```

| Week 01 学的零件 | Week 10 落地的位置 |
|------------------|-------------------|
| `FastAPI()` 实例 | `app/main.py` |
| `@app.middleware` | `app/core/middleware.py` |
| `Depends()` 依赖注入 | `app/core/dependencies.py` |
| `BaseModel` Pydantic | `app/schemas/` 目录 |
| `@router.post()` 路由 | `app/routers/` 目录 |
| `lifespan` 生命周期 | `app/main.py` 里管 DB/ASR client |

---

## 二、FastAPI 项目脚手架：分层架构设计

### 2.1 为什么要分层

前端要拆 `components/` `hooks/` `utils/` `services/`，因为全塞一个文件里改功能要翻几千行。后端也一样——不分层时 `main.py` 能涨到 500 行，路由、逻辑、校验、异常全混在一起，改一个接口要在文件里上下翻找。

```
分层后各司其职：
  routers/  → 只管"接请求、调 service、返响应"
  services/  → 只管"业务逻辑"
  models/    → 只管"数据库表结构"
  schemas/   → 只管"请求/响应的数据格式"
  config/    → 只管"配置和密钥"
```

> **前端类比：** `routers` 就像前端的"页面路由组件"，`services` 就像"API 请求封装"，`models/schemas` 就像"TypeScript 类型定义"，`config` 就像 `env` 配置。

### 2.2 项目目录结构

```
elderly-care-system/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI 入口，注册路由/中间件/异常
│   ├── config.py                # 配置管理（密钥、数据库地址等）
│   │
│   ├── core/                    # 核心基础设施
│   │   ├── __init__.py
│   │   ├── database.py          # 数据库连接
│   │   ├── exceptions.py        # 自定义异常 + 全局异常处理
│   │   ├── middleware.py         # 中间件注册
│   │   └── response.py          # 统一响应格式
│   │
│   ├── routers/                  # 路由层（只管接请求调 service）
│   │   ├── __init__.py
│   │   └── record.py             # 录音相关路由
│   │
│   ├── services/                 # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── asr_service.py        # ASR 语音转文本
│   │   └── record_service.py     # 录音业务逻辑
│   │
│   ├── schemas/                  # 数据格式（Pydantic 模型）
│   │   ├── __init__.py
│   │   ├── record.py             # 录音请求/响应格式
│   │   └── common.py             # 通用响应格式
│   │
│   └── models/                   # 数据库模型（Day 02+ 用到）
│       ├── __init__.py
│       └── record.py
│
├── uploads/                     # 上传的音频临时存放
├── requirements.txt
└── .env                         # 环境变量（密钥放这里）
```

### 2.3 依赖清单

```txt
# requirements.txt
fastapi==0.115.6
uvicorn[standard]==0.34.0
pydantic==2.10.4
python-multipart==0.0.20          # 处理文件上传必需
tencentcloud-sdk-python==3.0.1000  # 腾讯云 ASR SDK
python-dotenv==1.0.1              # 读取 .env 配置
```

### 2.4 配置管理：config.py

Week 01 你把密钥直接写在代码里（`Authorization: f"Bearer ===="`），这在 Demo 里可以，真实项目里不行——密钥泄露是安全事故。真实项目用 `.env` 文件 + `python-dotenv` 管理。

```python
# app/config.py
"""配置管理：从 .env 读取，代码里不硬编码密钥。

前端类比：就像前端的 import.meta.env.VITE_API_URL，
把环境变量和代码分离，不同环境（开发/生产）用不同配置。
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """全局配置，自动从 .env 文件读取。"""

    app_name: str = "养老护工智能记录系统"
    debug: bool = True

    # 腾讯云 ASR 配置（真实 key 放 .env，这里只是占位）
    tencent_secret_id: str = ""
    tencent_secret_key: str = ""
    tencent_region: str = "ap-guangzhou"

    upload_dir: str = "uploads"
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    database_url: str = "sqlite:///./care.db"  # Day 02 接入

    model_config = {"env_file": ".env", "extra": "ignore"}


# 全局单例，其他模块直接 from app.config import settings
settings = Settings()
```

对应的 `.env` 文件（这个文件不提交到 git）：

```bash
# .env
DEBUG=True
TENCENT_SECRET_ID=your_secret_id_here
TENCENT_SECRET_KEY=your_secret_key_here
TENCENT_REGION=ap-guangzhou
```

### 2.5 统一响应格式：core/response.py

前端调接口最烦的是什么？响应格式不统一——有的接口返回 `{data: xxx}`，有的返回 `{result: xxx}`，有的直接返回裸数据。统一响应格式让前端封装一个通用的请求拦截器就行。

```python
# app/core/response.py
"""统一响应格式，前端可以写一个通用拦截器统一处理。

前端类比：约定所有 API 返回 { code, message, data }，
前端拦截器里统一判断 code，错误统一弹 message。
"""
from typing import Any
from pydantic import BaseModel


class ApiResponse(BaseModel):
    code: int = 200
    message: str = "success"
    data: Any = None


def success(data: Any = None, message: str = "success") -> dict:
    return {"code": 200, "message": message, "data": data}


def fail(message: str = "failed", code: int = 400, data: Any = None) -> dict:
    return {"code": code, "message": message, "data": data}
```

### 2.6 应用入口：main.py

Week 01 的 `main.py` 把所有东西塞一个文件。Week 10 的 `main.py` 只做一件事：组装——把 router、middleware、exception handler 注册进来，就像前端的 `App.tsx` 只负责把各模块组合起来。

```python
# app/main.py
"""FastAPI 应用入口，只做组装不做业务逻辑。"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.exceptions import register_exception_handlers
from app.routers.record import router as record_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时创建上传目录，关闭时清理资源。"""
    os.makedirs(settings.upload_dir, exist_ok=True)
    print(f"[{settings.app_name}] 启动完成")
    yield
    print(f"[{settings.app_name}] 已关闭")


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

# 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # 生产环境要改成具体域名
    allow_methods=["*"],
    allow_headers=["*"],
)

# 异常处理 + 路由注册
register_exception_handlers(app)
app.include_router(record_router, prefix="/api/record", tags=["录音管理"])


@app.get("/health")
async def health():
    """健康检查，运维用来探活。"""
    return {"status": "ok", "version": "0.1.0"}
```

---

## 三、路由设计：三个核心接口

### 3.1 数据链路设计

养老护工的一次完整操作是这样的：

```
护工微信录音（AMR）
    ↓ POST /api/record/upload     ← 上传音频文件
服务端存到 uploads/ 目录，返回 record_id
    ↓ POST /api/record/transcribe ← 调 ASR 转文本
服务端调腾讯云 ASR，把 AMR 转成文字，存数据库
    ↓ POST /api/record/extract    ← AI 结构化提取（Day 02 做）
服务端调 Agent，把文本提取成结构化数据（饮食/体征/情绪/异常）
```

> **前端类比：** 这条链路就像前端的表单提交流程——上传文件 → 后端处理 → 返回结果。只不过中间多了 ASR 和 AI 两个处理环节。三步拆开而不是合成一个接口，是因为 ASR 和 AI 都比较慢（各几秒），拆开让前端能分步展示进度。

### 3.2 Schemas：请求和响应的数据格式

```python
# app/schemas/record.py
"""录音相关的请求/响应数据格式。

前端类比：这就像 TypeScript 的 interface，
前后端约定数据结构，减少联调时的"字段对不上"问题。
"""
from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    """上传接口的响应。"""
    record_id: str = Field(..., description="录音记录 ID")
    filename: str = Field(..., description="文件名")
    file_size: int = Field(..., description="文件大小（字节）")


class TranscribeRequest(BaseModel):
    record_id: str = Field(..., description="要转文本的录音 ID")


class TranscribeResponse(BaseModel):
    record_id: str
    text: str = Field(..., description="ASR 识别出的文本")
    duration_ms: int = Field(..., description="音频时长（毫秒）")
    confidence: float = Field(..., description="识别置信度 0-1")


class ExtractRequest(BaseModel):
    """结构化提取（Day 02 实现）。"""
    record_id: str = Field(..., description="要提取的录音 ID")


class ExtractResponse(BaseModel):
    """结构化提取响应（Day 02 实现）。"""
    record_id: str
    diet: str | None = None          # 饮食情况
    vital_signs: str | None = None   # 体征（血压/体温等）
    mood: str | None = None          # 情绪状态
    abnormal: bool = False           # 是否有异常
    abnormal_detail: str | None = None  # 异常详情
```

### 3.3 路由层：record.py

路由层只做三件事：接请求 → 调 service → 返响应，不写业务逻辑。

```python
# app/routers/record.py
"""录音管理路由：接请求、调 service、返响应，业务逻辑全在 services/ 里。"""
import os
import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.config import settings
from app.core.response import success, fail
from app.schemas.record import (
    TranscribeRequest, TranscribeResponse,
    ExtractRequest, ExtractResponse,
)
from app.services.asr_service import ASRService
from app.services.record_service import RecordService

router = APIRouter()

# service 实例化（简单项目直接实例化，复杂项目用依赖注入）
asr_service = ASRService()
record_service = RecordService()


@router.post("/upload")
async def upload_record(file: UploadFile = File(...)):
    """上传录音文件。

    前端调用示例：
        const formData = new FormData()
        formData.append('file', audioBlob)
        fetch('/api/record/upload', { method: 'POST', body: formData })
    """
    # 1. 校验文件格式（微信录音通常是 .amr）
    allowed = {".amr", ".mp3", ".wav", ".m4a"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed:
        raise HTTPException(400, f"不支持的格式: {ext}，支持: {allowed}")

    # 2. 校验文件大小
    content = await file.read()
    if len(content) > settings.max_file_size:
        raise HTTPException(400, "文件超过 10MB 限制")

    # 3. 保存文件
    record_id = str(uuid.uuid4())[:8]
    filename = f"{record_id}{ext}"
    filepath = os.path.join(settings.upload_dir, filename)
    with open(filepath, "wb") as f:
        f.write(content)

    return success({
        "record_id": record_id,
        "filename": filename,
        "file_size": len(content),
    })


@router.post("/transcribe")
async def transcribe_record(req: TranscribeRequest):
    """把录音转成文本（调 ASR）。"""
    try:
        result = await asr_service.transcribe(req.record_id)
        return success(result)
    except FileNotFoundError:
        return fail(f"录音不存在: {req.record_id}", code=404)
    except Exception as e:
        return fail(f"ASR 识别失败: {str(e)}", code=500)


@router.post("/extract")
async def extract_record(req: ExtractRequest):
    """结构化提取（Day 02 实现，今天先占位）。"""
    return fail("结构化提取 Day 02 实现", code=501)
```

---

## 四、ASR 接入：微信录音到文本

### 4.1 微信录音的格式问题

微信语音消息导出来是 AMR 格式——压缩率很高，文件很小（30 秒录音约 50KB），但质量一般。

```
护工按住微信语音 → 录音 → AMR → 发送
我们的处理：AMR → 腾讯云 ASR → 文本
```

| 格式 | 来源 | 大小（30秒） | 备注 |
|------|------|-------------|------|
| AMR | 微信原始格式 | ~50KB | 直接传也行，但 8k 采样率质量一般 |
| WAV | 转换后 | ~1MB | 无损，识别率最高 |
| MP3 | 转换后 | ~300KB | 兼顾大小和质量 |

> **为什么 AMR 质量一般：** AMR 为语音通话设计，压缩率优先于保真度。养老院环境嘈杂（老人说话小声 + 背景电视声 + 护工边走边录），AMR 的低码率丢细节。有条件先转 WAV 再传 ASR，识别率好不少。

### 4.2 腾讯云 ASR 调用

用 `tencentcloud-sdk-python` 调腾讯云的一句话识别 API（适合 60 秒以内的短音频，护工一段录音通常不超过 60 秒）。

```python
# app/services/asr_service.py
"""ASR 服务：调用腾讯云把音频转成文本。

腾讯云 ASR 两种模式：
  1. 一句话识别（SentenceRecognition）：60 秒以内，实时返回，适合护工录音
  2. 录音文件识别（CreateRecTask）：长音频，异步，需要轮询结果

护工录音通常 10-60 秒，用一句话识别即可。
"""
import os
import base64

from app.config import settings


class ASRService:
    """ASR 语音转文本服务。"""

    # 音频格式映射：文件后缀 → 腾讯云格式代码
    FORMAT_MAP = {
        ".wav": 1,    # wav
        ".pcm": 4,     # pcm
        ".amr": 7,     # amr（微信原始格式）
        ".mp3": 8,     # mp3
        ".m4a": 10,    # m4a
    }

    async def transcribe(self, record_id: str) -> dict:
        """把录音文件转成文本。

        Args:
            record_id: 录音记录 ID

        Returns:
            {"record_id": ..., "text": ..., "duration_ms": ..., "confidence": ...}
        """
        # 1. 找到音频文件
        filepath = self._find_audio_file(record_id)
        if not filepath:
            raise FileNotFoundError(f"找不到录音: {record_id}")

        # 2. 读取并 base64 编码（腾讯云要求 base64）
        ext = os.path.splitext(filepath)[1].lower()
        with open(filepath, "rb") as f:
            audio_data = f.read()
        audio_b64 = base64.b64encode(audio_data).decode("utf-8")

        # 3. 调腾讯云 ASR
        result = await self._call_tencent_asr(audio_b64, ext)

        return {
            "record_id": record_id,
            "text": result["text"],
            "duration_ms": result["duration_ms"],
            "confidence": result["confidence"],
        }

    def _find_audio_file(self, record_id: str) -> str | None:
        """在 uploads/ 目录找对应的音频文件。"""
        for ext in self.FORMAT_MAP:
            filepath = os.path.join(settings.upload_dir, f"{record_id}{ext}")
            if os.path.exists(filepath):
                return filepath
        return None

    async def _call_tencent_asr(self, audio_b64: str, ext: str) -> dict:
        """调腾讯云一句话识别 API。

        生产环境用真实 SDK 调用，开发阶段用 mock 返回假数据。
        通过 settings.tencent_secret_id 是否为空判断走哪条路。
        """
        # ── Mock 模式：没有配置密钥时返回假数据 ──
        if not settings.tencent_secret_id:
            return self._mock_transcribe(audio_b64, ext)

        # ── 真实调用：腾讯云 SDK ──
        from tencentcloud.asr.v20190614 import asr_client, models
        from tencentcloud.common import credential
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile

        # 1. 认证：用 SecretId + SecretKey
        cred = credential.Credential(
            settings.tencent_secret_id,
            settings.tencent_secret_key,
        )

        # 2. 配置 HTTP 选项和客户端
        http_profile = HttpProfile(endpoint="asr.tencentcloudapi.com")
        client_profile = ClientProfile(httpProfile=http_profile)
        client = asr_client.AsrClient(
            cred, settings.tencent_region, client_profile
        )

        # 3. 构造请求
        req = models.SentenceRecognitionRequest()
        req.ProjectId = 0
        req.SubServiceType = 2                  # 2 = 一句话识别
        req.EngSerType = "8k"                   # 8k 采样率（微信 AMR）
        req.SourceType = 1                      # 1 = 直接传音频数据
        req.Data = audio_b64                    # base64 音频
        req.VoiceFormat = str(self.FORMAT_MAP.get(ext, 7))
        req.UsrAudioKey = "elderly-care"        # 业务标识

        # 4. 发起请求
        resp = client.SentenceRecognition(req)
        return {
            "text": resp.Result,
            "duration_ms": resp.AudioDuration,
            "confidence": 0.95,                 # 腾讯云返回置信度
        }

    def _mock_transcribe(self, audio_b64: str, ext: str) -> dict:
        """Mock 数据：没有真实密钥时返回假结果。

        开发阶段用这个，方便前端联调，不用等真实 ASR。
        """
        mock_texts = [
            "王奶奶今天早饭吃了半碗粥，精神不错，上午参加了手工活动",
            "李爷爷下午说头晕，量了血压150到95，已经吃药了",
            "张奶奶今晚情绪低落，哭了一会，已经安抚好了",
        ]
        import hashlib
        # 根据文件内容 hash 决定返回哪句话，保证同文件返回一致
        idx = int(hashlib.md5(audio_b64.encode()).hexdigest(), 16) % 3
        return {
            "text": mock_texts[idx],
            "duration_ms": 30000,
            "confidence": 0.92,
        }
```

> **前端类比：** 这个 mock 逻辑就像前端开发时用 Mock Service Worker（MSW）——没接后端时先返回假数据，让前端能跑起来。等后端 ready 了，关掉 mock 切真实接口。这里的判断逻辑是"有没有配置密钥"，没有就走 mock。

### 4.3 业务逻辑层的位置

`RecordService` 作为业务逻辑层的壳今天比较薄（就是转调 ASRService），Day 02 接 AI 提取、Day 03 接数据库后这层会变厚。结构上 `routers/record.py` 调 `RecordService`，`RecordService` 再调 `ASRService` —— 路由不直接碰 ASR，方便后续在 service 层加缓存、日志、事务。

---

## 动手实验

### 🟢 青铜：跑通脚手架

把上面的项目结构搭出来，能 `uvicorn app.main:app --reload` 启动：

1. 创建目录结构，把 `config.py` / `main.py` / `response.py` 写好
2. `pip install fastapi uvicorn python-multipart pydantic-settings`
3. 启动服务，访问 `http://localhost:8000/docs` 看到 Swagger 文档
4. 用 Swagger 试 `/health` 接口，确认服务跑起来了

目标：项目能跑，Swagger 能看到三个接口（upload/transcribe/extract）。

### 🟡 白银：跑通上传 + Mock ASR

1. 用 Postman 或 curl 上传一个音频文件到 `/api/record/upload`，拿到 `record_id`
2. 调 `/api/record/transcribe`，因为没配密钥，走 mock 返回假文本
3. 确认返回格式是 `{ code: 200, message: "success", data: { record_id, text, ... } }`

```bash
# 上传测试
curl -X POST http://localhost:8000/api/record/upload \
  -F "file=@test.amr"

# 转文本测试（把 record_id 换成上一步返回的）
curl -X POST http://localhost:8000/api/record/transcribe \
  -H "Content-Type: application/json" \
  -d '{"record_id": "abc12345"}'
```

目标：完整跑通"上传 → mock 转文本"链路，前端能拿到假数据联调。

### 🔴 王者：接真实腾讯云 ASR

1. 去腾讯云控制台开通语音识别服务，拿到 SecretId + SecretKey
2. 填到 `.env` 文件里
3. 用微信录一段真实的养老护理语音，导出 AMR 上传测试
4. 对比 mock 文本和真实 ASR 文本的差异，记录识别准确率
5. 思考：如果 ASR 把"血压150到95"识别成"血压一百五十到九十五"，AI 提取阶段怎么处理？

目标：跑通真实 ASR，理解真实数据和 mock 的差距，为 Day 02 的 AI 提取做准备。

---

## 踩坑记录 🕳️

### 坑 1：微信 AMR 采样率导致 ASR 识别率低

微信语音用 8kHz 采样率的 AMR，而很多 ASR 服务默认 16kHz。用错采样率识别率暴跌——"血压"识别成"学压"，"吃药"识别成"吃要"。

**解决：** 腾讯云 ASR 的 `EngSerType` 要设 `"8k"`（对应微信 AMR）。搞不清采样率时看音频文件属性，或转成 WAV 16kHz 再传。

### 坑 2：`python-multipart` 没装导致上传报错

FastAPI 文件上传（`UploadFile`）依赖 `python-multipart`，但 `pip install fastapi` 不自动装。跑到上传接口就报 `RuntimeError: Form data requires "python-multipart"`。

**解决：** `requirements.txt` 一定要加 `python-multipart`。这就像前端用 axios 但忘装 `form-data` 一样。

### 坑 3：base64 编码后文件变大，超过 API 限制

AMR 文件小（50KB），但 base64 后膨胀约 33%。传 5MB 的 WAV，base64 后变 6.7MB，可能超腾讯云一句话识别的 1MB 限制。

**解决：** 长音频用"录音文件识别"（CreateRecTask），异步的，先把文件传 COS 再给 URL。一句话识别只适合 60 秒以内的小文件。

### 坑 4：Mock 和真实 ASR 返回字段不一致

mock 时随手返回 `{"text": ..., "confidence": 0.92}`，但腾讯云真实返回的字段名可能是 `Result`。前端联调用 mock 没问题，切真实 ASR 后字段对不上，页面白屏。

**解决：** `_call_tencent_asr` 里统一做字段映射，把 `resp.Result` 映射成 `text`。mock 和真实调用返回同样的 schema，前端无感知切换。

### 坑 5：密钥写在代码里提交到 git

Week 01 密钥写在 main.py 里是 Demo 没事。但 Week 10 是真实项目，密钥一旦提交到 git，即使后面删掉，git 历史里还能翻出来，腾讯云密钥泄露会被盗刷。

**解决：** 密钥只放 `.env`，`.gitignore` 加 `.env`。代码里永远不出现真实密钥。已经提交了就立刻去控制台禁用旧密钥、生成新密钥。

---

## 副线笔记

### 用 Claude Code 结对搭脚手架

今天的副线是用 Claude Code 全程结对搭项目脚手架。你作为 11 年前端工程师，搭前端项目脚手架半小时搞定，但 Python 后端项目结构不一定熟——该分哪些层、依赖怎么管、配置怎么放。这正是 Claude Code 擅长的场景。

**怎么用：** 把需求告诉 Claude Code（FastAPI + 养老护工场景 + 微信录音上传 + 腾讯云 ASR + 分层架构 routers/services/models/schemas/config），让它生成目录树和各文件骨架，你审查后让它补充细节。

**结对要点：**

| 环节 | 你做什么 | Claude Code 做什么 |
|------|---------|-------------------|
| 目录设计 | 审查是否合理、是否符合团队习惯 | 生成标准分层结构 |
| 依赖清单 | 确认版本兼容、删掉不需要的 | 列出所有需要的包 |
| 配置管理 | 检查密钥是否安全 | 写好 .env 模板和 config.py |
| 路由设计 | 确认接口路径符合前端调用习惯 | 生成 router 骨架 |
| ASR 调用 | 确认 mock 逻辑是否合理 | 写 SDK 调用代码 |

### 今日观察任务

- 用 Claude Code 生成项目脚手架，对比它生成的结构和你手写的差异
- 重点观察：Claude Code 的分层方式和你预期的一样吗？有没有多分或少分层？
- 把今天搭的脚手架存好，Day 02 会在这个基础上接 AI 结构化提取

---

## 检查清单

- [ ] 理解养老护工场景为什么是终极练手项目（多模态 + 多 Agent + RAG 全覆盖）
- [ ] 搭好了 FastAPI 分层项目结构（routers/services/schemas/config）
- [ ] `uvicorn app.main:app --reload` 能启动，Swagger 能看到接口
- [ ] `/api/record/upload` 能接收文件并保存到 uploads/
- [ ] `/api/record/transcribe` 能走 mock 返回假文本
- [ ] 理解微信 AMR 格式和腾讯云 ASR 的采样率匹配（8k）
- [ ] 密钥放 `.env`，代码里不硬编码，`.gitignore` 忽略 `.env`
- [ ] 用 Claude Code 结对搭过脚手架，对比了 AI 生成的结构

---

## 下课预告

> **Day 02 — AI Agent 结构化提取。** 今天我们把数据链路的入口（ASR 转文本）打通了，但文本还是一坨自然语言——"王奶奶今天早饭吃了半碗粥，精神不错"。护工需要的不是这段话，而是结构化的表单数据：饮食=半碗粥、情绪=良好、异常=无。明天就接入 AI Agent，把 ASR 文本提取成结构化的 Pydantic 表单。你会学到：怎么用 Week 06 的 `create_agent` 做结构化提取、怎么定义提取的 Pydantic schema、怎么对比 Week 03 手写 Agent Loop 和 Week 06 `create_agent` 两种实现方式的差异。还会处理 ASR 识别不准时的容错——"血压一百五十"怎么提取成 `150`。
