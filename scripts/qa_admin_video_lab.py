"""Opt-in real-video QA of deployed /admin TEST. Never an accuracy benchmark.

Needs an independently running remote_worker, ADMIN_ID/PW and an explicitly
supplied video. Uploads only that video, deletes only its own project afterward.
No production images or credentials are embedded in CI or repository assets.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
PREFIX = '/api/admin/video-lab'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--start-sec', type=float, default=0)
    parser.add_argument('--end-sec', type=float, required=True)
    parser.add_argument('--distance-m', type=float)
    parser.add_argument('--timeout-sec', type=int, default=900)
    parser.add_argument('--offline-check', action='store_true', help='Without a processor: native H.264 playback, blocked analysis, offline guidance, and administrator device approval')
    parser.add_argument('--expect-unsupported-native', action='store_true', help='Offline HEVC test: verify explicit conversion guidance instead of native playback')
    parser.add_argument('--base-url', default='https://swimtech.vercel.app', help='Production origin or a loopback-only integration harness')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'tmp/analysis_v2/admin-browser')
    args = parser.parse_args()
    url = urlsplit(args.base_url)
    if args.base_url != 'https://swimtech.vercel.app' and not (url.scheme == 'http' and url.hostname in {'127.0.0.1','localhost'} and url.path in {'','/'} and not url.username and not url.query and not url.fragment):
        parser.error('Only SwimMate production or loopback QA is allowed')
    if not args.video.is_file() or not 0 <= args.start_sec < args.end_sec <= 60:
        parser.error('Explicit local video and interval within 60 seconds required')
    load_dotenv(ROOT/'.env')
    if not os.getenv('ADMIN_ID') or not os.getenv('ADMIN_PW'):
        parser.error('Set ADMIN_ID / ADMIN_PW locally; never pass credentials on the command line')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {'status':'running', 'not_ground_truth':True, 'base_url':args.base_url+'/admin'}
    ident = None
    errors = []
    resource_errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(base_url=args.base_url, viewport={'width':1440, 'height':1000})
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('response', lambda r: resource_errors.append({'url':r.url.split('?')[0], 'status':r.status}) if r.status >= 400 else None)
        page.on('dialog', lambda dialog: dialog.accept())
        headers = {'X-Video-Lab':'1'}
        try:
            # Check anonymous rejection in an isolated context, not existing user state.
            assert context.request.get(PREFIX+'/session', timeout=90000).status == 401
            login = context.request.post('/auth/login', data={'username':os.environ['ADMIN_ID'], 'password':os.environ['ADMIN_PW']}, timeout=90000)
            assert login.status == 200, f'Administrator login failed (HTTP {login.status}); credentials not logged'
            status = context.request.get(PREFIX+'/session', timeout=90000)
            assert status.ok and status.json()['worker_online'] == (not args.offline_check), 'Processor state does not match requested QA mode'
            page.goto('/admin', wait_until='domcontentloaded', timeout=90000)
            page.locator('#admin-tab-video-lab').click()
            frame = page.frame_locator('#admin-video-lab')
            expect(frame.locator('#file')).to_be_enabled(timeout=90000)
            expect(frame.locator('#workerStatus')).to_contain_text('연결 대기' if args.offline_check else '연결됨')
            page.screenshot(path=str(args.output_dir/'entry-desktop.png'), full_page=True)
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith(PREFIX+'/videos'), timeout=180000) as created:
                frame.locator('#file').set_input_files(str(args.video.resolve()))
            assert created.value.ok, 'Create upload failed'
            ident = created.value.json()['id']
            if args.offline_check:
                expect(frame.locator('#workspace')).to_be_visible(timeout=90000)
                expect(frame.locator('#analyzeButton')).to_be_disabled()
                expect(frame.locator('#connectionTitle')).to_have_text('분석 PC가 연결되어 있지 않습니다')
                expect(frame.locator('#projects')).not_to_contain_text('0.0초')
                video = frame.locator('#video')
                if args.expect_unsupported_native:
                    expect(frame.locator('#mediaPending')).to_contain_text('원본 코덱을 재생할 수 없습니다',timeout=20000)
                    expect(frame.locator('#backFrame')).to_be_disabled()
                else:
                    expect(frame.locator('#mediaPending')).to_be_hidden(timeout=45000)
                    assert video.evaluate('v=>v.videoWidth>0&&v.readyState>=2'), 'Native source video must be playable without a processor'
                    frame.locator('#playButton').click()
                    page.wait_for_timeout(1000)
                    assert video.evaluate('v=>v.currentTime>0')
                    frame.locator('#playButton').click()
                frame.locator('#connectionHelp summary').click()
                checks=[]
                for width in [1920,1440,1024,768,390,320]:
                    page.set_viewport_size({'width':width,'height':950})
                    page.wait_for_timeout(200)
                    assert frame.locator('body').evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
                    checks.append(width)
                    if width in {1440,390}:page.screenshot(path=str(args.output_dir/f'offline-{width}.png'), full_page=True)
                # Reload must play the sealed server source, not a lost blob URL.
                page.reload(wait_until='domcontentloaded')
                page.locator('#admin-tab-video-lab').click()
                frame=page.frame_locator('#admin-video-lab')
                frame.locator('#projects button').filter(has_text=args.video.name).first.click()
                if args.expect_unsupported_native:
                    expect(frame.locator('#mediaPending')).to_contain_text('원본 코덱을 재생할 수 없습니다',timeout=20000)
                else:
                    expect(frame.locator('#mediaPending')).to_be_hidden(timeout=45000)
                    assert frame.locator('#video').evaluate('v=>v.videoWidth>0')
                # Browser approval is explicit, and never exposes the worker token in the DOM.
                pair=context.request.post(PREFIX+'/worker/pair').json()
                page.goto('/admin_video_lab?connect='+pair['code'],wait_until='domcontentloaded')
                expect(page.locator('#pairCode')).to_have_text(pair['code'])
                expect(page.locator('#approvePair')).to_be_enabled(timeout=30000)
                assert context.request.post(PREFIX+'/worker/pair/poll',data={'code':pair['code'],'secret':pair['secret']}).json()['status']=='pending'
                page.locator('#approvePair').click()
                expect(page.locator('#pairStatus')).to_contain_text('승인했습니다')
                approved=context.request.post(PREFIX+'/worker/pair/poll',data={'code':pair['code'],'secret':pair['secret']}).json()
                assert approved['status']=='approved' and approved['token'] not in page.locator('body').inner_text()
                assert not errors and not resource_errors, (errors,resource_errors)
                report.update(status='passed', mode='offline_source_and_device_approval', native_playback=not args.expect_unsupported_native,
                              unsupported_codec_guidance=args.expect_unsupported_native, reload_verified=True,
                              explicit_approval=True, layouts=checks, page_errors=errors, resource_errors=resource_errors)
                return
            expect(frame.locator('#analyzeButton')).to_be_enabled(timeout=360000)
            video = frame.locator('#video')
            deadline = time.monotonic()+45
            while time.monotonic() < deadline:
                if video.evaluate('v=>v.readyState>=2&&v.videoWidth>0'): break
                page.wait_for_timeout(200)
            assert video.evaluate('v=>v.videoWidth>0&&v.videoHeight>0'), 'Preview must have decoded video pixels'
            frame.locator('#start').fill(str(args.start_sec))
            frame.locator('#end').fill(str(args.end_sec))
            if args.distance_m: frame.locator('#distance').fill(str(args.distance_m))
            frame.locator('#roiButton').click()
            canvas = frame.locator('#overlay')
            canvas.scroll_into_view_if_needed()
            box = canvas.bounding_box()
            page.mouse.move(box['x']+box['width']*.4, box['y']+box['height']*.2)
            page.mouse.down()
            page.mouse.move(box['x']+box['width']*.6, box['y']+box['height']*.8)
            page.mouse.up()
            expect(frame.locator('#roiLabel')).to_contain_text('선택 영역')
            frame.locator('#resetRoi').click()
            frame.locator('#analyzeButton').click()
            expect(frame.locator('#armButton')).to_be_enabled(timeout=30000)
            frame.locator('#annotator').fill('QA UI smoke - NOT an event reference')
            frame.locator('#armButton').click()
            expect(frame.locator('#armCount')).to_have_text('1')
            frame.locator('#undoButton').click()
            page.keyboard.press('k')
            expect(frame.locator('#kickCount')).to_have_text('1')
            frame.locator('#undoButton').click()
            frame.locator('#armUnresolvable').check()
            frame.locator('#kickUnresolvable').check()
            frame.locator('#saveLabel').click()
            expect(frame.locator('#saveStatus')).to_contain_text('저장 완료', timeout=30000)
            hidden = context.request.get(PREFIX+f'/videos/{ident}/export').json()
            assert 'result' not in hidden and hidden['blind_label'] is None
            frame.locator('#nextFrame').click()
            page.wait_for_timeout(500)
            pixels = video.evaluate('''v=>{const c=document.createElement('canvas');c.width=64;c.height=64;
              const x=c.getContext('2d');x.drawImage(v,0,0,64,64);const a=x.getImageData(0,0,64,64).data;
              const rgb=Array.from(a).filter((_,i)=>i%4!==3);return Math.max(...rgb)-Math.min(...rgb);}''')
            assert pixels > 10, 'Video is blank'
            checks = []
            for width in [1920,1440,1024,768,390,320]:
                page.set_viewport_size({'width':width, 'height':950})
                page.wait_for_timeout(300)
                body = frame.locator('body')
                layout = body.evaluate('b=>({width:innerWidth,scroll:document.documentElement.scrollWidth})')
                assert layout['scroll'] <= layout['width']+1, layout
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                checks.append({'viewport':width, **layout})
                if width in {1440,390}: page.screenshot(path=str(args.output_dir/f'manual-{width}.png'), full_page=True)
            page.set_viewport_size({'width':1440, 'height':1000})
            expect(frame.locator('#revealButton')).to_be_enabled(timeout=args.timeout_sec*1000)
            frame.locator('#revealButton').click()
            frame.locator('#results').wait_for(state='visible', timeout=30000)
            expect(frame.locator('#labelMode')).to_contain_text('보정용')
            frame.locator('#poseToggle').check()
            if frame.locator('#candidates button').count(): frame.locator('#candidates button').first.click()
            for width in [1440,390,320]:
                page.set_viewport_size({'width':width, 'height':950})
                page.wait_for_timeout(250)
                assert frame.locator('body').evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
                if width != 320: page.screenshot(path=str(args.output_dir/f'comparison-{width}.png'), full_page=True)
            with page.expect_download() as download: frame.locator('#exportButton').click()
            download.value.save_as(str(args.output_dir/'qa-export.json'))
            exported = json.loads((args.output_dir/'qa-export.json').read_text(encoding='utf-8'))
            assert exported['label']['verified'] is False
            assert exported['comparison']['arm']['manual_count'] is None
            assert not errors and not resource_errors, (errors,resource_errors)
            report.update(status='passed', layouts=checks, decoded_pixel_range=pixels, page_errors=errors,
                          comparison=frame.locator('#resultCards').inner_text(), resource_errors=resource_errors)
        finally:
            if ident:
                response = context.request.delete(PREFIX+f'/videos/{ident}', headers=headers, timeout=60000)
                report['own_project_deleted'] = response.status in {200,404}
                if not report['own_project_deleted']: report['status'] = 'cleanup_failed'
            if report['status'] == 'running': report['status'] = 'failed'
            (args.output_dir/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            context.close()
            browser.close()
            if args.offline_check:
                print(json.dumps(report, ensure_ascii=False, indent=2))
                assert report['status'] != 'cleanup_failed'
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert report['status'] == 'passed' and report['own_project_deleted']


if __name__ == '__main__':
    main()
