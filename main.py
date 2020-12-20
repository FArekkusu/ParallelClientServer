import aioredis
import asyncio
import json
import websockets
import utils

CONNECTIONS = {}
HTTP_RESPONSE = utils.prepare_http_response("index.html")
GAME_STATE = "lobby"
CURRENT_WORD = None


async def process_request(path, request_headers):
    utils.redis_publish(redis, None, "http-request")

    if path == "/":
        return HTTP_RESPONSE


async def try_start():
    global GAME_STATE
    global CURRENT_WORD

    if len(CONNECTIONS) > 1 and all(CONNECTIONS.values()):
        GAME_STATE = "playing"
        CURRENT_WORD, shuffled = utils.pick_word()
        print(f"[WORD SELECTED] {CURRENT_WORD}")

        await asyncio.wait([
            ws.send(json.dumps({"type": "letters", "value": shuffled}))
            for ws in CONNECTIONS
        ])

        utils.redis_publish(redis, None, "start-game")


async def try_end(winner):
    global GAME_STATE
    global CURRENT_WORD

    GAME_STATE = "lobby"
    for x in list(CONNECTIONS):
        CONNECTIONS[x] = False
    
    await asyncio.wait([
        ws.send(json.dumps({"type": "game-over", "won": ws == winner, "word": CURRENT_WORD}))
        for ws in CONNECTIONS
    ])

    utils.redis_publish(redis, None, "end-game")


async def handle_message(websocket, data):
    global GAME_STATE
    global CURRENT_WORD

    data = json.loads(data)
    sender = websocket.remote_address
    print(f"[FROM {sender}] {data}")

    utils.redis_publish(redis, f"{sender[0]}:{sender[1]}", data["type"])

    if data["type"] == "toggle-ready":
        CONNECTIONS[websocket] = not CONNECTIONS[websocket]
        await websocket.send(json.dumps({"type": "ready-state", "value": CONNECTIONS[websocket]}))
        await try_start()
    elif data["type"] == "guess":
        if GAME_STATE == "playing" and data["value"] == CURRENT_WORD:
            await try_end(websocket)


async def handle_disconnect(websocket):
    global GAME_STATE

    sender = websocket.remote_address

    utils.redis_publish(redis, f"{sender[0]}:{sender[1]}", "drop-connection")
    del CONNECTIONS[websocket]
    print(f"[DISCONNECTED] {sender}")

    if len(CONNECTIONS) < 2:
        if len(CONNECTIONS) == 1 and GAME_STATE == "playing":
            await try_end(next(iter(CONNECTIONS)))
        GAME_STATE = "lobby"
    else:
        await try_start()


async def message_handler(websocket, path):
    global GAME_STATE

    sender = websocket.remote_address
    utils.redis_publish(redis, f"{sender[0]}:{sender[1]}", "establish-connection")

    if path != "/connect" or GAME_STATE == "playing":
        reason = "incorrect-url" if path != "/connect" else "game-in-progress"
        await websocket.send(json.dumps({"type": "connection-error", "reason": reason}))
        utils.redis_publish(redis, f"{sender[0]}:{sender[1]}", "deny-connection")
        return

    CONNECTIONS[websocket] = False
    print(f"[CONNECTED] {sender}")

    try:
        async for data in websocket:
            await handle_message(websocket, data)
    except websockets.exceptions.ConnectionClosedError:
        pass
    finally:
        await handle_disconnect(websocket)


if __name__ == "__main__":
    redis = asyncio.get_event_loop().run_until_complete(aioredis.create_redis(("127.0.0.1", 6379)))

    start_server = websockets.serve(message_handler, "0.0.0.0", 5000, process_request=process_request)
    asyncio.get_event_loop().run_until_complete(start_server)

    asyncio.get_event_loop().run_forever()