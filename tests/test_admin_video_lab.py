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
    monkeypatch.setattr(api, '_revoked_devices', set())
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


@pytest.mark.parametrize('path', ['/videos/{id}', '/videos/{id}/labels', '/videos/{id}/export', '/media/{id}', '/media/{id}/source'])
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


def test_source_preview_before_processor_connection(lab):
    client, _ = lab
    data = client.post(PREFIX+'/videos', json={'name':'source.mp4','size':len(BODY),'sha256':hashlib.sha256(BODY).hexdigest()}).json()
    path = PREFIX+'/media/'+data['id']+'/source'
    assert client.get(path).status_code == 409
    ident = upload(client)
    path = PREFIX+'/media/'+ident+'/source'
    assert client.get(PREFIX+'/session').json()['worker_online'] is False
    reply = client.get(path, headers={'Range':'bytes=3-9'})
    assert reply.status_code == 206 and reply.content == BODY[3:10]
    assert reply.headers['cache-control'] == 'no-store'
    assert client.get(PREFIX+f'/videos/{ident}').json()['preview'] is False
    assert client.post(PREFIX+f'/videos/{ident}/analyze', json=SETTINGS).status_code == 400
    client.cookies.clear()
    assert client.get(path).status_code == 401


def test_pairing_requires_explicit_admin_approval_and_private_device_secret(lab):
    client, _ = lab
    client.cookies.clear()
    pair = client.post(PREFIX+'/worker/pair').json()
    payload = {'code':pair['code'],'secret':pair['secret']}
    assert client.post(PREFIX+'/worker/pair/poll', json=payload).json() == {'status':'pending'}
    assert client.post(PREFIX+'/worker/pair/approve', json={'code':pair['code']}).status_code == 401
    client.cookies.set('swimtech_token', 'member')
    assert client.post(PREFIX+'/worker/pair/approve', json={'code':pair['code']}).status_code == 403
    client.cookies.set('swimtech_token', 'admin-a')
    assert client.post(PREFIX+'/worker/pair/approve', json={'code':pair['code']}, headers={'Sec-Fetch-Site':'cross-site'}).status_code == 403
    assert client.post(PREFIX+'/worker/pair/approve', json={'code':pair['code']}).json() == {'approved':True}
    assert client.post(PREFIX+'/worker/pair/poll', json={**payload,'secret':'A'*43}).status_code == 400
    reply = client.post(PREFIX+'/worker/pair/poll', json=payload)
    assert reply.headers['cache-control'] == 'no-store'
    token = reply.json()['token']
    assert client.post(PREFIX+'/worker/pair/poll', json=payload).status_code == 400
    client.cookies.clear()
    assert client.post(PREFIX+'/worker/claim', headers={'Authorization':'Bearer '+token}).status_code == 200
    # The worker capability is not an administrator browser cookie.
    client.cookies.set('swimtech_token', token)
    assert client.get(PREFIX+'/session').status_code == 403


def test_pairing_expiry_rate_limit_and_approval_not_replaceable(lab):
    client, store = lab
    pair = client.post(PREFIX+'/worker/pair').json()
    assert client.post(PREFIX+'/worker/pair/approve', json={'code':pair['code']}).status_code == 200
    client.cookies.set('swimtech_token', 'admin-b')
    assert client.post(PREFIX+'/worker/pair/approve', json={'code':pair['code']}).status_code == 400
    store.pairings[pair['code']]['expires_at'] = time.time()-1
    assert client.post(PREFIX+'/worker/pair/poll', json={'code':pair['code'],'secret':pair['secret']}).status_code == 400
    for _ in range(4): assert client.post(PREFIX+'/worker/pair').status_code == 200
    assert client.post(PREFIX+'/worker/pair').status_code == 400
    assert len(store.pairings) == 4


def test_css_dependencies_and_offline_actions_are_shipped():
    root = Path(__file__).resolve().parents[1]
    css = (root/'frontend/static/video-lab/style.css').read_text(encoding='utf-8')
    js = (root/'frontend/static/video-lab/app.js').read_text(encoding='utf-8')
    html = (root/'frontend/admin_video_lab.html').read_text(encoding='utf-8')
    assert '/static/type.css' not in css
    assert '.mobile-markers' in css and '.preview-note' in css
    assert 'connectionPanel' in html and '분석 PC 연결 승인' in html
    assert '이 페이지에서 기다려 주세요' not in js
    assert '||!workerOnline' in js and "'/source'" in js


def test_browser_worker_login_does_not_use_admin_password(monkeypatch, capsys):
    from analysis_v2.workbench import remote_worker
    from unittest.mock import Mock
    monkeypatch.setattr(remote_worker.time, 'sleep', lambda _: None)
    responses = [Mock(json=lambda:{'code':'1234ABCD','secret':'private-device-only','expires_in':300}),
                 Mock(json=lambda:{'status':'pending'}), Mock(json=lambda:{'status':'approved','token':'private-worker-only'})]
    session = Mock()
    session.post.side_effect = responses
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(remote_worker.requests, 'Session', lambda:session)
    assert remote_worker.browser_ticket('http://127.0.0.1:8791') == 'private-worker-only'
    out = capsys.readouterr().out
    assert 'connect=1234ABCD' in out
    assert 'private-device-only' not in out and 'private-worker-only' not in out
    assert all('/auth/login' not in call.args[0] for call in session.post.call_args_list)


@pytest.fixture
def remembered(lab, monkeypatch):
    from unittest.mock import Mock
    client, service = lab
    record = {'device_id':'a'*32,'secret':'S'*43}
    registry = Mock()
    registry.register.return_value = record.copy()
    registry.renew.return_value = 'admin-a'
    registry.list.return_value = [{'id':'a'*32,'name':'Test PC','expires_at':'future','last_used_at':'now'}]
    registry.revoke.side_effect = lambda owner, ident: owner == 'admin-a' and ident == 'a'*32
    monkeypatch.setattr(api, '_devices', registry)
    pair = client.post(PREFIX+'/worker/pair', json={'remember':True}).json()
    assert client.get(PREFIX+'/worker/pair/'+pair['code']).json()['remember_requested'] is True
    approved = client.post(PREFIX+'/worker/pair/approve',json={'code':pair['code'],'remember':True,'name':'Test PC'})
    assert approved.json() == {'approved':True}
    value = client.post(PREFIX+'/worker/pair/poll',json={'code':pair['code'],'secret':pair['secret']}).json()
    return client, service, registry, value


def test_persistent_device_renewal_keeps_worker_identity_and_lease(remembered):
    client, service, registry, grant = remembered
    ident = upload(client)
    header = {'Authorization':'Bearer '+grant['token']}
    job = client.post(PREFIX+'/worker/claim', headers=header).json()
    reply = client.post(PREFIX+'/worker/device/refresh', json=grant['device'])
    assert reply.status_code == 200
    header = {'Authorization':'Bearer '+reply.json()['token'], 'X-Lab-Lease':job['lease']}
    assert client.post(PREFIX+f'/worker/{ident}/heartbeat',headers=header).status_code == 200
    assert client.get(PREFIX+'/devices').json()[0]['online'] is True
    assert service.read(ident)['worker'] == grant['device']['device_id']
    registry.renew.assert_called_once()


def test_device_revoke_is_owner_scoped_and_invalidates_access(remembered):
    client, service, registry, grant = remembered
    ident = upload(client)
    header = {'Authorization':'Bearer '+grant['token']}
    client.post(PREFIX+'/worker/claim', headers=header)
    client.cookies.set('swimtech_token','admin-b')
    assert client.delete(PREFIX+'/devices/'+'a'*32).status_code == 404
    client.cookies.set('swimtech_token','admin-a')
    assert client.delete(PREFIX+'/devices/'+'a'*32).status_code == 200
    assert client.post(PREFIX+'/worker/claim',headers=header).status_code == 401
    assert client.post(PREFIX+'/worker/device/refresh',json=grant['device']).status_code == 401
    assert service.read(ident)['state'] == 'cancelled'


def test_server_restart_requires_durable_device_validation(remembered, monkeypatch):
    client, _, registry, grant = remembered
    monkeypatch.setattr(api,'_boot_id','new-process')
    assert client.post(PREFIX+'/worker/claim',headers={'Authorization':'Bearer '+grant['token']}).status_code == 401
    fresh = client.post(PREFIX+'/worker/device/refresh',json=grant['device']).json()['token']
    assert client.post(PREFIX+'/worker/claim',headers={'Authorization':'Bearer '+fresh}).status_code == 200
    registry.renew.return_value = None  # DB remembers revocation or expired grant after restart.
    assert client.post(PREFIX+'/worker/device/refresh',json=grant['device']).status_code == 401


def test_forged_refresh_never_queries_database(remembered):
    client, _, registry, grant = remembered
    bad = {**grant['device'],'proof':'0'*64}
    assert client.post(PREFIX+'/worker/device/refresh',json=bad).status_code == 401
    registry.renew.assert_not_called()


def test_legacy_pair_cannot_silently_become_persistent(lab):
    client, _ = lab
    pair = client.post(PREFIX+'/worker/pair').json()
    assert client.post(PREFIX+'/worker/pair/approve',json={'code':pair['code'],'remember':True}).status_code == 400


def test_worker_continues_past_55_minutes_and_recovers_network(monkeypatch):
    import requests
    from unittest.mock import Mock
    from analysis_v2.workbench import remote_worker as remote
    clock = [0]
    monkeypatch.setattr(remote.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(remote.time,'sleep',lambda delay:clock.__setitem__(0,clock[0]+1800))
    worker = Mock()
    worker.claim_job.side_effect = [None, requests.ConnectionError(), None, None, KeyboardInterrupt()]
    with pytest.raises(KeyboardInterrupt): remote.run_connected(worker)
    assert clock[0] >= 7200 and worker.claim_job.call_count == 5


def test_worker_refreshes_after_45_minutes_and_on_401(monkeypatch):
    from unittest.mock import Mock
    worker = RemoteWorker('http://127.0.0.1:8791','old',device={'device_id':'a'*32})
    worker.refresh_at = 0
    context = Mock()
    context.__enter__ = Mock(return_value=context)
    context.__exit__ = Mock(return_value=False)
    context.post.return_value = Mock(json=lambda:{'token':'fresh'})
    monkeypatch.setattr('analysis_v2.workbench.remote_worker.requests.Session',lambda:context)
    worker.session.request = Mock(side_effect=[Mock(status_code=401),Mock(status_code=200)])
    assert worker.request('POST','/worker/claim').status_code == 200
    assert context.post.call_count == 2
    assert worker.session.headers['Authorization'] == 'Bearer fresh'


def test_worker_refuses_reconnect_when_permission_is_revoked(monkeypatch):
    import requests
    from unittest.mock import Mock
    from analysis_v2.workbench import remote_worker as remote
    response = requests.Response();response.status_code = 401
    worker = Mock();worker.claim_job.side_effect = requests.HTTPError(response=response)
    with pytest.raises(requests.HTTPError): remote.run_connected(worker)
    worker.claim_job.assert_called_once()


def test_device_credentials_roundtrip_and_no_plaintext(tmp_path):
    import os
    from analysis_v2.workbench.device_credentials import DeviceCredentials
    if os.name != 'nt': pytest.skip('Windows DPAPI only; Linux has no plaintext fallback')
    store = DeviceCredentials('https://swimtech.vercel.app', root=tmp_path)
    device = {'device_id':'test-device','secret':'synthetic-private-grant'}
    store.save(device)
    assert b'synthetic-private-grant' not in store.path.read_bytes()
    assert store.load() == device
    with store.single_instance():
        with pytest.raises(RuntimeError):
            with store.single_instance(): pass
    store.forget();assert store.load() is None


def test_device_registry_checks_hash_role_version_expiry_and_owner(monkeypatch):
    from contextlib import contextmanager
    from unittest.mock import Mock
    from services import video_devices
    cursor = Mock()
    @contextmanager
    def db(): yield None, cursor
    monkeypatch.setattr(video_devices,'db_conn',db)
    registry = video_devices.DeviceRegistry()
    cursor.fetchone.side_effect = [(7,2),(0,)]
    record = registry.register('admin-a','PC')
    command, params = cursor.execute.call_args.args
    assert record['secret'] not in params
    assert hashlib.sha256(record['secret'].encode()).hexdigest() in params
    cursor.fetchone.side_effect = [('admin-a',)]
    assert registry.renew(record['device_id'],record['secret']) == 'admin-a'
    sql = cursor.execute.call_args.args[0]
    for check in ['revoked_at IS NULL','expires_at>NOW()','auth_version=','c.role=']: assert check in sql
    cursor.fetchone.side_effect = [None]
    assert registry.revoke('admin-b',record['device_id']) is False
    assert 'c.username=%s' in cursor.execute.call_args.args[0]
