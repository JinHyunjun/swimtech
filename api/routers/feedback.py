# -*- coding: utf-8 -*-
import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()
logger = logging.getLogger(__name__)


class FeedbackRequest(BaseModel):
    feedback_type: str
    page: str
    title: str
    content: str
    email: Optional[str] = None


@router.post("")
async def submit_feedback(body: FeedbackRequest):
    smtp_email = os.getenv("SMTP_EMAIL", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")

    if not smtp_email or not smtp_password:
        logger.error("SMTP 환경변수 미설정 — 피드백 이메일 발송 불가")
        raise HTTPException(status_code=500, detail="SMTP 설정이 누락되었습니다.")

    contact = body.email.strip() if body.email and body.email.strip() else "미입력"

    subject = f"[SwimTech 피드백] {body.feedback_type} - {body.title}"
    body_text = (
        f"유형: {body.feedback_type}\n"
        f"페이지: {body.page}\n"
        f"제목: {body.title}\n\n"
        f"내용:\n{body.content}\n\n"
        f"연락처: {contact}"
    )

    msg = MIMEMultipart()
    msg["From"] = smtp_email
    msg["To"] = smtp_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, smtp_email, msg.as_string())
        logger.info("피드백 이메일 발송 완료: %s", subject)
        return {"status": "ok", "message": "피드백이 전송되었습니다."}
    except smtplib.SMTPAuthenticationError:
        logger.error("Gmail SMTP 인증 실패")
        raise HTTPException(status_code=500, detail="이메일 인증 실패. 앱 비밀번호를 확인하세요.")
    except Exception as e:
        logger.error("이메일 발송 실패: %s", e)
        raise HTTPException(status_code=500, detail=f"이메일 발송 실패: {e}")
