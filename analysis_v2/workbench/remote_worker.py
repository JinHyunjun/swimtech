"""Opt-in workstation processor for the deployed admin TEST queue.

Outbound HTTPS only; no listening port or tunnel. Administrator passwords are
never stored. Remembered device grants renew short-lived worker capabilities.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from urllib.parse import urlsplit

import requests

from .service import Workbench, create_preview, inspect_video, save_json
from .device_credentials import DeviceCredentials

CHUNK = 1024 * 1024
ROOT = Path(__file__).resolve().parents[2]


def validate_base(base):
    url = urlsplit(base)
    if url.username or url.password or url.query or url.fragment or url.path not in {'', '/'}:
        raise ValueError('A service origin, without credentials or path, is required')
    if not (url.scheme == 'https' and url.hostname == 'swimtech.vercel.app' and url.port in {None,443}) and not (
            url.scheme == 'http' and url.hostname in {'127.0.0.1', 'localhost'}):
        raise ValueError('Only the deployed SwimMate origin or loopback QA is allowed')
    return base.rstrip('/')


def issue_ticket(base):
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    username = os.getenv('ADMIN_ID', '')
    password = os.getenv('ADMIN_PW', '')
    if not username or not password:
        raise RuntimeError('ADMIN_ID / ADMIN_PW are required in the local environment')
    with requests.Session() as session:
        response = session.post(base+'/auth/login', json={'username': username, 'password': password}, timeout=90)
        if response.status_code != 200:
            raise RuntimeError(f'Administrator login failed (HTTP {response.status_code}; credentials are not logged)')
        response = session.post(base+'/api/admin/video-lab/worker-ticket', headers={'X-Video-Lab': '1'}, timeout=60)
        if response.status_code != 200:
            raise RuntimeError('Administrator worker authorization failed')
        return response.json()['token']


def browser_ticket(base, remember=False):
    """Explicit device approval; never reads the browser's cookies/passwords."""
    base = validate_base(base)
    with requests.Session() as session:
        reply = session.post(base+'/api/admin/video-lab/worker/pair', json={'remember':remember}, timeout=90)
        reply.raise_for_status()
        pair = reply.json()
        print('Open this link while signed in as administrator, check the code, and approve this PC:', flush=True)
        print(base+'/admin_video_lab?connect='+pair['code'], flush=True)
        print('Code: '+pair['code']+' (expires in 5 minutes). No password is shared.', flush=True)
        deadline = time.monotonic()+min(pair['expires_in'], 300)
        while time.monotonic() < deadline:
            time.sleep(3)
            reply = session.post(base+'/api/admin/video-lab/worker/pair/poll',
                json={'code':pair['code'], 'secret':pair['secret']}, timeout=30)
            reply.raise_for_status()
            data = reply.json()
            if data['status'] == 'approved':
                return data if remember else data['token']
        raise RuntimeError('PC approval expired. Run again and approve the new code.')


class RemoteWorker:
    def __init__(self, base, ticket, device=None):
        self.base = validate_base(base)+'/api/admin/video-lab'
        self.session = requests.Session()
        self.session.headers['Authorization'] = 'Bearer '+(ticket or '')
        self.device = device
        self.auth_lock = threading.RLock()
        self.refresh_at = time.monotonic()+2700 if ticket else 0

    def authorization(self, force=False):
        with self.auth_lock:
            if self.device and (force or time.monotonic() >= self.refresh_at):
                with requests.Session() as renewal:
                    reply = renewal.post(self.base+'/worker/device/refresh', json=self.device, timeout=90, allow_redirects=False)
                    reply.raise_for_status()
                    self.session.headers['Authorization'] = 'Bearer '+reply.json()['token']
                    self.refresh_at = time.monotonic()+2700
                print('PC authorization renewed automatically.', flush=True)
            return self.session.headers['Authorization']

    def request(self, method, path, **kwargs):
        self.authorization()
        response = self.session.request(method, self.base+path, timeout=90, **kwargs)
        if response.status_code == 401 and self.device:
            self.authorization(force=True)
            response = self.session.request(method, self.base+path, timeout=90, **kwargs)
        response.raise_for_status()
        return response

    def claim_job(self):
        # Keep-alive connections can close just as the idle poll begins. Retry
        # only the claim, never replay a partially acknowledged upload/result.
        for attempt in range(4):
            try:
                return self.request('POST', '/worker/claim').json()
            except requests.RequestException as exc:
                status = exc.response.status_code if exc.response is not None else None
                if (status is not None and status < 500 and status != 429) or attempt == 3:
                    raise
                print('Queue connection interrupted; retrying.', flush=True)
                time.sleep(2*(attempt+1))

    def process(self, job):
        data = job['project']
        ident = data['id']
        headers = {'X-Lab-Lease': job['lease']}
        prefix = '/worker/'+ident
        stopped, lost = threading.Event(), threading.Event()
        # Only this temporary directory is removed; never the user's source.
        with tempfile.TemporaryDirectory(prefix='swimmate-video-worker-') as temp:
            bench = Workbench(Path(temp))
            directory = bench.directory(ident)
            directory.mkdir()
            save_json(directory/'meta.json', data)

            def heartbeat():
                # Separate session: requests.Session is not shared by threads.
                with requests.Session() as keepalive:
                    last_success = time.monotonic()
                    while not stopped.wait(20):
                        try:
                            reply = keepalive.post(self.base+prefix+'/heartbeat',
                                headers={**headers, 'Authorization': self.authorization()}, timeout=30)
                            if reply.status_code == 401 and self.device:
                                reply = keepalive.post(self.base+prefix+'/heartbeat',
                                    headers={**headers, 'Authorization': self.authorization(force=True)}, timeout=30)
                            reply.raise_for_status()
                            last_success = time.monotonic()
                        except requests.RequestException as exc:
                            code = exc.response.status_code if exc.response is not None else None
                            if (code is not None and code < 500 and code != 429) or time.monotonic()-last_success > 120:
                                lost.set(); bench.cancel(ident); return

            thread = threading.Thread(target=heartbeat, daemon=True)
            thread.start()
            try:
                digest = hashlib.sha256()
                offset = 0
                with (directory/'source.mp4').open('wb') as output:
                    while True:
                        response = self.request('GET', prefix+'/source', headers={**headers, 'Range': f'bytes={offset}-{offset+CHUNK-1}'})
                        total = int(response.headers['Content-Range'].split('/')[-1])
                        if total > 64*CHUNK or lost.is_set():
                            raise RuntimeError('Upload limit or lease lost')
                        block = response.content
                        if not block or len(block)>CHUNK or offset+len(block)>total:
                            raise RuntimeError('Invalid download chunk')
                        digest.update(block)
                        output.write(block)
                        offset += len(block)
                        if offset == total:
                            break
                if digest.hexdigest() != data['sha256']:
                    raise RuntimeError('Source hash mismatch')
                if job['phase'] == 'prepare':
                    info = inspect_video(directory/'source.mp4')
                    if info['duration'] > 60:
                        raise ValueError('Admin TEST accepts videos up to 60 seconds')
                    create_preview(directory/'source.mp4', info)
                    path = directory/'preview.mp4'
                    if path.stat().st_size > 32*CHUNK:
                        raise ValueError('Preview exceeds 32 MB')
                    offset = 0
                    with path.open('rb') as source:
                        for block in iter(lambda: source.read(CHUNK), b''):
                            if lost.is_set():
                                raise RuntimeError('Lease lost')
                            self.request('PUT', prefix+'/preview', params={'offset': offset}, headers=headers, data=block)
                            offset += len(block)
                    self.request('POST', prefix+'/prepared', headers=headers, json=info)
                else:
                    bench.run_model(ident)  # Exact local quality/RTMPose/OpenVINO pipeline.
                    if lost.is_set():
                        raise RuntimeError('Lease lost')
                    payload = {'sha256': data['sha256'],
                        'result': json.loads((directory/'result.json').read_text(encoding='utf-8')),
                        'review': json.loads((directory/'review.json').read_text(encoding='utf-8'))}
                    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
                    if len(raw) > 3*CHUNK:
                        raise ValueError('Result exceeds 3 MB; use a shorter interval')
                    self.request('POST', prefix+'/result', headers={**headers, 'Content-Type': 'application/json'}, data=raw)
                print(f"{job['phase']}: complete", flush=True)
            except Exception as exc:
                # Never print response bodies, cookies, source filenames or capabilities.
                print(f"{job['phase']}: failed ({type(exc).__name__})", flush=True)
                try:
                    self.request('POST', prefix+'/failed', headers=headers)
                except requests.RequestException:
                    pass
            finally:
                stopped.set()
                thread.join(timeout=35)
                bench.close()


def run_connected(worker, idle_timeout=0, max_minutes=0):
    deadline = time.monotonic()+max_minutes*60 if max_minutes else None
    last_work = time.monotonic()
    retry_delay, connected = 5, False
    while deadline is None or time.monotonic() < deadline:
        try:
            job = worker.claim_job()
        except requests.RequestException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status is not None and status < 500 and status not in {408,429}:
                raise
            print(f'Connection interrupted. Retrying in {retry_delay}s; approval is retained.', flush=True)
            connected = False
            time.sleep(retry_delay)
            retry_delay = min(retry_delay*2, 60)
            continue
        if not connected:
            print('Admin TEST processor connected. Automatic reconnect is enabled. Stop with Ctrl+C.', flush=True)
            connected = True
        retry_delay = 5
        if job:
            worker.process(job)
            last_work = time.monotonic()
        elif idle_timeout and time.monotonic()-last_work > idle_timeout:
            return
        time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='https://swimtech.vercel.app')
    parser.add_argument('--browser-login', action='store_true', help='Approve this PC using the existing administrator browser login; no .env password required')
    parser.add_argument('--env-login', action='store_true', help='Legacy temporary login using local ADMIN_ID/PW')
    parser.add_argument('--memory-only', action='store_true', help='Renew until stopped, without saving the device grant to disk')
    parser.add_argument('--forget-device', action='store_true', help='Delete only this service saved grant; revoke it separately in the administrator screen')
    parser.add_argument('--idle-timeout', type=int, default=0, help='Optional idle limit in seconds; 0 keeps waiting')
    parser.add_argument('--max-minutes', type=int, default=0, help='Optional runtime limit; 0 keeps connected')
    args = parser.parse_args()
    base = validate_base(args.base_url)
    if args.idle_timeout < 0 or args.max_minutes < 0: parser.error('Limits must be zero or positive')
    credentials = DeviceCredentials(base)
    with credentials.single_instance():
        if args.forget_device:
            credentials.forget(); print('Saved PC connection removed locally.'); return
        device = None if args.memory_only or args.browser_login or args.env_login else credentials.load()
        ticket = None
        if not device:
            if args.env_login:
                ticket = issue_ticket(base)
            else:
                if os.name != 'nt' and not args.memory_only:
                    parser.error('Use --memory-only on non-Windows systems; no plaintext credentials are stored')
                grant = browser_ticket(base, remember=True)
                ticket, device = grant['token'], grant.get('device')
                if device and not args.memory_only: credentials.save(device)
        worker = RemoteWorker(base, ticket, device)
        limit = args.max_minutes if device else min(args.max_minutes or 55, 55)
        print('Continuous PC connection enabled.' if device else 'Temporary approval: session remains limited to 55 minutes.', flush=True)
        try:
            run_connected(worker, args.idle_timeout, limit)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {401,403}:
                if device and not args.memory_only: credentials.forget()
                raise RuntimeError('PC authorization was revoked or expired. Restart and approve again.') from None
            raise
        except KeyboardInterrupt:
            print('Processor stopped. Saved approval is retained for the next run.', flush=True)
        finally:
            worker.session.close()


if __name__ == '__main__':
    main()
