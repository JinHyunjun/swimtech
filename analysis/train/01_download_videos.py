"""
SwimTech — Step 1. YouTube 영상 수집 (3-Track 버전)

Track 1. Competition  — 올림픽/세계선수권 경기 영상 기반 대회 모델
Track 2. Tutorial     — 유튜버/인플루언서 강의 영상 기반 교습 모델
Track 3. Start & Turn — 스타트/턴 전문 영상 기반 기술 모델

설치:
    pip install yt-dlp

실행:
    python analysis/train/01_download_videos.py                        # 전체 수집
    python analysis/train/01_download_videos.py --track competition    # 대회 모델만
    python analysis/train/01_download_videos.py --track tutorial       # 교습 모델만
    python analysis/train/01_download_videos.py --track start_turn     # 스타트/턴만
    python analysis/train/01_download_videos.py --track competition --stroke freestyle --max 20
"""
import os
import argparse
import subprocess
import sys

# ══════════════════════════════════════════════════════════
# Track 1. Competition — 올림픽 / 세계선수권 경기 영상
# 분석 포인트: 스트로크 효율, 발차기 빈도, 몸통 롤링, 입수 각도
# 촬영 영상 업로드 & 자유수영 영상 모두 적용 가능
# ══════════════════════════════════════════════════════════
COMPETITION_QUERIES = {

    # 자유형 대회
    "competition_freestyle": [
        "olympic freestyle swimming 100m final slow motion analysis",
        "world aquatics freestyle swimming race underwater camera",
        "olympic games freestyle swimming stroke technique side view",
        "world championship 200m freestyle swimming analysis",
        "olympic freestyle swimming underwater slow motion 2024",
        "자유형 올림픽 경기 슬로우모션 분석",
        "world record freestyle swimming stroke rate analysis",
    ],

    # 배영 대회
    "competition_backstroke": [
        "olympic backstroke swimming final slow motion",
        "world aquatics backstroke race underwater analysis",
        "backstroke swimming world championship technique",
        "olympic backstroke 100m final underwater camera",
        "배영 올림픽 경기 슬로우모션",
        "world record backstroke swimming analysis",
    ],

    # 평영 대회
    "competition_breaststroke": [
        "olympic breaststroke swimming final slow motion",
        "world aquatics breaststroke race underwater",
        "breaststroke world championship technique analysis",
        "olympic 100m breaststroke final underwater camera",
        "평영 올림픽 경기 슬로우모션 분석",
        "world record breaststroke pull kick timing",
    ],

    # 접영 대회
    "competition_butterfly": [
        "olympic butterfly swimming final slow motion",
        "world aquatics butterfly race underwater analysis",
        "butterfly swimming world championship technique",
        "olympic 100m butterfly final underwater slow motion",
        "접영 올림픽 경기 슬로우모션",
        "world record butterfly swimming dolphin kick",
    ],

    # 개인혼영 대회
    "competition_medley": [
        "olympic individual medley swimming final slow motion",
        "world aquatics IM race analysis",
        "400m IM swimming world championship technique",
        "개인혼영 올림픽 경기 분석",
    ],
}

# ══════════════════════════════════════════════════════════
# Track 2. Tutorial — 유튜버/인플루언서 강의 영상
# 분석 포인트: 자세 교정, 기본기, 드릴, 호흡 타이밍
# 영상 업로드 없이 Q&A 방식 피드백에 활용
# ══════════════════════════════════════════════════════════
TUTORIAL_QUERIES = {

    # 자유형 강의
    "tutorial_freestyle": [
        # 해외 유명 채널
        "Effortless Swimming freestyle technique tutorial",
        "Global Triathlon Network freestyle swimming tips",
        "Skills NT freestyle swimming drill tutorial",
        "Swim with Multisport freestyle technique breakdown",
        "SwimUp freestyle swimming correction tutorial",
        "Total Immersion freestyle swimming tutorial",
        "freestyle swimming tips beginners intermediate",
        # 한국 인플루언서
        "자유형 수영 강습 영법 교정 유튜브",
        "자유형 팔동작 발차기 강의 수영",
        "수영 자유형 초보 교정 강습 영상",
        "자유형 호흡 교정 강의",
    ],

    # 배영 강의
    "tutorial_backstroke": [
        "Effortless Swimming backstroke tutorial",
        "backstroke technique tips correction tutorial",
        "backstroke swimming drill beginner intermediate",
        "Skills NT backstroke technique breakdown",
        "배영 수영 강습 영법 교정",
        "배영 팔동작 발차기 강의",
        "수영 배영 초보 교정 강습",
    ],

    # 평영 강의
    "tutorial_breaststroke": [
        "Effortless Swimming breaststroke tutorial",
        "breaststroke technique tips pull kick timing",
        "breaststroke swimming drill correction tutorial",
        "Skills NT breaststroke technique breakdown",
        "평영 수영 강습 영법 교정",
        "평영 발차기 타이밍 강의",
        "수영 평영 초보 교정 강습",
    ],

    # 접영 강의
    "tutorial_butterfly": [
        "Effortless Swimming butterfly tutorial",
        "butterfly stroke technique tips correction",
        "butterfly swimming drill dolphin kick tutorial",
        "Skills NT butterfly technique breakdown",
        "접영 수영 강습 영법 교정",
        "접영 돌핀킥 강의 드릴",
        "수영 접영 초보 교정 강습",
    ],

    # 드릴 종합
    "tutorial_drill": [
        "swimming drill tutorial all strokes",
        "swim drill for beginners technique correction",
        "수영 드릴 훈련 강습 영상",
        "수영 영법 드릴 모음",
    ],
}

# ══════════════════════════════════════════════════════════
# Track 3. Start & Turn — 스타트/턴 전문 영상
# 분석 포인트: 입수 각도, 반응 시간, 턴 타이밍, 벽 킥, 스트림라인
# ══════════════════════════════════════════════════════════
START_TURN_QUERIES = {

    # 스타트
    "start_technique": [
        "swimming start technique slow motion analysis",
        "freestyle backstroke breaststroke butterfly start tutorial",
        "olympic swimming start block technique",
        "swimming reaction time start analysis slow motion",
        "grab start track start swimming tutorial",
        "수영 스타트 기술 슬로우모션",
        "수영 출발 기술 강습 영상",
        "swimming start underwater slow motion entry angle",
    ],

    # 자유형/접영 턴 (플립턴)
    "turn_flip": [
        "freestyle flip turn technique tutorial slow motion",
        "butterfly flip turn technique",
        "swimming flip turn correction tips",
        "flip turn underwater analysis slow motion",
        "자유형 플립턴 기술 강습",
        "수영 플립턴 교정 슬로우모션",
        "flip turn push off streamline underwater",
    ],

    # 배영 턴
    "turn_backstroke": [
        "backstroke turn technique tutorial slow motion",
        "backstroke flip turn underwater analysis",
        "배영 턴 기술 강습 슬로우모션",
        "backstroke touch turn technique correction",
    ],

    # 평영/접영 터치턴
    "turn_touch": [
        "breaststroke turn technique tutorial slow motion",
        "butterfly turn technique underwater analysis",
        "touch turn technique two hand touch",
        "평영 접영 턴 기술 강습",
        "수영 터치턴 교정 강습",
        "breaststroke butterfly touch turn correction",
    ],

    # 스트림라인 / 잠영
    "streamline_underwater": [
        "swimming streamline technique tutorial",
        "underwater dolphin kick streamline",
        "swimming breakout technique after turn start",
        "수영 스트림라인 잠영 기술",
        "underwater kick after turn swimming",
    ],
}

# ══════════════════════════════════════════════════════════
# 트랙별 데이터 디렉토리
# ══════════════════════════════════════════════════════════
BASE_DIR = os.path.join(os.path.dirname(__file__), "data")
TRACK_DIRS = {
    "competition": os.path.join(BASE_DIR, "competition"),
    "tutorial":    os.path.join(BASE_DIR, "tutorial"),
    "start_turn":  os.path.join(BASE_DIR, "start_turn"),
}
TRACK_QUERIES = {
    "competition": COMPETITION_QUERIES,
    "tutorial":    TUTORIAL_QUERIES,
    "start_turn":  START_TURN_QUERIES,
}
TRACK_DESC = {
    "competition": "대회/기록 모델 (올림픽·세계선수권)",
    "tutorial":    "교습/강의 모델 (유튜버·인플루언서)",
    "start_turn":  "스타트/턴 모델",
}

# ══════════════════════════════════════════════════════════
# 목적별 카테고리 (--category 옵션)
# 기존 3-Track과 별개로 목적 기반 데이터 수집에 사용
# ══════════════════════════════════════════════════════════
HEALTH_QUERIES = [
    "건강 수영 중장년",
    "수영 부상 예방",
    "swimming for health adults",
    "low impact swimming workout",
    "수영 어깨 부상 예방",
    "swimming injury prevention",
    "건강하게 오래 수영하기",
    "수영 재활 운동",
    "swimming for seniors",
    "gentle swimming technique",
]

MASTERS_QUERIES = [
    "마스터즈 수영",
    "masters swimming technique",
    "adult swimming improvement",
    "수영 효율 향상",
    "swimming efficiency adults",
    "마스터즈 수영 대회",
    "masters swimming competition",
    "수영 지구력 훈련",
    "swimming endurance training",
    "triathlon swimming technique",
]

CATEGORIES = {
    "competition": {
        "keywords":     [q for qs in COMPETITION_QUERIES.values() for q in qs],
        "max_videos":   100,
        "max_duration": 300,
        "save_dir":     os.path.join(BASE_DIR, "competition"),
        "desc":         "대회/기록 영상 (올림픽·세계선수권)",
    },
    "tutorial": {
        "keywords":     [q for qs in TUTORIAL_QUERIES.values() for q in qs],
        "max_videos":   80,
        "max_duration": 600,
        "save_dir":     os.path.join(BASE_DIR, "tutorial"),
        "desc":         "교습/강의 영상 (유튜버·인플루언서)",
    },
    "health": {
        "keywords":     HEALTH_QUERIES,
        "max_videos":   60,
        "max_duration": 600,
        "save_dir":     os.path.join(BASE_DIR, "health"),
        "desc":         "건강 수영 영상 (중장년·부상 예방)",
    },
    "masters": {
        "keywords":     MASTERS_QUERIES,
        "max_videos":   50,
        "max_duration": 480,
        "save_dir":     os.path.join(BASE_DIR, "masters"),
        "desc":         "마스터즈 영상 (성인 효율·지구력)",
    },
}


def check_yt_dlp():
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def download_category(category: str, queries: list, output_dir: str, max_videos: int = 15):
    os.makedirs(output_dir, exist_ok=True)
    downloaded = 0

    for query in queries:
        if downloaded >= max_videos:
            break
        remaining = max_videos - downloaded
        print(f"  [검색] '{query}' (남은 {remaining}개)")

        cmd = [
            "yt-dlp",
            f"ytsearch{remaining}:{query}",
            "--output", os.path.join(output_dir, "%(title)s.%(ext)s"),
            "--format", "mp4/bestvideo[height<=720]",
            "--max-downloads", str(remaining),
            "--no-playlist",
            "--match-filter", "duration < 600",  # 10분 이하
            "--ignore-errors",
            "--quiet",
            "--progress",
        ]
        subprocess.run(cmd)
        files = [f for f in os.listdir(output_dir) if f.endswith(".mp4")]
        downloaded = len(files)

    print(f"  → {category}: {downloaded}개 수집 완료")
    return downloaded


def download_track(track: str, stroke_filter: str = "all", max_videos: int = 15):
    queries_map = TRACK_QUERIES[track]
    track_base  = TRACK_DIRS[track]
    total = 0

    print(f"\n{'='*60}")
    print(f"  Track: {TRACK_DESC[track]}")
    print(f"{'='*60}")

    for category, queries in queries_map.items():
        # stroke 필터 적용
        if stroke_filter != "all":
            if not (category.endswith(stroke_filter) or stroke_filter in category):
                continue

        output_dir = os.path.join(track_base, category)
        print(f"\n[{category}]")
        count = download_category(category, queries, output_dir, max_videos)
        total += count

    print(f"\n✅ {TRACK_DESC[track]} 수집 완료: 총 {total}개")
    return total


def download_by_category(category: str):
    """목적별 카테고리 단위 수집 (CATEGORIES dict 기반)."""
    cfg        = CATEGORIES[category]
    save_dir   = cfg["save_dir"]
    max_videos = cfg["max_videos"]
    max_dur    = cfg["max_duration"]
    keywords   = cfg["keywords"]

    os.makedirs(save_dir, exist_ok=True)
    downloaded = 0

    print(f"\n{'='*60}")
    print(f"  Category: {cfg['desc']}")
    print(f"  저장 경로: {save_dir}")
    print(f"  목표: {max_videos}개 / 최대 {max_dur}초")
    print(f"{'='*60}")

    for query in keywords:
        if downloaded >= max_videos:
            break
        remaining = max_videos - downloaded
        print(f"  [검색] '{query}' (남은 {remaining}개)")

        cmd = [
            "yt-dlp",
            f"ytsearch{remaining}:{query}",
            "--output", os.path.join(save_dir, "%(title)s.%(ext)s"),
            "--format", "mp4/bestvideo[height<=720]",
            "--max-downloads", str(remaining),
            "--no-playlist",
            "--match-filter", f"duration < {max_dur}",
            "--ignore-errors",
            "--quiet",
            "--progress",
        ]
        subprocess.run(cmd)
        files = [f for f in os.listdir(save_dir) if f.endswith(".mp4")]
        downloaded = len(files)

    print(f"\n  → {category}: {downloaded}개 수집 완료")
    return downloaded


def main():
    parser = argparse.ArgumentParser(
        description="SwimTech 영상 수집 (3-Track 또는 목적별 카테고리)",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "예시:\n"
            "  python 01_download_videos.py                          # 전체 트랙\n"
            "  python 01_download_videos.py --track competition      # 대회 트랙만\n"
            "  python 01_download_videos.py --category health        # 건강 카테고리\n"
            "  python 01_download_videos.py --category all           # 목적별 전체\n"
            "  python 01_download_videos.py --track tutorial --stroke freestyle --max 20"
        )
    )
    parser.add_argument("--track",
        choices=["competition", "tutorial", "start_turn", "all"],
        default=None, help="3-Track 기반 수집 (기본: --category 없으면 all)")
    parser.add_argument("--category",
        choices=list(CATEGORIES.keys()) + ["all"],
        default=None, help="목적별 카테고리 수집 (competition/tutorial/health/masters/all)")
    parser.add_argument("--stroke",
        choices=["freestyle","backstroke","breaststroke","butterfly","medley","drill","all"],
        default="all", help="--track 모드에서 특정 영법만 수집 (기본: all)")
    parser.add_argument("--max", type=int, default=15,
        help="--track 모드: 카테고리당 최대 영상 수 (기본: 15)")
    args = parser.parse_args()

    if not check_yt_dlp():
        print("❌ yt-dlp 미설치\n   pip install yt-dlp")
        sys.exit(1)

    # ── 목적별 카테고리 모드 ──────────────────────────────
    if args.category:
        cats = list(CATEGORIES.keys()) if args.category == "all" else [args.category]
        grand_total = 0
        print(f"\n🏊 SwimTech 목적별 영상 수집 시작")
        print(f"   카테고리: {cats}")
        for cat in cats:
            grand_total += download_by_category(cat)
        print(f"\n🎉 목적별 수집 완료: 총 {grand_total}개")
        print(f"\n저장 구조:")
        for cat, cfg in CATEGORIES.items():
            print(f"  {cfg['save_dir'].replace(BASE_DIR, 'data')}  ← {cfg['desc']}")
        print(f"\n다음 단계: python analysis/train/02_extract_features.py")
        return

    # ── 기존 3-Track 모드 ────────────────────────────────
    track_arg  = args.track or "all"
    tracks     = ["competition", "tutorial", "start_turn"] if track_arg == "all" else [track_arg]
    grand_total = 0

    print(f"\n🏊 SwimTech 3-Track 영상 수집 시작")
    print(f"   트랙: {tracks}")
    print(f"   영법 필터: {args.stroke}")
    print(f"   카테고리당 최대: {args.max}개")

    for track in tracks:
        count = download_track(track, stroke_filter=args.stroke, max_videos=args.max)
        grand_total += count

    print(f"\n🎉 전체 수집 완료: 총 {grand_total}개")
    print(f"\n저장 구조:")
    print(f"  analysis/train/data/")
    print(f"  ├── competition/  ← 대회 영상")
    print(f"  ├── tutorial/     ← 강의 영상")
    print(f"  └── start_turn/   ← 스타트/턴 영상")
    print(f"\n다음 단계: python analysis/train/02_extract_features.py")


if __name__ == "__main__":
    main()
