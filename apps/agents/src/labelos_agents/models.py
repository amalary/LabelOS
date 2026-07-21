from pydantic import BaseModel


class RootResponse(BaseModel):
    name: str
    environment: str
    version: str


class HealthResponse(BaseModel):
    status: str


class StatusResponse(BaseModel):
    service: str
    status: str
    environment: str
    version: str
    model_provider: str
