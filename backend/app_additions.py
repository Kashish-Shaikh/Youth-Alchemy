# backend/app_additions.py
# Youth Alchemy — Additions to wire the 4 new features into app.py
#
# HOW TO APPLY:
#   Open  youthalchemy/backend/app.py  and make the following FOUR edits:
#
#   EDIT 1 — After the existing imports block (around line 15), add:
#     from routes.feature_routes import feature_bp
#
#   EDIT 2 — After the line `app = Flask(...)` and before `CORS(...)`, register the blueprint:
#     app.register_blueprint(feature_bp)
#
#   EDIT 3 — Replace the existing api_scan() function with the enhanced version below
#             (adds consent guard + image quality validation call + audit log).
#
#   EDIT 4 — Add the auto-image-cleanup scheduler at the bottom, before `if __name__ == '__main__':`
#
# Place this reference file at: youthalchemy/backend/app_additions.py
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# EDIT 1 — Add to imports block in app.py
# ─────────────────────────────────────────────────────────────────────────────
IMPORT_ADDITION = """
from routes.feature_routes import feature_bp
"""


# ─────────────────────────────────────────────────────────────────────────────
# EDIT 2 — Register blueprint (add right after app = Flask(...) line)
# ─────────────────────────────────────────────────────────────────────────────
BLUEPRINT_REGISTRATION = """
app.register_blueprint(feature_bp)
"""


# ─────────────────────────────────────────────────────────────────────────────
# EDIT 3 — Replace the existing api_scan() with this enhanced version
#           (copy-paste the entire function below into app.py, replacing the old one)
# ─────────────────────────────────────────────────────────────────────────────

def api_scan_enhanced():
    """
    ENHANCED api_scan — replaces the existing @app.route('/api/scan') handler.

    Adds:
      1. Medical disclaimer consent gate
      2. Face-scan privacy consent gate
      3. Image quality pre-validation
      4. Image audit logging (privacy compliance)

    Paste this function body into app.py and decorate it with:
        @app.route('/api/scan', methods=['POST'])
        @require_auth
    """
    import hashlib

    try:
        uid = request.current_user['user_id']

        # ── Gate 1: Medical disclaimer consent ───────────────────────────────
        DISCLAIMER_VERSION = "1.0.0"
        if not db_mgr.has_valid_consent(uid, 'medical_disclaimer', DISCLAIMER_VERSION):
            return jsonify({
                "success": False,
                "error": "Medical disclaimer consent required before scanning.",
                "action_required": "ACCEPT_DISCLAIMER",
                "disclaimer_url": "/api/disclaimer"
            }), 403

        # ── Gate 2: Face-scan privacy consent ────────────────────────────────
        PRIVACY_VERSION = "1.0.0"
        if not db_mgr.has_valid_consent(uid, 'face_scan_privacy', PRIVACY_VERSION):
            return jsonify({
                "success": False,
                "error": "Face scan privacy consent required before scanning.",
                "action_required": "ACCEPT_PRIVACY_CONSENT",
                "privacy_url": "/api/privacy/policy"
            }), 403

        # ── Image upload ──────────────────────────────────────────────────────
        if 'image' not in request.files:
            return jsonify({"success": False, "error": "No image provided."}), 400

        img_bytes = request.files['image'].read()
        if not img_bytes:
            return jsonify({"success": False, "error": "Empty image."}), 400

        # ── Gate 3: Image quality pre-validation ─────────────────────────────
        # Re-use the validation logic from feature_routes inline
        try:
            import cv2, numpy as np

            nparr  = np.frombuffer(img_bytes, np.uint8)
            image  = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if image is not None:
                h, w   = image.shape[:2]
                gray   = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                blur   = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                bright = float(np.mean(gray))

                issues = []
                if w < 200 or h < 200:
                    issues.append("too_low_res")
                if blur < 80.0:
                    issues.append("too_blurry")
                if bright < 40:
                    issues.append("too_dark")
                elif bright > 220:
                    issues.append("too_bright")

                # Quick face count check
                cascade = cv2.CascadeClassifier(
                    cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
                faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))
                n_faces = len(faces)

                if n_faces == 0:
                    issues.append("no_face")
                elif n_faces > 1:
                    issues.append("multiple_faces")

                quality_score = max(0, 100 - len(issues) * 20)

                # Log quality attempt
                db_mgr.save_quality_log(
                    user_id=uid,
                    valid=(len(issues) == 0),
                    quality_score=quality_score,
                    issues=issues,
                    metrics={"blur": round(blur, 1), "brightness": round(bright, 1),
                             "faces": n_faces, "width": w, "height": h}
                )

                if issues:
                    QUALITY_MESSAGES = {
                        "no_face":        "No face detected. Look directly at the camera.",
                        "multiple_faces": "Multiple faces detected. Only one face allowed.",
                        "too_blurry":     "Image is blurry. Hold your camera steady.",
                        "too_dark":       "Too dark. Move to a better-lit area.",
                        "too_bright":     "Overexposed. Avoid direct light in the camera.",
                        "too_low_res":    "Resolution too low. Use your phone camera.",
                    }
                    return jsonify({
                        "success": False,
                        "error": "Image quality too low for accurate analysis.",
                        "quality_issues": issues,
                        "messages": [QUALITY_MESSAGES.get(i, i) for i in issues],
                        "quality_score": quality_score,
                        "tips": [
                            "Use natural daylight or face a window",
                            "Hold the camera at arm's length",
                            "Look straight at the camera lens",
                            "Keep your face centred in the frame"
                        ]
                    }), 422

        except ImportError:
            pass  # Graceful skip if OpenCV unavailable

        # ── Analyse image ─────────────────────────────────────────────────────
        analyzer  = get_analyzer()
        result    = analyzer.analyze_image(img_bytes)
        scan_dict = result.to_dict()
        scan_id   = db_mgr.save_scan(
            user_id=uid,
            scan_data=scan_dict,
            image_b64=scan_dict.get('annotated_image', '')
        )
        scan_dict['scan_id'] = scan_id

        # ── Privacy: log upload action + hash fingerprint ─────────────────────
        image_hash = hashlib.sha256(img_bytes).hexdigest()
        db_mgr.log_image_action(
            user_id=uid,
            scan_id=scan_id,
            action='uploaded',
            image_hash=image_hash
        )

        return jsonify({
            "success": True,
            "scan": scan_dict,
            "privacy_notice": "Your image will be auto-deleted within 24 hours per our privacy policy."
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# EDIT 4 — Auto image cleanup scheduler
#           Add this block at the bottom of app.py, BEFORE `if __name__ == '__main__':`
# ─────────────────────────────────────────────────────────────────────────────
AUTO_CLEANUP_CODE = """
# ── Auto Image Cleanup (Privacy: delete images older than 24h) ────────────────
def _start_image_cleanup_scheduler():
    import threading

    def _cleanup_loop():
        import time
        while True:
            try:
                count = db_mgr.auto_expire_old_images(hours=24)
                if count > 0:
                    print(f"[Privacy Cleanup] Auto-expired {count} image(s) older than 24h.")
            except Exception as _e:
                print(f"[Privacy Cleanup] Error: {_e}")
            time.sleep(3600)  # run every hour

    t = threading.Thread(target=_cleanup_loop, daemon=True)
    t.name = "ImageCleanupThread"
    t.start()
    print("[Privacy Cleanup] Auto image cleanup scheduler started (24h retention).")

_start_image_cleanup_scheduler()
"""
