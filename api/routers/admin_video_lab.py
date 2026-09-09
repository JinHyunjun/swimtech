"""Admin experimental video review. Ephemeral HTTPS broker, not public inference."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import hashlib
import hmac
import os
import re
import tempfile
import time
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute
from jose import jwt, JWTError
from pydantic import BaseModel, ConfigDict, Field

from routers.admin import _require_admin
from routers.auth import SECRET_KEY, ALGORITHM
from services.video_lab import VideoLab, MAX_VIDEO, CHUNK, TTL, write_json, event_comparison
from services.video_devices import DeviceRegistry


class LabRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request):
            try:
                response = await original(request)
            except RequestValidationError:
                # Do not echo untrusted non-finite values into JSONResponse.
                raise HTTPException(422, '입력값의 형식과 범위를 확인해 주세요.')
            except FileNotFoundError:
                raise HTTPException(404, "영상이 없거나 보관 시간이 만료됐습니다.")
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            return response
        return handler


router = APIRouter(route_class=LabRoute)
_store = None
_devices = DeviceRegistry()
_boot_id = uuid4().hex
_revoked_devices = set()
_persistent_workers = set()


def store():
    global _store
    if _store is None:
        _store = VideoLab(os.path.join(tempfile.gettempdir(), 'swimmate-admin-video-lab'))
    return _store


def admin(request: Request):
    owner = _require_admin(request.cookies.get('swimtech_token'))
    if request.method not in {'GET', 'HEAD'}:
        # Custom header cannot be submitted by cross-site HTML forms. CORS does
        # not allow credentialed access from untrusted origins.
        if request.headers.get('x-video-lab') != '1' or request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, '관리자 화면에서 다시 시도해 주세요.')
    return owner


def worker(request: Request):
    try:
        scheme, token = request.headers.get('authorization', '').split(' ', 1)
        data = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], audience='video-lab')
        if scheme != 'Bearer' or data.get('scope') != 'video-lab-worker' or not re.fullmatch('[a-f0-9]{32}', data.get('worker', '')):
            raise ValueError('scope')
        # Restart requires durable re-authorization; a revoked token cannot
        # become valid again after the in-memory revocation set is lost.
        if data.get('device') and (data.get('boot') != _boot_id or data['worker'] in _revoked_devices):
            raise ValueError('device authorization')
        if data.get('device'): _persistent_workers.add((data['sub'],data['worker']))
        return data['sub'], data['worker']
    except (JWTError, ValueError, KeyError):
        raise HTTPException(401, '처리기 인증이 만료됐습니다.')


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Upload(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    size: int = Field(gt=0, le=MAX_VIDEO)
    sha256: str = Field(pattern='^[a-f0-9]{64}$')


class Settings(StrictModel):
    stroke: Literal['freestyle', 'backstroke', 'breaststroke', 'butterfly']
    start_sec: float = Field(ge=0)
    end_sec: float = Field(gt=0)
    distance_m: float | None = Field(default=None, gt=0, le=5000)
    roi: list[float] = Field(min_length=4, max_length=4)
    rotation: Literal['none', 'clockwise', 'counterclockwise'] = 'clockwise'


class Label(StrictModel):
    annotator: str = Field(min_length=1, max_length=80)
    arm_events: list[float] = Field(max_length=2000)
    kick_events: list[float] = Field(max_length=2000)
    arm_status: Literal['labeled', 'unresolvable'] = 'labeled'
    kick_status: Literal['labeled', 'unresolvable'] = 'labeled'
    never_seen_predictions: bool = False


class Prepared(StrictModel):
    fps: float = Field(ge=1, le=120)
    duration: float = Field(gt=0, le=60)
    frames: int = Field(ge=2, le=7200)
    width: int = Field(gt=0, le=4096)
    height: int = Field(gt=0, le=4096)


class PairCode(StrictModel):
    code: str = Field(pattern='^[A-F0-9]{8}$')


class PairPoll(PairCode):
    secret: str = Field(pattern='^[A-Za-z0-9_-]{43}$')


class PairStart(StrictModel):
    remember: bool = False


class PairApproval(PairCode):
    remember: bool = False
    name: str = Field(default='분석 PC', min_length=1, max_length=80)


class DeviceSecret(StrictModel):
    device_id: str = Field(pattern='^[a-f0-9]{32}$')
    secret: str = Field(pattern='^[A-Za-z0-9_-]{43}$')
    proof: str = Field(pattern='^[a-f0-9]{64}$')


def device_proof(ident, secret):
    return hmac.new(SECRET_KEY.encode(), ('video-lab-device:'+ident+':'+secret).encode(), hashlib.sha256).hexdigest()


async def bounded_body(request, maximum):
    result = bytearray()
    async for chunk in request.stream():
        if len(result) + len(chunk) > maximum:
            raise HTTPException(413, '요청 크기 제한을 초과했습니다.')
        result.extend(chunk)
    return bytes(result)


@router.get('/session')
def session(owner=Depends(admin)):
    s = store()
    with s.lock:
        s.cleanup()
        s.workers = {key: value for key, value in s.workers.items() if value > time.time()-180}
        online = any(key[0] == owner and value > time.time()-45 for key, value in s.workers.items())
        persistent = any(key[0] == owner and key in _persistent_workers and value > time.time()-45 for key, value in s.workers.items())
    return {'max_bytes': MAX_VIDEO, 'ttl_seconds': TTL, 'worker_online': online,
            'persistent_worker_online':persistent,
            'experimental': True, 'storage': 'ephemeral', 'token': '1'}


def make_worker_ticket(owner, device_id=None):
    ident = device_id or uuid4().hex
    claims = {'sub': owner, 'worker': ident, 'scope': 'video-lab-worker',
              'aud': 'video-lab', 'exp': int(time.time())+TTL}
    if device_id: claims.update(device=True, boot=_boot_id)
    ticket = jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)
    return {'token': ticket, 'expires_in': TTL}


@router.post('/worker-ticket')
def worker_ticket(owner=Depends(admin)):
    return make_worker_ticket(owner)


@router.post('/worker/pair')
def pair_start(request: Request, options: PairStart | None = None):
    # Unauthenticated creation alone grants no access. Bounded five-minute
    # requests require explicit approval by a signed-in administrator.
    return store().start_pairing(request.client.host if request.client else 'unknown', remember=bool(options and options.remember))


@router.get('/worker/pair/{code}')
def pair_info(code: str, owner=Depends(admin)):
    s = store()
    with s.lock:
        return {'remember_requested':s.pending_pair(code)['remember_requested']}


@router.post('/worker/pair/poll')
def pair_poll(data: PairPoll):
    return store().poll_pairing(data.code, data.secret)


@router.post('/worker/pair/approve')
def pair_approve(data: PairApproval, owner=Depends(admin)):
    s = store()
    with s.lock:
        pair = s.pending_pair(data.code)
        if data.remember and not pair['remember_requested']:
            raise ValueError('이 요청은 지속 연결을 지원하지 않습니다. 새 처리기로 다시 연결하세요.')
        if data.remember:
            device = _devices.register(owner, data.name.strip() or '분석 PC')
            device['proof'] = device_proof(device['device_id'], device['secret'])
            bundle = {**make_worker_ticket(owner, device['device_id']), 'device':device}
        else:
            bundle = make_worker_ticket(owner)['token']
        s.approve_pairing(data.code, bundle)
    return {'approved': True}


@router.post('/worker/device/refresh')
def device_refresh(data: DeviceSecret):
    if not hmac.compare_digest(data.proof, device_proof(data.device_id, data.secret)):
        raise HTTPException(401, '올바르지 않은 PC 연결 정보입니다.')
    s = store()
    with s.lock:
        owner = _devices.renew(data.device_id, data.secret)
        if not owner or data.device_id in _revoked_devices:
            raise HTTPException(401, 'PC 연결이 해제되었거나 만료되었습니다. 다시 승인하세요.')
        return make_worker_ticket(owner, data.device_id)


@router.get('/devices')
def devices(owner=Depends(admin)):
    s = store()
    with s.lock:
        return [{**d, 'online':s.workers.get((owner,d['id']),0)>time.time()-45} for d in _devices.list(owner)]


@router.delete('/devices/{ident}')
def revoke_device(ident: str, owner=Depends(admin)):
    s = store()
    with s.lock:
        if not _devices.revoke(owner, ident): raise HTTPException(404, '등록된 PC가 없습니다.')
        _revoked_devices.add(ident)
        s.workers.pop((owner,ident), None)
        for data in s.list(owner):
            private = s.read(data['id'])
            if private.get('worker') == ident and private['state'] in {'running','preparing'}:
                s.update(data['id'],state='cancelled',lease=None,error='관리자가 PC 연결을 해제했습니다.')
    return {'revoked':True}


@router.get('/videos')
def videos(owner=Depends(admin)):
    return store().list(owner)


@router.post('/videos')
def create(data: Upload, owner=Depends(admin)):
    return store().create(owner, data.name, data.size, data.sha256)


@router.put('/videos/{ident}/chunks')
async def upload_chunk(ident: str, request: Request, offset: int, owner=Depends(admin)):
    body = await bounded_body(request, CHUNK)
    store().append(ident, owner, offset, body)
    return {'received': offset+len(body)}


@router.post('/videos/{ident}/seal')
def seal(ident: str, owner=Depends(admin)):
    return store().seal(ident, owner)


@router.get('/videos/{ident}')
def video(ident: str, owner=Depends(admin)):
    s = store()
    with s.lock:
        s.cleanup()
        return s.public(s.owned(ident, owner))


@router.delete('/videos/{ident}')
def delete(ident: str, owner=Depends(admin)):
    store().delete(ident, owner)
    return {'deleted': True}


@router.post('/videos/{ident}/analyze')
def analyze(ident: str, settings: Settings, owner=Depends(admin)):
    s = store()
    with s.lock:
        data = s.owned(ident, owner)
        # Immutable interval: blind labels must never be compared to a new run.
        if data['state'] != 'uploaded' or data['settings']:
            raise ValueError('재생 준비가 끝난 새 영상에서 분석 조건을 확정하세요.')
        if not settings.start_sec < settings.end_sec <= data['duration']+.001 or settings.end_sec-settings.start_sec > 60:
            raise ValueError('영상 안의 60초 이하 분석 구간을 지정하세요.')
        x1, y1, x2, y2 = settings.roi
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1) or min(x2-x1, y2-y1) < .03:
            raise ValueError('선수 영역을 충분한 크기로 지정하세요.')
        return s.public(s.update(ident, state='queued', settings=settings.model_dump()))


@router.post('/videos/{ident}/cancel')
def cancel(ident: str, owner=Depends(admin)):
    s = store()
    with s.lock:
        data = s.owned(ident, owner)
        if data['state'] not in {'queued', 'running', 'prepare_queued', 'preparing'}:
            raise ValueError('진행 중인 작업이 없습니다.')
        return s.public(s.update(ident, state='cancelled', lease=None))


def read_label(ident, filename='label.json'):
    path = store().directory(ident)/filename
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


@router.get('/videos/{ident}/labels')
def get_label(ident: str, owner=Depends(admin)):
    store().owned(ident, owner)
    return read_label(ident)


@router.post('/videos/{ident}/labels')
def save_label(ident: str, label: Label, owner=Depends(admin)):
    s = store()
    with s.lock:
        data = s.owned(ident, owner)
        settings = data['settings']
        if not settings or not label.annotator.strip():
            raise ValueError('분석 조건과 검수자 이름이 필요합니다.')
        if any(not settings['start_sec'] <= t < settings['end_sec'] for t in label.arm_events+label.kick_events):
            raise ValueError('동작 시점은 분석 구간 [시작, 종료) 안에 있어야 합니다.')
        if (label.arm_status == 'unresolvable' and label.arm_events) or (label.kick_status == 'unresolvable' and label.kick_events):
            raise ValueError('판독 불가 기록에는 동작 시점을 넣을 수 없습니다.')
        assisted = data['revealed'] or not label.never_seen_predictions
        payload = dict(schema_version='swimmate-event-label-v2', video=data['sha256'], video_sha256=data['sha256'],
            display_filename=data['name'], stroke_kind=settings['stroke'], lane_id=1,
            interval_sec=[settings['start_sec'], settings['end_sec']], annotator=label.annotator.strip(),
            arm_event_times_sec=sorted(set(label.arm_events)), kick_event_times_sec=sorted(set(label.kick_events)),
            arm_label_status=label.arm_status, kick_label_status=label.kick_status,
            label_mode='prediction_assisted' if assisted else 'blinded_manual', prediction_visible=assisted,
            verified=False, created_at=datetime.now(timezone.utc).isoformat(),
            review_context={'roi': settings['roi'], 'timeline': 'source_frame_index_divided_by_fps'})
        directory = s.directory(ident)
        if not assisted:
            write_json(directory/'blind-label.json', payload)
        write_json(directory/'label.json', payload)
        return payload


def comparison(ident):
    s = store()
    directory = s.directory(ident)
    result = json.loads((directory/'result.json').read_text(encoding='utf-8'))
    review = json.loads((directory/'review.json').read_text(encoding='utf-8'))
    label = read_label(ident)
    return {'result': result, 'review': review,
            'comparison': event_comparison(label, result, s.read(ident)['settings']['distance_m']) if label else None}


@router.post('/videos/{ident}/reveal')
def reveal(ident: str, owner=Depends(admin)):
    s = store()
    with s.lock:
        if s.owned(ident, owner)['state'] != 'complete':
            raise ValueError('분석이 끝난 뒤 결과를 열 수 있습니다.')
        s.update(ident, revealed=True)
        return comparison(ident)


@router.get('/videos/{ident}/export')
def export(ident: str, owner=Depends(admin)):
    s = store()
    with s.lock:
        data = s.owned(ident, owner)
        payload = {'project': s.public(data), 'label': read_label(ident), 'blind_label': read_label(ident, 'blind-label.json')}
        if data['revealed'] and data['state'] == 'complete':
            value = comparison(ident)
            value['review'].pop('overlays', None)
            payload.update(value)
        return JSONResponse(payload, headers={'Content-Disposition': 'attachment; filename="swimmate-admin-review.json"'})


def stream_file(path, request, max_chunk=None):
    length = path.stat().st_size
    start, end = 0, length-1
    header = request.headers.get('range')
    if header:
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', header)
        if not match or not any(match.groups()):
            return Response(status_code=416, headers={'Content-Range': f'bytes */{length}'})
        first, last = match.groups()
        if first:
            start, end = int(first), min(int(last), end) if last else end
        else:
            start = max(0, length-int(last))
        if start > end or start >= length:
            return Response(status_code=416, headers={'Content-Range': f'bytes */{length}'})
    if max_chunk:
        end = min(end, start+max_chunk-1)
    def chunks():
        with path.open('rb') as source:
            source.seek(start)
            remaining = end-start+1
            while remaining:
                block = source.read(min(CHUNK, remaining))
                if not block:
                    break
                remaining -= len(block)
                yield block
    headers = {'Accept-Ranges': 'bytes', 'Content-Length': str(end-start+1)}
    if header or max_chunk:
        headers['Content-Range'] = f'bytes {start}-{end}/{length}'
    return StreamingResponse(chunks(), status_code=206 if header or max_chunk else 200,
                             media_type='video/mp4', headers=headers)


@router.get('/media/{ident}')
def media(ident: str, request: Request, owner=Depends(admin)):
    store().owned(ident, owner)
    return stream_file(store().directory(ident)/'preview.mp4', request)


@router.get('/media/{ident}/source')
def original_media(ident: str, request: Request, owner=Depends(admin)):
    s = store()
    if s.owned(ident, owner)['state'] == 'uploading':
        raise HTTPException(409, '업로드가 완료된 뒤 원본을 재생할 수 있습니다.')
    # Native browser preview only. Authoritative FPS/frame-index time and
    # model settings remain locked until workstation inspection completes.
    return stream_file(s.directory(ident)/'source.mp4', request, CHUNK)


@router.post('/worker/claim')
def claim(identity=Depends(worker)):
    return store().claim(*identity)


@router.post('/worker/{ident}/heartbeat')
def heartbeat(ident: str, request: Request, identity=Depends(worker)):
    store().heartbeat(ident, *identity, request.headers.get('x-lab-lease'))
    return {'ok': True}


@router.get('/worker/{ident}/source')
def source(ident: str, request: Request, identity=Depends(worker)):
    store().leased(ident, *identity, request.headers.get('x-lab-lease'))
    return stream_file(store().directory(ident)/'source.mp4', request, CHUNK)


@router.put('/worker/{ident}/preview')
async def preview_chunk(ident: str, request: Request, offset: int, identity=Depends(worker)):
    body = await bounded_body(request, CHUNK)
    s = store()
    with s.lock:
        data = s.leased(ident, *identity, request.headers.get('x-lab-lease'))
        path = s.directory(ident)/'preview.part'
        if data['state'] != 'preparing' or offset != (path.stat().st_size if path.exists() else 0) or not body or offset+len(body)>32*CHUNK:
            raise ValueError('재생 파일 업로드 순서 또는 크기가 잘못됐습니다.')
        with path.open('ab') as output:
            output.write(body)
    return {'received': offset+len(body)}


@router.post('/worker/{ident}/prepared')
def prepared(ident: str, info: Prepared, request: Request, identity=Depends(worker)):
    s = store()
    with s.lock:
        data = s.leased(ident, *identity, request.headers.get('x-lab-lease'))
        if data['state'] != 'preparing' or abs(info.frames/info.fps-info.duration)>.1:
            raise ValueError('재생 메타데이터가 일치하지 않습니다.')
        (s.directory(ident)/'preview.part').replace(s.directory(ident)/'preview.mp4')
        s.update(ident, state='uploaded', preview=True, lease=None, **info.model_dump())
    return {'ok': True}


@router.post('/worker/{ident}/result')
async def complete(ident: str, request: Request, identity=Depends(worker)):
    raw = await bounded_body(request, 3*CHUNK)
    try:
        payload = json.loads(raw)
        # Serialise before writing either file; rejects NaN/Infinity.
        json.dumps(payload, allow_nan=False)
        result, review = payload['result'], payload['review']
        if not isinstance(result['tracks'], list) or not isinstance(result['distance_metrics'], list) or not isinstance(review['windows'], list) or not isinstance(review['overlays'], list):
            raise ValueError('결과 형식이 올바르지 않습니다.')
    except (KeyError, TypeError):
        raise ValueError('결과 형식이 올바르지 않습니다.')
    s = store()
    with s.lock:
        data = s.leased(ident, *identity, request.headers.get('x-lab-lease'))
        if data['state'] != 'running' or payload.get('sha256') != data['sha256']:
            raise ValueError('분석 작업의 원본이 일치하지 않습니다.')
        write_json(s.directory(ident)/'result.json', result)
        write_json(s.directory(ident)/'review.json', review)
        s.update(ident, state='complete', lease=None)
    return {'ok': True}


@router.post('/worker/{ident}/failed')
def failed(ident: str, request: Request, identity=Depends(worker)):
    s = store()
    with s.lock:
        s.leased(ident, *identity, request.headers.get('x-lab-lease'))
        s.update(ident, state='failed', lease=None,
                 error='처리에 실패했습니다. 60초 이하·64MB 이하 영상인지 확인하고 다시 업로드하세요. 처리기 로그에서 상세 원인을 확인할 수 있습니다.')
    return {'ok': True}
