REDIS_META_KEY = "room:meta:{slug}" # room id
REDIS_USERS_KEY = "room:users:{slug}" # room id - set of connection IDs
REDIS_ROOM_CHANNEL = "room:channel:{slug}" # room slug - pub/sub channel name
REDIS_INVITE_KEY = "room:invite:{slug}" # room slug
REDIS_CONN_KEY = "conn:{connection_id}" # connection id - connection metadata

# **Example `room:meta:{id}` hash fields**
# - `id` = `{roomId}`
# - `created_at` = ISO timestamp
# - `expires_at` = ISO timestamp (or rely only on TTL)
# - `max_users` = integer
# - `password_hash` = bcrypt hash (optional)
# - `owner` = userId or null
# - `flags` = json string (e.g., allow_reconnect)