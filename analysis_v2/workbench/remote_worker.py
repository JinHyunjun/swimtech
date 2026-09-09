"""Opt-in workstation processor for the deployed admin TEST queue.

Outbound HTTPS only; no listening port or tunnel. Admin credentials are used
once to mint a short-lived, worker-only capability and never written to disk.
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

CHUNK = 1024 * 1024
ROOT = Path(__file__).resolve().parents[2]


def validate_base(base):
    url = urlsplit(base)
    if url.username or url.password or url.query or url.fragment or url.path not in {'', '/'}:
        raise ValueError('A service origin, without credentials or path, is required')
    if not (url.scheme == 'https' and url.hostname == 'swimtech.vercel.app') and not (
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


class RemoteWorker:
    def __init__(self, base, ticket):
        self.base = validate_base(base)+'/api/admin/video-lab'
        self.session = requests.Session()
        self.session.headers['Authorization'] = 'Bearer '+ticket

    def request(self, method, path, **kwargs):
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
                    while not stopped.wait(20):
                        try:
                            reply = keepalive.post(self.base+prefix+'/heartbeat',
                                headers={**headers, 'Authorization': self.session.headers['Authorization']}, timeout=30)
                            reply.raise_for_status()
                        except requests.RequestException:
                            lost.set()
                            bench.cancel(ident)
                            return

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='https://swimtech.vercel.app')
    parser.add_argument('--idle-timeout', type=int, default=900, help='Stop after this many idle seconds (default 15 minutes)')
    parser.add_argument('--max-minutes', type=int, default=55, help='Bounded session, at most 55 minutes per capability')
    args = parser.parse_args()
    base = validate_base(args.base_url)
    worker = RemoteWorker(base, issue_ticket(base))
    print('Admin TEST processor connected via outbound HTTPS. Stop with Ctrl+C.', flush=True)
    deadline = time.monotonic()+min(max(args.max_minutes, 1), 55)*60
    last_work = time.monotonic()
    try:
        while time.monotonic() < deadline:
            job = worker.claim_job()
            if job:
                worker.process(job)
                last_work = time.monotonic()
            elif time.monotonic()-last_work > max(30, args.idle_timeout):
                break
            time.sleep(5)
    finally:
        worker.session.close()
    print('Processor session ended. Re-run when testing again.', flush=True)


if __name__ == '__main__':
    main()
