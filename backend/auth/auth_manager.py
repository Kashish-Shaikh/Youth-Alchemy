# auth/auth_manager.py — JWT + bcrypt (Users + Doctors)

import os
import datetime
import hashlib
import hmac
import base64
import json

try:
    import jwt as pyjwt
    USE_PYJWT = True
except ImportError:
    USE_PYJWT = False

try:
    import bcrypt
    USE_BCRYPT = True
except ImportError:
    USE_BCRYPT = False

SECRET_KEY = os.environ.get('DERMIQ_SECRET_KEY')
if not SECRET_KEY:
    if os.environ.get('FLASK_ENV') == 'development' or os.environ.get('DEBUG') == '1':
        # Dev-only fallback so local testing isn't blocked — never reaches prod
        SECRET_KEY = 'dev-only-insecure-key-do-not-deploy'
        print("[WARN] DERMIQ_SECRET_KEY not set — using INSECURE dev fallback. "
              "This must NEVER happen in production.")
    else:
        raise RuntimeError(
            "DERMIQ_SECRET_KEY environment variable is not set. "
            "Refusing to start with no secret — this would let anyone forge login tokens. "
            "Set DERMIQ_SECRET_KEY in your environment (e.g. a long random string) before running."
        )
TOKEN_EXPIRY_HOURS = int(os.environ.get('TOKEN_EXPIRY_HOURS', '72'))


class AuthManager:

    # ── Password ─────────────────────────────────────

    def hash_password(self, plain_text: str) -> str:
        if USE_BCRYPT:
            return bcrypt.hashpw(plain_text.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')
        salt = os.urandom(32)
        key  = hashlib.pbkdf2_hmac('sha256', plain_text.encode('utf-8'), salt, 200_000)
        return base64.b64encode(salt + key).decode('utf-8')

    def verify_password(self, plain_text: str, hashed: str) -> bool:
        if USE_BCRYPT:
            try:
                return bcrypt.checkpw(plain_text.encode('utf-8'), hashed.encode('utf-8'))
            except Exception:
                return False
        try:
            raw  = base64.b64decode(hashed.encode('utf-8'))
            salt = raw[:32]
            key  = hashlib.pbkdf2_hmac('sha256', plain_text.encode('utf-8'), salt, 200_000)
            return hmac.compare_digest(key, raw[32:])
        except Exception:
            return False

    # ── User tokens ───────────────────────────────────

    def create_token(self, user_id: int, email: str, name: str) -> str:
        return self._encode({'user_id': user_id, 'email': email, 'name': name, 'role': 'user'})

    def verify_token(self, token: str):
        payload, err = self._decode(token)
        if err: return None, err
        if payload.get('role') not in ('user', None):
            return None, 'Invalid token role'
        return payload, None

    # ── Doctor tokens ─────────────────────────────────

    def create_doctor_token(self, doctor_id: int, email: str, name: str) -> str:
        return self._encode({'doctor_id': doctor_id, 'email': email, 'name': name, 'role': 'doctor'})

    def verify_doctor_token(self, token: str):
        payload, err = self._decode(token)
        if err: return None, err
        if payload.get('role') != 'doctor':
            return None, 'Not a doctor token'
        return payload, None

    # ── Core encode/decode ────────────────────────────

    def _encode(self, extra: dict) -> str:
        payload = {
            **extra,
            'iat': datetime.datetime.utcnow(),
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=TOKEN_EXPIRY_HOURS)
        }
        if USE_PYJWT:
            return pyjwt.encode(payload, SECRET_KEY, algorithm='HS256')
        return self._manual_encode(payload)

    def _decode(self, token: str):
        if USE_PYJWT:
            try:
                payload = pyjwt.decode(token, SECRET_KEY, algorithms=['HS256'])
                return payload, None
            except pyjwt.ExpiredSignatureError:
                return None, 'Token expired. Please log in again.'
            except pyjwt.InvalidTokenError as e:
                return None, f'Invalid token: {e}'
        return self._manual_decode(token)

    # ── Fallback manual JWT ────────────────────────────

    def _b64u(self, data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

    def _b64ud(self, s: str) -> bytes:
        return base64.urlsafe_b64decode(s + '=' * (4 - len(s) % 4))

    def _manual_encode(self, payload: dict) -> str:
        p = payload.copy()
        for k in ('iat', 'exp'):
            if isinstance(p.get(k), datetime.datetime):
                p[k] = int(p[k].timestamp())
        hdr  = self._b64u(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())
        body = self._b64u(json.dumps(p).encode())
        sig  = self._b64u(hmac.new(SECRET_KEY.encode(), f'{hdr}.{body}'.encode(), hashlib.sha256).digest())
        return f'{hdr}.{body}.{sig}'

    def _manual_decode(self, token: str):
        try:
            parts = token.split('.')
            if len(parts) != 3: return None, 'Malformed token'
            hdr, body, sig = parts
            expected = self._b64u(hmac.new(SECRET_KEY.encode(), f'{hdr}.{body}'.encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(sig, expected): return None, 'Invalid signature'
            payload = json.loads(self._b64ud(body))
            if payload.get('exp', 0) < datetime.datetime.utcnow().timestamp():
                return None, 'Token expired. Please log in again.'
            return payload, None
        except Exception as e:
            return None, f'Token decode error: {e}'