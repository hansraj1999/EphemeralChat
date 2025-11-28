from fastapi import APIRouter, HTTPException, Query, Request
from schemas.rooms import CreateRoomRequest, CreateRoomResponse, JoinRoomRequest, JoinRoomResponse, CloseRoomRequest, RoomDetailsResponse
import random
import string
from backend import redis_backend
import uuid
from datetime import datetime, timedelta
import os
import json
from typing import Optional
from schemas.rooms import LeaveRoomRequest
from logging_config import get_logger

logger = get_logger(__name__)

rooms_router = APIRouter(prefix="/rooms", tags=["rooms"])

def generate_random_slug(length: int = 20) -> str:
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

@rooms_router.post("/")
async def create_room(room: CreateRoomRequest, request: Request):
    # { "password": "optional-cleartext-or-hash", "expiry_seconds": 600, // optional, default 600 (10m) "max_users": 20, "name": "optional-room-name" }
    # Response 201: { "room_id": "7hd92f", "ws_url": "wss://api.example.com/rooms/7hd92f/ws?token=abc", "expires_at": "2025-11-17T12:34:56Z" }
    logger.info(f"Room creation request from {request.client.host}, name: {room.name}, max_users: {room.max_users}")
    expiry_seconds = room.expiry_seconds or 600
    max_users = room.max_users or 20
    name = room.name or generate_random_slug(20)
    room_id = uuid.uuid4().hex
    expires_at = (datetime.now() + timedelta(seconds=expiry_seconds)).isoformat()
    
    try:
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
        
        # Construct WebSocket URL using request's base URL
        base_url = str(request.base_url).rstrip('/')
        # Replace http/https with ws/wss
        ws_scheme = "wss" if base_url.startswith("https") else "ws"
        ws_base = base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_base}/rooms/{room_id}/ws"
        
        logger.info(f"Room {room_id} created successfully: name={name}, expires_at={expires_at}, max_users={max_users}")
        
        return CreateRoomResponse(
            room_id=room_id,
            ws_url=ws_url,
            expires_at=expires_at,
        )
    except Exception as e:
        logger.error(f"Error creating room: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create room")


@rooms_router.post("/{room_id}/join")
async def join_room(room_id: str, join_room_request: JoinRoomRequest, request: Request):
    # POST /rooms/{room_id}/join Body: { "password": "if-required", "display_name": "optional" }
    # Response 200: { "ws_url": "wss://.../rooms/{room_id}/ws?token=jwt-or-short-token", "expires_at": "..." }

    # - Client uses ws_url to open connection.
    logger.info(f"Join room request for {room_id} from {request.client.host}, display_name: {join_room_request.display_name}")
    
    room = redis_backend.get_room(room_id)
    if not room:
        logger.warning(f"Join room failed: Room {room_id} not found")
        raise HTTPException(status_code=400, detail="Room not found")
    
    room_password = room.get("password")
    # Check if password exists and is not None/empty/"None"
    if room_password and room_password != "None" and room_password != "" and room_password != join_room_request.password:
        logger.warning(f"Join room failed: Invalid password for room {room_id} from {request.client.host}")
        raise HTTPException(status_code=401, detail="Invalid password")
    
    # Construct WebSocket URL using request's base URL
    base_url = str(request.base_url).rstrip('/')
    # Replace http/https with ws/wss
    ws_base = base_url.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_base}/rooms/{room_id}/ws"
    
    expires_at = room.get("expires_at")
    if expires_at and expires_at < datetime.now().isoformat():
        logger.warning(f"Join room failed: Room {room_id} expired")
        redis_backend.delete_room(room_id)
        raise HTTPException(status_code=400, detail="Room expired")
    
    # Check max users
    max_users = room.get("max_users", 20)
    current_users = redis_backend.get_users_in_room(room_id)
    current_count = len(current_users)
    if current_count >= max_users:
        logger.warning(f"Join room failed: Room {room_id} is full ({current_count}/{max_users})")
        raise HTTPException(status_code=403, detail="Room is full")
    
    logger.info(f"Join room successful for {room_id}: {current_count}/{max_users} users")
    
    # Note: User is actually added to room when WebSocket connection is established
    # This endpoint just validates access and returns the WebSocket URL
    return JoinRoomResponse(
        ws_url=ws_url,
        expires_at=expires_at
    )


@rooms_router.post("/{room_id}/leave")
async def leave_room(room_id: str, leave_room_request: LeaveRoomRequest, request: Request):
    # POST /rooms/{room_id}/leave
    # Note: This is a notification endpoint. Actual cleanup happens when WebSocket disconnects.
    # If you need to force disconnect, you would need to track connection_id by IP/name
    # For now, this is just a placeholder - the WebSocket disconnect handler does the cleanup
    logger.info(f"Leave room request for {room_id} from {request.client.host}, display_name: {leave_room_request.display_name}")
    return {"message": "Leave request acknowledged. Disconnect WebSocket to complete leave."}


@rooms_router.get("/{room_id}", response_model=RoomDetailsResponse)
async def get_room_details(
    room_id: str, 
    password: Optional[str] = Query(None, description="Room password (required if room is password protected)"),
    request: Request = None
):
    """
    Get room details including online user count.
    Password is required if the room is password protected.
    
    Returns:
    - room_id: Unique room identifier
    - name: Room name
    - created_at: Room creation timestamp
    - expires_at: Room expiration timestamp
    - max_users: Maximum users allowed
    - online_users_count: Current number of online users
    - owner_name: Room owner's name
    - has_password: Whether room is password protected
    - is_expired: Whether room has expired
    - is_full: Whether room has reached max capacity
    """
    client_host = request.client.host if request and request.client else 'unknown'
    logger.info(f"Room details request for {room_id} from {client_host}")
    
    # Get room from Redis
    room = redis_backend.get_room(room_id)
    if not room:
        logger.warning(f"Room details failed: Room {room_id} not found")
        raise HTTPException(status_code=404, detail="Room not found")
    
    # Check if room has password and validate it
    room_password = room.get("password")
    # Handle both None and string "None" cases
    has_password = room_password is not None and room_password != "" and room_password != "None"
    
    if has_password:
        if not password:
            logger.warning(f"Room details failed: Password required for room {room_id}")
            raise HTTPException(status_code=401, detail="Password required for this room")
        
        if room_password != password:
            logger.warning(f"Room details failed: Invalid password for room {room_id}")
            raise HTTPException(status_code=401, detail="Invalid password")
    
    # Check if room is expired
    expires_at = room.get("expires_at")
    is_expired = False
    if expires_at:
        try:
            expires_datetime = datetime.fromisoformat(expires_at.replace('Z', '+00:00') if 'Z' in expires_at else expires_at)
            is_expired = expires_datetime < datetime.now()
            if is_expired:
                logger.info(f"Room {room_id} is expired, deleting it")
                redis_backend.delete_room(room_id)
        except (ValueError, TypeError):
            # If we can't parse the date, assume it's not expired
            pass
    
    # Get online users count
    current_users = redis_backend.get_users_in_room(room_id)
    online_users_count = len(current_users)
    
    # Check if room is full
    max_users = room.get("max_users", 20)
    is_full = online_users_count >= max_users
    
    logger.info(f"Room details retrieved for {room_id}: {online_users_count}/{max_users} users online")
    
    return RoomDetailsResponse(
        room_id=room_id,
        name=room.get("name"),
        created_at=room.get("created_at", ""),
        expires_at=room.get("expires_at", ""),
        max_users=max_users,
        online_users_count=online_users_count,
        owner_name=room.get("owner_name"),
        has_password=has_password,
        is_expired=is_expired,
        is_full=is_full
    )


@rooms_router.post("/{room_id}/close")
async def close_room(room_id: str, close_room_request: CloseRoomRequest, request: Request):
    # POST /rooms/{room_id}/close
    # - Room metadata (meta) is deleted from Redis.
    # - All active connections should be closed (handled by WebSocket cleanup)
    logger.info(f"Close room request for {room_id} from {request.client.host}")
    
    room = redis_backend.get_room(room_id)
    if not room:
        logger.warning(f"Close room failed: Room {room_id} not found")
        raise HTTPException(status_code=400, detail="Room not found")
    
    owner_ip = room.get("owner_ip")
    if owner_ip != request.client.host:
        logger.warning(f"Close room failed: {request.client.host} is not the owner ({owner_ip}) of room {room_id}")
        raise HTTPException(status_code=401, detail="You are not the owner of the room")
    
    redis_backend.delete_room(room_id)
    
    # Publish a room closure message to notify all connected clients
    closure_message = {
        "type": "system",
        "message": "Room has been closed by owner",
        "room_id": room_id,
        "timestamp": datetime.now().isoformat()
    }
    redis_backend.publish_message(room_id, closure_message)
    logger.info(f"Room {room_id} closed successfully by owner {request.client.host}")
    
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
