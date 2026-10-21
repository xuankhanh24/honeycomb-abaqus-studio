"""Public v1 document shapes. Extension fields preserve solver-specific evidence."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import ModelSpec


class Document(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    schema_version: Literal["1"] = "1"


class RunSpec(Document):
    requested: ModelSpec
    resolved: dict[str, Any]
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    design_id: str
    changes: dict[str, Any] = Field(default_factory=dict)


class Attempt(Document):
    number: int = Field(ge=1)
    path: str
    job_name: str
    started_at: str
    ended_at: str | None = None
    process: dict[str, Any] | None = None
    durations: dict[str, float] = Field(default_factory=dict)


class ProgressEvent(Document):
    seq: int = Field(ge=1)
    time: str
    batch_id: str | None = None
    run_id: str | None = None
    payload: dict[str, Any]


class Artifact(Document):
    path: str
    bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ArtifactManifest(Document):
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    files: list[Artifact]


class QualityReport(Document):
    solver_completed: bool
    numerical_quality: Literal["passed", "review"]
    physical_validation: Literal["not_established", "established", "test_solver"] = "not_established"
    findings: list[str] = Field(default_factory=list)
    thresholds: dict[str, float] = Field(default_factory=dict)
    ml_eligible: bool = False


PUBLIC_CONTRACTS = {t.__name__: t for t in (RunSpec, Attempt, ProgressEvent, ArtifactManifest, QualityReport)}
