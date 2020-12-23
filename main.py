import aioredis
import asyncio
import json
import websockets
import utils

IS_PLAYING = False
CURRENT_WORD = None
CONNECTIONS = {}
HTTP_RESPONSE = utils.prepare_http_response("index.html")


async def process_request(path, request_headers):
    utils.redis_publish(redis, None, "http-request")

    if path == "/":
        return HTTP_RESPONSE


def can_start():
    global IS_PLAYING

    return not IS_PLAYING and len(CONNECTIONS) > 1 and all(CONNECTIONS.values())


async def start_game():
    global IS_PLAYING
    global CURRENT_WORD

    IS_PLAYING = True
    CURRENT_WORD, shuffled = utils.pick_word()
    print(f"[WORD SELECTED] {CURRENT_WORD}")

    await asyncio.wait([
        ws.send(json.dumps({"type": "letters", "value": shuffled}))
        for ws in CONNECTIONS
    ])

    utils.redis_publish(redis, None, "start-game")


async def end_game(winner):
    global IS_PLAYING
    global CURRENT_WORD

    IS_PLAYING = False
    
    for x in list(CONNECTIONS):
        CONNECTIONS[x] = False
    
    await asyncio.wait([
        ws.send(json.dumps({"type": "game-over", "won": ws == winner, "word": CURRENT_WORD}))
        for ws in CONNECTIONS
    ])

    utils.redis_publish(redis, None, "end-game")


async def handle_message(websocket, data):
    global IS_PLAYING
    global CURRENT_WORD

    data = json.loads(data)
    sender = websocket.remote_address
    print(f"[FROM {sender}] {data}")

    utils.redis_publish(redis, f"{sender[0]}:{sender[1]}", data["type"])

    if data["type"] == "toggle-ready" and not IS_PLAYING:
        CONNECTIONS[websocket] = not CONNECTIONS[websocket]
        await websocket.send(json.dumps({"type": "ready-state", "value": CONNECTIONS[websocket]}))
        
        if can_start():
            await start_game()
    elif data["type"] == "guess" and IS_PLAYING and data["value"] == CURRENT_WORD:
        await end_game(websocket)


async def handle_disconnect(websocket):
    global IS_PLAYING

    sender = websocket.remote_address

    utils.redis_publish(redis, f"{sender[0]}:{sender[1]}", "drop-connection")
    del CONNECTIONS[websocket]
    print(f"[DISCONNECTED] {sender}")

    if can_start():
        await start_game()
    elif len(CONNECTIONS) < 2 and IS_PLAYING:
        winner = next(iter(CONNECTIONS))
        await end_game(winner)


async def message_handler(websocket, path):
    global IS_PLAYING

    sender = websocket.remote_address
    utils.redis_publish(redis, f"{sender[0]}:{sender[1]}", "establish-connection")

    if path != "/connect" or IS_PLAYING:
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
