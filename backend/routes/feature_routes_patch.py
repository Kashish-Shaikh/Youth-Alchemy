"""
feature_routes_patch.py
=======================
This file REPLACES or SUPPLEMENTS  backend/routes/feature_routes.py

It adds all the consent / disclaimer / privacy endpoints that  app.py
references, so the scan gate (which checks has_valid_consent) works end-to-end.

EXISTING ROUTES in your feature_routes.py are preserved — we simply extend
the same blueprint.  If your feature_routes.py already registers some of
these routes, comment out the duplicates below.

ENDPOINTS ADDED
---------------
GET  /api/disclaimer               — return disclaimer text + version
POST /api/consent/medical          — record medical disclaimer acceptance
POST /api/consent/privacy          — record face-scan privacy acceptance
GET  /api/privacy/policy           — return privacy policy text
GET  /api/consent/status           — check which consents the user has given
POST /api/consent/revoke           — revoke a specific consent
"""

import os
import sys
import datetime
import traceback

from flask import Blueprint, request, jsonify

# ── Try to reuse the blueprint from the existing feature_routes module ─────────
# If feature_routes.py already defines `feature_bp`, we add to it.
# Otherwise we create a fresh blueprint.
try:
    # This import will work when Python path is set up by app.py
    from routes.feature_routes import feature_bp as _existing_bp
    feature_bp = _existing_bp
    _IS_EXTENSION = True
except Exception:
    feature_bp = Blueprint('feature', __name__)
    _IS_EXTENSION = False


# ── Lazy access to db_mgr / auth_mgr from app context ─────────────────────────
def _db():
    """Return the DBManager instance from the Flask app (already patched)."""
    from flask import current_app
    import backend.app as _app_module
    return _app_module.db_mgr


def _auth():
    from flask import current_app
    import backend.app as _app_module
    return _app_module.auth_mgr


def _require_auth_inline():
    """Inline auth check — returns (user_payload, error_response | None)."""
    h = request.headers.get('Authorization', '')
    if not h.startswith('Bearer '):
        return None, (jsonify({"success": False, "error": "Missing Authorization header"}), 401)
    payload, err = _auth().verify_token(h.split(' ', 1)[1])
    if err:
        return None, (jsonify({"success": False, "error": err}), 401)
    return payload, None


# ─────────────────────────────────────────────────────────────────────────────
# Disclaimer content
# ─────────────────────────────────────────────────────────────────────────────

DISCLAIMER_VERSION = "1.0.0"
DISCLAIMER_TEXT = """
MEDICAL DISCLAIMER — Youth Alchemy AI Skincare Platform v1.0.0

The skin analysis and recommendations provided by this platform are for
informational and educational purposes only.  They do NOT constitute medical
advice, diagnosis, or treatment.

• Always consult a qualified dermatologist or healthcare professional for
  skin conditions.
• AI-generated analysis may not detect all conditions and can produce
  false positives or negatives.
• Do not use this platform as a substitute for professional medical care.
• If you experience severe skin reactions, consult a doctor immediately.

By accepting you confirm you are 18 years or older and you understand that
this tool is not a medical device.
""".strip()

PRIVACY_VERSION = "1.0.0"
PRIVACY_TEXT = """
FACE SCAN PRIVACY POLICY — Youth Alchemy v1.0.0

What we collect: A photograph of your face uploaded by you.
How we use it: Only to run a local CV analysis on our server.
Retention: Your uploaded image is automatically deleted within 24 hours.
Storage: Only the analysis result (scores, grades) is saved — not the raw image.
Sharing: We do not sell, share, or transmit your image to third parties.
Your rights: You may request deletion of your scan history at any time.

By accepting you consent to the above terms for this scanning session.
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@feature_bp.route('/api/disclaimer', methods=['GET'])
def api_get_disclaimer():
    """Return the medical disclaimer text and version."""
    return jsonify({
        "success": True,
        "version": DISCLAIMER_VERSION,
        "disclaimer": DISCLAIMER_TEXT,
        "title": "Medical Disclaimer"
    })


@feature_bp.route('/api/privacy/policy', methods=['GET'])
def api_get_privacy_policy():
    """Return the face-scan privacy policy."""
    return jsonify({
        "success": True,
        "version": PRIVACY_VERSION,
        "policy": PRIVACY_TEXT,
        "title": "Face Scan Privacy Policy"
    })


@feature_bp.route('/api/consent/medical', methods=['POST'])
def api_accept_medical_disclaimer():
    """
    Record the user's acceptance of the medical disclaimer.
    Body: { "accepted": true }
    """
    user, err = _require_auth_inline()
    if err:
        return err

    data = request.json or {}
    if not data.get('accepted'):
        return jsonify({"success": False, "error": "You must accept the disclaimer to proceed."}), 400

    try:
        ip = (request.headers.get('X-Forwarded-For', request.remote_addr or '')
              .split(',')[0].strip())
        db = _db()
        db.record_consent(
            user_id=user['user_id'],
            consent_type='medical_disclaimer',
            version=DISCLAIMER_VERSION,
            ip_address=ip
        )
        return jsonify({
            "success": True,
            "message": "Medical disclaimer accepted.",
            "consent_type": "medical_disclaimer",
            "version": DISCLAIMER_VERSION
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@feature_bp.route('/api/consent/privacy', methods=['POST'])
def api_accept_privacy_consent():
    """
    Record the user's face-scan privacy consent.
    Body: { "accepted": true }
    """
    user, err = _require_auth_inline()
    if err:
        return err

    data = request.json or {}
    if not data.get('accepted'):
        return jsonify({"success": False, "error": "You must accept the privacy policy to proceed."}), 400

    try:
        ip = (request.headers.get('X-Forwarded-For', request.remote_addr or '')
              .split(',')[0].strip())
        db = _db()
        db.record_consent(
            user_id=user['user_id'],
            consent_type='face_scan_privacy',
            version=PRIVACY_VERSION,
            ip_address=ip
        )
        return jsonify({
            "success": True,
            "message": "Face scan privacy consent recorded.",
            "consent_type": "face_scan_privacy",
            "version": PRIVACY_VERSION
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@feature_bp.route('/api/consent/status', methods=['GET'])
def api_consent_status():
    """
    Return which consents the authenticated user has given.
    Useful for the front-end to decide whether to show the disclaimer modal.
    """
    user, err = _require_auth_inline()
    if err:
        return err

    try:
        db = _db()
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


@feature_bp.route('/api/consent/revoke', methods=['POST'])
def api_revoke_consent():
    """
    Revoke a specific consent.
    Body: { "consent_type": "medical_disclaimer" | "face_scan_privacy" }
    """
    user, err = _require_auth_inline()
    if err:
        return err

    data = request.json or {}
    consent_type = data.get('consent_type', '').strip()
    allowed = {'medical_disclaimer', 'face_scan_privacy'}
    if consent_type not in allowed:
        return jsonify({"success": False, "error": f"Unknown consent_type. Choose from: {allowed}"}), 400

    try:
        version = DISCLAIMER_VERSION if consent_type == 'medical_disclaimer' else PRIVACY_VERSION
        _db().revoke_consent(user['user_id'], consent_type, version)
        return jsonify({"success": True, "message": f"Consent '{consent_type}' revoked."})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: accept BOTH consents in one call (used by the scan UI)
# ─────────────────────────────────────────────────────────────────────────────

@feature_bp.route('/api/consent/accept-all', methods=['POST'])
def api_accept_all_consents():
    """
    Accept both medical_disclaimer and face_scan_privacy in a single call.
    Body: { "accepted": true }
    Useful for a single-checkbox 'I agree to both' UI.
    """
    user, err = _require_auth_inline()
    if err:
        return err

    data = request.json or {}
    if not data.get('accepted'):
        return jsonify({"success": False, "error": "accepted must be true"}), 400

    try:
        ip = (request.headers.get('X-Forwarded-For', request.remote_addr or '')
              .split(',')[0].strip())
        db = _db()
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
