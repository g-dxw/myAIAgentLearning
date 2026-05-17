### 练习 1：LLM 调用配置模型（15 min）
import json
from typing import Literal
from pydantic import BaseModel, Field, field_validator;

class LLMCallConfig(BaseModel):
    model: str = Field(default="deepseek", description="模型名称")
    temperature: float = Field(default=0.7, ge= 0, le= 1, description="生成文本的随机程度，范围是0到1")
    max_tokens: int = Field(default=12048, ge=1, le= 20000, description="生成文本的最大长度，单位是token")
    system: str = Field(default="user", description="系统角色")
    stream: bool = Field(default=False, description="是否开启流式输出")
    stop_reason_expected: list[Literal['end_turn', 'tool_use', 'max_tokens']] = Field(default=["stop", "timeout"], description="停止生成的原因")
    input: dict = Field(default={}, description="输入内容，可以是字典")

    @field_validator("input", mode="before")
    def check_input(cls, v):
        if isinstance (v, str):
            return json.loads(v)
        return v

# 测试：创建合法配置，然后故意设错参数看报错信息

LLMCallConfig(model="gpt-4", temperature=0.5, max_tokens=10480, system="assistant", stream=True, stop_reason_expected=["end_turn", "tool_use"], input={"question": "What is the capital of France?"})
LLMCallConfig(model="gpt-4", temperature=0.5, max_tokens=10480, system="assistant", stream=True, stop_reason_expected=["end_turn", "tool_use"], input='{"question": "What is the capital of France?"}')


class VitalSigns(BaseModel):
    heart_rate: int = Field(default=70, ge=0, description="心率，单位是bpm")
    systolic_pressure: int = Field(default=100, ge=30, le=250, description="收缩压，单位是mmHg")
    diastolic_pressure: int = Field(default=65, ge=20, le=120, description="舒张压，单位是mmHg")
    oxygen_saturation: float = Field(default=98.0, ge=0, le=100, description="血氧饱和度，单位是%")
    temperature: float = Field(default=36.6, ge=0, description="体温，单位是摄氏度")

class Meal(BaseModel):
    meal_type: Literal["早餐", "午餐", "晚餐", "加餐"]
    name: str = Field(default="未命名", description="餐食名称")
    calories: int = Field(default=0, ge=0, description="卡路里，单位是大卡")
    protein: float = Field(default=0.0, ge=0, description="蛋白质含量，单位是克")
    fat: float = Field(default=0.0, ge=0, description="脂肪含量，单位是克")
    carbohydrates: float = Field(default=0.0, ge=0, description="碳水化合物含量，单位是克")

class Medication(BaseModel):
    name: str = Field(default="未命名", description="药物名称")
    dosage: float = Field(default=0.0, ge=0, description="药物剂量，单位是毫克")
    frequency: str = Field(default="每日一次", description="用药频率")

class CareForm(BaseModel):
    """护工照护表单 —— 对应 LLM 结构化输出的 Schema"""
    meals: list[Meal]
    medications: list[Medication] = []
    patient_name: str = Field(default="未命名", description="患者姓名")
    age: int = Field(default=0, ge=0, description="年龄，单位是岁")
    gender: Literal["男", "女"] = Field(default="男", description="性别")
    mental_status: str = Field(default="正常", description="精神状态")
    skin_condition: str = Field(default="健康", description="皮肤状况")
    activity_level: int = Field(default=5, ge=0, le=5, description="运动能力等级")
    pain_level: int = Field(default=0, ge=0, le=10, description="疼痛等级")
    vital_signs: VitalSigns = Field(default_factory=VitalSigns, description="生命体征")
    meals: list[Meal] = Field(default_factory=list, description="餐食记录")
    medications: list[Medication] = Field(default_factory=list, description="用药记录")

   
    @field_validator("pain_level", mode="before")
    def validate_pain_level(cls, value):
        """护工可能说 '疼得厉害' 而不是数字"""
        pain_map = {"无": 0, "轻微": 2, "中度": 5, "很疼": 8, "剧烈": 10}
        if isinstance(value, str):
            return pain_map.get(value, value)  # 默认无疼痛
        return value
    
# 测试：模拟 LLM 返回的结构化数据
mock_llm_output = {
    "vital_signs": {"blood_pressure_systolic": 145, "blood_pressure_diastolic": 90, "heart_rate": 78},
    "meals": [
        {"meal_type": "早餐", "content": "半碗粥 + 一个鸡蛋", "intake_percentage": 80},
    ],
    "fluid_intake_ml": 300,
    "pain_level": "中度",  # 字符串 → 自动转为 5
    "caregiver_notes": "情绪不错"
}


form = CareForm(**mock_llm_output)
print(form.model_dump())
print(f"疼痛评分: {form.pain_level}")  # 5


class GetWeatherInput(BaseModel):
    """查询天气的参数"""
    city: str = Field(description="城市名称，如北京、上海")
    date: str | None = Field(default=None, description="日期，YYYY-MM-DD 格式，默认今天")

# Pydantic v2 内置 JSON Schema 生成
schema = GetWeatherInput.model_json_schema()
print(json.dumps(schema, ensure_ascii=False, indent=2))

# 直接作为 Claude tool 的 input_schema
tool_definition = {
    "name": "get_weather",
    "description": "查询指定城市的天气信息",
    "input_schema": GetWeatherInput.model_json_schema(),
}

print(json.dumps(CareForm.model_json_schema(), ensure_ascii=False, indent=2))