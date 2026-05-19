import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session as DbSession, joinedload

from models.session import Session, SessionStatus
from models.chat_message import ChatMessage, MessageRole
from models.patient import Patient, PatientStatus
from models.patient_version import PatientVersion
from ai.client import AIClient
from ai.extract import extract_patient_info, check_completeness


def get_worker_patients(db: DbSession, worker_id: int):
    """护工端查询已分配的病人列表，含信息完善度百分比"""
    patients = db.query(Patient).options(
        joinedload(Patient.assigned_worker),
    ).filter(
        Patient.assigned_worker_id == worker_id,
        Patient.status == PatientStatus.ACTIVE,
    ).all()

    result = []
    for p in patients:
        # Determine info completeness level
        filled = 0
        total = 4
        if p.guardian_info:
            filled += 1
        if p.disease_info:
            filled += 1
        if p.care_requirements:
            filled += 1
        if p.personality:
            filled += 1

        result.append({
            "id": p.id,
            "name": p.name,
            "age": p.age,
            "gender": p.gender,
            "insurance_type": p.insurance_type,
            "guardian_info": p.guardian_info,
            "disease_info": p.disease_info,
            "care_requirements": p.care_requirements,
            "personality": p.personality,
            "info_completeness": round(filled / total * 100),
            "has_ongoing_session": db.query(Session).filter(
                Session.patient_id == p.id,
                Session.worker_id == worker_id,
                Session.status == SessionStatus.ONGOING,
            ).first() is not None,
        })

    return result


def get_or_create_session(db: DbSession, data, worker_id: int):
    """获取或创建护工-病人对话Session：每个病人对每个护工至多一个ongoing会话"""
    patient = db.query(Patient).filter(Patient.id == data.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="病人不存在")

    # Check worker is assigned to this patient
    if patient.assigned_worker_id != worker_id:
        raise HTTPException(status_code=403, detail="您未被分配到此病人")

    # Find existing ongoing session
    session = db.query(Session).filter(
        Session.patient_id == data.patient_id,
        Session.worker_id == worker_id,
        Session.status == SessionStatus.ONGOING,
    ).first()

    if session:
        return _session_to_dict(session, patient.name)

    # Create new session
    session = Session(
        patient_id=data.patient_id,
        worker_id=worker_id,
        status=SessionStatus.ONGOING,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return _session_to_dict(session, patient.name)


def _session_to_dict(s: Session, patient_name: str | None = None) -> dict:
    status = s.status
    if hasattr(status, "value"):
        status = status.value
    return {
        "id": s.id,
        "patient_id": s.patient_id,
        "worker_id": s.worker_id,
        "status": status,
        "summary": s.summary,
        "created_at": s.created_at.isoformat() if s.created_at else "",
        "patient_name": patient_name,
    }


def get_session(db: DbSession, session_id: int, worker_id: int):
    """获取Session详情，包含全部对话消息"""
    session = db.query(Session).options(
        joinedload(Session.patient),
    ).filter(
        Session.id == session_id,
        Session.worker_id == worker_id,
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="对话不存在")

    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id,
    ).order_by(ChatMessage.created_at).all()

    return {
        "session": _session_to_dict(session, session.patient.name if session.patient else None),
        "messages": [
            {
                "id": m.id,
                "session_id": m.session_id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else "",
            }
            for m in messages
        ],
    }


def _build_context(session_id: int, db: DbSession) -> list:
    """构建AI对话上下文：历史摘要（如有）+ 最近20条消息"""
    session = db.query(Session).filter(Session.id == session_id).first()
    context_messages = []

    # 1. If there's a summary, inject it as context
    if session and session.summary:
        context_messages.append({
            "role": "user",
            "content": f"[历史对话摘要]: {session.summary}",
        })
        context_messages.append({
            "role": "assistant",
            "content": "我已了解历史情况，请继续。",
        })

    # 2. Load recent messages
    recent = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id,
    ).order_by(ChatMessage.created_at.desc()).limit(20).all()

    for msg in reversed(recent):
        context_messages.append({
            "role": msg.role,
            "content": msg.content,
        })

    return context_messages


def add_message(db: DbSession, session_id: int, data, worker_id: int):
    """发送用户消息 → 调用AI获取回复 → 同时保存用户消息和AI回复"""
    session = db.query(Session).filter(
        Session.id == session_id,
        Session.worker_id == worker_id,
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="对话不存在")

    if session.status != SessionStatus.ONGOING:
        raise HTTPException(status_code=400, detail="对话已结束")

    # Save user message
    user_msg = ChatMessage(
        session_id=session_id,
        role=MessageRole.USER,
        content=data.content,
    )
    db.add(user_msg)
    db.flush()

    # Build context and get AI reply
    try:
        context = _build_context(session_id, db)
        # Add the new user message
        context.append({"role": "user", "content": data.content})

        client = AIClient()
        system_prompt = (
            "你是一个养老护理系统的 AI 助手，帮助护工补充病人信息。"
            "请友好地与护工对话，询问病人的监护人情况、基础疾病、照护要求和性格特点。"
            "每次只问 1-2 个问题，不要一次问太多。"
        )
        reply = client.chat(context, system_prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 回复失败: {str(e)}")

    # Save AI reply
    ai_msg = ChatMessage(
        session_id=session_id,
        role=MessageRole.ASSISTANT,
        content=reply,
    )
    db.add(ai_msg)
    db.commit()
    db.refresh(ai_msg)

    return {
        "user_message": {
            "id": user_msg.id,
            "session_id": user_msg.session_id,
            "role": user_msg.role,
            "content": user_msg.content,
            "created_at": user_msg.created_at.isoformat() if user_msg.created_at else "",
        },
        "ai_message": {
            "id": ai_msg.id,
            "session_id": ai_msg.session_id,
            "role": ai_msg.role,
            "content": ai_msg.content,
            "created_at": ai_msg.created_at.isoformat() if ai_msg.created_at else "",
        },
    }


def extract_info(db: DbSession, session_id: int, worker_id: int) -> dict:
    """调用AI从对话中提取结构化的病人信息（监护人、疾病、照护要求、性格）"""
    session = db.query(Session).filter(
        Session.id == session_id,
        Session.worker_id == worker_id,
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="对话不存在")

    try:
        result = extract_patient_info(session_id, db)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"信息提取失败: {str(e)}")


def confirm_submit(db: DbSession, session_id: int, data, worker_id: int):
    """护工二次确认提交：更新Patient表 + 创建PatientVersion + 完整性校验 + AI生成摘要"""
    session = db.query(Session).filter(
        Session.id == session_id,
        Session.worker_id == worker_id,
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="对话不存在")

    patient = db.query(Patient).filter(Patient.id == session.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="病人不存在")

    # Build changed fields tracking
    changed = {}
    fields_map = {
        "guardian_info": "监护人情况",
        "disease_info": "基础疾病信息",
        "care_requirements": "照护要求",
        "personality": "性格特点",
    }

    for field, label in fields_map.items():
        new_val = getattr(data, field)
        if new_val is not None and new_val.strip():
            old_val = getattr(patient, field)
            if old_val != new_val:
                changed[field] = {"old": old_val or "", "new": new_val}
                setattr(patient, field, new_val)

    if not changed:
        return {"updated": False, "message": "没有新的信息需要更新", "completeness": None}

    # Update patient tracking fields
    patient.last_updater_id = worker_id
    patient.update_method = "ai_supplement"
    patient.updated_at = datetime.utcnow()
    db.flush()

    # Create PatientVersion
    version = PatientVersion(
        patient_id=patient.id,
        updater_id=worker_id,
        update_method="ai_supplement",
        changed_fields=json.dumps(changed, ensure_ascii=False),
    )
    db.add(version)
    db.flush()

    # Check completeness
    try:
        completeness = check_completeness(patient.id, db)
    except Exception:
        completeness = {"is_complete": False, "missing_fields": ["完整性检查失败"]}

    # Generate summary via AI
    try:
        client = AIClient()
        messages = db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id,
        ).order_by(ChatMessage.created_at).all()

        chat_text = "\n".join([f"{m.role}: {m.content}" for m in messages])
        summary_prompt = "请用一段话总结以上关于病人信息的对话内容。"
        summary = client.chat(
            [{"role": "user", "content": chat_text}],
            summary_prompt,
            max_tokens=300,
        )
        session.summary = summary
    except Exception:
        session.summary = f"AI 补充更新: {', '.join(fields_map.get(f, f) for f in changed)}"

    db.commit()

    return {
        "updated": True,
        "changed_fields": list(changed.keys()),
        "completeness": completeness,
    }
