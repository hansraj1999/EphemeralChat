import redis
from constants import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD
from redis_keys import REDIS_META_KEY, REDIS_USERS_KEY, REDIS_ROOM_CHANNEL, REDIS_INVITE_KEY, REDIS_CONN_KEY

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD)


class RedisBackend:
    def __init__(self):
        self.redis_client = redis_client

    def create_room(self, room_id: str, room_data: dict, ttl: int = 600):
        self.redis_client.hset(REDIS_META_KEY.format(slug=room_id), mapping=room_data)
        return room_id
    
    def get_room(self, room_id: str):
        return self.redis_client.hget(REDIS_META_KEY.format(slug=room_id))
    
    def delete_room(self, room_id: str):
        self.redis_client.hdel(REDIS_META_KEY.format(slug=room_id))
        # del connected users
        self.redis_client.srem(REDIS_USERS_KEY.format(slug=room_id), "*")
        # del room channel
        self.redis_client.delete(REDIS_ROOM_CHANNEL.format(slug=room_id))
        return True
    
    def add_user_to_room(self, room_id: str, ip: str, name: str, ttl: int = 600):
        self.redis_client.sadd(REDIS_USERS_KEY.format(ip=ip, name=name), room_id)
        return True
    
    def remove_user_from_room(self, room_id: str, user_id: str):
        self.redis_client.srem(REDIS_USERS_KEY.format(slug=room_id), user_id)
        return True
    
    def get_users_in_room(self, room_id: str):
        return self.redis_client.smembers(REDIS_USERS_KEY.format(slug=room_id))
    
    def get_room_channel(self, room_id: str):
        return self.redis_client.get(REDIS_ROOM_CHANNEL.format(slug=room_id))
    
    def get_invite(self, room_id: str):
        return self.redis_client.get(REDIS_INVITE_KEY.format(slug=room_id))

    def purge_redis_keys_all(self):
        # purge all using regex redis keys from redis_keys.py
        for key in [REDIS_META_KEY, REDIS_USERS_KEY, REDIS_ROOM_CHANNEL, REDIS_INVITE_KEY, REDIS_CONN_KEY]:
            self.redis_client.delete(key.format(slug="*"))
        return True

    
redis_backend = RedisBackend()
