"""User-confirmed race target, independent of a fixed screen rectangle.

Lane numbers are user-provided identities, never inferred from screen order.
Ambiguous association/camera discontinuities latch a review requirement until
an explicit user checkpoint. No automatic switch to another visible person.
"""
from dataclasses import replace

import numpy as np

from .lanes import _remap_crop_detection


class CameraMotion:
    """Small-frame, background LK + RANSAC similarity transform (including zoom)."""
    def __init__(self):
        self.previous = None
        self.mask = None

    def update(self, rgb, detections):
        import cv2
        height, width = rgb.shape[:2]
        size = (640, max(32, round(height * 640 / width)))
        gray = cv2.resize(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), size)
        affine = None
        if self.previous is not None:
            points = cv2.goodFeaturesToTrack(self.previous, 250, .015, 8, mask=self.mask)
            if points is not None and len(points) >= 12:
                moved, status, _ = cv2.calcOpticalFlowPyrLK(self.previous, gray, points, None)
                if moved is not None:
                    back, backward, _ = cv2.calcOpticalFlowPyrLK(gray, self.previous, moved, None)
                    if back is not None:
                        valid = (status.ravel() == 1) & (backward.ravel() == 1)
                        valid &= np.linalg.norm(back[:, 0] - points[:, 0], axis=1) < 1.5
                        if valid.sum() >= 12:
                            matrix, inliers = cv2.estimateAffinePartial2D(
                                points[valid], moved[valid], method=cv2.RANSAC, ransacReprojThreshold=2)
                            if matrix is not None and inliers is not None and inliers.mean() >= .65:
                                scale = np.linalg.norm(matrix[:, 0])
                                # Reject cuts, extreme zooms, and local-only feature clusters.
                                spread = np.ptp(points[valid, 0][inliers.ravel() == 1], axis=0) / size
                                if .8 < scale < 1.25 and np.all(spread > .15):
                                    units = np.diag([size[0], size[1], 1.])
                                    affine = (np.linalg.inv(units) @ np.vstack([matrix, [0, 0, 1]]) @ units)[:2]
        self.previous = gray
        self.set_mask(detections)
        return affine

    def set_mask(self, detections):
        import cv2
        gray = self.previous
        size = (gray.shape[1], gray.shape[0])
        self.mask = np.full(gray.shape, 255, np.uint8)
        for pose in detections:
            x1, y1, x2, y2 = pose.bbox
            cv2.rectangle(self.mask, (int((x1-.02)*size[0]), int((y1-.02)*size[1])),
                          (int((x2+.02)*size[0]), int((y2+.02)*size[1])), 0, -1)


def torso_scale(pose):
    points = pose.metric_keypoints
    return max(.025, float(np.linalg.norm(points[[11,12], :2].mean(axis=0) - points[[23,24], :2].mean(axis=0))))


def appearance(rgb, pose):
    """Weak local colour evidence; never sufficient by itself to re-identify."""
    import cv2
    h, w = rgb.shape[:2]
    points = pose.keypoints[[0,11,12,23,24]]
    visible = points[points[:,3] >= .25, :2]
    if not len(visible): return None
    x1, y1 = np.maximum(0, (visible.min(axis=0)-.008)*[w,h]).astype(int)
    x2, y2 = np.minimum([w,h], (visible.max(axis=0)+.008)*[w,h]).astype(int)
    if x2 <= x1 or y2 <= y1: return None
    hsv = cv2.cvtColor(rgb[y1:y2,x1:x2], cv2.COLOR_RGB2HSV)
    hist = cv2.calcHist([hsv], [0,1], None, [12,8], [0,180,0,256]).ravel()
    return hist / max(1, hist.sum())


class TargetAssociator:
    def __init__(self, lane_id, checkpoints):
        self.lane_id, self.checkpoints = lane_id, checkpoints
        self.next_checkpoint = 0
        self.last = None
        self.position = None
        self.velocity = np.zeros(2)
        self.last_time = None
        self.last_hit = None
        self.identity = None
        self.blocked = True
        self.frames = []

    def select(self, detections, time, affine, descriptors=None):
        descriptors = descriptors or [None] * len(detections)
        anchor = None
        while self.next_checkpoint < len(self.checkpoints) and self.checkpoints[self.next_checkpoint]['time_sec'] <= time + .001:
            anchor = self.checkpoints[self.next_checkpoint]
            self.next_checkpoint += 1
        dt = time - self.last_time if self.last_time is not None else 0
        self.last_time = time
        reason = 'target_lost'
        candidates = []
        if anchor is not None:
            self.blocked = True
            point = np.array([anchor['x'], anchor['y']])
            for i, pose in enumerate(detections):
                aspect = pose.frame_aspect_ratio or 1
                distance = np.linalg.norm((pose.centroid - point) * [aspect,1])
                if distance <= max(.035, torso_scale(pose)*.9):
                    candidates.append((distance/max(.035, torso_scale(pose)), i))
            reason = 'target_not_found'
        elif not self.blocked and self.last is not None:
            if affine is None or dt > .25:
                self.blocked = True
                reason = 'camera_motion_unverified'
            else:
                self.position = affine @ np.r_[self.position, 1.] + self.velocity * dt
                scale = torso_scale(self.last)
                for i, pose in enumerate(detections):
                    aspect = pose.frame_aspect_ratio or 1
                    distance = np.linalg.norm((pose.centroid-self.position)*[aspect,1])
                    ratio = torso_scale(pose) / scale
                    if distance > max(.025, scale*.65) or not .65 <= ratio <= 1.55: continue
                    colour = 0.
                    if self.identity is not None and descriptors[i] is not None:
                        colour = 1-float(np.sqrt(self.identity*descriptors[i]).sum())
                        if colour > .65: continue
                    candidates.append((distance/scale + .2*abs(np.log(ratio)) + .3*colour, i))
        candidates.sort()
        if len(candidates) > 1 and candidates[1][0]-candidates[0][0] < .25:
            self.blocked = True
            reason = 'target_ambiguous'
        elif candidates:
            i = candidates[0][1]
            pose = detections[i]
            if anchor is not None:
                self.velocity = np.zeros(2)
                self.identity = descriptors[i]
            elif dt > 0:
                residual = (pose.centroid-self.position) / dt
                self.velocity = np.clip(.7*self.velocity + .3*residual, -.5, .5)
            self.position, self.last, self.last_hit = pose.centroid.copy(), pose, time
            self.blocked = False
            self.frames.append({'time':time, 'status':'tracked'})
            return [replace(pose, lane_hint=self.lane_id)]
        if self.last_hit is None or time-self.last_hit > .2:
            self.blocked = True
        self.frames.append({'time':time, 'status':reason})
        return []

    def summary(self):
        windows = []
        for row in self.frames:
            if row['status'] == 'tracked': continue
            if windows and windows[-1]['reason'] == row['status'] and row['time']-windows[-1]['end_sec'] < .1:
                windows[-1]['end_sec'] = row['time']
            else:
                windows.append({'reason':row['status'], 'start_sec':row['time'], 'end_sec':row['time']})
        good = sum(row['status']=='tracked' for row in self.frames)
        return {'lane_id':self.lane_id, 'status':'tracked' if good and good==len(self.frames) else 'needs_review',
                'observed_frames':good, 'total_frames':len(self.frames),
                'coverage':good/max(1,len(self.frames)), 'windows':windows,
                'identity_source':'user_confirmed_lane_and_checkpoints', 'accuracy_validated':False}


class SelectedSwimmerProvider:
    """Move/scale a multi-person search with camera + athlete, not screen ROI.

    A full race frame makes distant swimmers too small for the person detector.
    A moving search crop retains their resolution and still detects competing
    people; association, not the crop itself, determines identity.
    """
    def __init__(self, provider, target, rotation='clockwise'):
        self.provider, self.rotation = provider, rotation
        self.associator = TargetAssociator(target['lane_id'], target['checkpoints'])
        self.camera = CameraMotion()

    def detect(self, rgb, timestamp_ms):
        h,w = rgb.shape[:2]
        time = timestamp_ms/1000
        motion = self.camera.update(rgb, [])
        tracker = self.associator
        pending = [p for p in tracker.checkpoints[tracker.next_checkpoint:] if p['time_sec'] <= time+.001]
        if pending:
            center = np.array([pending[-1]['x'],pending[-1]['y']])
            radius = np.array([.27,.20])
        elif not tracker.blocked and tracker.position is not None and motion is not None:
            center = motion @ np.r_[tracker.position,1.] + tracker.velocity*(time-tracker.last_time)
            x1,y1,x2,y2 = tracker.last.bbox
            radius = np.clip(np.array([x2-x1,y2-y1])*.95, [.14,.12], [.45,.4])
        else:
            return tracker.select([],time,motion)
        x1,y1 = np.floor(np.clip(center-radius,0,1)*[w,h]).astype(int)
        x2,y2 = np.ceil(np.clip(center+radius,0,1)*[w,h]).astype(int)
        if x2-x1 < 32 or y2-y1 < 32:
            return tracker.select([],time,motion)
        crop = np.ascontiguousarray(rgb[y1:y2,x1:x2])
        rotated = crop if self.rotation=='none' else np.ascontiguousarray(np.rot90(crop, 3 if self.rotation=='clockwise' else 1))
        detections = [_remap_crop_detection(p, (x1,y1,x2,y2), w,h, tracker.lane_id, self.rotation)
                      for p in self.provider.detect(rotated, timestamp_ms)]
        self.camera.set_mask(detections)
        return tracker.select(detections, time, motion, [appearance(rgb,p) for p in detections])

    def close(self): self.provider.close()
    def __enter__(self): return self
    def __exit__(self, *args): self.close()


def apply_target_safety(result, summary):
    result['target_tracking'] = summary
    if summary['status'] == 'tracked': return
    # Never report observed fragments as a full race/interval total, or let the
    # signal counter bridge an unverified identity gap with interpolation.
    for track in result['tracks']:
        for key in ('arm_strokes','kicks'):
            track[key].update(available=False, count=None, rate_per_min=None, reason='target_identity_incomplete', event_times_sec=[])
        track.update(complete_cycles=None, cycle_equivalents=None, kicks_per_cycle=None)
        for key in ('merged_arm_candidate_times_sec','kick_candidate_times_sec'):
            track['diagnostics'][key] = [t for t in track['diagnostics'].get(key, [])
                if not any(w['start_sec']-.25 <= t <= w['end_sec']+.25 for w in summary['windows'])]
        track['warnings'].append('target_identity_incomplete')
    for metric in result['distance_metrics']:
        metric.update(available=False, dps_m_per_stroke=None, reason='target_identity_incomplete')
