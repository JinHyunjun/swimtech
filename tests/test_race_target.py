"""Selected-athlete identity regressions, not measured real-race accuracy."""
from dataclasses import replace
import numpy as np
import pytest

from analysis_v2.target import TargetAssociator, CameraMotion, SelectedSwimmerProvider, apply_target_safety
from analysis_v2.pipeline import MultiSwimmerAnalyzer
from test_multiswimmer_analysis import _synthetic_swimmer


IDENTITY=np.array([[1,0,0],[0,1,0]],dtype=float)


def pose(x=.5,y=.5,t=0):
    return replace(_synthetic_swimmer(x,y,t),frame_aspect_ratio=1.)


def target(checkpoints=None):
    return TargetAssociator(7,checkpoints or [dict(time_sec=0,x=.47,y=.5)])


@pytest.mark.parametrize('lane',[0,7,10])
def test_selects_confirmed_person_not_highest_confidence_or_screen_order(lane):
    tracker=target()
    tracker.lane_id=lane
    other=replace(pose(.5,.7),confidence=1.)
    selected=replace(pose(),confidence=.6)
    assert tracker.select([other,selected],0,None)[0].centroid==pytest.approx(selected.centroid)
    assert tracker.select([selected,other],1/30,IDENTITY)[0].lane_hint==lane
    analyzer=MultiSwimmerAnalyzer('freestyle')
    analyzer.process_frame([replace(selected,lane_hint=lane)],0,0)
    assert analyzer.tracker.all_tracks()[0][0].lane_id==lane


def test_camera_pan_and_zoom_keep_lane_identity():
    tracker=target()
    tracker.select([pose()],0,None)
    shift=np.array([[1.1,0,.1],[0,1.1,.06]])
    p=pose();points=p.keypoints.copy();points[:,:2]=np.c_[points[:,:2],np.ones(33)]@shift.T
    moved=replace(p,keypoints=points)
    result=tracker.select([pose(.47,.5),moved],1/30,shift)
    assert len(result)==1 and result[0].centroid==pytest.approx(moved.centroid)
    assert tracker.summary()['status']=='tracked'


def test_overlap_latches_review_and_never_switches_to_remaining_person():
    tracker=target([dict(time_sec=0,x=.47,y=.5),dict(time_sec=1,x=.57,y=.5)])
    assert tracker.select([pose()],0,None)
    assert tracker.select([pose(.49),pose(.51)],.03,IDENTITY)==[]
    assert tracker.frames[-1]['status']=='target_ambiguous'
    assert tracker.select([pose(.51)],.06,IDENTITY)==[]
    assert tracker.select([pose(.6)],1,None)[0].lane_hint==7  # explicit checkpoint after cut
    assert tracker.summary()['status']=='needs_review'


def test_long_occlusion_or_camera_cut_cannot_reidentify_automatically():
    for cut in (True,False):
        tracker=target();tracker.select([pose()],0,None)
        assert tracker.select([],.3,None if cut else IDENTITY)==[]
        assert tracker.select([pose()],.33,IDENTITY)==[]
        assert tracker.summary()['status']=='needs_review'


def test_initial_ambiguity_and_missed_click_do_not_choose_somebody():
    tracker=target()
    assert tracker.select([pose(.49),pose(.51)],0,None)==[]
    assert tracker.select([pose()],.03,IDENTITY)==[]
    tracker=target()
    assert tracker.select([pose(.8)],0,None)==[]
    assert tracker.select([pose()],.03,IDENTITY)==[]


def test_different_appearance_is_not_accepted_as_same_person():
    tracker=target()
    tracker.select([pose()],0,None,[np.array([1.,0.])])
    assert tracker.select([pose()],.03,IDENTITY,[np.array([0.,1.])])==[]


def test_counter_receives_only_selected_person_and_gap_withholds_totals():
    tracker=target();analyzer=MultiSwimmerAnalyzer('freestyle',stroke_source='user_confirmed')
    for i in range(361):
        t=i/30
        selected=tracker.select([pose(.5,.75,t),pose(.5,.5,t)],t,IDENTITY)
        analyzer.process_frame(selected,i,t)
    result=analyzer.finalize().to_dict();apply_target_safety(result,tracker.summary())
    assert len(result['tracks'])==1 and result['tracks'][0]['lane_id']==7
    assert result['tracks'][0]['arm_strokes']['available']
    expected=result['tracks'][0]['arm_strokes']['count']
    assert expected>0 and result['target_tracking']['coverage']==1
    apply_target_safety(result,{'status':'needs_review','windows':[dict(start_sec=2,end_sec=4)]})
    assert result['tracks'][0]['arm_strokes']['count'] is None
    assert not result['tracks'][0]['kicks']['available']
    assert all(not 1.75<=t<=4.25 for t in result['tracks'][0]['diagnostics']['merged_arm_candidate_times_sec'])


def test_background_optical_flow_handles_pan_and_rejects_unrelated_frame():
    cv2=pytest.importorskip('cv2')
    rng=np.random.default_rng(17)
    gray=rng.integers(0,256,(360,640),dtype=np.uint8)
    rgb=cv2.cvtColor(gray,cv2.COLOR_GRAY2RGB)
    camera=CameraMotion()
    assert camera.update(rgb,[]) is None
    moved=cv2.warpAffine(rgb,np.float32([[1,0,12],[0,1,5]]),(640,360))
    matrix=camera.update(moved,[])
    assert matrix is not None
    assert matrix[:,2]==pytest.approx([12/640,5/360],abs=.003)
    assert camera.update(rng.integers(0,256,(360,640,3),dtype=np.uint8),[]) is None


def test_selected_provider_moves_search_instead_of_reusing_fixed_roi():
    cv2=pytest.importorskip('cv2')
    origins=[]
    class Detector:
        def detect(self,frame,ms):
            assert frame.shape[0]<300 and frame.shape[1]<600
            origins.append(int(frame[0,0,0]))
            return [pose(.53),pose(.5,.8)]
        def close(self): pass
    provider=SelectedSwimmerProvider(Detector(),{'lane_id':7,'checkpoints':[dict(time_sec=0,x=.47,y=.5)]},'none')
    frame=np.zeros((300,600,3),np.uint8)
    frame[:,:,0]=(np.arange(600)/3).astype(np.uint8)
    result=provider.detect(frame,0)
    assert len(result)==1 and result[0].lane_hint==7
    class Camera:
        def update(self,*args): return np.array([[1,0,.2],[0,1,0.]])
        def set_mask(self,*args): pass
    provider.camera=Camera()
    provider.detect(frame,33)
    assert origins[1]-origins[0]>30
