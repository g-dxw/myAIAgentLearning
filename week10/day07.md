# Day 07 — 多模态处理（概念了解）+ 通知分发

## 学习目标

Day 01-06 我们搭了一个完整的养老护工智能记录系统：ASR 接入 → 结构化提取 Agent → Reflection 自纠错 → Agentic RAG → 趋势分析 → 多 Agent 编排。护工录一段音，系统自动跑出结构化记录 + 异常检测 + 趋势分析 + 护理建议 + 通知消息。这套系统已经能跑了，但有个现实问题：护工不只录音，还会拍照——拍老人的伤口、拍饭盒吃了多少、拍药盒确认用药。这些图片怎么进系统？

今天解决两个收尾问题。第一，多模态处理的概念——图片/表格怎么被 Agent 理解和使用。这部分只学原理不做完整代码（方案 B 降级，原因后面解释），面试时能说清思路即可。第二，把 Day 06 通知 Agent 的能力正式做成**通知分发模块**——按异常等级通知护工/家属/医生，接微信/短信渠道。这是本周最后一个可运行产出。

学完今天你能：

1. 理解多模态处理的四类问题（表格/图片/大表格/跨页图文）和解决思路，面试 Q17-Q20 能说清原理
2. 知道为什么多模态不做完整代码——方案 B 降级，概念清晰即可，面试不考代码实现
3. 实现通知分发模块：按异常等级（normal/warning/critical）走不同通知渠道
4. 能用企业微信机器人 Webhook + 短信 API 实现多渠道通知
5. 完成本周项目的完整闭环：从录音到通知的全链路

---

## 一、多模态处理：概念了解（面试 Q17-Q20）

### 1.1 为什么需要多模态

养老护工的真实工作场景不只有语音。看一个护工的完整记录流程：

```
护工查房一个老人的完整记录：
┌─────────────────────────────────────────┐
│  ① 录音："今天王奶奶体温37度8，血压150"  │ ← ASR 处理（Day 01）
│  ② 拍照：伤口愈合情况                    │ ← 图片，今天要解决
│  ③ 拍照：饭盒（吃了多少）                │ ← 图片
│  ④ 拍照：药盒（确认用药）                │ ← 图片
│  ⑤ 拍表格：本周生命体征记录表            │ ← 表格图片
└─────────────────────────────────────────┘
```

Day 01-06 只处理了 ①（语音→文本→结构化提取）。②③④⑤ 都是多模态问题——Agent 需要理解图片内容，把它转成结构化数据或文本描述，才能纳入 CareRecord。

> **前端类比：** 这就像前端的富文本编辑器——纯文本好处理（textarea），但插入图片、表格、附件就需要特殊组件。Agent 也一样，纯文本输入是"textarea 模式"，多模态输入是"富文本模式"——需要把不同格式的内容统一成 Agent 能理解的表示。

### 1.2 四类多模态问题（面试 Q17-Q20）

面试 Q17-Q20 考的是多模态文档处理。这类问题的核心是：**非文本内容（图片/表格）怎么转成 Agent 能处理的文本**。四种典型场景：

| 面试题 | 问题 | 解决思路 | 代码实现？ |
|--------|------|---------|-----------|
| Q17 表格处理 | 图片里的表格怎么提取 | 解析为 Markdown 表格 + 摘要索引 | 概念了解 |
| Q18 图片插入 | 文档中的图片怎么保留位置 | 占位符 `[IMG_001]` + 前端渲染 | 概念了解 |
| Q19 大表格优化 | 超大表格 token 爆炸 | Select-then-Read：先 Schema 后提取 | 概念了解 |
| Q20 跨页图文 | 图文跨页，布局断裂 | 滑动窗口 + 布局距离聚合 | 概念了解 |

### 1.3 Q17：表格处理

**问题：** 护工拍了一张"本周生命体征记录表"的图片，里面有 7 天的体温/血压/心率。Agent 怎么理解这个表格？

**解决思路：**

```
表格图片
  │
  ▼
OCR / 多模态模型识别表格结构
  │
  ▼
转为 Markdown 表格（LLM 能理解的格式）
  │
  │  | 日期 | 体温 | 高压 | 低压 | 心率 |
  │  |------|------|------|------|------|
  │  | 周一 | 36.8 | 135  | 85   | 78   |
  │  | 周二 | 37.0 | 138  | 88   | 80   |
  │  | ...  | ...  | ...  | ...  | ...  |
  │
  ▼
生成摘要索引（"本周体温在36.8-37.5之间，血压稳定"）
  │
  ▼
摘要入向量库，完整表格存文件系统
```

**关键点：** 表格不直接塞进 Agent 上下文（token 爆炸），而是先转 Markdown、再生成摘要、摘要入向量库。Agent 检索时拿到的摘要，需要看完整表格时再从文件系统取。

> **前端类比：** 这就像前端的分页表格——你不会把 1000 行数据全渲染出来，而是只渲染当前页 20 行 + 分页器。Agent 处理大表格也是"分页"思路：先看摘要（当前页），需要细节时再看原始表格（翻页）。

### 1.4 Q18：图片插入

**问题：** 护工拍了伤口照片，这张照片在 CareRecord 里怎么表示？

**解决思路：** 用占位符标记位置，图片本身存对象存储，前端渲染时替换。

```python
# Agent 生成的结构化记录
care_record = {
    "patient_name": "王奶奶",
    "wound_description": "左小腿伤口愈合良好，无明显红肿",
    "wound_image_ref": "[IMG_WOUND_001]",  # 占位符，不是 base64
}

# 前端渲染时替换占位符
# React: <img src={imageMap[record.wound_image_ref]} />
```

**关键点：** 不要把图片 base64 编码塞进 Agent 上下文——一张 1MB 的图片 base64 后约 1.3MB，远超 LLM 上下文窗口。用占位符引用，图片存 OSS/S3，前端按引用加载。

### 1.5 Q19：大表格优化

**问题：** 如果护工拍的是一个月的详细生命体征记录表（30 行 × 6 列 = 180 个数据点），全塞进 Agent 上下文会 token 爆炸。怎么处理？

**解决思路：** Select-then-Read 策略——先看 Schema（表格结构），再按需读取特定行列。

```
第一步：Select（先看 Schema）
  "这个表格有哪些列？" → 列名：日期/体温/高压/低压/心率/备注
  
第二步：Agent 决定需要哪些数据
  "我要看体温超过37.5的记录" → 只提取体温列的异常值
  
第三步：Read（按需提取）
  只返回异常行的数据，不是全部 180 个数据点
```

**关键点：** 不是把整张大表扔给 Agent，而是让 Agent 先了解"表格有什么"，再指定需要什么，按需提取。这和 SQL 的 `SELECT` 逻辑一样——你不会 `SELECT *` 拿全表，而是 `SELECT 体温 WHERE 体温 > 37.5`。

### 1.6 Q20：跨页图文

**问题：** 一份健康报告跨了两页，第一页底部是文字，第二页顶部是图片，中间还有个表格跨了两页。布局被打断了，怎么处理？

**解决思路：** 滑动窗口 + 布局距离聚合。

```
原始文档（跨页）：
  ┌─── 第1页 ───┐   ┌─── 第2页 ───┐
  │ 文字段落A    │   │ 图片B        │
  │ 表格(上半)  │   │ 表格(下半)   │
  │ 文字段落C    │   │ 文字段落D    │
  └─────────────┘   └─────────────┘

滑动窗口处理：
  窗口1：第1页 + 第2页前半 → 文字A + 表格上半 + 表格下半 = 完整表格
  窗口2：第2页后半 → 图片B + 文字D

布局距离聚合：
  表格上半和下半在页面上的垂直距离很近（跨页但连续）→ 合并
  文字A和图片B距离远 → 分开处理
```

**关键点：** 跨页问题不是"拼接文本"就行，而是要理解布局——哪些内容在视觉上是连续的（跨页表格），哪些是独立的（不同段落）。这需要布局分析，通常用文档解析工具（如 unstructured、LayoutLM）来完成。

### 1.7 为什么多模态不做完整代码

用户原计划要做多模态实战的，但这里做了"方案 B 降级"——只做概念了解。原因有三个：

| 原因 | 说明 |
|------|------|
| **环境依赖重** | 多模态需要 OCR 引擎（Tesseract/PaddleOCR）或多模态模型（GPT-4o Vision/Claude Vision），本地跑成本高 |
| **面试只考原理** | 面试官问"多模态怎么处理"，你说清 Markdown 化 + Captioning + Select-then-Read 思路就够了，不会让你现场写 OCR 代码 |
| **时间分配** | 本周 7 天内容已经很满（ASR + 提取 Agent + Reflection + Agentic RAG + 趋势 + 编排），多模态留到概念层面更划算 |

> **学习建议：** 多模态的原理理解了就够了——知道"图片不塞 base64 进上下文，用占位符引用""大表格用 Select-then-Read""跨页用滑动窗口"。等真正做需要多模态的项目时，再深挖 OCR 或 Vision API 的具体实现。

### 1.8 面试 Q17-Q20 速答模板

面试时被问到多模态，按这个模板回答：

> **"多模态文档处理的核心是把非文本内容转成 Agent 能理解的文本表示。**
> 
> **表格处理**：OCR 识别后转 Markdown 表格，再生成摘要入向量库，完整表格存文件系统——Agent 检索时拿摘要，需要细节时再取原文。
> 
> **图片插入**：用占位符 `[IMG_001]` 在文本中标记位置，图片存对象存储，前端渲染时替换——不把 base64 塞进上下文。
> 
> **大表格优化**：Select-then-Read 策略——先看表格 Schema（有哪些列），Agent 按需指定要哪些数据，只提取需要的行列——像 SQL 的 WHERE 过滤。
> 
> **跨页图文**：滑动窗口 + 布局距离聚合——跨页但视觉连续的内容（如跨页表格）合并，视觉独立的内容分开处理。"

---

## 二、通知分发模块

### 2.1 从 Day 06 的通知 Agent 说起

Day 06 的 orchestrator.py 里有一个 `notify_node`，它调用通知 Agent 生成通知消息。但那个 Agent 只生成了"通知谁、什么内容"的文本，没有真正发送。今天把这个环节做实——接到真实的通知渠道。

先回顾 Day 06 通知 Agent 的输出：

```python
# Day 06 通知 Agent 的输出示例（severity=critical）
notification = """
通知等级：critical（危急）
通知对象：护工张姐 + 家属王先生 + 李医生
通知内容：王奶奶体温39.1°C，血压170/105，心率110，
         伴头痛恶心，建议立即就医。
通知渠道：企业微信（护工）+ 短信（家属）+ 电话（医生）
"""
```

今天的任务是把"通知渠道"从文本变成真实发送——企业微信机器人 Webhook 发消息、短信 API 发短信。

### 2.2 通知分发的设计

通知分发模块按异常等级走不同渠道：

```
                    通知分发决策
                    ============

  异常等级
    │
    ├─ normal（日常记录）
    │   └─ 渠道：企业微信（仅护工）
    │      内容："王奶奶今日记录已归档，体温36.8，一切正常"
    │
    ├─ warning（需关注）
    │   └─ 渠道：企业微信（护工）+ 短信（家属）
    │      内容："王奶奶体温37.8，血压150/95，请关注"
    │
    └─ critical（危急）
        └─ 渠道：企业微信（护工）+ 短信（家属）+ 电话提醒（医生）
           内容："王奶奶体温39.1，血压170/105，建议立即就医"
```

三个等级对应三种渠道组合。核心逻辑是"信息越紧急，触达渠道越多"——normal 只发企业微信给护工（不打扰家属），warning 加上家属短信，critical 全渠道触达。

> **前端类比：** 这就像前端的 toast 通知——normal 是 info toast（右下角弹一下），warning 是 warning toast（需要用户点击确认），critical 是 modal dialog（必须立即处理）。信息越重要，打断程度越高。

### 2.3 通知渠道实现

#### 企业微信机器人 Webhook

企业微信群机器人是最简单的通知方式——一个 Webhook URL，POST JSON 就能在群里发消息。护工团队有个企业微信群，Agent 产出的通知直接发到群里。

```python
"""notification_dispatcher.py — 通知分发模块

按异常等级走不同通知渠道：
- normal：企业微信（护工群）
- warning：企业微信 + 短信（家属）
- critical：企业微信 + 短信 + 电话提醒（医生）

使用：
    from notification_dispatcher import NotificationDispatcher
    dispatcher = NotificationDispatcher()
    dispatcher.dispatch(severity="warning", message="王奶奶体温37.8...")
"""
import json
import logging
import time
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    """异常等级。"""
    NORMAL = "normal"       # 日常记录
    WARNING = "warning"      # 需关注
    CRITICAL = "critical"    # 危急


@dataclass
class NotificationChannel:
    """通知渠道配置。"""
    name: str               # 渠道名称
    webhook_url: str = ""   # Webhook URL（企业微信）
    phone: str = ""         # 手机号（短信/电话）
    enabled: bool = True    # 是否启用


class WeChatWorkBot:
    """企业微信群机器人。

    使用方法：
    1. 在企业微信群里添加机器人，获取 Webhook URL
    2. 调 send_message 发消息到群里
    """

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send_text(self, content: str, mentioned_list: list[str] = None) -> dict:
        """发送文本消息。

        content: 消息内容
        mentioned_list: 要@的用户ID列表（如["@all"]@所有人）
        """
        # 实际代码用 requests.post，这里用 mock 展示结构
        payload = {
            "msgtype": "text",
            "text": {
                "content": content,
                "mentioned_list": mentioned_list or [],
            }
        }
        # 实际发送：
        # import requests
        # resp = requests.post(self.webhook_url, json=payload)
        # return resp.json()
        logger.info(f"[企业微信] 发送消息：{content[:50]}...")
        return {"errcode": 0, "errmsg": "ok"}

    def send_markdown(self, content: str) -> dict:
        """发送 Markdown 消息（格式更好看）。"""
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": content},
        }
        logger.info(f"[企业微信] 发送 Markdown：{content[:50]}...")
        return {"errcode": 0, "errmsg": "ok"}


class SMSNotifier:
    """短信通知（用于通知家属）。

    实际使用腾讯云短信或阿里云短信服务。
    这里展示接口设计，实际发送需要配置签名和模板。
    """

    def __init__(self, app_id: str = "", app_key: str = ""):
        self.app_id = app_id
        self.app_key = app_key

    def send_sms(self, phone: str, template_id: str, params: list[str]) -> dict:
        """发短信。

        phone: 手机号
        template_id: 短信模板ID（需在云服务控制台审核通过）
        params: 模板参数（如["王奶奶", "37.8", "150/95"]）
        """
        # 实际代码用腾讯云/阿里云 SDK 发送
        # from tencentcloud.sms.v20210111 import sms_client, models
        # client = sms_client.SmsClient(credential, "ap-guangzhou")
        # ...
        logger.info(f"[短信] 发送到 {phone}：模板{template_id}，参数{params}")
        return {"code": 0, "message": "发送成功"}


class PhoneCallNotifier:
    """电话提醒（用于 critical 级别通知医生）。

    实际使用腾讯云语音通知或阿里云语音服务。
    """

    def __init__(self, app_id: str = "", app_key: str = ""):
        self.app_id = app_id
        self.app_key = app_key

    def make_call(self, phone: str, message: str) -> dict:
        """拨打电话，语音播报消息。"""
        # 实际代码用语音 API
        logger.info(f"[电话] 拨打 {phone}，播报：{message[:50]}...")
        return {"code": 0, "message": "呼叫成功"}


class NotificationDispatcher:
    """通知分发器：按异常等级走不同通知渠道。

    核心逻辑：
    - normal  → 企业微信（护工群）
    - warning → 企业微信 + 短信（家属）
    - critical → 企业微信 + 短信（家属）+ 电话（医生）
    """

    def __init__(self):
        # 初始化各渠道（实际使用时从 config 读 Webhook URL 和密钥）
        self.wechat = WeChatWorkBot(webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx")
        self.sms = SMSNotifier(app_id="mock", app_key="mock")
        self.phone = PhoneCallNotifier(app_id="mock", app_key="mock")

        # 通知对象配置（实际从数据库或配置文件读）
        self.recipients = {
            "nurse": {
                "wechat_mentioned": ["@zhang_nurse"],  # 护工张姐的企业微信ID
                "name": "护工张姐",
            },
            "family": {
                "phone": "138****8888",  # 家属手机号
                "name": "家属王先生",
            },
            "doctor": {
                "phone": "139****9999",  # 李医生手机号
                "name": "李医生",
            },
        }

        # 短信模板ID（需在云服务控制台审核）
        self.sms_templates = {
            "warning": "SMS_001",    # "【养老看护】{name}今日{vitals}，请关注。"
            "critical": "SMS_002",   # "【养老看护】{name}危急：{vitals}，建议立即就医。"
        }

    def dispatch(self, severity: str, message: str, care_record: dict = None) -> dict:
        """根据异常等级分发通知。

        severity: normal / warning / critical
        message: 通知内容文本
        care_record: 护理记录（用于提取短信参数）
        """
        results = {"severity": severity, "channels": []}

        if severity == Severity.NORMAL:
            # normal：仅企业微信通知护工
            result = self._send_wechat(
                content=f"📋 日常记录归档\n{message}",
                mentioned=[self.recipients["nurse"]["wechat_mentioned"][0]],
            )
            results["channels"].append({"channel": "wechat", "to": "nurse", "result": result})

        elif severity == Severity.WARNING:
            # warning：企业微信（护工）+ 短信（家属）
            # 1. 企业微信通知护工
            result1 = self._send_wechat(
                content=f"⚠️ 需关注\n{message}",
                mentioned=self.recipients["nurse"]["wechat_mentioned"],
            )
            results["channels"].append({"channel": "wechat", "to": "nurse", "result": result1})

            # 2. 短信通知家属
            sms_params = self._extract_sms_params(care_record)
            result2 = self.sms.send_sms(
                phone=self.recipients["family"]["phone"],
                template_id=self.sms_templates["warning"],
                params=sms_params,
            )
            results["channels"].append({"channel": "sms", "to": "family", "result": result2})

        elif severity == Severity.CRITICAL:
            # critical：企业微信（护工）+ 短信（家属）+ 电话（医生）
            # 1. 企业微信通知护工（@all 引起注意）
            result1 = self._send_wechat(
                content=f"🔴 危急警报\n{message}",
                mentioned=["@all"],
            )
            results["channels"].append({"channel": "wechat", "to": "nurse", "result": result1})

            # 2. 短信通知家属
            sms_params = self._extract_sms_params(care_record)
            result2 = self.sms.send_sms(
                phone=self.recipients["family"]["phone"],
                template_id=self.sms_templates["critical"],
                params=sms_params,
            )
            results["channels"].append({"channel": "sms", "to": "family", "result": result2})

            # 3. 电话提醒医生
            result3 = self.phone.make_call(
                phone=self.recipients["doctor"]["phone"],
                message=message,
            )
            results["channels"].append({"channel": "phone", "to": "doctor", "result": result3})

        else:
            logger.warning(f"未知异常等级：{severity}，不发送通知")

        # 记录通知日志（实际存数据库）
        logger.info(f"通知分发完成：severity={severity}, channels={len(results['channels'])}")
        return results

    def _send_wechat(self, content: str, mentioned: list[str] = None) -> dict:
        """发送企业微信消息。"""
        return self.wechat.send_text(content=content, mentioned_list=mentioned)

    def _extract_sms_params(self, care_record: dict) -> list[str]:
        """从护理记录提取短信模板参数。"""
        if not care_record:
            return ["王奶奶", "体温正常", "血压正常"]
        name = care_record.get("patient_name", "老人")
        vitals = f"体温{care_record.get('temperature', '?')}°C"
        bp = f"血压{care_record.get('systolic', '?'}/{care_record.get('diastolic', '?')}"
        return [name, vitals, bp]

    def dispatch_from_orchestrator(self, orchestrator_result: dict) -> dict:
        """从 Day 06 orchestrator 的输出直接分发通知。

        orchestrator_result: Day 06 run_pipeline() 的返回值
        """
        severity = orchestrator_result.get("severity", "normal")
        notification_text = orchestrator_result.get("notification", "")
        care_record = orchestrator_result.get("care_record", "")

        # 解析 care_record（如果是 JSON 字符串）
        if isinstance(care_record, str):
            import json
            try:
                care_record = json.loads(care_record)
            except (json.JSONDecodeError, TypeError):
                care_record = {}

        return self.dispatch(severity, notification_text, care_record)


# ============================================================
# 测试：三种等级的通知分发
# ============================================================

if __name__ == "__main__":
    dispatcher = NotificationDispatcher()

    # 场景1：日常记录（normal）
    print("=" * 60)
    print("场景1：日常记录（normal）")
    print("=" * 60)
    result1 = dispatcher.dispatch(
        severity="normal",
        message="王奶奶今日记录已归档：体温36.8°C，血压135/85，心率78，饮食正常。",
        care_record={"patient_name": "王奶奶", "temperature": 36.8, "systolic": 135, "diastolic": 85},
    )
    print(f"通知结果：{result1}\n")

    # 场景2：需关注（warning）
    print("=" * 60)
    print("场景2：需关注（warning）")
    print("=" * 60)
    result2 = dispatcher.dispatch(
        severity="warning",
        message="王奶奶体温37.8°C，血压150/95，请关注。建议增加体温监测频次。",
        care_record={"patient_name": "王奶奶", "temperature": 37.8, "systolic": 150, "diastolic": 95},
    )
    print(f"通知结果：{result2}\n")

    # 场景3：危急（critical）
    print("=" * 60)
    print("场景3：危急（critical）")
    print("=" * 60)
    result3 = dispatcher.dispatch(
        severity="critical",
        message="王奶奶体温39.1°C，血压170/105，心率110，伴头痛恶心，建议立即就医！",
        care_record={"patient_name": "王奶奶", "temperature": 39.1, "systolic": 170, "diastolic": 105},
    )
    print(f"通知结果：{result3}\n")

    # 场景4：从 orchestrator 结果直接分发
    print("=" * 60)
    print("场景4：从 orchestrator 结果直接分发")
    print("=" * 60)
    mock_orchestrator_result = {
        "severity": "critical",
        "notification": "王奶奶危急：体温39.1，建议立即就医",
        "care_record": '{"patient_name": "王奶奶", "temperature": 39.1, "systolic": 170, "diastolic": 105}',
    }
    result4 = dispatcher.dispatch_from_orchestrator(mock_orchestrator_result)
    print(f"通知结果：{result4}")
```

### 2.4 通知分发在系统中的位置

把通知分发放回到整个系统里看：

```
护工录音
  │
  ▼
Day 01: ASR 转文本
  │
  ▼
Day 06: orchestrator.py（多 Agent 编排）
  ├─ 提取 Agent → CareRecord
  ├─ 异常 Agent → anomalies + severity
  ├─ 趋势 Agent → trend_report
  ├─ 建议 Agent → advice_list
  └─ 通知 Agent → notification（只生成文本）
        │
        ▼
Day 07: notification_dispatcher.py（今天的新增）
  │
  ├─ severity=normal  → 企业微信（护工群）
  ├─ severity=warning → 企业微信 + 短信（家属）
  └─ severity=critical → 企业微信 + 短信 + 电话（医生）
```

Day 06 的通知 Agent 负责"生成通知内容"，今天的 `NotificationDispatcher` 负责"把内容发到正确渠道"。这是关注点分离——Agent 决定"说什么"，Dispatcher 决定"怎么说、说给谁"。

### 2.5 接入 FastAPI

把通知分发接入 Day 01 的 FastAPI 项目结构，加一个通知路由：

```python
# routers/notification.py
from fastapi import APIRouter
from notification_dispatcher import NotificationDispatcher

router = APIRouter(prefix="/api/notification", tags=["通知"])
dispatcher = NotificationDispatcher()


@router.post("/dispatch")
async def dispatch_notification(severity: str, message: str, care_record: dict = None):
    """手动触发通知分发（测试用）。"""
    result = dispatcher.dispatch(severity, message, care_record)
    return result


@router.post("/dispatch-from-pipeline")
async def dispatch_from_pipeline(orchestrator_result: dict):
    """从编排流水线结果自动分发通知（生产用）。"""
    result = dispatcher.dispatch_from_orchestrator(orchestrator_result)
    return result
```

这样 Day 06 的 orchestrator 跑完后，结果直接传给 `/api/notification/dispatch-from-pipeline`，通知就自动按等级发出去了。整个链路从录音到通知全自动。

---

## 三、本周项目完整闭环

### 3.1 从录音到通知的全链路

把 Day 01-07 串起来，看完整的数据流：

```
护工手机录音（微信/企业微信）
  │
  │ POST /api/record/upload（AMR 文件）
  ▼
┌──────────────────────────────────────────────────────────┐
│  Day 01: ASR 转文本                                       │
│  腾讯云 ASR → "今天给王奶奶量了体温37度8..."               │
└──────────────────────────────────────────────────────────┘
  │
  │ POST /api/record/process
  ▼
┌──────────────────────────────────────────────────────────┐
│  Day 06: 多 Agent 编排（orchestrator.py）                 │
│                                                          │
│  ┌─ 提取 Agent ──────────────────────────────────────┐  │
│  │ Day 02: create_agent + Pydantic                   │  │
│  │ ASR文本 → CareRecord（体温/血压/心率/饮食/情绪）    │  │
│  └───────────────────────────────────────────────────┘  │
│         │                                                │
│         ▼                                                │
│  ┌─ Reflection ──────────────────────────────────────┐  │
│  │ Day 03: Critic Agent 检查 → 修正                  │  │
│  └───────────────────────────────────────────────────┘  │
│         │                                                │
│     ┌───┴───┐                                           │
│     ▼       ▼                                           │
│  ┌─异常──┐ ┌─趋势──────────────────────────────────┐   │
│  │检测异常│ │ Day 04-05: Agentic RAG + Qdrant      │   │
│  │severity│ │ 检索历史记录 + Reranking + 趋势分析   │   │
│  └────────┘ └──────────────────────────────────────┘   │
│     │       │                                           │
│     └───┬───┘                                           │
│         ▼                                                │
│  ┌─建议 Agent ───────────────────────────────────────┐  │
│  │ 综合异常 + 趋势 → 护理建议                        │  │
│  └───────────────────────────────────────────────────┘  │
│         │                                                │
│         ▼                                                │
│  ┌─通知 Agent ──────────────────────────────────────┐  │
│  │ 生成通知消息 + 确定等级                            │  │
│  └───────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────┐
│  Day 07: 通知分发（notification_dispatcher.py）           │
│                                                          │
│  severity=normal  → 企业微信（护工群）                    │
│  severity=warning → 企业微信 + 短信（家属）                │
│  severity=critical → 企业微信 + 短信 + 电话（医生）          │
└──────────────────────────────────────────────────────────┘
  │
  ▼
护工/家属/医生收到通知
```

### 3.2 本周产出物清单

| Day | 产出 | 代码文件 |
|-----|------|---------|
| Day 01 | FastAPI 脚手架 + ASR 接入 | `main.py` + `routers/record.py` + `services/asr.py` |
| Day 02 | 结构化提取 Agent | `extraction_agent.py` |
| Day 03 | Reflection/Self-Correction | `reflection_agent.py` |
| Day 04 | Agentic RAG（冲突处理 + Reranking） | `agentic_rag.py` |
| Day 05 | 向量检索 + 趋势分析 | `trend_agent.py` |
| Day 06 | 多 Agent 编排 | `orchestrator.py` |
| Day 07 | 通知分发 + 多模态概念笔记 | `notification_dispatcher.py` |

### 3.3 面试覆盖

Week 10 直接覆盖了面试高频题：

| 面试题 | Week 10 哪天 | 能答吗 |
|--------|------------|--------|
| Q8 Reflection/Self-Correction | Day 03 | ✅ |
| Q13 RAG 冲突处理 | Day 04 | ✅ |
| Q14 权限隔离 ACL | Day 04（复用 Week 09 Day 06） | ✅ |
| Q15 实时更新知识库 | Day 04（动态路由） | ✅ |
| Q16 提升准确度（Reranking） | Day 04 | ✅ |
| Q17 表格处理 | Day 07 | ✅（概念） |
| Q18 图片插入 | Day 07 | ✅（概念） |
| Q19 大表格优化 | Day 07 | ✅（概念） |
| Q20 跨页图文 | Day 07 | ✅（概念） |

---

## 动手实验

### 🟢 青铜：跑通通知分发，验证三种等级

1. 把 `notification_dispatcher.py` 存成文件
2. 运行 `python notification_dispatcher.py`，观察三种场景的输出
3. 确认：normal 只发企业微信，warning 加了短信，critical 三个渠道都发了
4. 理解 `dispatch_from_orchestrator` 怎么从 Day 06 的输出提取 severity 和 care_record

目标：跑通通知分发，理解"按等级走不同渠道"的决策逻辑。

### 🟡 白银：接入真实企业微信 Webhook

1. 在企业微信群里添加一个机器人，获取 Webhook URL
2. 把 URL 填入 `WeChatWorkBot` 的 `webhook_url`
3. 取消注释 `requests.post` 那行代码，真实发送消息
4. 跑 `dispatch(severity="warning", ...)`，看企业微信群是否收到消息
5. 注意：短信和电话通道需要云服务配置，可以先只通企业微信

目标：至少通一个真实通知渠道，验证全链路。

### 🔴 王者：完整全链路 Demo

1. 把 Day 01 的 FastAPI + Day 06 的 orchestrator + Day 07 的 notification_dispatcher 串起来
2. 写一个 `/api/record/process` 接口：上传录音 → ASR → orchestrator → 通知分发，全自动
3. 用 Postman 或 curl 上传一段录音，观察整个链路自动跑完
4. 在企业微信群验证收到通知
5. 用 Week 09 的评估系统对这个全链路跑评估，记录成功率

目标：跑通从"护工上传录音"到"家属收到短信"的完整闭环。

---

## 踩坑记录 🕳️

### 坑 1：企业微信 Webhook 有频率限制

企业微信群机器人 Webhook 每分钟最多发 20 条消息。如果系统短时间内触发大量通知（比如同时检测到多个老人异常），会被限流。

**解决：** 加消息队列缓冲——通知不直接发，先进队列，按频率限速消费。养老场景通知量不大，简单的 `time.sleep(1)` 限速即可；生产环境用 Redis 队列或 Celery。

### 坑 2：短信模板需要审核

短信不是想发什么就发什么——云服务商要求短信内容走"模板"，模板需要审核通过。你不能临时写"王奶奶危急，体温39度"直接发，得用预审的模板 + 参数填充。

**解决：** 提前在腾讯云/阿里云控制台申请模板。模板格式如：`【养老看护】{1}今日{2}，请关注。`，参数是 `["王奶奶", "体温37.8°C，血压150/95"]`。审核一般 1-2 个工作日。

### 坑 3：通知内容可能包含敏感信息

护工记录里可能有老人隐私信息（身份证号、具体诊断），直接发企业微信或短信可能泄漏。

**解决：** 通知内容做脱敏处理——身份证号显示前4后4（`3201****5678`），诊断用通用描述（"体温异常"而非"肺炎"）。这和 Week 09 Day 05 的输出过滤 + PII 检测是一脉相承的。

### 坑 4：多模态概念不要过度投入

多模态处理的概念看起来不难（Markdown 化 + 占位符 + Select-then-Read），但实际实现涉及 OCR 引擎、文档解析、布局分析——每一个都是独立的坑。学习阶段不要被这些技术细节吸进去。

**解决：** 把多模态当"知识储备"——面试时能说清四类问题的解决思路就够了。等真正做多模态项目时，再深挖具体实现。本周的重点是 Agent 编排和通知分发，不是 OCR。

### 坑 5：通知等级和 orchestrator 的 severity 要对齐

Day 06 的 orchestrator 用 `severity` 字段（"normal"/"warning"/"critical"），今天的 NotificationDispatcher 也用同样的等级。但如果两边定义不一致（比如 orchestrator 输出 "safe" 而 dispatcher 期望 "normal"），通知就发不出去。

**解决：** 用 Enum 统一定义等级，orchestrator 和 dispatcher 都引用同一个 Enum。本代码的 `Severity(str, Enum)` 就是这个目的。如果 orchestrator 和 dispatcher 是不同团队开发的，在接口文档里明确枚举值。

---

## 副线笔记

### 全程 Claude Code 结对编程

本周是 12 周学习的核心项目周，全程 Claude Code 结对编程。实际协作方式：

```
你：我要搭养老护工记录系统，从 ASR 到通知全链路。
   分 7 天，每天一个模块。帮我先出项目结构。

Claude Code：（生成 FastAPI 项目结构）

你：Day 02 的提取 Agent 用 create_agent，不要用手写的 while 循环。
   结构化输出用 Pydantic，异常标记自动算。

Claude Code：（生成 extraction_agent.py）

你：Day 03 的 Reflection，我听说 2026 有个 RubricGradingMiddleware？
   先用经典 StateGraph 双节点做，更容易理解。

Claude Code：（生成 reflection_agent.py）
...
```

这种协作的核心是：**你定架构和验收标准，Claude Code 出实现**。你不写代码，但审代码。每天的内容你都要跑通验证，发现问题让 Claude Code 修。

### 本周项目的面试讲法

这个养老护工项目是面试的核心故事。按这个顺序讲：

```
1. 业务背景（30秒）：
   "养老护工每天查房，记录老人状况。传统方式是手写表单，
   费时且遗漏多。我做了个 AI 系统，护工录音就能自动提取记录。"

2. 技术架构（1分钟）：
   "ASR 转文本 → 多 Agent 编排（提取/异常/趋势/建议/通知）
   → 按等级分发通知。用了 LangGraph StateGraph 编排五个子 Agent，
   Qdrant 做历史记录检索，BGE-Reranker 做 Reranking。"

3. 技术亮点（2分钟，挑 2-3 个讲）：
   - Reflection 模式："提取 Agent 输出后，Critic Agent 检查并反馈修正"
   - Agentic RAG："历史记录冲突用元数据加权解决，检索用 Cross-Encoder Reranking 精排"
   - 多 Agent 编排："StateGraph 编排，异常和趋势 fan-out 并行，advice 节点 barrier 汇合"

4. 质量保障（30秒）：
   "用 Week 09 的评估系统跑了 24 个测试任务，Shadow Testing 验证升级无退化"
```

### 与前几周产出物的关系

把 Week 07-10 的产出物串起来看：

```
Week 07 Day 07：多 Agent 徒步规划系统（能力验证）
    → "我能做多 Agent 协作"
Week 08 Day 07：MCP Server + Skill（协议生态）
    → "我的 Agent 能连接外部世界"
Week 09 Day 07：评估表格 + 安全审计（质量保障）
    → "我的 Agent 跑得好不好、安不安全"
Week 10 Day 07：养老护工系统 + 通知分发（完整项目）
    → "我做过一个从 0 到 1 的完整 Agent 项目"
```

Week 07-09 是单点能力验证，Week 10 是综合项目实战。面试时 Week 10 的项目是主讲，Week 07-09 的产出是"我有证据"——"你不信我能做多 Agent？看 Week 07 的徒步系统。不信我做了评估？看 Week 09 的评估表格"。

---

## 检查清单

- [ ] 理解多模态处理的四类问题（表格/图片/大表格/跨页）和解决思路
- [ ] 面试 Q17-Q20 能说清原理（Markdown 化 / 占位符 / Select-then-Read / 滑动窗口）
- [ ] 理解为什么多模态不做完整代码（方案 B 降级）
- [ ] 跑通了 `notification_dispatcher.py`，验证三种等级的通知分发
- [ ] 理解通知等级和渠道的映射（normal→企微 / warning→企微+短信 / critical→全渠道）
- [ ] 能把 Day 06 orchestrator 的输出接入通知分发（`dispatch_from_orchestrator`）
- [ ] 知道企业微信 Webhook 的使用方式和频率限制
- [ ] 理解通知内容需要脱敏（复用 Week 09 的 PII 检测）
- [ ] 能画出从录音到通知的完整全链路图
- [ ] 用 Claude Code 结对编程完成了至少一个模块

---

## 本周总结

### Week 10 学了什么

这周把 Week 01-09 学的全部串成一个完整项目：

| Day | 主题 | 核心产出 | 衔接的前几周 |
|-----|------|---------|------------|
| Day 01 | 项目脚手架 + ASR | FastAPI 结构 + 腾讯云 ASR | Week 01 FastAPI |
| Day 02 | 结构化提取 Agent | `extraction_agent.py` | Week 03 Agent Loop + Week 06 create_agent |
| Day 03 | Reflection/Self-Correction | `reflection_agent.py` | 面试 Q8 新增 |
| Day 04 | Agentic RAG | `agentic_rag.py` | Week 04 RAG + 面试 Q13/Q16 |
| Day 05 | 向量检索 + 趋势 | `trend_agent.py` | Week 05 Qdrant |
| Day 06 | 多 Agent 编排 | `orchestrator.py` | Week 07 Subagents |
| Day 07 | 通知分发 + 多模态概念 | `notification_dispatcher.py` | Week 09 安全 + 面试 Q17-Q20 |

### 核心认知升级

```
Week 01-09：分模块学习（FastAPI / RAG / Agent / MCP / 评估 / 安全）
    ↓
Week 10：综合应用——把所有模块串成一个完整项目
```

三个核心认知：

1. **完整项目 > 单点能力**——面试官不只看你"会不会 create_agent"，更看你能不能从 0 到 1 做一个有业务价值的系统
2. **新增能力填补面试空白**——Reflection（Q8）和 Agentic RAG（Q13-Q16）是前 9 周没覆盖的高频考点
3. **从 Demo 到产品**——通知分发让系统从"能跑"变成"能用"，护工/家属/医生真能收到通知

### 本周新增的面试考点

| 面试题 | 新增于 | 答题要点 |
|--------|--------|---------|
| Q8 Reflection | Day 03 | 提取→Critic检查→反馈→修正，StateGraph 双节点或 RubricGradingMiddleware |
| Q13 RAG 冲突处理 | Day 04 | 元数据加权（时间越近权重越高）+ 多源验证 |
| Q15 实时更新 | Day 04 | 动态路由：实时问题调 API，历史问题调向量库 |
| Q16 Reranking | Day 04 | Cross-Encoder 精排：Qdrant 粗排 top-K → BGE-Reranker 精排 top-N |
| Q17-Q20 多模态 | Day 07 | Markdown 化 + 占位符 + Select-then-Read + 滑动窗口 |

加上前几周的覆盖，到 Week 10 结束时面试 20 题全部覆盖（20/20 ✅），且每个考点都有代码实战支撑。

---

## 下周预告

> **Week 11 — 部署 + 浏览器 Agent + 沙箱。** Week 10 让养老护工系统"能跑了"，但还跑在你的本地电脑上。Week 11 让它"上线"——Docker 容器化、GitHub Actions CI/CD、Langfuse 监控仪表盘。同时补齐两个 2026 年 Agent 工程师必备能力：浏览器 Agent（browser-use + Playwright，让 AI 像人一样操作浏览器）和沙箱代码执行（E2B/Modal，Agent 写的代码在隔离环境里跑）。产出：上线项目 + 浏览器 Agent demo。
