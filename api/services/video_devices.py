"""Durable device authorization. The database contains only a secret digest.

Used during enrollment, access renewal (45 minutes), and explicit management;
never on the five-second job poll. Video/pose/label data stays ephemeral.
"""
import hashlib
import os
import secrets
from uuid import uuid4

from db import db_conn


class DeviceRegistry:
    def register(self, owner, name):
        ident, secret = uuid4().hex, secrets.token_urlsafe(32)
        with db_conn() as (_, cur):
            cur.execute('SELECT id, COALESCE(auth_version, 0) FROM customers WHERE username=%s FOR UPDATE', (owner,))
            customer = cur.fetchone()
            if not customer: raise ValueError('관리자 계정을 찾지 못했습니다.')
            cur.execute("DELETE FROM video_worker_devices WHERE customer_id=%s AND (revoked_at IS NOT NULL OR expires_at<NOW())", (customer[0],))
            cur.execute('SELECT COUNT(*) FROM video_worker_devices WHERE customer_id=%s', (customer[0],))
            if cur.fetchone()[0] >= 5: raise ValueError('등록 PC는 5개까지입니다. 사용하지 않는 연결을 해제하세요.')
            cur.execute("""INSERT INTO video_worker_devices
                (id, customer_id, auth_version, name, secret_hash, expires_at)
                VALUES (%s,%s,%s,%s,%s,NOW()+INTERVAL '90 days')""",
                (ident, customer[0], customer[1], name, hashlib.sha256(secret.encode()).hexdigest()))
        return {'device_id':ident, 'secret':secret}

    def renew(self, ident, secret):
        with db_conn() as (_, cur):
            cur.execute("""UPDATE video_worker_devices d SET last_used_at=NOW(), expires_at=NOW()+INTERVAL '90 days'
                FROM customers c WHERE d.id=%s AND d.secret_hash=%s AND d.customer_id=c.id
                AND d.revoked_at IS NULL AND d.expires_at>NOW() AND d.auth_version=COALESCE(c.auth_version,0)
                AND (c.role='admin' OR c.username=%s) RETURNING c.username""",
                (ident, hashlib.sha256(secret.encode()).hexdigest(), os.getenv('ADMIN_ID','admin')))
            row = cur.fetchone()
            return row[0] if row else None

    def list(self, owner):
        with db_conn() as (_, cur):
            cur.execute("""SELECT d.id,d.name,d.last_used_at,d.expires_at FROM video_worker_devices d
                JOIN customers c ON c.id=d.customer_id WHERE c.username=%s AND d.revoked_at IS NULL
                AND d.expires_at>NOW() ORDER BY d.created_at DESC""", (owner,))
            return [{'id':r[0],'name':r[1],'last_used_at':r[2].isoformat(),'expires_at':r[3].isoformat()} for r in cur.fetchall()]

    def revoke(self, owner, ident):
        with db_conn() as (_, cur):
            cur.execute("""UPDATE video_worker_devices d SET revoked_at=NOW() FROM customers c
                WHERE d.id=%s AND d.customer_id=c.id AND c.username=%s RETURNING d.id""", (ident, owner))
            return cur.fetchone() is not None
