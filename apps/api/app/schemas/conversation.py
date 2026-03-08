from pydantic import BaseModel

class ConversationListItem(BaseModel):
    id: str
    wa_id: str
    intercept_mode: str
    status: str

class InterceptRequest(BaseModel):
    agent_id: str | None = None