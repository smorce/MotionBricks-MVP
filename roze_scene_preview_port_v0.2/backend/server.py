"""FastAPI WebSocket bridge. Run under the cloned NVlabs/motionbricks uv project."""
from __future__ import annotations
import asyncio
import json
import logging
import os
import itertools
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from queue import Queue
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from jev_router import load_catalog, choose_pose

logger = logging.getLogger('roze')
commands = Queue()
clients: set[WebSocket] = set()
latest: dict[str, dict] = {}
catalog = load_catalog()
request_numbers: dict[WebSocket, int] = {}
move_id_source = itertools.count(1)

async def broadcast(data: dict):
    latest[data['type']] = data
    if not clients: return
    message = json.dumps(data, ensure_ascii=False)
    for ws in tuple(clients):
        try:
            await ws.send_text(message)
        except Exception:
            clients.discard(ws)

@asynccontextmanager
async def lifespan(app: FastAPI):
    from engine import worker
    loop = asyncio.get_running_loop()
    def publish(message):
        def schedule():
            asyncio.create_task(broadcast(message))
        loop.call_soon_threadsafe(schedule)
    def run():
        try:
            worker(commands, publish)
        except BaseException as exc:
            logger.exception('MotionBricks failed')
            publish({'type':'error','message':str(exc)})
    thread = threading.Thread(target=run, name='motionbricks-gpu', daemon=True)
    thread.start()
    try: yield
    finally:
        commands.put({'type':'quit'})
        thread.join(timeout=3)

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173','http://127.0.0.1:5173'],allow_methods=['GET'],allow_headers=['*'])

@app.get('/health')
def health():
    return {'ok': True, 'catalog_count':len(catalog), 'engine_ready': 'rig' in latest, 'engine_error': latest.get('error')}

@app.get('/catalog')
def get_catalog():
    return catalog

async def route_and_submit(ws: WebSocket, msg: dict, move_id: int):
    x = float(msg.get('x', 0))
    y = float(msg.get('y', 0))
    zone = str(msg.get('zone','floor'))
    if zone not in ('floor','chair','reaction'): zone='floor'
    intent = str(msg.get('intent','move and stand'))[:200]
    poses = latest.get('frame',{}).get('poses', [])
    distance = ((x-poses[0][0])**2 + (y-poses[0][1])**2)**0.5 if poses else 2.0
    try:
        decision = await asyncio.to_thread(choose_pose, zone, intent, distance, catalog)
        if request_numbers.get(ws) != move_id:
            return
        commands.put({'type':'pose_choice','pose_id':decision.pose_id,'move_id':move_id})
        await ws.send_json({'type':'decision','pose_id':decision.pose_id,'name':decision.pose_name,
                            'confidence':decision.confidence,'backend':decision.backend})
    except Exception as exc:
        logger.exception('Routing error')
        await ws.send_json({'type':'error','message':str(exc)})

@app.websocket('/ws')
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    request_numbers[ws] = 0
    for key in ('rig','frame','motion_state','error'):
        if key in latest:
            await ws.send_json(latest[key])
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get('type') == 'move':
                # Move immediately; obsolete Jev decisions are discarded on repeated clicks.
                move_id = next(move_id_source)
                request_numbers[ws] = move_id
                commands.put({'type':'move','x':float(msg['x']),'y':float(msg['y']), 'move_id':move_id})
                asyncio.create_task(route_and_submit(ws, msg, move_id))
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)
        request_numbers.pop(ws, None)
