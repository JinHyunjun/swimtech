"""Fail-closed, non-PII analytics eligibility/configuration."""
import os
import re
from fastapi import APIRouter, Cookie, Response
from db import get_db
from routers.auth import decode_token

router=APIRouter()
# Public identifiers supplied by the owner. These never enable collection;
# both explicit activation/review flags below are still required.
DEFAULT_GTM_CONTAINER_ID='GTM-5TQRKVQ5'
DEFAULT_GA4_MEASUREMENT_ID='G-B43M43WPM9'


@router.get('/config')
def analytics_config(response: Response, swimtech_token: str = Cookie(default=None)):
    response.headers['Cache-Control']='private, no-store'
    disabled={'enabled':False}
    container=os.getenv('GTM_CONTAINER_ID',DEFAULT_GTM_CONTAINER_ID).strip()
    measurement=os.getenv('GA4_MEASUREMENT_ID',DEFAULT_GA4_MEASUREMENT_ID).strip()
    if (os.getenv('PRODUCT_ANALYTICS_ENABLED')!='true'
            or os.getenv('ANALYTICS_PRIVACY_REVIEWED')!='true'
            or os.getenv('ANALYTICS_POLICY_VERSION')!='2026-10-v2'
            or not re.fullmatch(r'GTM-[A-Z0-9]+',container)
            or not re.fullmatch(r'G-[A-Z0-9]+',measurement)
            or not swimtech_token):
        return disabled
    conn=cur=None
    try:
        payload=decode_token(swimtech_token)
        if payload.get('is_demo') or not payload.get('sub'):return disabled
        conn=get_db();cur=conn.cursor()
        cur.execute('SELECT role, is_qa_account FROM customers WHERE username = %s',(payload['sub'],))
        row=cur.fetchone()
        # Unknown classification is excluded, not assumed regular.
        if not row or row[0] not in (None,'user','coach') or row[1] is not False:return disabled
        return dict(enabled=True,container_id=container,measurement_id=measurement,policy_version='2026-10-v2')
    except Exception:
        return disabled
    finally:
        if cur is not None:cur.close()
        if conn is not None:conn.close()
