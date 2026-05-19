from pydantic import BaseModel, Field


class PatientCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    age: int = Field(..., ge=0, le=150)
    gender: str = Field(..., pattern="^(男|女)$")
    insurance_type: str = Field(..., min_length=1, max_length=20)
    phone: str = Field(..., min_length=1, max_length=20)
    address: str = Field(..., min_length=1, max_length=200)
    emergency_contact: str = Field(default="", max_length=100)
    assigned_worker_id: int | None = None


class PatientUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    age: int = Field(..., ge=0, le=150)
    gender: str = Field(..., pattern="^(男|女)$")
    insurance_type: str = Field(..., min_length=1, max_length=20)
    phone: str = Field(..., min_length=1, max_length=20)
    address: str = Field(..., min_length=1, max_length=200)
    emergency_contact: str = Field(default="", max_length=100)
    assigned_worker_id: int | None = None


class PatientOut(BaseModel):
    id: int
    name: str
    age: int
    gender: str
    insurance_type: str
    phone: str
    address: str
    emergency_contact: str
    guardian_info: str | None = None
    disease_info: str | None = None
    care_requirements: str | None = None
    personality: str | None = None
    status: str
    assigned_worker_id: int | None = None
    assigned_worker_name: str | None = None
    last_updater_id: int | None = None
    update_method: str | None = None
    updated_at: str | None = None
    created_at: str

    model_config = {"from_attributes": True}


class PatientAssign(BaseModel):
    worker_id: int = Field(..., ge=1)


class SpecialConditionCreate(BaseModel):
    type: str = Field(..., pattern="^(死亡|就医|外出|其他)$")
    description: str = Field(..., min_length=1, max_length=500)


class SpecialConditionOut(BaseModel):
    id: int
    patient_id: int
    type: str
    description: str
    recorded_at: str

    model_config = {"from_attributes": True}


class PatientVersionOut(BaseModel):
    id: int
    patient_id: int
    updater_id: int
    update_method: str
    changed_fields: str
    created_at: str

    model_config = {"from_attributes": True}


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)
