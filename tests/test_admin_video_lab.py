"""Cloud TEST broker contracts; no live DB, credentials, GPU or model download."""
import hashlib
import time
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from routers import admin_video_lab as api
from services.video_lab import VideoLab, CHUNK
from analysis_v2.workbench.remote_worker import validate_base, RemoteWorker

PREFIX = '/api/admin/video-lab'
BODY = b'private fake video - not a model accuracy fixture'
SETTINGS = dict(stroke='freestyle', start_sec=0, end_sec=12, distance_m=25, roi=[0, 0, 1, 1])


@pytest.fixture
def lab(tmp_path, monkeypatch):
    service = VideoLab(tmp_path/'private')
    monkeypatch.setattr(api, '_store', service)
    def require(token):
        if token not in {'admin-a', 'admin-b'}:
            raise HTTPException(401 if not token else 403)
        return token
    monkeypatch.setattr(api, '_require_admin', require)
    app = FastAPI()
    app.include_router(api.router, prefix=PREFIX)
    with TestClient(app) as client:
        client.cookies.set('swimtech_token', 'admin-a')
        client.headers['X-Video-Lab'] = '1'
        yield client, service


def upload(client):
    response = client.post(PREFIX+'/videos', json={'name':'example.mp4', 'size':len(BODY), 'sha256':hashlib.sha256(BODY).hexdigest()})
    assert response.status_code == 200, response.text
    ident = response.json()['id']
    assert client.put(PREFIX+f'/videos/{ident}/chunks?offset=0', content=BODY).status_code == 200
    assert client.post(PREFIX+f'/videos/{ident}/seal').status_code == 200
    return ident


def ticket(client):
    token = client.post(PREFIX+'/worker-ticket').json()['token']
    return {'Authorization':'Bearer '+token}


def prepare(client, ident, headers):
    job = client.post(PREFIX+'/worker/claim', headers=headers).json()
    assert job['project']['id'] == ident
    headers = {**headers, 'X-Lab-Lease':job['lease']}
    assert client.put(PREFIX+f'/worker/{ident}/preview?offset=0', content=BODY, headers=headers).status_code == 200
    assert client.post(PREFIX+f'/worker/{ident}/prepared', json=dict(fps=30, frames=540, duration=18, width=1080, height=1920), headers=headers).status_code == 200
    return headers


@pytest.mark.parametrize('cookie,status', [(None,401), ('member',403), ('demo',403)])
def test_admin_authorization(lab, cookie, status):
    client, _ = lab
    client.cookies.clear()
    if cookie: client.cookies.set('swimtech_token', cookie)
    assert client.get(PREFIX+'/session').status_code == status
    assert client.post(PREFIX+'/worker-ticket').status_code == status


def test_mutations_require_custom_header_and_same_site(lab):
    client, _ = lab
    del client.headers['X-Video-Lab']
    assert client.post(PREFIX+'/worker-ticket').status_code == 403
    assert client.post(PREFIX+'/worker-ticket', headers={'X-Video-Lab':'1', 'Sec-Fetch-Site':'cross-site'}).status_code == 403


@pytest.mark.parametrize('path', ['/videos/{id}', '/videos/{id}/labels', '/videos/{id}/export', '/media/{id}'])
def test_other_admin_cannot_read_private_video(lab, path):
    client, _ = lab
    ident = upload(client)
    client.cookies.set('swimtech_token', 'admin-b')
    assert client.get(PREFIX+path.format(id=ident)).status_code == 404
    assert client.get(PREFIX+'/videos').json() == []
    assert client.delete(PREFIX+f'/videos/{ident}').status_code == 404


def test_chunk_order_hash_size_and_quota(lab):
    client, s = lab
    data = dict(name='fixture.mp4', size=3, sha256='0'*64)
    ident = client.post(PREFIX+'/videos', json=data).json()['id']
    assert client.put(PREFIX+f'/videos/{ident}/chunks?offset=1', content=b'abc').status_code == 400
    assert client.put(PREFIX+f'/videos/{ident}/chunks?offset=0', content=b'a'*(CHUNK+1)).status_code == 413
    assert client.put(PREFIX+f'/videos/{ident}/chunks?offset=0', content=b'abc').status_code == 200
    assert client.post(PREFIX+f'/videos/{ident}/seal').status_code == 400
    assert s.read(ident)['state'] == 'uploading'
    client.post(PREFIX+'/videos', json=data)
    client.post(PREFIX+'/videos', json=data)
    assert client.post(PREFIX+'/videos', json=data).status_code == 400
    assert client.post(PREFIX+'/videos', json={**data,'size':65*CHUNK}).status_code == 422


def test_worker_scope_ownership_and_source_ranges(lab):
    client, _ = lab
    ident = upload(client)
    assert client.post(PREFIX+'/worker/claim').status_code == 401
    worker = ticket(client)
    client.cookies.set('swimtech_token', 'admin-b')
    assert client.post(PREFIX+'/worker/claim', headers=ticket(client)).json() is None
    client.cookies.clear()  # Worker must not need an admin session or DB on poll.
    job = client.post(PREFIX+'/worker/claim', headers=worker).json()
    assert job['phase'] == 'prepare'
    wrong = client.get(PREFIX+f'/worker/{ident}/source', headers=worker)
    assert wrong.status_code == 400
    right = {**worker, 'X-Lab-Lease':job['lease'], 'Range':'bytes=1-4'}
    response = client.get(PREFIX+f'/worker/{ident}/source', headers=right)
    assert response.status_code == 206 and response.content == BODY[1:5]
    assert client.post(PREFIX+'/worker/claim', headers=worker).json() is None


def test_cancel_invalidates_lease_and_delete_is_scoped(lab):
    client, s = lab
    ident = upload(client)
    worker = ticket(client)
    job = client.post(PREFIX+'/worker/claim', headers=worker).json()
    headers = {**worker, 'X-Lab-Lease':job['lease']}
    assert client.post(PREFIX+f'/videos/{ident}/cancel').json()['state'] == 'cancelled'
    assert client.post(PREFIX+f'/worker/{ident}/heartbeat', headers=headers).status_code == 400
    assert client.delete(PREFIX+f'/videos/{ident}').status_code == 200
    assert not s.directory(ident).exists()
    with pytest.raises(ValueError): s.directory('../outside')


def test_expiry_and_offline_status(lab):
    client, s = lab
    assert client.get(PREFIX+'/session').json()['worker_online'] is False
    ident = upload(client)
    worker = ticket(client)
    client.post(PREFIX+'/worker/claim', headers=worker)
    assert client.get(PREFIX+'/session').json()['worker_online'] is True
    s.update(ident, lease_until=time.time()-1)
    assert client.get(PREFIX+f'/videos/{ident}').json()['state'] == 'failed'
    s.update(ident, expires_at=time.time()-1)
    assert client.get(PREFIX+f'/videos/{ident}/export').status_code == 404
    assert client.get(PREFIX+'/videos').json() == []
    assert not s.directory(ident).exists()


@pytest.mark.parametrize('changes', [{'end_sec':20}, {'roi':[0,0,.001,1]}, {'start_sec':12}, {'end_sec':float('inf')}, {'stroke':'unknown'}])
def test_analysis_settings_validation(lab, changes):
    client, _ = lab
    ident = upload(client)
    prepare(client, ident, ticket(client))
    # Use raw JSON for nonfinite input; compliant serializers reject it earlier.
    import json
    response = client.post(PREFIX+f'/videos/{ident}/analyze', content=json.dumps({**SETTINGS, **changes}), headers={'Content-Type':'application/json'})
    assert response.status_code in {400,422}


def test_blind_labels_result_reveal_and_manual_dps(lab):
    client, s = lab
    ident = upload(client)
    headers = prepare(client, ident, ticket(client))
    response = client.get(PREFIX+f'/media/{ident}', headers={'Range':'bytes=2-6'})
    assert response.content == BODY[2:7] and response.status_code == 206
    assert client.get(PREFIX+f'/media/{ident}', headers={'Range':'bytes=999-'}).status_code == 416
    assert client.post(PREFIX+f'/videos/{ident}/analyze', json=SETTINGS).status_code == 200
    assert client.post(PREFIX+f'/videos/{ident}/analyze', json=SETTINGS).status_code == 400
    label = dict(annotator='QA synthetic contract only', arm_events=[1,3],kick_events=[],kick_status='unresolvable',never_seen_predictions=True)
    assert client.post(PREFIX+f'/videos/{ident}/labels', json=label).json()['label_mode'] == 'blinded_manual'
    assert client.post(PREFIX+f'/videos/{ident}/labels', json={**label,'arm_events':[12]}).status_code == 400
    job = client.post(PREFIX+'/worker/claim', headers=headers).json()
    headers['X-Lab-Lease'] = job['lease']
    payload = {'sha256':hashlib.sha256(BODY).hexdigest(),
        'result':{'tracks':[{'lane_id':1,'arm_strokes':{'available':False},'kicks':{'available':False},
                           'diagnostics':{'merged_arm_candidate_times_sec':[1.05,3.05],'kick_candidate_times_sec':[]}}], 'distance_metrics':[]},
        'review':{'windows':[], 'overlays':[]}}
    assert client.post(PREFIX+f'/worker/{ident}/result', json={**payload,'sha256':'bad'}, headers=headers).status_code == 400
    assert client.post(PREFIX+f'/worker/{ident}/result', json=payload, headers=headers).status_code == 200
    assert 'result' not in client.get(PREFIX+f'/videos/{ident}/export').json()
    value = client.post(PREFIX+f'/videos/{ident}/reveal').json()
    assert value['comparison']['manual_dps'] == 12.5
    assert value['comparison']['arm']['model_count'] is None
    assert value['comparison']['arm']['timing']['f1'] == 1
    assert value['comparison']['kick']['manual_count'] is None
    saved = client.post(PREFIX+f'/videos/{ident}/labels', json={**label,'arm_events':[1]}).json()
    assert saved['label_mode'] == 'prediction_assisted' and saved['verified'] is False
    export = client.get(PREFIX+f'/videos/{ident}/export').json()
    assert export['blind_label']['arm_event_times_sec'] == [1,3]
    assert 'owner' not in export['project'] and 'lease' not in export['project']
    assert export['label']['arm_event_times_sec'] == [1]


@pytest.mark.parametrize('base', ['http://example.com','https://evil.com','https://swimtech.vercel.app@evil.com','https://swimtech.vercel.app/a'])
def test_worker_cannot_send_credentials_to_arbitrary_origins(base):
    with pytest.raises(ValueError): validate_base(base)


def test_deployed_admin_assets_and_qa_are_mapped():
    root = Path(__file__).resolve().parents[1]
    html = (root/'frontend/admin.html').read_text(encoding='utf-8')
    js = (root/'frontend/static/video-lab/app.js').read_text(encoding='utf-8')
    assert 'admin-tab-video-lab' in html and "videoLab.src = '/admin_video_lab'" in html
    assert '/api/admin/video-lab' in js and 'X-Video-Lab' in js and 'workerStatus' in js
    assert '127.0.0.1' not in html+js
    assert 'test_admin_video_lab.py' in (root/'.github/workflows/qa.yml').read_text(encoding='utf-8')


def test_worker_retries_transient_poll_but_not_auth_failure(monkeypatch):
    import requests
    from unittest.mock import Mock
    monkeypatch.setattr('analysis_v2.workbench.remote_worker.time.sleep', lambda _: None)
    worker = RemoteWorker('http://127.0.0.1:8791', 'synthetic-only')
    worker.request = Mock(side_effect=[requests.ConnectionError(), Mock(json=lambda:None)])
    assert worker.claim_job() is None
    assert worker.request.call_count == 2
    reply = requests.Response()
    reply.status_code = 401
    worker.request = Mock(side_effect=requests.HTTPError(response=reply))
    with pytest.raises(requests.HTTPError): worker.claim_job()
    assert worker.request.call_count == 1
