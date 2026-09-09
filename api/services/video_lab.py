"""Ephemeral admin-only video test queue. Never uses the production database.

The API brokers bounded files; an authenticated workstation runs the existing
model. No CV dependencies or shell commands run on the public API host.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import threading
import time
from uuid import uuid4

MAX_VIDEO = 64 * 1024 * 1024
CHUNK = 1024 * 1024
TTL = 3600


def write_json(path, value):
    temp=path.with_suffix('.part')
    temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    temp.replace(path)


def event_comparison(label, result, distance):
    """Candidate agreement is not independent accuracy or a completed count."""
    track=next((t for t in result.get('tracks',[]) if t.get('lane_id')==1),None)
    comparison={'status':'single_reviewer_comparison_not_validated_accuracy','manual_dps':None,
                'label_mode':label['label_mode']}
    for kind,field,candidates in [('arm','arm_strokes','merged_arm_candidate_times_sec'),('kick','kicks','kick_candidate_times_sec')]:
        if label[kind+'_label_status']=='unresolvable':
            comparison[kind]={'status':'unresolvable','manual_count':None};continue
        ref=label[kind+'_event_times_sec'];prediction=track.get(field,{}) if track else {}
        events=prediction.get('event_times_sec',[]) if prediction.get('available') else (track or {}).get('diagnostics',{}).get(candidates,[])
        unused=set(range(len(events)));matched=0
        for t in sorted(ref):
            options=[i for i in unused if abs(events[i]-t)<=.25]
            if options: unused.remove(min(options,key=lambda i:abs(events[i]-t)));matched+=1
        precision=matched/len(events) if events else 0;recall=matched/len(ref) if ref else 0
        f1=2*precision*recall/(precision+recall) if precision+recall else (1 if not events and not ref else 0)
        comparison[kind]={'manual_count':len(ref),'candidate_count':len(events),
            'model_count':prediction.get('count') if prediction.get('available') else None,
            'timing':{'precision':precision,'recall':recall,'f1':f1},
            'status':'prediction_comparison' if prediction.get('available') else 'candidate_comparison'}
        if kind=='arm' and distance and ref:comparison['manual_dps']=round(distance/len(ref),4)
    return comparison


class VideoLab:
    def __init__(self, root):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.workers={};self.pairings={};self.pair_requests={}

    def start_pairing(self, address):
        """Device authorization: no account password or browser session is shared."""
        with self.lock:
            now=time.time()
            self.pairings={k:v for k,v in self.pairings.items() if v['expires_at']>now}
            self.pair_requests={k:v for k,v in self.pair_requests.items() if v['until']>now}
            rate=self.pair_requests.get(address, {'until':now+60,'count':0})
            if rate['count']>=5 or len(self.pairings)>=32:
                raise ValueError('연결 요청이 많습니다. 잠시 후 다시 시도하세요.')
            rate['count']+=1;self.pair_requests[address]=rate
            code=secrets.token_hex(4).upper()
            while code in self.pairings:code=secrets.token_hex(4).upper()
            secret=secrets.token_urlsafe(32)
            self.pairings[code]={'digest':hashlib.sha256(secret.encode()).hexdigest(),'expires_at':now+300,'token':None}
            return {'code':code,'secret':secret,'expires_in':300}

    def approve_pairing(self, code, token):
        with self.lock:
            data=self.pairings.get(code)
            if not data or data['expires_at']<=time.time() or data['token']:
                raise ValueError('연결 코드가 만료되었거나 이미 사용되었습니다. PC에서 다시 실행하세요.')
            data['token']=token

    def poll_pairing(self, code, secret):
        with self.lock:
            data=self.pairings.get(code)
            if not data or data['expires_at']<=time.time() or not secrets.compare_digest(data['digest'], hashlib.sha256(secret.encode()).hexdigest()):
                raise ValueError('연결 요청이 만료되었거나 올바르지 않습니다.')
            if not data['token']:return {'status':'pending'}
            token=data['token'];del self.pairings[code]
            return {'status':'approved','token':token}

    def directory(self, ident):
        if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('잘못된 영상 ID입니다.')
        path=(self.root/ident).resolve()
        if path.parent!=self.root:raise ValueError('잘못된 저장 경로입니다.')
        return path

    def read(self,ident):
        return json.loads((self.directory(ident)/'meta.json').read_text(encoding='utf-8'))

    def owned(self,ident,owner):
        data=self.read(ident)
        if data['owner']!=owner or data['expires_at']<time.time():raise FileNotFoundError(ident)
        return data

    def public(self,data):
        return {k:v for k,v in data.items() if k not in {'owner','lease','lease_until','worker','phase','received','size'}}

    def update(self,ident,**changes):
        data=self.read(ident);data.update(changes);write_json(self.directory(ident)/'meta.json',data);return data

    def cleanup(self):
        now=time.time()
        for p in self.root.glob('*/meta.json'):
            data=self.read(p.parent.name)
            if data['expires_at']<now:
                shutil.rmtree(self.directory(data['id']))
            elif data.get('lease_until',now+1)<now and data['state'] in {'preparing','running'}:
                self.update(data['id'],state='failed',error='분석 처리기 연결이 끊겼습니다. 영상을 새로 올려 다시 시도하세요.',lease=None)

    def list(self,owner):
        with self.lock:
            self.cleanup()
            items=[json.loads(p.read_text(encoding='utf-8')) for p in self.root.glob('*/meta.json')]
            return sorted([self.public(x) for x in items if x['owner']==owner],key=lambda x:x['created_at'],reverse=True)

    def create(self,owner,name,size,sha):
        with self.lock:
            self.cleanup();all_items=list(self.root.glob('*/meta.json'))
            if len(all_items)>=6 or len(self.list(owner))>=3:raise ValueError('테스트 영상은 관리자별 3개, 전체 6개까지 보관합니다. 먼저 삭제하세요.')
            reserved=sum(json.loads(p.read_text(encoding='utf-8'))['size'] for p in all_items)
            if reserved+size>192*1024*1024:raise ValueError('테스트 저장 한도입니다. 먼저 영상을 삭제하세요.')
            ident=uuid4().hex;path=self.directory(ident);path.mkdir()
            data=dict(id=ident,owner=owner,name=name.replace('\\','/').split('/')[-1],size=size,received=0,sha256=sha,
                      created_at=time.time(),expires_at=time.time()+TTL,state='uploading',revealed=False,settings=None,
                      fps=30,duration=0,frames=0,width=0,height=0,error=None,preview=False)
            write_json(path/'meta.json',data);return self.public(data)

    def append(self,ident,owner,offset,body):
        with self.lock:
            data=self.owned(ident,owner)
            if data['state']!='uploading' or offset!=data['received']:raise ValueError('업로드 위치가 일치하지 않습니다.')
            if not body or len(body)>CHUNK or offset+len(body)>data['size']:raise ValueError('파일 크기 제한을 초과했습니다.')
            with (self.directory(ident)/'source.mp4').open('ab') as out:out.write(body)
            self.update(ident,received=offset+len(body))

    def seal(self,ident,owner):
        with self.lock:
            data=self.owned(ident,owner)
            if data['state']!='uploading' or data['received']!=data['size']:raise ValueError('업로드가 완료되지 않았습니다.')
            digest=hashlib.sha256()
            with (self.directory(ident)/'source.mp4').open('rb') as stream:
                for block in iter(lambda:stream.read(CHUNK),b''):digest.update(block)
            if digest.hexdigest()!=data['sha256']:raise ValueError('원본 파일 해시가 다릅니다.')
            return self.public(self.update(ident,state='prepare_queued',phase='prepare'))

    def claim(self,owner,worker):
        with self.lock:
            self.cleanup();self.workers[(owner,worker)]=time.time()
            for data in self.list(owner):
                if data['state'] not in {'prepare_queued','queued'}:continue
                phase='prepare' if data['state']=='prepare_queued' else 'analyze'
                lease=secrets.token_urlsafe(32)
                job=self.update(data['id'],state='preparing' if phase=='prepare' else 'running',phase=phase,
                                worker=worker,lease=lease,lease_until=time.time()+180,started_at=time.time())
                return {'project':self.public(job),'phase':phase,'lease':lease}
            return None

    def leased(self,ident,owner,worker,lease):
        data=self.owned(ident,owner)
        if data['state'] not in {'preparing','running'} or data.get('worker')!=worker or not secrets.compare_digest(data.get('lease') or '',lease or '') or data.get('lease_until',0)<time.time():
            raise ValueError('작업이 취소되었거나 처리 권한이 만료됐습니다.')
        return data

    def heartbeat(self,ident,owner,worker,lease):
        with self.lock:
            self.leased(ident,owner,worker,lease)
            self.workers[(owner,worker)]=time.time();self.update(ident,lease_until=time.time()+180)

    def delete(self,ident,owner):
        with self.lock:
            self.owned(ident,owner)
            # UUID and resolved parent are checked by directory().
            shutil.rmtree(self.directory(ident))
