"""Offline web contracts: synthetic jobs only, no DB/cloud/model downloads."""
from __future__ import annotations

from dataclasses import replace
import json
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from analysis_v2.workbench.app import create_app
from analysis_v2.workbench.service import save_json, review_diagnostics, single_review_comparison, Workbench
from analysis_v2 import MultiSwimmerAnalyzer
from analysis_v2.distance import DistanceSegment
from analysis_v2.pose_cache import serialize_frame, deserialize_detections
from analysis_v2.counting import CounterConfig, _projected_signal, _ankle_difference_signal
from analysis_v2.types import KeypointIndex, TrackObservation
from analysis_v2.adjudication import compare_annotations
from analysis_v2.annotation import build_annotation
from test_multiswimmer_analysis import _synthetic_swimmer


def synthetic_result(settings: dict):
    analyzer = MultiSwimmerAnalyzer(settings["stroke"])
    frames = []
    for index in range(361):
        t = index / 30
        pose = replace(_synthetic_swimmer(.5, .5, t), lane_hint=1, frame_aspect_ratio=1)
        analyzer.process_frame([pose], index, t)
        frames.append(serialize_frame(index, t, [pose]))
    distance = [DistanceSegment("L01", 0, 12, settings["distance_m"])] if settings.get("distance_m") else []
    return analyzer.finalize(distance).to_dict(), {"frames": frames}


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr("analysis_v2.workbench.app.inspect_video", lambda path: dict(fps=30, frames=360, width=640, height=480, duration=12))
    monkeypatch.setattr("analysis_v2.workbench.app.create_preview", lambda path, info: (path.parent / "preview.mp4").write_bytes(path.read_bytes()))
    app = create_app(tmp_path / "private")

    def fake_job(ident):
        directory=app.state.store.directory(ident)
        result, cache=synthetic_result(app.state.store.read(ident)["settings"])
        save_json(directory / "result.json", result)
        save_json(directory / "review.json", review_diagnostics(cache, "freestyle"))

    app.state.store.runner=fake_job
    with TestClient(app) as client:
        token=client.get("/api/session").json()["token"]
        client.headers["X-Review-Token"]=token
        yield client,app.state.store


def upload(client, name="fixture.mp4"):
    response=client.post("/api/videos", params={"filename":name}, content=b"private video fixture", headers={"Content-Type":"application/octet-stream"})
    assert response.status_code==200, response.text
    return response.json()["id"]


def analyze(client, ident):
    response=client.post(f"/api/videos/{ident}/analyze", json={"stroke":"freestyle","start_sec":0,"end_sec":12,"roi":[0,0,1,1],"distance_m":24})
    assert response.status_code==200, response.text
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        state=client.get(f"/api/videos/{ident}").json()["state"]
        if state=="complete": return
        if state=="failed": pytest.fail("synthetic job failed")
        time.sleep(.05)
    pytest.fail("synthetic job timed out")


def label_data(**changes):
    return dict(annotator="QA independent fixture", arm_events=[.5,1.5,2.5], kick_events=[], arm_status="labeled", kick_status="unresolvable", never_seen_predictions=True) | changes


def test_local_headers_and_csrf_reject_foreign_sites(lab):
    client,_=lab
    assert client.get("/").status_code==200
    assert "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]
    assert client.get("/api/videos",headers={"Origin":"https://evil.test"}).status_code==403
    assert client.get("/api/videos",headers={"Host":"evil.test"}).status_code==403
    assert client.get("/api/videos",headers={"Sec-Fetch-Site":"cross-site"}).status_code==403
    assert client.post("/api/videos",content=b"x",headers={"X-Review-Token":"wrong"}).status_code==403


def test_uploaded_filename_never_controls_private_path(lab):
    client,store=lab
    ident=upload(client,"../../secret.mp4")
    assert store.read(ident)["name"]=="secret.mp4"
    assert (store.directory(ident)/"source.mp4").is_file()
    assert client.get("/api/videos/not-an-id").status_code==400
    assert client.get("/api/videos/"+"0"*32).status_code==404


def test_upload_size_and_decode_failure_are_cleaned_up(lab,monkeypatch):
    client,store=lab
    monkeypatch.setattr("analysis_v2.workbench.app.MAX_BYTES",4)
    assert client.post("/api/videos",content=b"12345").status_code==413
    assert list(store.root.iterdir())==[]
    def reject(path): raise ValueError("invalid video")
    monkeypatch.setattr("analysis_v2.workbench.app.inspect_video",reject)
    assert client.post("/api/videos",content=b"123").status_code==400
    assert list(store.root.iterdir())==[]


@pytest.mark.parametrize("header,status,body",[("bytes=0-6",206,b"private"),("bytes=8-",206,b"video fixture"),("bytes=-7",206,b"fixture"),("bytes=999-",416,None),("bytes=4-2",416,None),("bytes=0-1,4-5",416,None)])
def test_video_range_requests_support_seeking(lab,header,status,body):
    client,_=lab;ident=upload(client)
    response=client.get(f"/media/{ident}",headers={"Range":header})
    assert response.status_code==status
    if body is not None: assert response.content==body
    assert "content-range" in response.headers


@pytest.mark.parametrize("changes",[{"end_sec":13},{"start_sec":11,"end_sec":1},{"roi":[0,0,2,1]},{"roi":[.5,.5,.5,.6]},{"stroke":"unknown"},{"distance_m":-1}])
def test_invalid_analysis_settings_rejected(lab,changes):
    client,_=lab;ident=upload(client)
    settings=dict(stroke="freestyle",start_sec=0,end_sec=12,roi=[0,0,1,1])|changes
    assert client.post(f"/api/videos/{ident}/analyze",json=settings).status_code in {400,422}


def test_blind_review_export_reveal_and_assisted_edits(lab):
    client,store=lab;ident=upload(client);analyze(client,ident)
    hidden=client.get(f"/api/videos/{ident}/export").json()
    assert "result" not in hidden and "review" not in hidden
    assert client.get(f"/api/videos/{ident}").json().get("result") is None
    response=client.post(f"/api/videos/{ident}/labels",json=label_data())
    assert response.json()["label_mode"]=="blinded_manual"
    assert response.json()["verified"] is False
    revealed=client.post(f"/api/videos/{ident}/reveal").json()
    assert revealed["comparison"]["kick"]["manual_count"] is None
    assert revealed["comparison"]["arm"]["candidate_count"]==12
    assert revealed["comparison"]["status"]=="single_reviewer_comparison_not_validated_accuracy"
    changed=client.post(f"/api/videos/{ident}/labels",json=label_data(arm_events=[.5])).json()
    assert changed["label_mode"]=="prediction_assisted" and changed["prediction_visible"]
    exported=client.get(f"/api/videos/{ident}/export").json()
    assert exported["blind_label"]["arm_event_times_sec"]==[.5,1.5,2.5]
    assert exported["label"]["arm_event_times_sec"]==[.5]
    assert "overlays" not in exported["review"]
    assert client.post(f"/api/videos/{ident}/analyze",json=store.read(ident)["settings"]).status_code==400


def test_label_without_blind_attestation_is_assisted(lab):
    client,_=lab;ident=upload(client);analyze(client,ident)
    result=client.post(f"/api/videos/{ident}/labels",json=label_data(never_seen_predictions=False)).json()
    assert result["label_mode"]=="prediction_assisted"


def test_label_events_and_unresolvable_state_are_validated(lab):
    client,_=lab;ident=upload(client);analyze(client,ident)
    assert client.post(f"/api/videos/{ident}/labels",json=label_data(arm_events=[12])).status_code==400
    assert client.post(f"/api/videos/{ident}/labels",json=label_data(arm_status="unresolvable")).status_code==400
    assert client.post(f"/api/videos/{ident}/labels",json=label_data(annotator=" ")).status_code==400


def test_delete_only_removes_its_project(lab):
    client,store=lab;first=upload(client);second=upload(client)
    assert client.delete(f"/api/videos/{first}").status_code==200
    assert not store.directory(first).exists() and store.directory(second).exists()


def test_queue_serialization_cancel_and_active_delete_guard(lab):
    client,store=lab;first=upload(client);second=upload(client)
    entered,release=threading.Event(),threading.Event()
    def waiting(ident): entered.set();release.wait(timeout=5)
    store.runner=waiting
    settings=dict(stroke="freestyle",start_sec=0,end_sec=12,roi=[0,0,1,1])
    try:
        assert client.post(f"/api/videos/{first}/analyze",json=settings).status_code==200
        assert entered.wait(2)
        assert client.post(f"/api/videos/{second}/analyze",json=settings).status_code==200
        assert client.get(f"/api/videos/{second}").json()["state"]=="queued"
        assert client.delete(f"/api/videos/{first}").status_code==400
        assert client.post(f"/api/videos/{second}/cancel").status_code==200
        assert client.delete(f"/api/videos/{second}").status_code==200
    finally: release.set()


def test_single_review_withheld_candidates_are_not_complete_counts():
    settings=dict(stroke="freestyle",distance_m=25)
    result,_=synthetic_result(settings)
    result["tracks"][0]["arm_strokes"].update(available=False,reason="arm_signal_gaps",count=0,event_times_sec=[])
    label=build_annotation("hash","freestyle",1,0,12,[.5],[],"test",video_sha256="a"*64,kick_label_status="unresolvable")
    comparison=single_review_comparison(label,result,25)
    assert comparison["arm"]["model_count"] is None and comparison["arm"]["candidate_count"]==12
    assert comparison["manual_dps"]==25 and comparison["kick"]["manual_count"] is None


def test_review_diagnostics_locate_gaps_without_filling_them():
    frames=[]
    for index in range(150):
        t=index/30;pose=replace(_synthetic_swimmer(.5,.5,t),lane_hint=1)
        if 2<t<3: pose.keypoints[[15,16],3]=0
        frames.append(serialize_frame(index,t,[pose]))
    result=review_diagnostics({"frames":frames},"freestyle")
    gaps=[row for row in result["windows"] if row["reason"]=="arm_evidence_gap"]
    assert gaps and gaps[0]["start_sec"]==2 and gaps[0]["end_sec"]==3
    assert result["status"]=="review_hints_not_ground_truth"


@pytest.mark.parametrize("aspect",[9/16,16/9,1])
def test_body_signals_are_invariant_to_image_aspect_and_body_rotation(aspect):
    originals=[];transformed=[]
    angle=.6;rotation=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    for index in range(90):
        t=index/30;pose=_synthetic_swimmer(.5,.5,t)
        points=pose.keypoints.copy();points[:,:2]=(points[:,:2]-.5)@rotation.T+.5
        original=replace(pose,keypoints=points,frame_aspect_ratio=1)
        scaled=points.copy();scaled[:,0]/=aspect
        changed=replace(pose,keypoints=scaled,frame_aspect_ratio=aspect)
        originals.append(TrackObservation("S001",1,index,t,original))
        transformed.append(TrackObservation("S001",1,index,t,changed))
    cfg=CounterConfig()
    a,_=_projected_signal(originals,KeypointIndex.LEFT_WRIST,"longitudinal",cfg)
    b,_=_projected_signal(transformed,KeypointIndex.LEFT_WRIST,"longitudinal",cfg)
    assert np.allclose(a,b)
    assert np.allclose(_ankle_difference_signal(originals,cfg)[0],_ankle_difference_signal(transformed,cfg)[0])
    cached=serialize_frame(0,0,[transformed[0].detection])
    assert deserialize_detections(cached)[0].frame_aspect_ratio==aspect


@pytest.mark.parametrize("value",[0,-1,float("nan"),float("inf")])
def test_invalid_pose_geometry_is_rejected(value):
    with pytest.raises(ValueError): replace(_synthetic_swimmer(.5,.5,0),frame_aspect_ratio=value)


@pytest.mark.parametrize("changes",[{"arm_event_times_sec":[float("nan")]},{"interval_sec":[0,float("inf")]},{"arm_event_times_sec":[1,1]},{"lane_id":True}])
def test_imported_independent_labels_cannot_forge_invalid_agreement(changes):
    first=build_annotation("hash","freestyle",1,0,12,[1],[],"first",video_sha256="a"*64)
    second=dict(first,annotator="second")
    with pytest.raises(ValueError): compare_annotations(first|changes,second)


def test_different_swimmer_regions_cannot_be_independent_consensus():
    first=build_annotation("hash","freestyle",1,0,12,[1],[],"first",video_sha256="a"*64)
    first["review_context"]={"roi":[0,0,.5,1],"timeline":"source_frame_index_divided_by_fps"}
    second=dict(first,annotator="second",review_context={"roi":[.5,0,1,1],"timeline":"source_frame_index_divided_by_fps"})
    with pytest.raises(ValueError,match="ROI"): compare_annotations(first,second)


def test_blind_corrections_are_retained_until_result_exposure(lab):
    client,_=lab;ident=upload(client);analyze(client,ident)
    client.post(f"/api/videos/{ident}/labels",json=label_data())
    client.post(f"/api/videos/{ident}/labels",json=label_data(arm_events=[1,2]))
    exported=client.get(f"/api/videos/{ident}/export").json()
    assert exported["blind_label"]["arm_event_times_sec"]==[1,2]
    assert exported["label"]["review_context"]["roi"]==[0,0,1,1]


def test_preview_failure_removes_partial_upload(lab,monkeypatch):
    client,store=lab
    def fail(path,info): raise ValueError("preview failure")
    monkeypatch.setattr("analysis_v2.workbench.app.create_preview",fail)
    response=client.post("/api/videos",content=b"fixture")
    assert response.status_code==400 and list(store.root.iterdir())==[]


def test_preview_command_preserves_original_and_frame_clock(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace
    from analysis_v2.workbench.service import create_preview
    source=tmp_path/"source.mp4";source.write_bytes(b"original")
    info=dict(fps=30,frames=360,width=1080,height=1920,duration=12)
    captured=[]
    def run(command,**kwargs): captured.append((command,kwargs))
    monkeypatch.setitem(sys.modules,"imageio_ffmpeg",SimpleNamespace(get_ffmpeg_exe=lambda:"local-ffmpeg"))
    monkeypatch.setattr("analysis_v2.workbench.service.subprocess.run",run)
    monkeypatch.setattr("analysis_v2.workbench.service.inspect_video",lambda path:info)
    create_preview(source,info)
    command,options=captured[0]
    assert "libx264" in command and "-an" in command and "file,pipe" in command
    assert "setpts=N/(30*TB)" in command[command.index("-vf")+1]
    assert command[-1]==str(tmp_path/"preview.mp4") and options["timeout"]==300
    assert source.read_bytes()==b"original"
