from fastapi import APIRouter, HTTPException
from schemas.rooms import CreateRoomRequest, CreateRoomResponse, JoinRoomRequest, JoinRoomResponse, CloseRoomRequest
import random
import string
from backend import redis_backend
import uuid
from datetime import datetime, timedelta
import os
import json
from fastapi import Request
from schemas.rooms import LeaveRoomRequest


rooms_router = APIRouter(prefix="/rooms", tags=["rooms"])

def generate_random_slug(length: int = 20) -> str:
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

@rooms_router.post("/")
async def create_room(room: CreateRoomRequest, request: Request):
    # { "password": "optional-cleartext-or-hash", "expiry_seconds": 600, // optional, default 600 (10m) "max_users": 20, "name": "optional-room-name" }
    # Response 201: { "room_id": "7hd92f", "ws_url": "wss://api.example.com/rooms/7hd92f/ws?token=abc", "expires_at": "2025-11-17T12:34:56Z" }
    expiry_seconds = room.expiry_seconds or 600
    max_users = room.max_users or 20
    name = room.name or generate_random_slug(20)
    room_id = uuid.uuid4().hex
    expires_at = (datetime.now() + timedelta(seconds=expiry_seconds)).isoformat()
    redis_backend.create_room(room_id, {
        "expiry_seconds": expiry_seconds,
        "max_users": max_users,
        "name": name,
        "created_at": datetime.now().isoformat(),
        "expires_at": expires_at,
        "password": room.password if room.password else None,
        "owner_ip": request.client.host,
        "owner_name": room.owner_name
    }, ttl=expiry_seconds)
    ws_url = f"wss://{os.getenv('DOMAIN', 'localhost')}/rooms/{room_id}/ws"
    return CreateRoomResponse(
        room_id=room_id,
        ws_url=ws_url,
        expires_at=expires_at,
    )


@rooms_router.post("/{room_id}/join")
async def join_room(room_id: str, join_room_request: JoinRoomRequest, request: Request):
    # POST /rooms/{room_id}/join Body: { "password": "if-required", "display_name": "optional" }
    # Response 200: { "ws_url": "wss://.../rooms/{room_id}/ws?token=jwt-or-short-token", "expires_at": "..." }

    # - Client uses ws_url to open connection.
    room = redis_backend.get_room(room_id)
    room = json.loads(room.decode('utf-8'))
    if not room:
        raise HTTPException(status_code=400, detail="Room not found")
    if room.get("password") and room.get("password") != join_room_request.password:
        raise HTTPException(status_code=401, detail="Invalid password")
    ws_url = f"wss://{os.getenv('DOMAIN', 'localhost')}/rooms/{room_id}/ws"
    expires_at = room.get("expires_at")
    if expires_at < datetime.now().isoformat():
        redis_backend.delete_room(room_id)
        raise HTTPException(status_code=400, detail="Room expired")
    # user expiry must consider room expiry
    user_expiry = expires_at - datetime.now().timestamp()
    redis_backend.add_user_to_room(room_id, request.client.host, join_room_request.display_name, ttl=user_expiry)
    return JoinRoomResponse(
        ws_url=ws_url,
        expires_at=expires_at
    )


@rooms_router.post("/{room_id}/leave")
async def leave_room(room_id: str, leave_room_request: LeaveRoomRequest, request: Request):
    # POST /rooms/{room_id}/leave
    # - Client uses ws_url to open connection.
    redis_backend.remove_user_from_room(room_id, request.client.host, leave_room_request.display_name)
    return {"message": "User left room successfully"}


@rooms_router.post("/rooms/{room_id}/close")
async def close_room(room_id: str, close_room_request: CloseRoomRequest, request: Request):
    # POST /rooms/{room_id}/close
    # - Room metadata (meta) is deleted from Redis.
    # - All active connections are closed.
    room = redis_backend.get_room(room_id)
    room = json.loads(room.decode('utf-8'))
    if not room:
        raise HTTPException(status_code=400, detail="Room not found")
    if room.get("owner_ip") != request.client.host :
        raise HTTPException(status_code=401, detail="You are not the owner of the room")
    redis_backend.delete_room(room_id)
    return {"message": "Room closed successfully"}


## Redis Schema / Keys


# **Key naming conventions**
# - `room:meta:{roomId}` — hash
# - `room:users:{roomId}` — set of user IDs / connection IDs
# - `room:channel:{roomId}` — pubsub channel name (string)
# - `invite:token:{token}` — invite metadata with TTL
# - `conn:{connId}` — transient mapping connection -> user


# **Example `room:meta:{id}` hash fields**
# - `id` = `{roomId}`
# - `created_at` = ISO timestamp
# - `expires_at` = ISO timestamp (or rely only on TTL)
# - `max_users` = integer
# - `password_hash` = bcrypt hash (optional)
# - `owner` = userId or null
# - `flags` = json string (e.g., allow_reconnect)


# **TTL**
# - Set Redis TTL on `room:meta:{id}` to `expiry_seconds` at creation.
# - Mirror TTL on `invite:token:{t}` and other ephemeral keys.


# **Connected users tracking**
# - On connect: `SADD room:users:{id} {connId}` and set `conn:{connId}` -> metadata with small TTL (unless persistent while connected).
# - On disconnect: `SREM room:users:{id} {connId}`. If set becomes empty, optionally trigger room deletion (if policy says room dies when empty).


# **Pub/Sub**
# - Channel name: `room:channel:{roomId}`
# - Messages published are JSON blobs with minimal required fields (senderId, text, ts, type).
