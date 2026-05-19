from pydantic import BaseModel, Field


class AbsenteeismOut(BaseModel):
    id: int
    schedule_id: int
    worker_id: int
    patient_id: int
    status: str
    auto_marked_at: str
    corrected_at: str | None = None
    corrected_by: int | None = None
    correction_reason: str | None = None
    score: int | None = None
    created_at: str
    worker_name: str | None = None
    patient_name: str | None = None

    model_config = {"from_attributes": True}


class AbsenteeismCorrect(BaseModel):
    correction_reason: str = Field(..., min_length=1, max_length=500)
