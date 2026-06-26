"""SwimMate — Google Sheets 연동 라우터"""
import os
import json
from datetime import datetime
from fastapi import APIRouter, Request, Cookie, HTTPException
from fastapi.responses import HTMLResponse

router = APIRouter()

CREDENTIALS_FILE = "/app/credentials/google_oauth_client.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
REDIRECT_URI = "https://localhost/api/sheets/callback"
DATABASE_URL = os.getenv("DATABASE_URL", "")

# localhost HTTP 허용 (개발용)
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

HEADERS = ["날짜", "영법", "목적", "종합점수", "왼팔각도", "오른팔각도",
           "좌우대칭", "발차기횟수", "발차기빈도", "머리각도", "강점요약", "개선점요약"]
STROKE_KO = {"freestyle": "자유형", "backstroke": "배영",
             "breaststroke": "평영", "butterfly": "접영", "unknown": "미확인"}
PURPOSE_KO = {"record": "기록 단축", "health": "건강하게 오래",
              "technique": "영법 교정", "competition": "대회 준비", "hobby": "취미/건강유지"}


import psycopg2


def _get_db():
    return psycopg2.connect(DATABASE_URL)


def _require_customer(token: str | None) -> int:
    if not token:
        raise HTTPException(401, "로그인이 필요합니다.")
    from routers.auth import decode_token
    cid = decode_token(token).get("customer_id")
    if not cid:
        raise HTTPException(401, "고객 계정으로 로그인해주세요.")
    return int(cid)


def _close_popup(payload: dict) -> HTMLResponse:
    payload_json = json.dumps(payload, ensure_ascii=False)
    return HTMLResponse(f"""<!DOCTYPE html>
<html><body>
<script>
  try {{ if (window.opener) window.opener.postMessage({payload_json}, '*'); }} catch(e) {{}}
  window.close();
</script>
<p>처리 완료. 창을 닫는 중...</p>
</body></html>""")


@router.get("/auth")
def sheets_auth(swimtech_token: str = Cookie(default=None)):
    """Google OAuth 인증 URL 반환"""
    if not os.path.exists(CREDENTIALS_FILE):
        raise HTTPException(
            503,
            "Google OAuth 클라이언트 파일 없음. "
            "credentials/google_oauth_client.json 을 설정해주세요."
        )
    customer_id = _require_customer(swimtech_token)

    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=str(customer_id),
    )
    return {"auth_url": auth_url}


@router.get("/callback")
def sheets_callback(
    code: str = None, state: str = None, error: str = None
):
    """OAuth 콜백: 토큰 저장 후 팝업 닫기"""
    if error:
        return _close_popup({"type": "sheets_auth_error", "error": error})
    if not code or not state:
        return _close_popup({"type": "sheets_auth_error", "error": "인증 코드 없음"})

    try:
        customer_id = int(state)
    except ValueError:
        return _close_popup({"type": "sheets_auth_error", "error": "잘못된 상태값"})

    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(
            CREDENTIALS_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI
        )
        flow.fetch_token(code=code)
        token_json = flow.credentials.to_json()
    except Exception as e:
        return _close_popup({"type": "sheets_auth_error", "error": str(e)})

    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE customers SET google_token = %s WHERE id = %s",
            (token_json, customer_id),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        return _close_popup({"type": "sheets_auth_error", "error": f"DB 저장 실패: {e}"})

    return _close_popup({"type": "sheets_auth_success"})


@router.post("/save")
async def sheets_save(request: Request, swimtech_token: str = Cookie(default=None)):
    """분석 결과를 Google Sheets에 저장"""
    customer_id = _require_customer(swimtech_token)
    data = await request.json()

    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT google_token, sheets_id FROM customers WHERE id = %s",
            (customer_id,),
        )
        row = cur.fetchone()
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")

    if not row or not row[0]:
        cur.close(); conn.close()
        raise HTTPException(400, "Google 인증이 필요합니다.")

    token_json, sheets_id = row

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        creds = Credentials.from_authorized_user_info(json.loads(token_json))

        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request as GRequest
            creds.refresh(GRequest())
            cur.execute(
                "UPDATE customers SET google_token = %s WHERE id = %s",
                (creds.to_json(), customer_id),
            )
            conn.commit()

        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    except Exception as e:
        cur.close(); conn.close()
        raise HTTPException(500, f"Google API 초기화 실패: {e}")

    try:
        if not sheets_id:
            spreadsheet = service.spreadsheets().create(body={
                "properties": {"title": "SwimMate 수영 분석 기록"},
                "sheets": [{"properties": {"title": "분석 결과"}}],
            }).execute()
            sheets_id = spreadsheet["spreadsheetId"]
            cur.execute(
                "UPDATE customers SET sheets_id = %s WHERE id = %s",
                (sheets_id, customer_id),
            )
            conn.commit()
            service.spreadsheets().values().update(
                spreadsheetId=sheets_id,
                range="분석 결과!A1",
                valueInputOption="RAW",
                body={"values": [HEADERS]},
            ).execute()

        # 종합점수 계산 (viewer.html 동일 공식)
        sym  = float(data.get("arm_symmetry_score") or 0)
        head = float(data.get("head_rotation_score") or 0)
        freq = min(100.0, float(data.get("kick_frequency_hz") or 0) * 20)
        score = round(sym * 0.4 + head * 0.3 + freq * 0.3)

        strengths_sum = "; ".join(
            s.get("item", "") for s in (data.get("strengths") or [])[:3]
        )
        improvements_sum = "; ".join(
            i.get("item", "") for i in (data.get("improvements") or [])[:3]
        )

        row_vals = [
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            STROKE_KO.get(data.get("stroke_type", ""), data.get("stroke_type", "")),
            PURPOSE_KO.get(data.get("purpose", ""), data.get("purpose", "")),
            score,
            round(float(data.get("left_arm_angle_avg") or 0), 1),
            round(float(data.get("right_arm_angle_avg") or 0), 1),
            round(sym, 1),
            int(data.get("kick_count") or 0),
            round(float(data.get("kick_frequency_hz") or 0), 2),
            round(float(data.get("head_angle_avg") or 0), 1),
            strengths_sum,
            improvements_sum,
        ]

        service.spreadsheets().values().append(
            spreadsheetId=sheets_id,
            range="분석 결과!A:L",
            valueInputOption="USER_ENTERED",
            body={"values": [row_vals]},
        ).execute()

        cur.close(); conn.close()
        return {
            "status": "ok",
            "sheets_url": f"https://docs.google.com/spreadsheets/d/{sheets_id}",
        }
    except Exception as e:
        cur.close(); conn.close()
        raise HTTPException(500, f"Sheets 저장 실패: {e}")
