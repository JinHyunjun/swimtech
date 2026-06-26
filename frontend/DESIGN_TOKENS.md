# SwimMate Design Tokens

> 포트폴리오 증거 문서 — v2.7.0 기준 토큰 정의

---

## 1. 색상 시스템 (Color)

### 액센트 (2색 원칙)
| 토큰 | 값 | 용도 |
|---|---|---|
| `--accent-primary` | `#00b4d8` (light: `#0096b4`) | 브랜드 청색 — 버튼, 링크, 강조 |
| `--accent-secondary` | `#48cae4` (light: `#0891b2`) | 보조 시안 — 차트, 보조 강조 |

> **하위 호환 alias**: `--blue` → `--accent-primary`, `--cyan` → `--accent-secondary`, `--purple` → `--accent-secondary`

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
| `--bg` | `#0a1628` | `#f0f4f8` |
| `--surface` | `#1a3a5c` | `#ffffff` |
| `--surface2` | `#0f2942` | `#e8eef5` |
| `--border` | `#1e4d6b` | `#c5d6e8` |
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

### 폰트 스케일 (6단계)
| 토큰 | 값 | 용도 |
|---|---|---|
| `--fs-caption` | `12px` | 라벨, 메타정보, 뱃지 |
| `--fs-body` | `14px` | 본문 기본 |
| `--fs-body-lg` | `16px` | 강조 본문, 버튼 |
| `--fs-title` | `20px` | 카드 제목, 섹션 제목 |
| `--fs-heading` | `28px` | 페이지 헤딩 |
| `--fs-display` | `36px` | 히어로 타이틀 (h1), 숫자 대형 표시 |

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

## 5. 마이그레이션 요약 (v2.6.x → v2.7.0)

| 변경 | 이전 | 이후 |
|---|---|---|
| 폰트 패밀리 | 시스템 기본값 (`-apple-system`) | Pretendard (한글 최적화) |
| 폰트 스케일 | 11단계 (10~36px 산발) | 6단계 토큰 |
| 액센트 색상 | 6색 동시 (`blue/green/amber/red/cyan/purple`) | 2색 + 상태색 분리 |
| `--purple` | `#a78bfa` | `var(--accent-secondary)` 흡수 |
| border-radius | 8단계 (4~20px 산발) | 3단계 토큰 |
| 하드코딩 배경색 | `#0d2137` (18개 파일) | `var(--surface)` |
| 헤더 버튼 | 인라인 스타일 (dashboard, chat) | `.back-btn` 공통 클래스 |
