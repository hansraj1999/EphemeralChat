import redis
import json
from constants import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD
from redis_keys import REDIS_META_KEY, REDIS_USERS_KEY, REDIS_ROOM_CHANNEL, REDIS_INVITE_KEY, REDIS_CONN_KEY
from logging_config import get_logger

logger = get_logger(__name__)

try:
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
    # Test connection
    redis_client.ping()
    logger.info(f"Redis client connected successfully to {REDIS_HOST}:{REDIS_PORT}")
except Exception as e:
    logger.error(f"Failed to connect to Redis at {REDIS_HOST}:{REDIS_PORT}: {e}", exc_info=True)
    raise


class RedisBackend:
    def __init__(self):
        self.redis_client = redis_client
        logger.info(f"Initializing RedisBackend with connection to {REDIS_HOST}:{REDIS_PORT}")
        # Separate connection for pub/sub (required by Redis)
        try:
            self.pubsub_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
            self.pubsub_client.ping()
            logger.info("Redis pub/sub client connected successfully")
        except Exception as e:
            logger.error(f"Failed to connect Redis pub/sub client: {e}", exc_info=True)
            raise

    def create_room(self, room_id: str, room_data: dict, ttl: int = 600):
        logger.info(f"Creating room {room_id} with TTL {ttl} seconds")
        key = REDIS_META_KEY.format(slug=room_id)
        # Convert dict values to strings for Redis hash, skip None values
        room_data_str = {}
        for k, v in room_data.items():
            if v is None:
                continue  # Skip None values
            if isinstance(v, (dict, list)):
                room_data_str[k] = json.dumps(v)
            else:
                room_data_str[k] = str(v)
        self.redis_client.hset(key, mapping=room_data_str)
        if ttl:
            self.redis_client.expire(key, ttl)
        logger.debug(f"Room {room_id} created successfully with key: {key}")
        return room_id
    
    def get_room(self, room_id: str):
        logger.debug(f"Fetching room {room_id}")
        key = REDIS_META_KEY.format(slug=room_id)
        room_data = self.redis_client.hgetall(key)
        if not room_data:
            logger.debug(f"Room {room_id} not found in Redis")
            return None
        # Convert back from strings
        result = {}
        for k, v in room_data.items():
            try:
                result[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                result[k] = v
        logger.debug(f"Room {room_id} retrieved successfully")
        return result
    
    def delete_room(self, room_id: str):
        logger.info(f"Deleting room {room_id}")
        key = REDIS_META_KEY.format(slug=room_id)
        deleted = self.redis_client.delete(key)
        # Delete connected users set
        users_key = REDIS_USERS_KEY.format(slug=room_id)
        users_deleted = self.redis_client.delete(users_key)
        logger.debug(f"Room {room_id} deleted: meta_key={deleted}, users_key={users_deleted}")
        return True
    
    def add_user_to_room(self, room_id: str, connection_id: str, user_data: dict = None, ttl: int = 600):
        """Add a connection to a room. connection_id should be unique per WebSocket connection."""
        logger.debug(f"Adding user {connection_id} to room {room_id}")
        users_key = REDIS_USERS_KEY.format(slug=room_id)
        added = self.redis_client.sadd(users_key, connection_id)
        if ttl:
            self.redis_client.expire(users_key, ttl)
        
        # Store connection metadata
        if user_data:
            conn_key = REDIS_CONN_KEY.format(connection_id=connection_id)
            self.redis_client.hset(conn_key, mapping={k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in user_data.items()})
            if ttl:
                self.redis_client.expire(conn_key, ttl)
            logger.debug(f"Stored connection metadata for {connection_id} with TTL {ttl}")
        
        if added:
            logger.debug(f"User {connection_id} added to room {room_id} (new user)")
        else:
            logger.debug(f"User {connection_id} already exists in room {room_id}")
        return True
    
    def remove_user_from_room(self, room_id: str, connection_id: str):
        """Remove a connection from a room."""
        logger.debug(f"Removing user {connection_id} from room {room_id}")
        users_key = REDIS_USERS_KEY.format(slug=room_id)
        removed = self.redis_client.srem(users_key, connection_id)
        
        # Clean up connection metadata
        conn_key = REDIS_CONN_KEY.format(connection_id=connection_id)
        deleted = self.redis_client.delete(conn_key)
        logger.debug(f"User {connection_id} removed from room {room_id}: user_set={removed}, metadata={deleted}")
        return True
    
    def get_users_in_room(self, room_id: str):
        """Get all connection IDs in a room."""
        logger.debug(f"Getting users in room {room_id}")
        users_key = REDIS_USERS_KEY.format(slug=room_id)
        users = self.redis_client.smembers(users_key)
        logger.debug(f"Room {room_id} has {len(users)} users")
        return users
    
    def get_display_names_in_room(self, room_id: str):
        """Get all display names currently in use in a room."""
        logger.debug(f"Getting display names in room {room_id}")
        connection_ids = self.get_users_in_room(room_id)
        display_names = set()
        
        for conn_id in connection_ids:
            try:
                conn_key = REDIS_CONN_KEY.format(connection_id=conn_id)
                conn_data = self.redis_client.hgetall(conn_key)
                if conn_data and "display_name" in conn_data:
                    display_name = conn_data["display_name"]
                    if display_name:
                        display_names.add(display_name.lower())  # Case-insensitive comparison
            except Exception as e:
                logger.debug(f"Could not get display name for connection {conn_id}: {e}")
        
        logger.debug(f"Room {room_id} has display names: {display_names}")
        return display_names
    
    def get_room_channel_name(self, room_id: str) -> str:
        """Get the Redis pub/sub channel name for a room."""
        return REDIS_ROOM_CHANNEL.format(slug=room_id)
    
    def publish_message(self, room_id: str, message: dict):
        """Publish a message to the room's Redis pub/sub channel."""
        channel = self.get_room_channel_name(room_id)
        message_json = json.dumps(message)
        subscribers = self.redis_client.publish(channel, message_json)
        logger.debug(f"Published message to room {room_id} channel {channel}, {subscribers} subscribers")
        return True
    
    def subscribe_to_room(self, room_id: str):
        """Create a pubsub subscriber for a room channel."""
        channel = self.get_room_channel_name(room_id)
        logger.debug(f"Subscribing to Redis channel {channel} for room {room_id}")
        pubsub = self.pubsub_client.pubsub()
        pubsub.subscribe(channel)
        logger.debug(f"Successfully subscribed to channel {channel}")
        return pubsub
    
    def get_invite(self, room_id: str):
        return self.redis_client.get(REDIS_INVITE_KEY.format(slug=room_id))

    def purge_redis_keys_all(self):
        # Note: This won't work with wildcards in delete - would need SCAN
        # For now, this is a placeholder
        return True

    
redis_backend = RedisBackend()
