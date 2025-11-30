from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from routers.rooms import rooms_router
from backend import redis_backend
import uuid
import json
import asyncio
from typing import Dict, Set
from datetime import datetime
from logging_config import get_logger, setup_logging
import os

# Setup logging
log_level = os.getenv("LOG_LEVEL", "INFO")
log_file = os.getenv("LOG_FILE", None)
setup_logging(log_level=log_level, log_file=log_file)
logger = get_logger(__name__)

app = FastAPI()

# Configure CORS to allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)

app.include_router(rooms_router)

logger.info("FastAPI application initialized")

# In-memory connection tracking per room
# Format: {room_id: {connection_id: websocket}}
# NOTE: This is intentionally in-memory per instance. Each FastAPI instance tracks only its own
# WebSocket connections. Redis pub/sub distributes messages across all instances, and each
# instance broadcasts to its local connections. This enables horizontal scaling.
room_connections: Dict[str, Dict[str, WebSocket]] = {}

# Background tasks for Redis pub/sub listeners per room
# Format: {room_id: task}
room_pubsub_tasks: Dict[str, asyncio.Task] = {}


async def listen_to_redis_channel(room_id: str):
    """Background task to listen for messages from Redis pub/sub and broadcast to local connections."""
    logger.info(f"Starting Redis pub/sub listener for room: {room_id}")
    pubsub = None
    try:
        pubsub = redis_backend.subscribe_to_room(room_id)
        
        # Get the channel name
        channel = redis_backend.get_room_channel_name(room_id)
        logger.debug(f"Subscribed to Redis channel: {channel} for room: {room_id}")
        
        # Process messages from Redis using get_message() with timeout
        loop = asyncio.get_event_loop()
        
        while True:
            # Check if room still has connections (if not, we can exit)
            if room_id not in room_connections or len(room_connections[room_id]) == 0:
                logger.info(f"No more connections in room {room_id}, stopping listener")
                break
            
            # Run blocking get_message() in thread pool with timeout
            def get_message():
                """Blocking call to get next message from Redis pub/sub with timeout."""
                try:
                    return pubsub.get_message(timeout=1.0, ignore_subscribe_messages=True)
                except Exception as e:
                    logger.error(f"Error in pubsub.get_message() for room {room_id}: {e}", exc_info=True)
                    return None
            
            message = await loop.run_in_executor(None, get_message)
            
            if message is None:
                # Timeout or no message, continue loop
                continue
                
            message_type = message.get('type')
            if message_type in ['message', 'presence']:
                try:
                    # Parse the message
                    message_data = json.loads(message['data'])
                    logger.debug(f"Received message from Redis for room {room_id}: {message_data.get('type', 'unknown')}")
                    
                    # Broadcast to all local connections in this room
                    if room_id in room_connections:
                        local_connections = len(room_connections[room_id])
                        logger.debug(f"Broadcasting message to {local_connections} local connections in room {room_id}")
                        
                        # Create a list of tasks for concurrent sending
                        send_tasks = []
                        disconnected_connections = []
                        
                        for conn_id, ws in room_connections[room_id].items():
                            try:
                                send_tasks.append(ws.send_text(json.dumps(message_data)))
                            except Exception as e:
                                # Connection might be closed, mark for cleanup
                                disconnected_connections.append(conn_id)
                                logger.warning(f"Error sending to connection {conn_id} in room {room_id}: {e}")
                        
                        # Clean up disconnected connections
                        for conn_id in disconnected_connections:
                            if room_id in room_connections and conn_id in room_connections[room_id]:
                                del room_connections[room_id][conn_id]
                                redis_backend.remove_user_from_room(room_id, conn_id)
                                logger.info(f"Cleaned up disconnected connection {conn_id} from room {room_id}")
                        
                        # Send to all connections concurrently
                        if send_tasks:
                            await asyncio.gather(*send_tasks, return_exceptions=True)
                            logger.debug(f"Successfully broadcasted message to {len(send_tasks)} connections in room {room_id}")
                            
                except json.JSONDecodeError as e:
                    logger.error(f"Error parsing message from Redis for room {room_id}: {e}")
                except Exception as e:
                    logger.error(f"Error processing Redis message for room {room_id}: {e}", exc_info=True)
                    
    except asyncio.CancelledError:
        # Task was cancelled, clean up
        logger.info(f"Redis listener task cancelled for room: {room_id}")
    except Exception as e:
        logger.error(f"Error in Redis listener for room {room_id}: {e}", exc_info=True)
    finally:
        if pubsub:
            try:
                pubsub.close()
                logger.debug(f"Closed pub/sub connection for room: {room_id}")
            except Exception as e:
                logger.error(f"Error closing pub/sub for room {room_id}: {e}")
        # Clean up task reference
        if room_id in room_pubsub_tasks:
            del room_pubsub_tasks[room_id]
            logger.debug(f"Removed pub/sub task reference for room: {room_id}")


@app.websocket("/rooms/{room_id}/ws")
async def websocket_endpoint(room_id: str, websocket: WebSocket, display_name: str = None, password: str = None):
    """WebSocket endpoint with Redis pub/sub for distributed messaging.
    
    Query parameters:
    - display_name: Optional display name for the user
    - password: Required if room is password protected
    """
    connection_id = None
    logger.info(f"WebSocket connection attempt for room: {room_id}, display_name: {display_name}")
    
    try:
        # Verify room exists
        room = redis_backend.get_room(room_id)
        if not room:
            logger.info(f"WebSocket connection rejected: Room {room_id} not found")
            await websocket.close(code=1008, reason="Room not found")
            return
        
        # Check if room is expired
        expires_at = room.get("expires_at")
        if expires_at and expires_at < datetime.now().isoformat():
            logger.info(f"WebSocket connection rejected: Room {room_id} expired")
            await websocket.close(code=1008, reason="Room expired")
            redis_backend.delete_room(room_id)
            return
        
        # Validate password if room is password protected
        room_password = room.get("password")
        # Check if password exists and is not None/empty/"None"
        if room_password and room_password != "None" and room_password != "":
            if not password or room_password != password:
                logger.warning(f"WebSocket connection rejected: Invalid password for room {room_id}")
                await websocket.close(code=1008, reason="Invalid password")
                return
        
        # Check max users
        max_users = room.get("max_users", 20)
        current_users = redis_backend.get_users_in_room(room_id)
        current_count = len(current_users)
        if current_count >= max_users:
            logger.info(f"WebSocket connection rejected: Room {room_id} is full ({current_count}/{max_users})")
            await websocket.close(code=1008, reason="Room is full")
            return
        
        # Generate unique connection ID first (needed for default display name)
        connection_id = str(uuid.uuid4())
        
        # Determine display name
        final_display_name = display_name.strip() if display_name and display_name.strip() else f"User_{connection_id[:8]}"
        
        # Check if display_name is unique in the room (case-insensitive)
        existing_names = redis_backend.get_display_names_in_room(room_id)
        if final_display_name.lower() in existing_names:
            logger.warning(f"WebSocket connection rejected: Display name '{final_display_name}' already taken in room {room_id}")
            await websocket.close(code=1008, reason=f"Display name '{final_display_name}' is already taken. Please choose a different name.")
            return
        
        # Accept connection
        await websocket.accept()
        logger.info(f"WebSocket connection accepted for room: {room_id}")
        
        # Add connection to room tracking
        if room_id not in room_connections:
            room_connections[room_id] = {}
        room_connections[room_id][connection_id] = websocket
        logger.debug(f"Added connection {connection_id} to room {room_id} (local connections: {len(room_connections[room_id])})")
        
        # Start Redis pub/sub listener for this room if not already running (MUST be before adding user to Redis)
        if room_id not in room_pubsub_tasks or room_pubsub_tasks[room_id].done():
            room_pubsub_tasks[room_id] = asyncio.create_task(listen_to_redis_channel(room_id))
            logger.debug(f"Started Redis pub/sub listener for room: {room_id}")
            # Give the listener a moment to subscribe to Redis channel
            await asyncio.sleep(0.1)
        
        # Add to Redis set with user metadata (AFTER listener is ready)
        user_data = {
            "connected_at": datetime.now().isoformat(),
            "room_id": room_id,
            "display_name": final_display_name
        }
        redis_backend.add_user_to_room(room_id, connection_id, user_data)
        logger.info(f"User {connection_id} ({user_data['display_name']}) joined room {room_id}")
        
        # Get current online users list (including the new user)
        current_users = redis_backend.get_users_in_room(room_id)
        online_count = len(current_users)
        
        # Get list of all online users with their details
        online_users_list = []
        for conn_id in current_users:
            try:
                conn_key = redis_backend.redis_client.hgetall(f"conn:{conn_id}")
                if conn_key and "display_name" in conn_key:
                    online_users_list.append({
                        "connection_id": conn_id,
                        "display_name": conn_key["display_name"],
                        "connected_at": conn_key.get("connected_at", "")
                    })
            except Exception as e:
                logger.debug(f"Could not get user details for {conn_id}: {e}")
        
        try:
            # Send welcome message with initial online users list
            welcome_msg = {
                "type": "system",
                "message": "Connected to room",
                "room_id": room_id,
                "connection_id": connection_id,
                "timestamp": datetime.now().isoformat(),
                "online_users": online_users_list,
                "online_count": online_count
            }
            await websocket.send_text(json.dumps(welcome_msg))
            logger.debug(f"Sent welcome message to connection {connection_id} with {online_count} online users")
            
            # Broadcast user online presence to all instances (including this one)
            presence_message = {
                "type": "presence",
                "event": "user_online",
                "connection_id": connection_id,
                "display_name": user_data["display_name"],
                "room_id": room_id,
                "timestamp": datetime.now().isoformat(),
                "online_count": online_count
            }
            redis_backend.publish_message(room_id, presence_message)
            logger.debug(f"Broadcasted user online presence for {connection_id} with count {online_count}")
            
            # Listen for messages from WebSocket
            message_count = 0
            while True:
                try:
                    data = await websocket.receive_text()
                    message_count += 1
                    logger.debug(f"Received message #{message_count} from connection {connection_id} in room {room_id}")
                    
                    # Parse incoming message
                    try:
                        message = json.loads(data)
                    except json.JSONDecodeError:
                        # If not JSON, treat as plain text message
                        message = {
                            "type": "message",
                            "text": data,
                            "connection_id": connection_id,
                            "timestamp": datetime.now().isoformat()
                        }
                        logger.debug(f"Converted plain text to message format for connection {connection_id}")
                    
                    # Add connection_id if not present
                    if "connection_id" not in message:
                        message["connection_id"] = connection_id
                    if "timestamp" not in message:
                        message["timestamp"] = datetime.now().isoformat()
                    if "room_id" not in message:
                        message["room_id"] = room_id
                    
                    # Add user metadata if available
                    try:
                        conn_data = redis_backend.redis_client.hgetall(f"conn:{connection_id}")
                        if conn_data and "display_name" in conn_data:
                            message["display_name"] = conn_data["display_name"]
                    except Exception as e:
                        logger.debug(f"Could not retrieve user metadata for connection {connection_id}: {e}")
                    
                    # Publish to Redis pub/sub (this will distribute to all instances)
                    redis_backend.publish_message(room_id, message)
                    logger.debug(f"Published message to Redis pub/sub for room {room_id}")
                    
                except WebSocketDisconnect:
                    logger.info(f"WebSocket disconnected normally for connection {connection_id} in room {room_id}")
                    break
                except Exception as e:
                    logger.error(f"Error receiving message from connection {connection_id} in room {room_id}: {e}", exc_info=True)
                    break
                    
        except Exception as e:
            logger.error(f"WebSocket error for connection {connection_id} in room {room_id}: {e}", exc_info=True)
        finally:
            # Cleanup on disconnect
            if connection_id:
                if room_id in room_connections and connection_id in room_connections[room_id]:
                    del room_connections[room_id][connection_id]
                    logger.debug(f"Removed connection {connection_id} from local tracking for room {room_id}")
                
                # Remove from Redis
                redis_backend.remove_user_from_room(room_id, connection_id)
                logger.info(f"User {connection_id} left room {room_id}")
                
                # Broadcast user offline presence to all instances
                try:
                    # Get user display_name before removing
                    conn_data = redis_backend.redis_client.hgetall(f"conn:{connection_id}")
                    display_name = conn_data.get("display_name", f"User_{connection_id[:8]}") if conn_data else f"User_{connection_id[:8]}"
                    
                    presence_message = {
                        "type": "presence",
                        "event": "user_offline",
                        "connection_id": connection_id,
                        "display_name": display_name,
                        "room_id": room_id,
                        "timestamp": datetime.now().isoformat(),
                        "online_count": len(redis_backend.get_users_in_room(room_id))
                    }
                    logger.debug(f"Publishing user offline presence for {connection_id} to Redis pub/sub")
                    
                    redis_backend.publish_message(room_id, presence_message)
                    # Check if room owner went offline and should destroy room
                    room = redis_backend.get_room(room_id)
                    if room and display_name == room.get("owner_name"):
                        preferences = room.get("preferences", {})
                        if isinstance(preferences, dict) and preferences.get("destroy_on_owner_offline", False):
                            logger.info(f"Room owner {display_name} went offline shutting down room {room_id}")
                            redis_backend.publish_message(room_id, {
                                "type": "system",
                                "message": "Room owner went offline shutting down room",
                                "room_id": room_id,
                                "timestamp": datetime.now().isoformat()
                            })
                            redis_backend.delete_room(room_id)
                    logger.debug(f"Broadcasted user offline presence for {connection_id}")
                except Exception as e:
                    logger.debug(f"Could not broadcast offline presence: {e}")
                
                # If no more connections in this room, clean up
                if room_id in room_connections and len(room_connections[room_id]) == 0:
                    del room_connections[room_id]
                    logger.info(f"No more local connections in room {room_id}, cleaning up")
                    # Cancel pub/sub task if running
                    if room_id in room_pubsub_tasks:
                        room_pubsub_tasks[room_id].cancel()
                        try:
                            await room_pubsub_tasks[room_id]
                        except asyncio.CancelledError:
                            pass
                        del room_pubsub_tasks[room_id]
                        logger.debug(f"Cancelled pub/sub task for room {room_id}")
            
            try:
                await websocket.close()
            except Exception as e:
                logger.debug(f"Error closing WebSocket: {e}")
    except Exception as e:
        logger.error(f"Error during WebSocket connection setup for room {room_id}: {e}", exc_info=True)
        try:
            await websocket.close()
        except:
            pass