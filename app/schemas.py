
from datetime import datetime
from typing import Optional, List, Literal, Union
from pydantic import BaseModel, Field


class ProvisionResponse(BaseModel):
    status: Literal["PROVISIONED"] = "PROVISIONED"
    client_identity: str
    api_key: str
    api_key_prefix: str
    tier: str
    credit_allocated: float


class BalanceResponse(BaseModel):
    client_identity: str
    credit_balance: float
    tier: str
    is_active: bool


class UsageEntry(BaseModel):
    endpoint: str
    model: Optional[str]
    input_tokens: int
    output_tokens: int
    total_cost: float
    success: bool
    upstream_status: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


class UsageSummary(BaseModel):
    client_identity: str
    credit_balance: float
    total_input_tokens_30d: int
    total_output_tokens_30d: int
    total_cost_30d: float
    request_count_30d: int
    recent: List[UsageEntry]


# ---- OpenAI-compatible request/response ----

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str = "llama3"
    messages: List[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = Field(default=None, ge=1, le=32000)
    stop: Optional[Union[str, List[str]]] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    user: Optional[str] = None


class EmbeddingRequest(BaseModel):
    model: str = "text-embedding-3-small"
    input: Union[str, List[str], List[int], List[List[int]]]
    encoding_format: Optional[Literal["float", "base64"]] = "float"
    user: Optional[str] = None
