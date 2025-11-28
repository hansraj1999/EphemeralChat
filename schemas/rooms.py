from pydantic import BaseModel
from typing import Optional


class CreateRoomRequest(BaseModel):
    password: Optional[str] = None
    expiry_seconds: Optional[int] = 600
    max_users: Optional[int] = 20
    name: Optional[str] = None
    owner_name: Optional[str] = None

class CreateRoomResponse(BaseModel):
    room_id: str
    ws_url: str
    expires_at: str

class JoinRoomRequest(BaseModel):
    password: Optional[str] = None
    display_name: Optional[str] = None

class LeaveRoomRequest(BaseModel):
    display_name: Optional[str] = None

class CloseRoomRequest(BaseModel):
    display_name: Optional[str] = None

class JoinRoomResponse(BaseModel):
    ws_url: str
    expires_at: str

class InviteRequest(BaseModel):
    valid_for_secs: int

class InviteResponse(BaseModel):
    invite_url: str

class OnlineUser(BaseModel):
    connection_id: str
    display_name: str
    connected_at: str

class RoomDetailsResponse(BaseModel):
    room_id: str
    name: Optional[str]
    created_at: str
    expires_at: str
    max_users: int
    online_users_count: int
    online_users: Optional[list[OnlineUser]] = None
    owner_name: Optional[str]
    has_password: bool
    is_expired: bool
    is_full: bool