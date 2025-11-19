from fastapi import FastAPI, WebSocket
from routers.rooms import rooms_router

app = FastAPI()
app.include_router(rooms_router)

@app.websocket("/rooms/{room_id}/ws")
async def websocket_endpoint(room_id: str, websocket: WebSocket):

    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        print(data)
        
        await websocket.send_text(f"Hello, {data}!")
    await websocket.close()