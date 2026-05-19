"""AI information extraction and completeness check."""

import os

from sqlalchemy.orm import Session

from models.chat_message import ChatMessage
from models.patient import Patient
from ai.client import AIClient


def _load_prompt(name: str) -> str:
    """Load a prompt file from the prompts directory."""
    path = os.path.join(os.path.dirname(__file__), "prompts", name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def extract_patient_info(session_id: int, db: Session) -> dict:
    """Extract structured patient info from session chat history."""
    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id,
    ).order_by(ChatMessage.created_at).all()

    if not messages:
        return {
            "guardian_info": "",
            "disease_info": "",
            "care_requirements": "",
            "personality": "",
        }

    ai_messages = [{"role": m.role, "content": m.content} for m in messages]

    client = AIClient()
    system_prompt = _load_prompt("extract.md")
    result = client.extract_json(ai_messages, system_prompt)

    return {
        "guardian_info": result.get("guardian_info", ""),
        "disease_info": result.get("disease_info", ""),
        "care_requirements": result.get("care_requirements", ""),
        "personality": result.get("personality", ""),
    }


def check_completeness(patient_id: int, db: Session) -> dict:
    """Check if patient info is complete using AI."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        return {"is_complete": False, "missing_fields": ["病人不存在"]}

    info = {
        "disease_info": patient.disease_info or "",
        "care_requirements": patient.care_requirements or "",
    }

    # Simple local check first
    missing = []
    if not info["disease_info"]:
        missing.append("基础疾病信息（disease_info）")
    if not info["care_requirements"]:
        missing.append("照护要求（care_requirements）")

    if not missing:
        return {"is_complete": True, "missing_fields": []}

    # Use AI for more nuanced check
    try:
        client = AIClient()
        system_prompt = _load_prompt("completeness.md")
        ai_messages = [{
            "role": "user",
            "content": f"请检查以下病人信息是否完整：\n{str(info)}",
        }]
        result = client.extract_json(ai_messages, system_prompt)
        return result
    except Exception:
        # Fall back to simple check if AI fails
        return {"is_complete": len(missing) == 0, "missing_fields": missing}
