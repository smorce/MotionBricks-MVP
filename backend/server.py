"""FastAPI WebSocket bridge. Run under the cloned NVlabs/motionbricks uv project."""
from __future__ import annotations
import asyncio
import itertools
import json
import logging
import math
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from queue import Queue
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from cafe_usecases import resolve_usecase
from d3_router import load_catalog, choose_arrival_pose
from gait_log import GAIT_LOG

logger = logging.getLogger('roze')
commands = Queue()
clients: set[WebSocket] = set()
latest: dict[str, dict] = {}
catalog = load_catalog()
request_numbers: dict[WebSocket, int] = {}
move_ids = itertools.count(1)
VRM_PATH = Path(__file__).resolve().parents[1] / "ロゼ.vrm"


def pose_summary(poses) -> str:
    if not poses:
        return "unknown"
    root = poses[0]
    x, y, z = float(root[0]), float(root[1]), float(root[2])
    qx, qy, qz, qw = (float(v) for v in root[3:7])
    # 正規化後の姿勢は +X が正面。ルート回転後の前方を yaw にする。
    fx = 1 - 2 * (qy * qy + qz * qz)
    fy = 2 * (qx * qy + qz * qw)
    facing = math.degrees(math.atan2(fy, fx)) if math.isfinite(fx) and math.isfinite(fy) else 0.0
    return f"root=({x:.2f},{y:.2f}) facing={facing:.0f}deg height={z:.2f}"

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173', 'http://localhost:5188', 'http://127.0.0.1:5188'],
    allow_methods=['GET'],
    allow_headers=['*'],
)

@app.get('/health')
def health():
    metrics = latest.get('metrics', {})
    return {
        'ok': True,
        'catalog_count': len(catalog),
        'engine_ready': 'rig' in latest,
        'engine_error': latest.get('error'),
        'stream_hz': metrics.get('stream_hz'),
        'generate_ms': metrics.get('generate_ms'),
        'vrm': VRM_PATH.is_file(),
    }

@app.get('/roze.vrm')
def roze_vrm():
    if not VRM_PATH.is_file():
        raise HTTPException(status_code=404, detail="Roze VRM file was not found")
    return FileResponse(VRM_PATH, media_type='model/gltf-binary', filename='roze.vrm')

@app.get('/catalog')
def get_catalog():
    return catalog

@app.get('/gait-log')
def gait_log_json():
    from fastapi.responses import Response
    return Response(GAIT_LOG.to_json(), media_type='application/json')

@app.get('/gait-log.csv')
def gait_log_csv():
    from fastapi.responses import Response
    return Response(GAIT_LOG.to_csv(), media_type='text/csv')

async def route_and_submit(ws: WebSocket, msg: dict, request_number: int):
    # 通常の床クリックは到着ポーズを生成しない。特定動作だけ d3-mini に渡す。
    if msg.get('hold_stance') is True:
        await ws.send_json({
            'type': 'decision', 'pose_id': '', 'name': '立ち待機', 'confidence': 1.0,
            'backend': 'hold_stance', 'elapsed_ms': 0, 'usecase': msg.get('usecase') or 'open-floor',
            'usecase_title': '空いた床', 'category': 'idle', 'catalog_size': len(catalog),
        })
        return
    x = float(msg.get('x', 0))
    y = float(msg.get('y', 0))
    case = resolve_usecase(msg.get('usecase'))
    poses = latest.get('frame',{}).get('poses', [])
    distance = ((x-poses[0][0])**2 + (y-poses[0][1])**2)**0.5 if poses else 2.0
    summary = pose_summary(poses)
    try:
        decision = await asyncio.to_thread(choose_arrival_pose, case, distance, catalog, x, y, summary)
        if request_numbers.get(ws) != request_number:
            return
        commands.put({'type':'pose_choice','pose_id':decision.pose_id,'move_id':request_number})
        await ws.send_json({'type':'decision','pose_id':decision.pose_id,'name':decision.pose_name,
                            'confidence':decision.confidence,'backend':decision.backend,
                            'elapsed_ms': round(decision.elapsed_ms, 2),
                            'usecase': case['id'], 'usecase_title': case['title'],
                            'category': decision.category, 'catalog_size': decision.catalog_size})
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
            if msg.get('type') == 'collect_review':
                commands.put({name: msg.get(name) for name in ('type', 'move_id', 'settle_seq', 'accepted', 'metrics')})
            if msg.get('type') == 'upper_idle_ready':
                commands.put({name: msg.get(name) for name in ('type', 'move_id', 'settle_seq')})
            if msg.get('type') == 'move':
                # 移動はすぐ開始する。遅れて届いた d3-mini の結果は move_id が違うので捨てる。
                move_id = next(move_ids)
                request_numbers[ws] = move_id
                commands.put({'type':'move','x':float(msg['x']),'y':float(msg['y']),'move_id':move_id, 'hold_stance':msg.get('hold_stance') is True})
                asyncio.create_task(route_and_submit(ws, msg, move_id))
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)
        request_numbers.pop(ws, None)
