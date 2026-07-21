from pydantic import BaseModel, ConfigDict


class RootResponse(BaseModel):
    name: str
    environment: str
    version: str


class HealthResponse(BaseModel):
    status: str


class DatabaseHealthResponse(BaseModel):
    status: str
    database: str


class StatusResponse(BaseModel):
    service: str
    status: str
    environment: str
    version: str


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: str
