from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    patient_id: int = Field(..., ge=1)


class MessageAdd(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)


class SessionOut(BaseModel):
    id: int
    patient_id: int
    worker_id: int
    status: str
    summary: str | None = None
    created_at: str
    patient_name: str | None = None

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    created_at: str

    model_config = {"from_attributes": True}


class ExtractResult(BaseModel):
    guardian_info: str | None = None
    disease_info: str | None = None
    care_requirements: str | None = None
    personality: str | None = None


class ConfirmSubmit(BaseModel):
    guardian_info: str | None = None
    disease_info: str | None = None
    care_requirements: str | None = None
    personality: str | None = None
