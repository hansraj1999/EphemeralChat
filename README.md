# EphemeralChat

A distributed, ephemeral chat application built with FastAPI, WebSockets, and Redis. Designed for horizontal scaling with automatic room expiration and real-time message distribution across multiple server instances.

## Features

- 🚀 **Horizontal Scaling**: Multiple FastAPI instances can run behind a load balancer
- 📡 **Distributed Messaging**: Redis pub/sub ensures messages reach all users across all instances
- ⏱️ **Ephemeral Rooms**: Rooms automatically expire after a configurable time period
- 🔒 **Password Protection**: Optional password protection for rooms
- 👥 **User Limits**: Configurable maximum users per room
- 📊 **Room Details API**: Get room information including online user count and list
- 👤 **Real-Time Presence**: Automatic online/offline status updates via WebSocket
- 🔌 **WebSocket Support**: Real-time bidirectional communication
- 🧹 **Auto Cleanup**: Automatic cleanup of expired rooms and disconnected users
- 👑 **Owner-Based Room Management**: Rooms can be automatically destroyed when the owner disconnects

## Architecture

### System Architecture

```
┌─────────────┐         ┌─────────────┐         ┌─────────────┐
│   Client A  │         │   Client B  │         │   Client C  │
└──────┬──────┘         └──────┬──────┘         └──────┬──────┘
       │                       │                       │
       │  WebSocket            │  WebSocket            │  WebSocket
       │                       │                       │
┌──────▼───────────────────────▼───────────────────────▼──────┐
│                    Load Balancer                              │
└──────┬───────────────────────┬───────────────────────┬──────┘
       │                       │                       │
┌──────▼──────┐         ┌──────▼──────┐         ┌──────▼──────┐
│  Instance 1 │         │  Instance 2 │         │  Instance 3 │
│  FastAPI    │         │  FastAPI    │         │  FastAPI    │
│             │         │             │         │             │
│ In-Memory:  │         │ In-Memory:  │         │ In-Memory:  │
│ Connections │         │ Connections │         │ Connections │
└──────┬──────┘         └──────┬──────┘         └──────┬──────┘
       │                       │                       │
       │  Redis Pub/Sub        │  Redis Pub/Sub        │  Redis Pub/Sub
       │                       │                       │
       └───────────────────────┴───────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   Redis Server      │
                    │                     │
                    │ - Room Metadata    │
                    │ - User Tracking    │
                    │ - Pub/Sub Channels │
                    └─────────────────────┘
```

### Component Architecture

#### 1. **FastAPI Application Layer**
- **REST API**: Room management endpoints (create, join, leave, close)
- **WebSocket Handler**: Real-time message handling per room
- **In-Memory State**: Tracks local WebSocket connections per instance

#### 2. **Redis Backend Layer**
- **Room Metadata**: Stored in Redis hashes with TTL
- **User Tracking**: Redis sets track all connections across instances
- **Pub/Sub Channels**: One channel per room for message distribution
- **Connection Metadata**: Hash storage for user information

#### 3. **Message Flow**

```
User A (Instance 1) sends message
    ↓
Publish to Redis: room:channel:{room_id}
    ↓
Redis broadcasts to all subscribed instances
    ↓
Instance 1 receives → broadcasts to local connections
Instance 2 receives → broadcasts to local connections
Instance 3 receives → broadcasts to local connections
    ↓
All users in room receive the message
```

### Data Structures

#### In-Memory (Per Instance)
```python
room_connections: Dict[str, Dict[str, WebSocket]]
# Format: {room_id: {connection_id: websocket}}

room_pubsub_tasks: Dict[str, asyncio.Task]
# Format: {room_id: background_task}
```

#### Redis Keys
- `room:meta:{room_id}` - Hash: Room metadata (expiry, max_users, password, etc.)
- `room:users:{room_id}` - Set: All connection IDs in room (across all instances)
- `room:channel:{room_id}` - String: Pub/sub channel name
- `conn:{connection_id}` - Hash: Connection metadata (display_name, connected_at, etc.)

## Installation

### Prerequisites

- Python 3.8+ (for local development)
- Redis 6.0+ (for local development)
- Docker and Docker Compose (for containerized deployment)
- pip (for local development)

## Installation

### Option 1: Docker Deployment (Recommended)

1. **Clone the repository**
```bash
git clone <repository-url>
cd EphemeralChat
```

2. **Configure environment variables (optional)**

Create a `.env` file (or use defaults):
```env
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=
DOMAIN=localhost
LOG_LEVEL=INFO
LOG_FILE=/app/logs/app.log
HOST=0.0.0.0
PORT=8000
```

3. **Build and start with Docker Compose**
```bash
docker-compose up -d
```

This will:
- Build the application Docker image
- Start Redis container
- Start the application container
- Set up networking between services

4. **View logs**
```bash
# All services
docker-compose logs -f

# Application only
docker-compose logs -f app

# Redis only
docker-compose logs -f redis
```

5. **Stop services**
```bash
docker-compose down
```

6. **Stop and remove volumes**
```bash
docker-compose down -v
```

**Access the application:**
- API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Redis: localhost:6379

### Option 2: Local Development

1. **Clone the repository**
```bash
git clone <repository-url>
cd EphemeralChat
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

Or manually:
```bash
pip install fastapi uvicorn[standard] redis python-dotenv pydantic pydantic[email] pillow
```

3. **Configure environment variables**

Create a `.env` file:
```env
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
DOMAIN=localhost
LOG_LEVEL=INFO
LOG_FILE=logs/app.log
HOST=0.0.0.0
PORT=8000
```

4. **Start Redis**
```bash
# Using Docker
docker run -d -p 6379:6379 redis:latest

# Or using local Redis
redis-server
```

5. **Run the application**
```bash
python entrypoint.py
```

Or directly with uvicorn:
```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

## API Documentation

### REST Endpoints

#### 1. Create Room
```http
POST /rooms/
Content-Type: application/json

{
  "password": "optional-password",
  "expiry_seconds": 600,
  "max_users": 20,
  "name": "My Chat Room",
  "owner_name": "John Doe"
}
```

**Note:** The `owner_name` field is required. When the room owner disconnects, the room will be automatically destroyed by default (controlled by `preferences.destroy_on_owner_offline`).

**Response:**
```json
{
  "room_id": "abc123def456",
  "ws_url": "ws://localhost:8000/rooms/abc123def456/ws",
  "expires_at": "2025-01-17T12:34:56.789Z"
}
```

#### 2. Join Room
```http
POST /rooms/{room_id}/join
Content-Type: application/json

{
  "password": "optional-password",
  "display_name": "Jane Doe"
}
```

**Response:**
```json
{
  "ws_url": "ws://localhost:8000/rooms/abc123def456/ws",
  "expires_at": "2025-01-17T12:34:56.789Z"
}
```

#### 3. Get Room Details
```http
GET /rooms/{room_id}?password=optional-password
```

**Query Parameters:**
- `password` (optional): Required if the room is password protected

**Response:**
```json
{
  "room_id": "abc123def456",
  "name": "My Chat Room",
  "created_at": "2025-01-17T12:00:00.000Z",
  "expires_at": "2025-01-17T12:10:00.000Z",
  "max_users": 20,
  "online_users_count": 5,
  "online_users": [
    {
      "connection_id": "uuid-1234",
      "display_name": "John",
      "connected_at": "2025-01-17T12:05:00.000Z"
    },
    {
      "connection_id": "uuid-5678",
      "display_name": "Jane",
      "connected_at": "2025-01-17T12:06:00.000Z"
    }
  ],
  "owner_name": "John Doe",
  "has_password": true,
  "is_expired": false,
  "is_full": false
}
```

**Error Responses:**
- `404`: Room not found
- `401`: Password required or invalid password

**Examples:**
```bash
# Room without password
GET /rooms/abc123def456

# Room with password
GET /rooms/abc123def456?password=mypassword

# Invalid password
GET /rooms/abc123def456?password=wrong
# Returns: 401 Unauthorized
```

#### 4. Leave Room
```http
POST /rooms/{room_id}/leave
Content-Type: application/json

{
  "display_name": "Jane Doe"
}
```

**Response:**
```json
{
  "message": "Leave request acknowledged. Disconnect WebSocket to complete leave."
}
```

#### 5. Close Room (Owner Only)
```http
POST /rooms/{room_id}/close
Content-Type: application/json

{
  "display_name": "John Doe"
}
```

**Response:**
```json
{
  "message": "Room closed successfully"
}
```

### WebSocket Endpoint

#### Connect to Room
```javascript
const ws = new WebSocket('ws://localhost:8000/rooms/{room_id}/ws?display_name=John');
```

#### Send Message
```javascript
// JSON format
ws.send(JSON.stringify({
  "type": "message",
  "text": "Hello, world!",
  "timestamp": "2025-01-17T12:34:56.789Z"
}));

// Or plain text (auto-converted to message type)
ws.send("Hello, world!");
```

#### Receive Messages
```javascript
ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  
  switch(message.type) {
    case 'message':
      console.log(`${message.display_name}: ${message.text}`);
      break;
    case 'presence':
      if (message.event === 'user_online') {
        console.log(`${message.display_name} came online`);
      } else if (message.event === "user_offline") {
        console.log(`${message.display_name} went offline`);
      }
      console.log(`Online users: ${message.online_count}`);
      break;
    case 'system':
      console.log(`System: ${message.message}`);
      break;
  }
};
```

### Message Types

#### System Messages
```json
{
  "type": "system",
  "message": "Connected to room",
  "room_id": "abc123",
  "connection_id": "uuid",
  "timestamp": "2025-01-17T12:34:56.789Z"
}
```

#### User Messages
```json
{
  "type": "message",
  "text": "Hello, world!",
  "connection_id": "uuid",
  "display_name": "John",
  "room_id": "abc123",
  "timestamp": "2025-01-17T12:34:56.789Z"
}
```

#### Presence Messages (Online/Offline Status)
```json
{
  "type": "presence",
  "event": "user_online",
  "connection_id": "uuid",
  "display_name": "John",
  "room_id": "abc123",
  "timestamp": "2025-01-17T12:34:56.789Z",
  "online_count": 5
}
```

**Presence Events:**
- `user_online`: Broadcast when a user connects to the room
- `user_offline`: Broadcast when a user disconnects from the room

**Note:** Presence messages are automatically sent to all connected clients in real-time. No polling required!

#### Room Closure
```json
{
  "type": "system",
  "message": "Room has been closed by owner",
  "room_id": "abc123",
  "timestamp": "2025-01-17T12:34:56.789Z"
}
```

**Room Owner Offline Auto-Destruction:**
When a room owner disconnects, if the room preference `destroy_on_owner_offline` is enabled (default: `true`), the room is automatically destroyed. All connected users receive a system message before the room is deleted:

```json
{
  "type": "system",
  "message": "Room owner went offline shutting down room",
  "room_id": "abc123",
  "timestamp": "2025-01-17T12:34:56.789Z"
}
```

## Usage Examples

### Python Client Example

```python
import asyncio
import websockets
import json
import requests

async def chat_client():
    # First, create a room via REST API
    response = requests.post('http://localhost:8000/rooms/', json={
        "name": "My Room",
        "expiry_seconds": 3600,
        "max_users": 10,
        "password": "secret123"
    })
    room_data = response.json()
    room_id = room_data['room_id']
    ws_url = room_data['ws_url'].replace('http://', 'ws://')
    
    # Get room details (with password for protected rooms)
    details_response = requests.get(
        f'http://localhost:8000/rooms/{room_id}',
        params={'password': 'secret123'}
    )
    room_details = details_response.json()
    print(f"Room: {room_details['name']}")
    print(f"Online users: {room_details['online_users_count']}/{room_details['max_users']}")
    print(f"Is full: {room_details['is_full']}")
    
    # Connect via WebSocket
    async with websockets.connect(ws_url) as websocket:
        # Send a message
        message = {
            "type": "message",
            "text": "Hello from Python!"
        }
        await websocket.send(json.dumps(message))
        
        # Receive messages
        async for message in websocket:
            data = json.loads(message)
            if data.get('type') == 'presence':
                if data.get('event') == 'user_online':
                    print(f"{data['display_name']} came online")
                elif data.get('event') == 'user_offline':
                    print(f"{data['display_name']} went offline")
                print(f"Online users: {data['online_count']}")
            else:
                print(f"Received: {data}")

asyncio.run(chat_client())
```

### JavaScript Client Example

```javascript
// Create room
fetch('http://localhost:8000/rooms/', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    name: 'My Room',
    expiry_seconds: 3600,
    max_users: 10,
    password: 'secret123'
  })
})
.then(res => res.json())
.then(data => {
  const roomId = data.room_id;
  
  // Get room details
  const detailsUrl = new URL(`http://localhost:8000/rooms/${roomId}`);
  detailsUrl.searchParams.append('password', 'secret123');
  
  fetch(detailsUrl)
    .then(res => res.json())
    .then(details => {
      console.log('Room:', details.name);
      console.log(`Online users: ${details.online_users_count}/${details.max_users}`);
      console.log('Is full:', details.is_full);
    });
  
  // Connect via WebSocket
  const ws = new WebSocket(data.ws_url);
  
  ws.onopen = () => {
    console.log('Connected to room:', roomId);
    ws.send(JSON.stringify({
      type: 'message',
      text: 'Hello from JavaScript!'
    }));
  };
  
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    console.log('Received:', message);
  };
  
  ws.onerror = (error) => {
    console.error('WebSocket error:', error);
  };
  
  ws.onclose = () => {
    console.log('Disconnected');
  };
});
```

## Scaling

### Horizontal Scaling Setup

#### Using Docker Compose

1. **Scale application instances**
```bash
# Scale to 3 instances
docker-compose up -d --scale app=3

# Each instance will be accessible on different ports
# Instance 1: localhost:8000
# Instance 2: localhost:8001
# Instance 3: localhost:8002
```

2. **Update docker-compose.yml for custom ports**
```yaml
services:
  app:
    ports:
      - "8000-8002:8000"
```

#### Using Local Deployment

1. **Run multiple instances**
```bash
# Instance 1
uvicorn app:app --host 0.0.0.0 --port 8000

# Instance 2
uvicorn app:app --host 0.0.0.0 --port 8001

# Instance 3
uvicorn app:app --host 0.0.0.0 --port 8002
```

2. **Configure load balancer** (nginx example)
```nginx
upstream backend {
    least_conn;
    server localhost:8000;
    server localhost:8001;
    server localhost:8002;
}

server {
    listen 80;
    
    location / {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

3. **Shared Redis instance**
All instances must connect to the same Redis server for pub/sub to work correctly.

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS_HOST` | Redis server hostname | `localhost` |
| `REDIS_PORT` | Redis server port | `6379` |
| `REDIS_PASSWORD` | Redis password (optional) | `None` |
| `DOMAIN` | Domain for WebSocket URLs | `localhost` |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) | `INFO` |
| `LOG_FILE` | Path to log file (optional, enables file logging) | `None` |
| `HOST` | Server host address | `0.0.0.0` |
| `PORT` | Server port | `8000` |

### Room Configuration

- **Default Expiry**: 600 seconds (10 minutes)
- **Default Max Users**: 20
- **Password**: Optional, plain text (consider hashing for production)
- **Owner Name**: Required when creating a room
- **Auto-Destroy on Owner Offline**: Enabled by default (`preferences.destroy_on_owner_offline: true`)
  - When the room owner disconnects, the room is automatically deleted
  - All connected users receive a system notification before room deletion

## Project Structure

```
EphemeralChat/
├── app.py                 # FastAPI application and WebSocket handlers
├── backend.py             # Redis backend operations
├── constants.py           # Environment configuration
├── redis_keys.py          # Redis key naming conventions
├── requirements.txt       # Python dependencies
├── logging_config.py      # Logging configuration
├── entrypoint.py          # Application entry point
├── Dockerfile             # Docker image definition
├── docker-compose.yml     # Docker Compose configuration
├── .dockerignore          # Docker ignore patterns
├── routers/
│   └── rooms.py          # Room management REST endpoints
├── schemas/
│   └── rooms.py          # Pydantic models for requests/responses
└── worker/
    └── worker.py         # Background worker (if needed)
```

## Key Design Decisions

### 1. In-Memory Connection Tracking
- **Why**: WebSocket objects are process-local and cannot be shared across instances
- **Trade-off**: Each instance only knows its own connections, but Redis pub/sub ensures message distribution

### 2. Redis Pub/Sub for Distribution
- **Why**: Enables horizontal scaling without complex message routing
- **Benefit**: Messages automatically reach all instances, each broadcasts to local connections

### 3. Connection IDs
- **Why**: Unique identifier per WebSocket connection for tracking and cleanup
- **Implementation**: UUID generated on connection

### 4. TTL on Redis Keys
- **Why**: Automatic cleanup of expired rooms and stale connections
- **Benefit**: No manual cleanup required, reduces memory usage

### 5. Owner-Based Room Management
- **Why**: Provides room creators control over their rooms
- **Implementation**: Room owner is tracked by `display_name` matching `owner_name`
- **Behavior**: When owner disconnects, room is automatically destroyed (if preference enabled)
- **Benefit**: Prevents abandoned rooms and ensures rooms are managed by their creators

## Error Handling

### WebSocket Errors
- **Room not found**: Connection closed with code 1008
- **Room expired**: Connection closed, room deleted
- **Room full**: Connection closed when max_users reached
- **Invalid password**: HTTP 401 on join endpoint

### Connection Cleanup
- Automatic cleanup on disconnect
- Stale connections cleaned up when sending fails
- Redis TTL ensures eventual cleanup

## Performance Considerations

### Redis Pub/Sub
- Each room has one pub/sub channel
- Background tasks run per room (only when room has connections)
- Timeout-based polling (1 second) prevents blocking

### WebSocket Management
- Concurrent message sending using `asyncio.gather()`
- Connection tracking optimized for O(1) lookups
- Automatic cleanup of disconnected connections

### Memory Management
- TTL on all Redis keys prevents memory leaks
- In-memory state cleared when rooms empty
- Background tasks cancelled when not needed

## Security Considerations

### Current Implementation
- Password stored in plain text (consider hashing for production)
- IP-based owner verification (consider authentication tokens)
- No rate limiting (consider adding for production)

### Production Recommendations
1. **Password Hashing**: Use bcrypt or similar
2. **Authentication**: Implement JWT or session-based auth
3. **Rate Limiting**: Add rate limiting middleware
4. **HTTPS/WSS**: Use secure connections in production
5. **Input Validation**: Additional validation on WebSocket messages
6. **CORS**: Configure CORS appropriately

## Testing

### Manual Testing

#### Using Docker
```bash
# Start services
docker-compose up -d

# Test room creation
curl -X POST http://localhost:8000/rooms/ \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Room", "expiry_seconds": 600}'

# Test WebSocket (use wscat or similar)
wscat -c ws://localhost:8000/rooms/{room_id}/ws

# View logs
docker-compose logs -f app
```

#### Using Local Development
```bash
# Start server
python entrypoint.py
# or
uvicorn app:app --reload

# Test room creation
curl -X POST http://localhost:8000/rooms/ \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Room", "expiry_seconds": 600}'

# Test WebSocket (use wscat or similar)
wscat -c ws://localhost:8000/rooms/{room_id}/ws
```

## Troubleshooting

### Common Issues

1. **Messages not reaching all users**
   - Check Redis connection
   - Verify all instances subscribe to same Redis server
   - Check pub/sub channel names match

2. **Rooms not expiring**
   - Verify Redis TTL is set correctly
   - Check Redis server is running
   - Verify system clock is synchronized

3. **Connection cleanup issues**
   - Check WebSocket disconnect handlers
   - Verify Redis connection cleanup
   - Monitor Redis memory usage

## Docker Commands Reference

### Basic Commands
```bash
# Build and start services
docker-compose up -d

# Start services (without building)
docker-compose start

# Stop services
docker-compose stop

# Stop and remove containers
docker-compose down

# Stop, remove containers and volumes
docker-compose down -v

# View logs
docker-compose logs -f

# View logs for specific service
docker-compose logs -f app
docker-compose logs -f redis

# Rebuild after code changes
docker-compose up -d --build

# Scale application instances
docker-compose up -d --scale app=3
```

### Development Commands
```bash
# Execute command in running container
docker-compose exec app python -c "print('Hello')"

# Access container shell
docker-compose exec app /bin/bash

# View Redis CLI
docker-compose exec redis redis-cli

# Monitor Redis
docker-compose exec redis redis-cli MONITOR
```

### Production Deployment
```bash
# Build production image
docker build -t ephemeralchat:latest .

# Run production container
docker run -d \
  --name ephemeralchat \
  -p 8000:8000 \
  --env-file .env \
  --restart unless-stopped \
  ephemeralchat:latest

# Run with custom network (if Redis is on different host)
docker run -d \
  --name ephemeralchat \
  -p 8000:8000 \
  -e REDIS_HOST=redis.example.com \
  -e REDIS_PORT=6379 \
  ephemeralchat:latest
```

## Future Enhancements

- [ ] User authentication and authorization
- [ ] Message persistence (optional)
- [ ] File/image sharing
- [ ] Typing indicators
- [ ] User presence status
- [ ] Room invite system
- [ ] Message history (with TTL)
- [ ] Rate limiting
- [ ] Metrics and monitoring

## License


## Contributing


## Support


