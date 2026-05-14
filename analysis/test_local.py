"""
로컬 테스트용 — Docker 없이 영상 하나를 바로 분석해볼 때 사용
실행: python analysis/test_local.py --video your_video.mp4
"""
import argparse, json, sys, os
sys.path.insert(0, os.path.dirname(__file__))

from pose import analyze_video
from classifier import classify_stroke, generate_rule_based_feedback

def main():
    parser = argparse.ArgumentParser(description="SwimTech 로컬 분석 테스트")
    parser.add_argument("--video",  required=True, help="분석할 영상 경로")
    parser.add_argument("--output", default="output_analyzed.mp4", help="오버레이 영상 저장 경로")
    args = parser.parse_args()

    print(f"\n[분석 시작] {args.video}")
    print("-" * 50)

    summary = analyze_video(args.video, output_path=args.output)

    classification = classify_stroke(summary.frame_metrics)
    feedback       = generate_rule_based_feedback(summary, classification.stroke_type)

    print(f"영법        : {classification.stroke_type} (신뢰도 {classification.confidence:.0f}%)")
    print(f"분류 근거    : {classification.reason}")
    print(f"총 프레임    : {summary.total_frames} / 감지 {summary.analyzed_frames}")
    print(f"영상 길이    : {summary.duration_sec:.1f}초")
    print()
    print(f"[팔 각도]")
    print(f"  왼팔 평균  : {summary.left_arm_angle_avg:.1f}°  (최소 {summary.left_arm_angle_min:.1f}°)")
    print(f"  오른팔 평균: {summary.right_arm_angle_avg:.1f}°  (최소 {summary.right_arm_angle_min:.1f}°)")
    print(f"  좌우 대칭  : {summary.arm_symmetry_score:.1f}점")
    print()
    print(f"[발차기]")
    print(f"  총 횟수    : {summary.kick_count}회")
    print(f"  빈도       : {summary.kick_frequency_hz:.2f}회/초")
    print()
    print(f"[머리/시선]")
    print(f"  평균 각도  : {summary.head_angle_avg:.1f}°")
    print(f"  자세 점수  : {summary.head_rotation_score:.1f}점")
    print()
    print(f"[종합 점수]  : {summary.overall_score:.1f} / 100")
    print()
    print(f"[피드백]")
    print(feedback["feedback"])
    print()
    print(f"[추천 드릴]")
    for d in feedback["drills"]:
        print(f"  - {d}")
    print()
    print(f"오버레이 영상 저장: {args.output}")

if __name__ == "__main__":
    main()
