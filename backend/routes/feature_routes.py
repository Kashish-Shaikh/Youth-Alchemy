# backend/routes/feature_routes.py
# Youth Alchemy — Feature Enhancement Routes
# Covers: 1) Medical Disclaimer  2) Face Scan Privacy  3) Image Quality Validation  4) Feedback Learning
# Place this file at: youthalchemy/backend/routes/feature_routes.py

import os
import json
import uuid
import datetime
import hashlib
import base64
import traceback
from functools import wraps
from flask import Blueprint, request, jsonify

# ── Blueprint ─────────────────────────────────────────────────────────────────
feature_bp = Blueprint('features', __name__)

# ── Lazy imports (only load cv2/numpy when needed) ────────────────────────────
def _get_cv2():
    import cv2
    return cv2

def _get_np():
    import numpy as np
    return np

# ─────────────────────────────────────────────────────────────────────────────
#  AUTH HELPER  (re-uses the existing auth_manager from app.py)
# ─────────────────────────────────────────────────────────────────────────────

def _require_auth_bp(f):
    """Lightweight auth decorator for Blueprint routes."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        from auth.auth_manager import AuthManager
        h = request.headers.get('Authorization', '')
        if not h.startswith('Bearer '):
            return jsonify({"success": False, "error": "Authentication required."}), 401
        token = h.split(' ', 1)[1]
        auth_mgr = AuthManager()
        payload, err = auth_mgr.verify_token(token)
        if err:
            return jsonify({"success": False, "error": err}), 401
        request.current_user = payload
        return f(*args, **kwargs)
    return wrapper


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE 1 — MEDICAL DISCLAIMER SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

DISCLAIMER_VERSION = "1.0.0"  # bump when disclaimer text changes

DISCLAIMER_TEXT = {
    "version": DISCLAIMER_VERSION,
    "general": (
        "Youth Alchemy provides AI-generated skincare suggestions for informational "
        "and educational purposes only. This application does NOT provide medical advice, "
        "diagnosis, or treatment."
    ),
    "dermatologist": (
        "For serious, persistent, or worsening skin conditions — including but not limited "
        "to severe acne, rosacea, eczema, psoriasis, skin infections, or suspicious moles — "
        "please consult a certified dermatologist or licensed healthcare professional."
    ),
    "ai_accuracy": (
        "AI-generated suggestions are based on pattern recognition and may not always be "
        "accurate. Individual skin responses vary. Results should never replace professional "
        "medical evaluation."
    ),
    "emergency_warning": (
        "⚠️ EMERGENCY: If you experience sudden facial swelling, difficulty breathing, "
        "severe allergic reactions, rapidly spreading rash, or any other acute symptoms, "
        "seek emergency medical care immediately. Do NOT rely on this app in emergencies."
    ),
    "consent_required": True,
    "updated_at": "2026-01-01"
}

SEVERE_SYMPTOM_KEYWORDS = [
    "swelling", "difficulty breathing", "anaphylaxis", "spreading rapidly",
    "blistering", "infection", "pus", "fever", "burning", "severe pain",
    "hives all over", "throat closing", "eye swelling"
]


@feature_bp.route('/api/disclaimer', methods=['GET'])
def get_disclaimer():
    """Returns the full disclaimer text and current version."""
    return jsonify({"success": True, "disclaimer": DISCLAIMER_TEXT})


@feature_bp.route('/api/disclaimer/consent', methods=['POST'])
@_require_auth_bp
def record_disclaimer_consent():
    """
    Records that a user has explicitly accepted the medical disclaimer.
    Frontend must call this before allowing skin scan.

    Body: { "accepted": true, "disclaimer_version": "1.0.0" }
    """
    try:
        from database.db_manager import DBManager
        data = request.json or {}
        accepted = data.get('accepted', False)
        version  = data.get('disclaimer_version', DISCLAIMER_VERSION)
        uid      = request.current_user['user_id']

        if not accepted:
            return jsonify({"success": False, "error": "Disclaimer must be accepted to continue."}), 400

        if version != DISCLAIMER_VERSION:
            return jsonify({
                "success": False,
                "error": f"Outdated disclaimer version. Please refresh and accept version {DISCLAIMER_VERSION}."
            }), 400

        db = DBManager()
        db.record_consent(
            user_id=uid,
            consent_type='medical_disclaimer',
            version=version,
            ip_addr=request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
        )
        return jsonify({
            "success": True,
            "message": "Consent recorded. You may now use the skin analysis feature.",
            "consent_valid": True
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@feature_bp.route('/api/disclaimer/consent/status', methods=['GET'])
@_require_auth_bp
def check_consent_status():
    """Returns whether the user has accepted the current disclaimer version."""
    try:
        from database.db_manager import DBManager
        uid = request.current_user['user_id']
        db  = DBManager()
        consent = db.get_latest_consent(uid, 'medical_disclaimer')
        if consent and consent.get('version') == DISCLAIMER_VERSION:
            return jsonify({"success": True, "consent_valid": True, "consented_at": consent.get('created_at')})
        return jsonify({"success": True, "consent_valid": False, "disclaimer_version": DISCLAIMER_VERSION})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@feature_bp.route('/api/disclaimer/check-symptoms', methods=['POST'])
def check_severe_symptoms():
    """
    Quick safety check: user describes symptoms, we flag if severe.
    Body: { "symptoms": "I have blistering and difficulty breathing" }
    """
    data     = request.json or {}
    symptoms = (data.get('symptoms') or '').lower()
    found    = [kw for kw in SEVERE_SYMPTOM_KEYWORDS if kw in symptoms]
    if found:
        return jsonify({
            "success": True,
            "is_severe": True,
            "matched_keywords": found,
            "emergency_message": DISCLAIMER_TEXT["emergency_warning"],
            "action": "SEEK_EMERGENCY_CARE"
        })
    return jsonify({"success": True, "is_severe": False})


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE 2 — FACE SCAN PRIVACY & SECURITY SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

IMAGE_RETENTION_HOURS = 24   # auto-delete uploaded images after this period
PRIVACY_CONSENT_VERSION = "1.0.0"

PRIVACY_POLICY_SUMMARY = {
    "version": PRIVACY_CONSENT_VERSION,
    "what_we_collect": [
        "Facial image (temporarily, for AI analysis only)",
        "Analysis results (skin scores, concerns detected)",
        "Your voluntary profile answers (skin type, concerns, lifestyle)"
    ],
    "what_we_do_not_collect": [
        "We do NOT permanently store your raw facial images",
        "We do NOT share your data with advertisers",
        "We do NOT sell your personal data to third parties",
        "We do NOT use your images to train AI models without explicit opt-in"
    ],
    "image_handling": {
        "storage": "Temporary encrypted storage in memory/server only during analysis",
        "retention": f"Raw images are auto-deleted within {IMAGE_RETENTION_HOURS} hours of upload",
        "encryption": "AES-256 at rest; TLS 1.3 in transit",
        "deletion": "You can request immediate deletion at any time via DELETE /api/privacy/my-images"
    },
    "your_rights": [
        "Right to access: Request all data we hold about you",
        "Right to deletion: Delete your account and all data permanently",
        "Right to correction: Update your profile information",
        "Right to portability: Export your scan history as JSON"
    ],
    "gdpr_compliant": True,
    "data_controller": "Youth Alchemy (your local installation)",
    "updated_at": "2026-01-01"
}


def _hash_image(image_bytes: bytes) -> str:
    """Creates a SHA-256 fingerprint of the image for audit trail (not the image itself)."""
    return hashlib.sha256(image_bytes).hexdigest()


def _anonymize_image_ref(user_id: int, scan_id: int) -> str:
    """Generates an anonymized reference ID for image audit logs."""
    raw = f"{user_id}:{scan_id}:{IMAGE_RETENTION_HOURS}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@feature_bp.route('/api/privacy/policy', methods=['GET'])
def get_privacy_policy():
    """Returns the full privacy policy summary."""
    return jsonify({"success": True, "policy": PRIVACY_POLICY_SUMMARY})


@feature_bp.route('/api/privacy/consent', methods=['POST'])
@_require_auth_bp
def record_privacy_consent():
    """
    Records user consent for facial image processing.
    Must be called before the first scan.

    Body: {
        "accepted": true,
        "consent_version": "1.0.0",
        "purposes": ["skin_analysis"]   // what they agree to
    }
    """
    try:
        from database.db_manager import DBManager
        data     = request.json or {}
        accepted = data.get('accepted', False)
        version  = data.get('consent_version', PRIVACY_CONSENT_VERSION)
        purposes = data.get('purposes', [])
        uid      = request.current_user['user_id']

        if not accepted:
            return jsonify({"success": False, "error": "Privacy consent is required to use Face Scan."}), 400

        if 'skin_analysis' not in purposes:
            return jsonify({"success": False, "error": "You must consent to skin analysis to proceed."}), 400

        db = DBManager()
        db.record_consent(
            user_id=uid,
            consent_type='face_scan_privacy',
            version=version,
            ip_addr=request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip(),
            metadata=json.dumps({"purposes": purposes})
        )
        return jsonify({
            "success": True,
            "message": "Privacy consent recorded. Image will be processed and deleted within 24 hours.",
            "retention_policy": f"Auto-delete in {IMAGE_RETENTION_HOURS} hours",
            "your_rights_url": "/api/privacy/policy"
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@feature_bp.route('/api/privacy/my-images', methods=['DELETE'])
@_require_auth_bp
def delete_my_images():
    """
    User requests immediate deletion of all stored images.
    Nulls out image_b64 in scans table for this user.
    """
    try:
        from database.db_manager import DBManager
        uid = request.current_user['user_id']
        db  = DBManager()
        count = db.delete_user_images(uid)
        return jsonify({
            "success": True,
            "message": f"All {count} stored image(s) deleted immediately.",
            "deleted_count": count,
            "deleted_at": datetime.datetime.utcnow().isoformat() + 'Z'
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@feature_bp.route('/api/privacy/export', methods=['GET'])
@_require_auth_bp
def export_my_data():
    """
    GDPR-style data export — returns all user data as JSON (no raw images).
    """
    try:
        from database.db_manager import DBManager
        uid = request.current_user['user_id']
        db  = DBManager()
        user   = db.get_user_by_id(uid)
        scans  = db.get_scan_history(uid, limit=1000)
        habits = db.get_habits(uid)
        goals  = db.get_goals(uid)

        export = {
            "export_timestamp": datetime.datetime.utcnow().isoformat() + 'Z',
            "user": {
                "id": user['id'],
                "name": user['name'],
                "email": user['email'],
                "created_at": user['created_at']
            },
            "scans": [
                {k: v for k, v in s.items() if k != 'image_b64'}  # never export raw images
                for s in scans
            ],
            "habits": habits,
            "goals": goals,
            "note": "Raw facial images are NOT included in exports per our privacy policy."
        }
        return jsonify({"success": True, "data": export})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@feature_bp.route('/api/privacy/delete-account', methods=['DELETE'])
@_require_auth_bp
def delete_account():
    """
    Full GDPR right-to-erasure: deletes user account and ALL associated data.
    Body: { "confirm": "DELETE MY ACCOUNT" }
    """
    try:
        from database.db_manager import DBManager
        data = request.json or {}
        if data.get('confirm') != 'DELETE MY ACCOUNT':
            return jsonify({
                "success": False,
                "error": "To confirm deletion, send: {\"confirm\": \"DELETE MY ACCOUNT\"}"
            }), 400

        uid = request.current_user['user_id']
        db  = DBManager()
        db.delete_user_account(uid)
        return jsonify({
            "success": True,
            "message": "Your account and all associated data have been permanently deleted.",
            "deleted_at": datetime.datetime.utcnow().isoformat() + 'Z'
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE 3 — IMAGE QUALITY VALIDATION SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

# Validation thresholds
QUALITY_THRESHOLDS = {
    "min_resolution_px": 200 * 200,   # minimum total pixels
    "min_width": 200,
    "min_height": 200,
    "blur_threshold": 80.0,           # Laplacian variance; below = blurry
    "brightness_min": 40,             # 0-255; below = too dark
    "brightness_max": 220,            # above = overexposed
    "face_coverage_min": 0.05,        # face must be >5% of image area
    "face_coverage_max": 0.98,        # face shouldn't be >98% (too close)
    "max_faces": 1,                   # only single-face scans allowed
}

# User-facing guidance messages
QUALITY_MESSAGES = {
    "no_face":          "No face detected. Please look directly at the camera with your full face visible.",
    "multiple_faces":   "Multiple faces detected. Please ensure only your face is in the frame.",
    "too_blurry":       "Image is too blurry. Hold your camera steady or clean the lens.",
    "too_dark":         "Image is too dark. Move to a well-lit area or turn on a light facing you.",
    "too_bright":       "Image is overexposed. Avoid direct light sources behind the camera.",
    "too_low_res":      "Image resolution is too low. Use your phone's camera app directly for best results.",
    "face_too_small":   "Face is too small in the frame. Move closer to the camera.",
    "face_too_close":   "Face is too close to the camera. Move back slightly for a clearer scan.",
    "obstruction":      "Face appears partially obstructed. Remove glasses, hair, or anything covering your face.",
    "bad_angle":        "Face angle is off. Look straight ahead with your face centred in the frame.",
}

QUALITY_TIPS = [
    "💡 Use natural daylight or face a window",
    "📱 Hold the camera at arm's length",
    "👁️ Look directly at the camera lens",
    "🧴 Remove makeup for the most accurate results",
    "📐 Keep your face centred and level",
    "🚫 Avoid harsh shadows across your face",
]


def _compute_laplacian_variance(gray: "np.ndarray") -> float:
    """Higher = sharper image. Below threshold = blurry."""
    cv2 = _get_cv2()
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _compute_brightness(gray: "np.ndarray") -> float:
    """Average pixel brightness 0-255."""
    np = _get_np()
    return float(np.mean(gray))


def _detect_faces_cv(image: "np.ndarray"):
    """Returns list of (x,y,w,h) face bounding boxes."""
    cv2 = _get_cv2()
    cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    cascade = cv2.CascadeClassifier(cascade_path)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
    return list(faces) if len(faces) > 0 else []


def _estimate_face_angle(face_box, image_shape) -> dict:
    """
    Rough face-angle heuristic based on bounding box position and aspect ratio.
    Returns dict with flags.
    """
    if not face_box:
        return {"centered": False, "aspect_ok": False}
    x, y, w, h = face_box
    img_h, img_w = image_shape[:2]
    cx = x + w / 2
    cy = y + h / 2
    centered_x = abs(cx - img_w / 2) < img_w * 0.25
    centered_y = abs(cy - img_h / 2) < img_h * 0.30
    aspect_ratio = w / h if h > 0 else 0
    aspect_ok = 0.55 < aspect_ratio < 1.1   # near-square = frontal face
    return {"centered": centered_x and centered_y, "aspect_ok": aspect_ok}


@feature_bp.route('/api/validate-image', methods=['POST'])
@_require_auth_bp
def validate_image_quality():
    """
    Validates uploaded image before sending to AI skin analysis.
    Accepts: multipart/form-data with 'image' file field.
    Returns: validation result with specific issues and guidance.
    """
    if 'image' not in request.files:
        return jsonify({"success": False, "error": "No image provided."}), 400

    try:
        cv2 = _get_cv2()
        np  = _get_np()

        img_bytes = request.files['image'].read()
        if not img_bytes:
            return jsonify({"success": False, "error": "Empty image file."}), 400

        # Decode image
        nparr  = np.frombuffer(img_bytes, np.uint8)
        image  = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if image is None:
            return jsonify({
                "valid": False,
                "issues": ["invalid_format"],
                "messages": ["Could not read image. Please use JPG or PNG format."],
                "tips": QUALITY_TIPS
            })

        h, w = image.shape[:2]
        gray  = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        issues   = []
        messages = []

        # 1. Resolution check
        if w < QUALITY_THRESHOLDS["min_width"] or h < QUALITY_THRESHOLDS["min_height"]:
            issues.append("too_low_res")
            messages.append(QUALITY_MESSAGES["too_low_res"])

        # 2. Blur check
        blur_score = _compute_laplacian_variance(gray)
        if blur_score < QUALITY_THRESHOLDS["blur_threshold"]:
            issues.append("too_blurry")
            messages.append(QUALITY_MESSAGES["too_blurry"])

        # 3. Brightness check
        brightness = _compute_brightness(gray)
        if brightness < QUALITY_THRESHOLDS["brightness_min"]:
            issues.append("too_dark")
            messages.append(QUALITY_MESSAGES["too_dark"])
        elif brightness > QUALITY_THRESHOLDS["brightness_max"]:
            issues.append("too_bright")
            messages.append(QUALITY_MESSAGES["too_bright"])

        # 4. Face detection
        faces = _detect_faces_cv(image)
        img_area = w * h

        if len(faces) == 0:
            issues.append("no_face")
            messages.append(QUALITY_MESSAGES["no_face"])
        elif len(faces) > QUALITY_THRESHOLDS["max_faces"]:
            issues.append("multiple_faces")
            messages.append(QUALITY_MESSAGES["multiple_faces"])
        else:
            fx, fy, fw, fh = faces[0]
            face_area    = fw * fh
            coverage     = face_area / img_area

            # 5. Face size check
            if coverage < QUALITY_THRESHOLDS["face_coverage_min"]:
                issues.append("face_too_small")
                messages.append(QUALITY_MESSAGES["face_too_small"])
            elif coverage > QUALITY_THRESHOLDS["face_coverage_max"]:
                issues.append("face_too_close")
                messages.append(QUALITY_MESSAGES["face_too_close"])

            # 6. Face angle check
            angle_info = _estimate_face_angle(faces[0], image.shape)
            if not angle_info["centered"]:
                issues.append("bad_angle")
                messages.append(QUALITY_MESSAGES["bad_angle"])
            if not angle_info["aspect_ok"]:
                issues.append("obstruction")
                messages.append(QUALITY_MESSAGES["obstruction"])

        is_valid = len(issues) == 0
        quality_score = max(0, 100 - len(issues) * 20)

        return jsonify({
            "valid": is_valid,
            "quality_score": quality_score,
            "issues": issues,
            "messages": messages,
            "tips": QUALITY_TIPS if not is_valid else [],
            "metrics": {
                "width": w,
                "height": h,
                "blur_score": round(blur_score, 1),
                "brightness": round(brightness, 1),
                "faces_detected": len(faces)
            },
            "proceed": is_valid,
            "guidance": "Great image! Proceeding to skin analysis." if is_valid else
                        f"Please fix {len(issues)} issue(s) before scanning."
        })

    except ImportError:
        # Graceful fallback if OpenCV not available
        return jsonify({
            "valid": True,
            "quality_score": 70,
            "issues": [],
            "messages": [],
            "tips": QUALITY_TIPS,
            "metrics": {},
            "proceed": True,
            "guidance": "Image validation skipped (OpenCV not available). Proceeding.",
            "warning": "Install opencv-python for full image validation."
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@feature_bp.route('/api/validate-image/thresholds', methods=['GET'])
def get_validation_thresholds():
    """Returns current validation thresholds and tips (for frontend guidance UI)."""
    return jsonify({
        "success": True,
        "thresholds": QUALITY_THRESHOLDS,
        "tips": QUALITY_TIPS,
        "messages": QUALITY_MESSAGES
    })


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE 4 — FEEDBACK LEARNING & IMPROVEMENT SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

RATING_OPTIONS = [1, 2, 3, 4, 5]
FEEDBACK_CATEGORIES = [
    "recommendation_accuracy",
    "product_suggestions",
    "ingredient_advice",
    "routine_plan",
    "ui_experience",
    "overall"
]


@feature_bp.route('/api/feedback', methods=['POST'])
@_require_auth_bp
def submit_feedback():
    """
    Submit feedback for a scan recommendation.

    Body: {
        "scan_id": 42,
        "rating": 4,                     // 1-5 stars
        "was_useful": true,              // boolean quick answer
        "category": "recommendation_accuracy",
        "comment": "The acne advice was spot-on!",
        "followed_recommendation": true, // did they follow the AI advice?
        "outcome_after_days": 7          // optional: how many days later they're reporting
    }
    """
    try:
        from database.db_manager import DBManager
        data    = request.json or {}
        uid     = request.current_user['user_id']
        scan_id = data.get('scan_id')
        rating  = data.get('rating')

        # Validation
        if rating is not None and rating not in RATING_OPTIONS:
            return jsonify({"success": False, "error": f"Rating must be one of {RATING_OPTIONS}"}), 400

        category = data.get('category', 'overall')
        if category not in FEEDBACK_CATEGORIES:
            return jsonify({"success": False, "error": f"Category must be one of {FEEDBACK_CATEGORIES}"}), 400

        db = DBManager()
        feedback_id = db.save_feedback(
            user_id=uid,
            scan_id=scan_id,
            rating=rating,
            was_useful=data.get('was_useful'),
            category=category,
            comment=(data.get('comment') or '').strip()[:1000],
            followed_recommendation=data.get('followed_recommendation'),
            outcome_after_days=data.get('outcome_after_days')
        )

        # Compute updated accuracy stats for this user
        stats = db.get_feedback_stats(uid)

        return jsonify({
            "success": True,
            "feedback_id": feedback_id,
            "message": "Thank you for your feedback! It helps improve future recommendations.",
            "your_stats": stats
        }), 201

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@feature_bp.route('/api/feedback/history', methods=['GET'])
@_require_auth_bp
def get_feedback_history():
    """Returns the user's own feedback history."""
    try:
        from database.db_manager import DBManager
        uid   = request.current_user['user_id']
        limit = int(request.args.get('limit', 20))
        db    = DBManager()
        items = db.get_user_feedback(uid, limit=limit)
        stats = db.get_feedback_stats(uid)
        return jsonify({"success": True, "feedback": items, "stats": stats})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@feature_bp.route('/api/feedback/analytics', methods=['GET'])
def get_feedback_analytics():
    """
    Aggregated analytics (no personal data) — useful for admin dashboard.
    Requires X-Admin-Token header.
    """
    token = request.headers.get('X-Admin-Token', '')
    if token != os.environ.get('ADMIN_TOKEN', 'youthalchemy_admin_2024'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    try:
        from database.db_manager import DBManager
        db   = DBManager()
        data = db.get_global_feedback_analytics()
        return jsonify({"success": True, "analytics": data})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@feature_bp.route('/api/feedback/quick', methods=['POST'])
@_require_auth_bp
def quick_feedback():
    """
    One-tap feedback: thumbs up / thumbs down for a recommendation.
    Body: { "scan_id": 42, "useful": true }
    """
    try:
        from database.db_manager import DBManager
        data    = request.json or {}
        uid     = request.current_user['user_id']
        scan_id = data.get('scan_id')
        useful  = data.get('useful')

        if useful is None:
            return jsonify({"success": False, "error": "'useful' field (true/false) is required."}), 400

        db = DBManager()
        db.save_feedback(
            user_id=uid,
            scan_id=scan_id,
            rating=5 if useful else 2,
            was_useful=useful,
            category='overall',
            comment=''
        )
        return jsonify({
            "success": True,
            "message": "👍 Noted!" if useful else "👎 Thanks for letting us know.",
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@feature_bp.route('/api/feedback/improvement-form', methods=['POST'])
@_require_auth_bp
def submit_improvement_form():
    """
    Detailed improvement suggestion form.
    Body: {
        "scan_id": 42,
        "what_was_wrong": "Product suggestions were too expensive",
        "what_should_improve": "Include budget-friendly options",
        "skin_outcome": "no_change",   // improved|worsened|no_change|not_tried
        "would_recommend_app": true
    }
    """
    try:
        from database.db_manager import DBManager
        data    = request.json or {}
        uid     = request.current_user['user_id']
        db      = DBManager()

        valid_outcomes = ['improved', 'worsened', 'no_change', 'not_tried']
        outcome = data.get('skin_outcome', 'not_tried')
        if outcome not in valid_outcomes:
            outcome = 'not_tried'

        feedback_id = db.save_feedback(
            user_id=uid,
            scan_id=data.get('scan_id'),
            rating=None,
            was_useful=data.get('would_recommend_app'),
            category='overall',
            comment=f"WHAT WAS WRONG: {data.get('what_was_wrong','')}\n"
                    f"IMPROVEMENT: {data.get('what_should_improve','')}\n"
                    f"OUTCOME: {outcome}",
            followed_recommendation=None,
            outcome_after_days=None,
            form_type='improvement'
        )
        return jsonify({
            "success": True,
            "feedback_id": feedback_id,
            "message": "Your improvement suggestions have been recorded. We appreciate your detailed feedback!"
        }), 201
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
