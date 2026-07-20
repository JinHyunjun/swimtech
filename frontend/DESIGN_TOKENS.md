# SwimMate Design Tokens

> 포트폴리오 증거 문서 — v2.8 Hydro Velocity 및 2026-07 전체 페이지 레이아웃 기준

---

## 1. 색상 시스템 (Color)

### 액센트 (2색 원칙)
| 토큰 | 값 | 용도 |
|---|---|---|
| `--accent-primary` | `#00b4d8` (light: `#0096b4`) | 브랜드 청색 — 버튼, 링크, 강조 |
| `--accent-secondary` | `#48cae4` (light: `#0891b2`) | 보조 시안 — 차트, 보조 강조 |

> **하위 호환 alias**: `--blue` → `--accent-primary`, `--cyan` → `--accent-secondary`, `--purple` → `--accent-secondary`

### 성취·스코어보드 전용

| 토큰 | 다크 | 라이트 | 용도 |
|---|---|---|---|
| `--energy` | `#ff6a3d` | `#ea580c` | PB, 신기록, 랭킹처럼 실제 성취 표시 |
| `--energy-soft` | `rgba(255,106,61,.14)` | `rgba(234,88,12,.10)` | 성취 필 배경 |
| `--aqua` | `#2ff0c4` | `#0891b2` | 대형 스코어 그라데이션 보조 |

`--energy`는 일반 카드 장식에 사용하지 않고 실제 성취 상태에만 사용한다.

### 상태색 (기능 표시 전용)
| 토큰 | 값 | 용도 |
|---|---|---|
| `--status-success` | `#4ade80` (light: `#16a34a`) | 성공, 완료, 양호 |
| `--status-warning` | `#f59e0b` (light: `#d97706`) | 경고, 주의 |
| `--status-danger` | `#f87171` (light: `#dc2626`) | 에러, 위험 |

> **하위 호환 alias**: `--green`, `--amber`, `--red`

### 배경/서피스
| 토큰 | 다크 | 라이트 |
|---|---|---|
| `--bg` | `#06121c` | `#f0f4f8` |
| `--surface` | `#0f2a44` | `#ffffff` |
| `--surface2` | `#0a2032` | `#e8eef5` |
| `--border` | `#173f5c` | `#c5d6e8` |
| `--text` | `#e8f4f8` | `#1a2332` |
| `--muted` | `#90c4d4` | `#64748b` |

### 사용 규칙
- **한 화면에 액센트 2색 초과 금지** (primary + secondary만)
- 상태색은 성공/경고/에러 **상태 표시에만** 사용 — 카드 border accent에 상태색 금지
- 커뮤니티 카테고리 배지: 카테고리당 1색, 최대 2종류 color 동시 노출

---

## 2. 타이포그래피 (Typography)

### 폰트 패밀리
| 토큰 | 값 |
|---|---|
| `--font-base` | `'Pretendard', -apple-system, 'Segoe UI', sans-serif` |
| `--font-mono` | `'Consolas', 'Monaco', monospace` |

> **CDN**: `https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css` (`@import` in style.css)

### 폰트 스케일
| 토큰 | 값 | 용도 |
|---|---|---|
| `--fs-caption` | `12px` | 라벨, 메타정보, 뱃지 |
| `--fs-body` | `14px` | 본문 기본 |
| `--fs-body-lg` | `16px` | 강조 본문, 버튼 |
| `--fs-title` | `20px` | 카드 제목, 섹션 제목 |
| `--fs-heading` | `28px` | 페이지 헤딩 |
| `--fs-display` | `36px` | 히어로 타이틀 (h1), 숫자 대형 표시 |
| `--fs-display-xl` | `clamp(56px, 14vw, 104px)` | 반응형 스코어보드 빅 넘버 |

> **계층 원칙**: h1은 최소 `--fs-heading` 이상. 랜딩 홈 h1 = `--fs-display`. 본문 대비 제목 2배 이상 확보.

---

## 3. 반경 (Border Radius)

| 토큰 | 값 | 용도 |
|---|---|---|
| `--radius-sm` | `8px` | 뱃지, 인풋, 작은 버튼 |
| `--radius-md` | `12px` | 버튼, 입력창, 카드 내부 요소 |
| `--radius-lg` | `16px` | 카드, 모달, 드롭다운 |
| `--radius-pill` | `9999px` | 필 형태 탭/태그 |

> 다중값 `border-radius`(예: `20px 20px 0 0`)는 모달 bottom-sheet에만 예외 허용.

---

## 4. 간격 (Spacing)

4px 베이스 그리드 기반.

| 토큰 | 값 |
|---|---|
| `--space-1` | `4px` |
| `--space-2` | `8px` |
| `--space-3` | `12px` |
| `--space-4` | `16px` |
| `--space-6` | `24px` |
| `--space-8` | `32px` |

---

## 5. Hydro Velocity 공통 유틸리티

| 클래스 | 용도 | 접근성·사용 규칙 |
|---|---|---|
| `.display-italic` | 이탤릭 헤비 그라데이션 제목 | 페이지 핵심 제목·강조에 제한 |
| `.num-score` | 대형 거리·점수·기록 | 숫자 의미를 주변 라벨과 함께 제공 |
| `.pill-energy` | PB·신기록·랭킹 필 | 실제 성취 상태에만 사용 |
| `.st-lift` | 카드 hover lift·glow | 클릭 가능한 카드 중심 |
| `.st-stagger` | 자식 순차 등장 | `prefers-reduced-motion`에서 비활성화 |
| `.st-fill` | 진행 바 채우기 | 실제 값은 DOM 스타일·ARIA와 일치 |

## 6. 레이아웃·반응형 원칙

- 공통 토큰은 `frontend/static/style.css`와 호환 복제본 `frontend/style.css`에 동일하게 유지한다.
- 페이지별 2열 레이아웃은 데스크톱에서 정보 우선순위를 보여주고 모바일에서는 1열로 쌓는다.
- 가로 스크롤 탭은 작은 화면에서 버튼 글자를 줄이지 않고 탐색 가능하게 한다.
- 모션은 정보 이해를 돕는 범위에서만 사용하고 `prefers-reduced-motion: reduce`를 존중한다.
- 상태는 색상만으로 구분하지 않고 텍스트·아이콘·라벨을 함께 제공한다.

## 7. 마이그레이션 요약 (v2.6.x → v2.8)

| 변경 | 이전 | 이후 |
|---|---|---|
| 폰트 패밀리 | 시스템 기본값 (`-apple-system`) | Pretendard (한글 최적화) |
| 폰트 스케일 | 11단계 (10~36px 산발) | 6단계 토큰 |
| 액센트 색상 | 6색 동시 (`blue/green/amber/red/cyan/purple`) | 2색 + 상태색 분리 |
| `--purple` | `#a78bfa` | `var(--accent-secondary)` 흡수 |
| border-radius | 8단계 (4~20px 산발) | 3단계 토큰 |
| 하드코딩 배경색 | `#0d2137` (18개 파일) | `var(--surface)` |
| 헤더 버튼 | 인라인 스타일 (dashboard, chat) | `.back-btn` 공통 클래스 |
| 성취 강조 | 일반 상태색·액센트와 혼용 | `--energy`, `.pill-energy`로 분리 |
| 대형 숫자 | 페이지별 크기 하드코딩 | `--fs-display-xl`, `.num-score` |
| 모션 | 페이지별 hover·animation | `.st-lift`, `.st-stagger`, `.st-fill` + 모션 최소화 대응 |
