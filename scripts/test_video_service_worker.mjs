import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const source=readFileSync(new URL('../frontend/sw.js',import.meta.url),'utf8');
function worker({status=200,headers={},offline=false,quota=false}={}) {
  const handlers={},puts=[],deleted=[];
  const cache={addAll:async()=>{},put:async(req,res)=>{if(quota)throw Error('quota');puts.push([req.url,res.status]);}};
  runInNewContext(source,{URL,Response,
    self:{location:{origin:'https://swim.test'},addEventListener:(k,v)=>handlers[k]=v,skipWaiting:()=>{},clients:{claim:async()=>{}}},
    caches:{open:async()=>cache,match:async()=>undefined,keys:async()=>['swimmate-v2','swimmate-public-v3','unrelated-app'],delete:async k=>deleted.push(k)},
    fetch:async()=>{if(offline)throw Error('offline');return new Response('media',{status,headers});}});
  async function request(path,extra={}) {
    const pending=[];let response;
    handlers.fetch({request:new Request('https://swim.test'+path,extra),waitUntil:p=>pending.push(p),respondWith:p=>response=p});
    const result=await response;await Promise.all(pending);return result;
  }
  return {handlers,puts,deleted,request};
}
test('never intercept private video, API, admin, range, or cross-origin requests',async()=>{
  const w=worker({status:206});
  for(const url of ['/api/admin/video-lab/media/abc','/api/admin/video-lab/videos','/admin','/admin_video_lab'])assert.equal(await w.request(url),undefined);
  assert.equal(await w.request('/static/style.css',{headers:{Range:'bytes=0-9'}}),undefined);
  assert.equal(w.puts.length,0);
});
test('only successful public responses enter CacheStorage',async()=>{
  const ok=worker();assert.equal((await ok.request('/static/style.css')).status,200);assert.equal(ok.puts.length,1);
  for(const settings of [{status:206},{status:401},{status:500},{headers:{'Cache-Control':'private, no-store'}},{quota:true}]){
    const w=worker(settings);assert.ok(await w.request('/static/style.css'));assert.equal(w.puts.length,0);
  }
});
test('offline miss returns a response and activation removes old private caches',async()=>{
  const w=worker({offline:true});assert.equal((await w.request('/landing')).type,'error');
  let done;w.handlers.activate({waitUntil:p=>done=p});await done;
  assert.deepEqual(w.deleted,['swimmate-v2']);
});
