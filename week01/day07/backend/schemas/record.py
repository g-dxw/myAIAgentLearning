from pydantic import BaseModel


class CareRecordOut(BaseModel):
    id: int
    patient_id: int
    worker_id: int
    content: str
    created_at: str
    patient_name: str | None = None
    worker_name: str | None = None

    model_config = {"from_attributes": True}
