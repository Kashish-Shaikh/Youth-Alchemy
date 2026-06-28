"""
backend/routes/consent_routes.py
=================================
New file — add to backend/routes/ folder.

Registers all consent / disclaimer endpoints that the scan gate in app.py
depends on.  Does NOT touch your existing feature_routes.py.

ACTIVATE: In backend/app.py, add these two lines anywhere after
          `app = Flask(...)`:

    from routes.consent_routes import consent_bp
    app.register_blueprint(consent_bp)
"""

import datetime
import traceback

from flask import Blueprint, request, jsonify

consent_bp = Blueprint('consent', __name__)

# ── Lazy references to app-level singletons ────────────────────────────────
# Pulled from app.config instead of re-importing app.py, so this works no
# matter how app.py is launched (python app.py / python run.py / -m backend.app).
def _db():
    from flask import current_app
    return current_app.config['DB_MGR']

def _auth():
    from flask import current_app
    return current_app.config['AUTH_MGR']

# ── Inline auth check (avoids circular import with app.require_auth) ────────
def _get_user():
    h = request.headers.get('Authorization', '')
    if not h.startswith('Bearer '):
        return None, (jsonify({"success": False, "error": "Missing Authorization header"}), 401)
    payload, err = _auth().verify_token(h.split(' ', 1)[1])
    if err:
        return None, (jsonify({"success": False, "error": err}), 401)
    return payload, None

# ── Consent versions (must match the constants in app.py) ──────────────────
DISCLAIMER_VERSION = "1.0.0"
PRIVACY_VERSION    = "1.0.0"

DISCLAIMER_TEXT = (
    "MEDICAL DISCLAIMER — Youth Alchemy AI Skincare Platform\n\n"
    "The skin analysis and recommendations provided by this platform are for "
    "informational and educational purposes ONLY. They do NOT constitute medical "
    "advice, diagnosis, or treatment.\n\n"
    "• Always consult a qualified dermatologist or healthcare professional.\n"
    "• AI analysis may produce false positives or negatives.\n"
    "• Do not use this as a substitute for professional medical care.\n\n"
    "By accepting you confirm you are 18+ and understand this is not a medical device."
)

PRIVACY_TEXT = (
    "FACE SCAN PRIVACY POLICY — Youth Alchemy\n\n"
    "What we collect: A photo of your face that you upload.\n"
    "How we use it: Only to run local CV analysis on our server.\n"
    "Retention: Your image is auto-deleted within 24 hours.\n"
    "Storage: Only the analysis result (scores/grades) is saved — not the raw image.\n"
    "Sharing: We do NOT sell or share your image with third parties.\n\n"
    "By accepting you consent to the above terms for this scanning session."
)


# ── Endpoints ───────────────────────────────────────────────────────────────

@consent_bp.route('/api/disclaimer', methods=['GET'])
def get_disclaimer():
    return jsonify({
        "success": True,
        "version": DISCLAIMER_VERSION,
        "disclaimer": DISCLAIMER_TEXT,
        "title": "Medical Disclaimer"
    })


@consent_bp.route('/api/privacy/policy', methods=['GET'])
def get_privacy_policy():
    return jsonify({
        "success": True,
        "version": PRIVACY_VERSION,
        "policy": PRIVACY_TEXT,
        "title": "Face Scan Privacy Policy"
    })


@consent_bp.route('/api/consent/status', methods=['GET'])
def consent_status():
    user, err = _get_user()
    if err:
        return err
    try:
        db  = _db()
        uid = user['user_id']
        return jsonify({
            "success": True,
            "consents": {
                "medical_disclaimer": db.has_valid_consent(uid, 'medical_disclaimer', DISCLAIMER_VERSION),
                "face_scan_privacy":  db.has_valid_consent(uid, 'face_scan_privacy',  PRIVACY_VERSION),
            },
            "versions": {
                "medical_disclaimer": DISCLAIMER_VERSION,
                "face_scan_privacy":  PRIVACY_VERSION,
            }
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@consent_bp.route('/api/consent/medical', methods=['POST'])
def accept_medical():
    user, err = _get_user()
    if err:
        return err
    if not (request.json or {}).get('accepted'):
        return jsonify({"success": False, "error": "accepted must be true"}), 400
    try:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
        _db().record_consent(user['user_id'], 'medical_disclaimer', DISCLAIMER_VERSION, ip)
        return jsonify({"success": True, "message": "Medical disclaimer accepted."})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@consent_bp.route('/api/consent/privacy', methods=['POST'])
def accept_privacy():
    user, err = _get_user()
    if err:
        return err
    if not (request.json or {}).get('accepted'):
        return jsonify({"success": False, "error": "accepted must be true"}), 400
    try:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
        _db().record_consent(user['user_id'], 'face_scan_privacy', PRIVACY_VERSION, ip)
        return jsonify({"success": True, "message": "Privacy consent recorded."})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@consent_bp.route('/api/consent/accept-all', methods=['POST'])
def accept_all():
    """Accept both consents in one call — used by the scan UI modal."""
    user, err = _get_user()
    if err:
        return err
    if not (request.json or {}).get('accepted'):
        return jsonify({"success": False, "error": "accepted must be true"}), 400
    try:
        ip  = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
        db  = _db()
        uid = user['user_id']
        db.record_consent(uid, 'medical_disclaimer', DISCLAIMER_VERSION, ip)
        db.record_consent(uid, 'face_scan_privacy',  PRIVACY_VERSION,   ip)
        return jsonify({
            "success": True,
            "message": "All consents accepted. You may now scan.",
            "consents_accepted": ["medical_disclaimer", "face_scan_privacy"]
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@consent_bp.route('/api/consent/revoke', methods=['POST'])
def revoke_consent():
    user, err = _get_user()
    if err:
        return err
    data = request.json or {}
    ctype = data.get('consent_type', '').strip()
    if ctype not in ('medical_disclaimer', 'face_scan_privacy'):
        return jsonify({"success": False,
                        "error": "consent_type must be 'medical_disclaimer' or 'face_scan_privacy'"}), 400
    try:
        ver = DISCLAIMER_VERSION if ctype == 'medical_disclaimer' else PRIVACY_VERSION
        _db().revoke_consent(user['user_id'], ctype, ver)
        return jsonify({"success": True, "message": f"Consent '{ctype}' revoked."})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500