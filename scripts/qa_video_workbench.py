"""Opt-in real-video UI QA for the loopback lab; never human event ground truth.

Requires a running workbench and Playwright Chromium. Only the project uploaded
by this run is deleted afterward. No production URL, credentials or DB access.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video",type=Path,required=True)
    parser.add_argument("--start-sec",type=float,default=0)
    parser.add_argument("--end-sec",type=float,required=True)
    parser.add_argument("--distance-m",type=float)
    parser.add_argument("--base-url",default="http://127.0.0.1:8765")
    parser.add_argument("--timeout-sec",type=int,default=900)
    parser.add_argument("--output-dir",type=Path,default=Path("tmp/analysis_v2/workbench-browser"))
    args=parser.parse_args()
    url=urlsplit(args.base_url)
    if url.scheme!="http" or url.hostname not in {"127.0.0.1","localhost"} or url.path not in {"","/"}:
        parser.error("QA may target only the local workbench")
    if not args.video.is_file() or not 0<=args.start_sec<args.end_sec or args.end_sec-args.start_sec>60:
        parser.error("supply a local video and a valid interval of at most 60 seconds")
    args.output_dir.mkdir(parents=True,exist_ok=True)
    errors=[];report={"status":"running","not_ground_truth":True};ident=None
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(base_url=args.base_url,viewport={"width":1440,"height":1000})
        page=context.new_page()
        page.on("pageerror",lambda error:errors.append(str(error)))
        token=context.request.get("/api/session").json()["token"]
        headers={"X-Review-Token":token}
        try:
            page.goto("/")
            page.screenshot(path=str(args.output_dir/"upload-desktop.png"),full_page=True)
            with page.expect_response(lambda response: response.request.method=="POST" and "/api/videos?" in response.url,timeout=360000) as upload:
                page.locator("#file").set_input_files(str(args.video.resolve()))
            assert upload.value.ok,upload.value.text()
            page.locator("#workspace").wait_for(state="visible",timeout=360000)
            ident=page.locator("#video").get_attribute("src").split("/")[-1]
            video=page.locator("#video")
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                if video.evaluate("v=>v.readyState>=2 && v.videoWidth>0"):break
                time.sleep(.1)
            assert video.evaluate("v=>v.videoWidth>0 && v.videoHeight>0"),"Video must contain visible pixels, not audio only"
            page.locator("#start").fill(str(args.start_sec));page.locator("#end").fill(str(args.end_sec))
            if args.distance_m:page.locator("#distance").fill(str(args.distance_m))
            # Verify ROI selection before settings lock; reset to preserve test condition.
            page.locator("#roiButton").click()
            box=page.locator("#overlay").bounding_box()
            page.mouse.move(box["x"]+box["width"]*.4,box["y"]+box["height"]*.2)
            page.mouse.down();page.mouse.move(box["x"]+box["width"]*.6,box["y"]+box["height"]*.8);page.mouse.up()
            expect(page.locator("#roiLabel")).to_contain_text("선택 영역")
            page.locator("#resetRoi").click()
            page.locator("#analyzeButton").click()
            expect(page.locator("#armButton")).to_be_enabled()
            page.locator("#annotator").fill("QA UI smoke - NOT an event reference")
            page.locator("#armButton").click()
            expect(page.locator("#armCount")).to_have_text("1")
            page.locator("#undoButton").click()
            # Shortcuts must still work when a button retains keyboard focus.
            page.keyboard.press("a");expect(page.locator("#armCount")).to_have_text("1")
            page.locator("#undoButton").click()
            page.keyboard.press("k");expect(page.locator("#kickCount")).to_have_text("1")
            page.locator("#undoButton").click()
            page.set_viewport_size({"width":390,"height":950})
            page.locator("#mobileArm").click();expect(page.locator("#mobileArmCount")).to_have_text("1")
            page.locator("#mobileUndo").click();expect(page.locator("#armCount")).to_have_text("0")
            page.set_viewport_size({"width":1440,"height":1000})
            page.locator("#armUnresolvable").check();page.locator("#kickUnresolvable").check()
            page.locator("#saveLabel").click()
            expect(page.locator("#saveStatus")).to_contain_text("저장 완료")
            hidden=context.request.get(f"/api/videos/{ident}/export").json()
            assert "result" not in hidden and hidden["blind_label"] is None
            page.locator("#nextFrame").click()
            # Confirm decoded frame content instead of counting an audio-only player as success.
            deadline=time.monotonic()+10
            while time.monotonic()<deadline and video.evaluate("v=>v.seeking"):time.sleep(.1)
            pixels=video.evaluate("""v=>{const c=document.createElement('canvas');c.width=64;c.height=64;
                const x=c.getContext('2d');x.drawImage(v,0,0,64,64);const a=x.getImageData(0,0,64,64).data;
                return Math.max(...a.filter((_,i)=>i%4!==3))-Math.min(...a.filter((_,i)=>i%4!==3));}""")
            assert pixels>10,"Decoded review frame must not be blank"
            page.screenshot(path=str(args.output_dir/"manual-desktop.png"),full_page=True)
            checks=[]
            for width in (1920,1440,1024,768,390,320):
                page.set_viewport_size({"width":width,"height":950})
                layout=page.evaluate("({width:innerWidth,scroll:document.documentElement.scrollWidth})")
                assert layout["scroll"]<=width,layout
                checks.append(layout)
                if width==390:page.screenshot(path=str(args.output_dir/"manual-mobile.png"),full_page=True)
            page.set_viewport_size({"width":1440,"height":1000})
            expect(page.locator("#revealButton")).to_be_enabled(timeout=args.timeout_sec*1000)
            page.on("dialog",lambda dialog:dialog.accept())
            page.locator("#revealButton").click();page.locator("#results").wait_for(state="visible")
            expect(page.locator("#labelMode")).to_contain_text("보정용")
            page.locator("#poseToggle").check()
            page.locator("#candidates button").first.click()
            page.screenshot(path=str(args.output_dir/"comparison-desktop.png"),full_page=True)
            for width in (1440,768,390,320):
                page.set_viewport_size({"width":width,"height":950})
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                if width==390:page.screenshot(path=str(args.output_dir/"comparison-mobile.png"),full_page=True)
            with page.expect_download() as download:page.locator("#exportButton").click()
            download.value.save_as(str(args.output_dir/"qa-export.json"))
            exported=json.loads((args.output_dir/"qa-export.json").read_text(encoding="utf-8"))
            assert exported["label"]["verified"] is False and exported["comparison"]["arm"]["manual_count"] is None
            report.update(status="passed",layouts=checks,decoded_pixel_range=pixels,page_errors=errors,
                          comparison=page.locator("#resultCards").inner_text())
            assert not errors,errors
        finally:
            if ident:
                context.request.post(f"/api/videos/{ident}/cancel",headers=headers)
                for _ in range(50):
                    deleted=context.request.delete(f"/api/videos/{ident}",headers=headers)
                    if deleted.status in {200,404}:break
                    time.sleep(.2)
                report["cleanup_status"]=deleted.status
            if report["status"]=="running":report["status"]="failed"
            (args.output_dir/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
            print(json.dumps(report,ensure_ascii=False,indent=2))
            browser.close()


if __name__=="__main__":main()
