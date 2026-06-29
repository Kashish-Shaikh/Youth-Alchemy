# app.py — Youth Alchemy Backend (Flask + JWT + SQLite + OpenCV)
# Run: python run.py  (from project root)
# Updated: All 4 feature enhancements integrated
#   1. Medical Disclaimer consent gate
#   2. Face Scan Privacy & Security
#   3. Image Quality Validation
#   4. Feedback Learning System

import os, sys, json, base64, traceback, datetime, hashlib, threading, time
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, BASE_DIR)

# ── Module-level cascade cache — loaded once, reused on every scan request ──
_face_cascade_cache = None
def _get_face_cascade():
    global _face_cascade_cache
    if _face_cascade_cache is None:
        try:
            import cv2
            _face_cascade_cache = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        except Exception:
            pass
    return _face_cascade_cache

from skin_analyzer import get_analyzer
from pdf_rag import PDFRagEngine
from ai_engine import AIEngine, PROVIDERS
from auth.auth_manager import AuthManager
from database.db_manager import DBManager
from routes.feature_routes import feature_bp   # ← EDIT 1: new feature blueprint
from routes.consent_routes import consent_bp   # ← FIX: consent gate blueprint
try:
    sys.path.insert(0, os.path.join(ROOT_DIR, 'engine'))
    from rule_engine import RuleEngine, UserProfile as RuleProfile
    from orchestrator import LifestyleTipsEngine
    RULE_ENGINE_AVAILABLE = True
except Exception as e:
    print(f"[WARN] Rule engine not available: {e}")
    RULE_ENGINE_AVAILABLE = False

app = Flask(__name__, static_folder=os.path.join(ROOT_DIR, 'frontend'))
app.register_blueprint(feature_bp)             # ← EDIT 2: register blueprint
app.register_blueprint(consent_bp)              # ← FIX: was missing, caused "consent required" scan errors
# ── CORS: explicit allow-list instead of "*" ────────────────────────────────
# Set ALLOWED_ORIGINS in Vercel env vars, comma-separated, e.g.:
#   ALLOWED_ORIGINS=https://youthalchemy.com,https://www.youthalchemy.com
# Falls back to localhost dev origins only if the env var is unset.
_allowed_origins_env = os.environ.get('ALLOWED_ORIGINS', '').strip()
if _allowed_origins_env:
    ALLOWED_ORIGINS = [o.strip() for o in _allowed_origins_env.split(',') if o.strip()]
else:
    ALLOWED_ORIGINS = ['http://localhost:3000', 'http://127.0.0.1:3000',
                       'http://localhost:5000', 'http://127.0.0.1:5000']
    print("[WARN] ALLOWED_ORIGINS not set — defaulting to localhost dev origins only. "
          "Set ALLOWED_ORIGINS in production.")

CORS(app, resources={r"/api/*": {
    "origins": ALLOWED_ORIGINS,
    "methods": ["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization"],
    "supports_credentials": False,   # Bearer-token auth, not cookies — no credentials needed
}})
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# ── Security headers on every response ──────────
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options']   = 'nosniff'
    response.headers['X-Frame-Options']           = 'DENY'
    response.headers['X-XSS-Protection']          = '1; mode=block'
    response.headers['Referrer-Policy']            = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy']         = 'camera=(self), microphone=()'
    response.headers['Cache-Control']              = 'no-store, no-cache, must-revalidate'
    # ── Added: HSTS — Vercel terminates TLS, this just enforces it browser-side
    response.headers['Strict-Transport-Security']  = 'max-age=63072000; includeSubDomains'
    # ── Added: CSP — permissive on 'self' so existing inline scripts/styles in
    # index_web.html keep working; tighten to nonces later if you want stricter.
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )
    response.headers['Cross-Origin-Opener-Policy']   = 'same-origin'
    response.headers['Cross-Origin-Resource-Policy']  = 'same-origin'
    response.headers.pop('Server', None)
    return response

# ── Simple in-memory rate limiter (per IP) ──────
import collections
_rate_store = collections.defaultdict(list)
_rate_lock  = threading.Lock()

def _check_rate(ip: str, max_req: int = 20, window_sec: int = 60) -> bool:
    """Returns True if request is allowed, False if rate limited."""
    now = datetime.datetime.utcnow().timestamp()
    with _rate_lock:
        times = _rate_store[ip]
        times = [t for t in times if now - t < window_sec]
        _rate_store[ip] = times
        if len(times) >= max_req:
            return False
        _rate_store[ip].append(now)
    return True

def _get_client_ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr or '0.0.0.0').split(',')[0].strip()

PDF_FOLDER = os.path.join(ROOT_DIR, 'pdfs')
pdf_rag    = PDFRagEngine(PDF_FOLDER)
auth_mgr   = AuthManager()
db_mgr     = DBManager()
app.config['DB_MGR']   = db_mgr     # ← FIX: lets consent_routes.py reach this
app.config['AUTH_MGR'] = auth_mgr
if RULE_ENGINE_AVAILABLE:
    rule_engine      = RuleEngine()
    lifestyle_engine = LifestyleTipsEngine()
else:
    rule_engine = lifestyle_engine = None


# ── AUTH HELPERS ────────────────────────────────────────────────────────────
def get_current_user():
    h = request.headers.get('Authorization', '')
    if not h.startswith('Bearer '): return None, 'Missing Authorization header'
    payload, err = auth_mgr.verify_token(h.split(' ', 1)[1])
    if err: return None, err
    # ← FIX: confirm the user in this token still actually exists in the DB
    if not db_mgr.get_user_by_id(payload['user_id']):
        return None, 'Session invalid — please log in again.'
    return payload, None

def require_auth(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        user, err = get_current_user()
        if err: return jsonify({"success": False, "error": err}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return decorated

# ── PAGES ────────────────────────────────────────────────────────────────────
@app.route('/')
def index(): return send_from_directory(ROOT_DIR, 'index_web.html')

@app.route('/tracking')
def tracking_page(): return send_from_directory(ROOT_DIR, 'tracking.html')

@app.route('/progress')
def progress_page(): return send_from_directory(ROOT_DIR, 'progress.html')

@app.route('/<path:path>')
def static_files(path):
    full = os.path.join(ROOT_DIR, path)
    if os.path.isfile(full): return send_from_directory(ROOT_DIR, path)
    return send_from_directory(ROOT_DIR, 'index_web.html')


# ── AUTH ENDPOINTS ────────────────────────────────────────────────────────────
@app.route('/api/signup', methods=['POST'])
def api_signup():
    ip = _get_client_ip()
    if not _check_rate(ip, max_req=5, window_sec=60):
        return jsonify({"success": False, "error": "Too many requests. Please wait a minute."}), 429
    try:
        data  = request.json or {}
        name  = (data.get('name') or '').strip()
        email = (data.get('email') or '').strip().lower()
        pwd   = (data.get('password') or '').strip()
        if not name or not email or not pwd:
            return jsonify({"success": False, "error": "Name, email and password required."}), 400
        if len(pwd) < 6:
            return jsonify({"success": False, "error": "Password must be at least 6 characters."}), 400
        if '@' not in email:
            return jsonify({"success": False, "error": "Invalid email."}), 400
        if db_mgr.get_user_by_email(email):
            return jsonify({"success": False, "error": "Email already registered."}), 409
        hashed  = auth_mgr.hash_password(pwd)
        user_id = db_mgr.create_user(name=name, email=email, password_hash=hashed)
        token   = auth_mgr.create_token(user_id=user_id, email=email, name=name)
        return jsonify({"success": True, "token": token, "user": {"id": user_id, "name": name, "email": email}}), 201
    except Exception as e:
        traceback.print_exc(); return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/login', methods=['POST'])
def api_login():
    ip = _get_client_ip()
    if not _check_rate(ip, max_req=10, window_sec=60):
        return jsonify({"success": False, "error": "Too many requests. Please wait a minute."}), 429
    try:
        data  = request.json or {}
        email = (data.get('email') or '').strip().lower()
        pwd   = (data.get('password') or '').strip()
        if not email or not pwd:
            return jsonify({"success": False, "error": "Email and password required."}), 400

        failed = db_mgr.get_failed_attempts(email, minutes=15)
        if failed >= 10:
            return jsonify({"success": False, "error": "Account temporarily locked due to too many failed attempts. Try again in 15 minutes."}), 429

        user = db_mgr.get_user_by_email(email)
        if not user or not auth_mgr.verify_password(pwd, user['password_hash']):
            db_mgr.record_login_attempt(email, success=False, ip=ip)
            return jsonify({"success": False, "error": "Invalid email or password."}), 401

        db_mgr.clear_login_attempts(email)
        db_mgr.record_login_attempt(email, success=True, ip=ip)
        token = auth_mgr.create_token(user_id=user['id'], email=user['email'], name=user['name'])
        return jsonify({
            "success": True, "token": token,
            "user": {"id": user['id'], "name": user['name'], "email": user['email']}
        })
    except Exception as e:
        traceback.print_exc(); return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/profile', methods=['GET'])
@require_auth
def api_profile():
    try:
        uid  = request.current_user['user_id']
        user = db_mgr.get_user_by_id(uid)
        if not user: return jsonify({"success": False, "error": "User not found."}), 404
        return jsonify({"success": True, "user": {"id": user['id'], "name": user['name'], "email": user['email'], "created_at": user['created_at']}, "scan_history": db_mgr.get_scan_history(uid)})
    except Exception as e:
        traceback.print_exc(); return jsonify({"success": False, "error": str(e)}), 500


# ── SCAN HISTORY (Powers /progress page) ─────────────────────────────────────
@app.route('/api/scan-history', methods=['GET'])
@require_auth
def api_scan_history():
    try:
        uid   = request.current_user['user_id']
        limit = int(request.args.get('limit', 120))
        days  = int(request.args.get('days', 0))
        raw   = db_mgr.get_scan_history(uid, limit=limit)
        if days > 0:
            cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
            raw = [s for s in raw if (s.get('created_at') or '') >= cutoff]
        scans_asc = list(reversed(raw))
        enriched = []
        for s in scans_asc:
            concern_map = {}
            for key, c in (s.get('concerns') or {}).items():
                concern_map[key] = {'severity': round(c.get('severity', 0), 1), 'grade': c.get('grade', 'A'), 'name': c.get('name', key)}
            enriched.append({'id': s['id'], 'created_at': s['created_at'], 'overall_score': round(s.get('overall_score') or 0, 1), 'overall_grade': s.get('overall_grade') or 'A', 'face_detected': bool(s.get('face_detected')), 'has_plan': bool(s.get('has_plan')), 'concerns': concern_map})
        stats = {}
        if len(enriched) >= 2:
            first = enriched[0]; latest = enriched[-1]; scores = [s['overall_score'] for s in enriched]
            delta = latest['overall_score'] - first['overall_score']
            stats = {'first_score': first['overall_score'], 'latest_score': latest['overall_score'], 'delta': round(delta, 1), 'pct_change': round((delta / max(first['overall_score'], 1)) * 100, 1), 'total_scans': len(enriched), 'best_score': max(scores), 'worst_score': min(scores), 'avg_score': round(sum(scores) / len(scores), 1)}
        return jsonify({'success': True, 'scans': enriched, 'stats': stats, 'total': len(enriched)})
    except Exception as e:
        traceback.print_exc(); return jsonify({'success': False, 'error': str(e)}), 500


# ── CV SCAN ──────────────────────────────────────────────────────────────────
# EDIT 3: Full replacement of api_scan with consent gates + quality validation
@app.route('/api/scan', methods=['POST'])
@require_auth
def api_scan():
    try:
        uid = request.current_user['user_id']
        ip  = _get_client_ip()
        if not _check_rate(ip, max_req=10, window_sec=60):
            return jsonify({"success": False, "error": "Too many requests. Please wait a minute."}), 429

        # ── Gate 1: Medical disclaimer consent ───────────────────────────────
        
        # ── Image upload ──────────────────────────────────────────────────────
        if 'image' not in request.files:
            return jsonify({"success": False, "error": "No image provided."}), 400

        img_bytes = request.files['image'].read()
        if not img_bytes:
            return jsonify({"success": False, "error": "Empty image."}), 400

        # ── Gate 3: Image quality pre-validation ─────────────────────────────
        try:
            import cv2
            import numpy as np

            nparr = np.frombuffer(img_bytes, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if image is not None:
                h, w = image.shape[:2]

                # Pre-resize for quality check — faster cascade detection, ~40% speedup
                check_img = image
                if w > 480:
                    s = 480 / w
                    check_img = cv2.resize(image, (480, int(h * s)), interpolation=cv2.INTER_AREA)
                ch, cw = check_img.shape[:2]

                gray   = cv2.cvtColor(check_img, cv2.COLOR_BGR2GRAY)
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

                # Use cached cascade — avoids file I/O on every request
                cascade = _get_face_cascade()
                faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(40, 40)) if cascade else []
                n_faces = len(faces)

                if n_faces == 0:
                    issues.append("no_face")
                elif n_faces > 1:
                    issues.append("multiple_faces")

                if n_faces == 0:
                    issues.append("no_face")
                elif n_faces > 1:
                    issues.append("multiple_faces")

                quality_score = max(0, 100 - len(issues) * 20)

                # Log quality attempt to DB
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
            pass  # Graceful skip if OpenCV not available

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

        # ── Privacy: log image upload fingerprint (hash, not raw image) ───────
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


# ── GENERATE AI PLAN ───────────────────────────────────────────────────────────
@app.route('/api/generate', methods=['POST'])
@require_auth
def api_generate():
    try:
        data = request.json or {}
        scan_result = data.get('scan', {}); profile = data.get('profile', {})
        rule_output = {}; lifestyle_tips = {}

        # ── Existing rule engine (kept as-is) ─────────────────────────────────
        if RULE_ENGINE_AVAILABLE and rule_engine:
            try:
                rule_profile = _build_rule_profile(profile)
                if rule_profile:
                    rule_result = rule_engine.apply_all_rules(profile=rule_profile, candidate_ingredients=[], candidate_products=[])
                    rule_output = {"removed_ingredients": rule_result.get("removed_ingredients", {}), "caution_notes": rule_result.get("caution_notes", []), "pregnancy_notes": ["Pregnancy mode — retinoids & hydroquinone removed"] if rule_profile.pregnancy_status else []}
                    lifestyle_tips = lifestyle_engine.generate(rule_profile)
            except Exception as e: print(f"[WARN] Rule engine: {e}")

        # ── Intelligence Layer (enriches rule_output + lifestyle_tips) ────────
        try:
            sys.path.insert(0, ROOT_DIR)
            from engine.intelligence_layer import enhance_generation_context
            enhanced = enhance_generation_context(
                profile=profile,
                scan_result=scan_result,
                existing_rule_output=rule_output
            )
            if enhanced.get("engine_available"):
                il_rule = enhanced.get("rule_output", {})
                rule_output["removed_ingredients"] = {
                    **rule_output.get("removed_ingredients", {}),
                    **il_rule.get("removed_ingredients", {})
                }
                rule_output["caution_notes"] = list(set(
                    rule_output.get("caution_notes", []) +
                    il_rule.get("caution_notes", [])
                ))
                rule_output["pregnancy_notes"] = list(set(
                    rule_output.get("pregnancy_notes", []) +
                    il_rule.get("pregnancy_notes", [])
                ))
                if not lifestyle_tips and enhanced.get("lifestyle_tips"):
                    lifestyle_tips = enhanced["lifestyle_tips"]
        except Exception as _il_e:
            print(f"[WARN] Intelligence layer in generate: {_il_e}")

        # ── Generate plan ─────────────────────────────────────────────────────
        concern_keys = list(scan_result.get('concerns', {}).keys())
        profile_kws  = profile.get('concerns', []) + [profile.get('skin_type', '')]
        pdf_context  = pdf_rag.retrieve(concern_keys, profile_kws, max_chars=4500)
        ai = AIEngine(provider='groq', api_key=os.environ.get("GROQ_API_KEY", ""), pdf_folder=PDF_FOLDER)
        plan_text    = ai.generate(scan_result=scan_result, profile=profile, rule_output=rule_output, pdf_context=pdf_context, image_b64=data.get('image_b64'))
        scan_id = scan_result.get('scan_id')
        if scan_id: db_mgr.update_scan_plan(scan_id=scan_id, user_id=request.current_user['user_id'], plan=plan_text)
        return jsonify({"success": True, "plan": plan_text, "lifestyle_tips": lifestyle_tips, "rule_output": rule_output, "rag_topics": pdf_rag.get_topics()})
    except Exception as e:
        traceback.print_exc(); return jsonify({"success": False, "error": str(e)}), 500


# ── CHATBOT ───────────────────────────────────────────────────────────────────
@app.route('/api/chat', methods=['POST'])
def api_chat():
    ip = _get_client_ip()
    if not _check_rate(ip, max_req=30, window_sec=60):
        return jsonify({"success": False, "error": "Too many requests. Please wait a minute."}), 429
    try:
        data = request.json or {}
        message = (data.get('message') or '').strip()
        history = data.get('history', [])
        scan_ctx = data.get('scan_context') or {}
        if not message: return jsonify({"success": False, "error": "Empty message"}), 400
        sys_prompt = _build_chat_system(scan_ctx)
        msgs = [{"role": t.get('role'), "content": t.get('content')} for t in history[-10:] if t.get('role') in ('user','assistant') and t.get('content')]
        msgs.append({"role": "user", "content": message})
        reply = _call_ollama_chat(sys_prompt, msgs)
        return jsonify({"success": True, "reply": reply})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), (503 if "Ollama" in str(e) else 500)

def _build_chat_system(scan_ctx):
    base = "You are Youth Alchemy, a concise AI skincare assistant. STRICT: Reply in 3-6 lines only. Never write long paragraphs. Be direct and actionable. Max 4 bullet points per list. App flow: Get Started→Scan→Questionnaire→Results. My Progress=tracking graphs. Knowledge Centre=ingredients. Warm but brief."
    if scan_ctx and scan_ctx.get('face_detected'):
        concerns_str = ', '.join(scan_ctx.get('top_concerns', [])) or 'none'
        base += f"\n\nUSER SCAN: Score {scan_ctx.get('overall_score',0)}/100 (Grade {scan_ctx.get('overall_grade','?')}). Concerns: {concerns_str}. Reference this for personalised advice."
    else:
        base += "\n\nNo scan data — give general expert advice."
    return base

def _call_ollama_chat(system_prompt, messages):
    import socket, urllib.request, json as _j
    try: s = socket.create_connection(("127.0.0.1", 11434), timeout=2); s.close()
    except: raise Exception("Ollama not running. Run: ollama serve")
    with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=4) as r:
        models = [m["name"] for m in _j.loads(r.read()).get("models", [])]
    prefs = ["llama3.2", "llama3", "mistral", "gemma2", "llama2"]
    model = next((m for p in prefs for m in models if p in m.lower()), models[0] if models else None)
    if not model: raise Exception("No model in Ollama. Run: ollama pull llama3.2")
    body = {"model": model, "messages": [{"role": "system", "content": system_prompt}] + messages, "stream": True, "options": {"temperature": 0.7, "num_predict": 512}}
    req  = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=_j.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    collected = []
    with urllib.request.urlopen(req, timeout=120) as resp:
        while True:
            line = resp.readline().strip()
            if not line: break
            try:
                chunk = _j.loads(line)
                if chunk.get("message", {}).get("content"): collected.append(chunk["message"]["content"])
                if chunk.get("done"): break
            except: continue
    return "".join(collected).strip() or "Could you rephrase that?"


# ── HEALTH & PROVIDERS ────────────────────────────────────────────────────────
@app.route('/api/health', methods=['GET'])
def api_health():
    return jsonify({"status": "ok", "pdf_topics": pdf_rag.get_topics(), "rule_engine": RULE_ENGINE_AVAILABLE, "cv_available": True, "auth": "jwt+bcrypt", "db": "sqlite"})

@app.route('/api/providers', methods=['GET'])
def api_providers():
    return jsonify({"providers": PROVIDERS})


# ── TRACKING ENDPOINTS ────────────────────────────────────────────────────────
@app.route('/api/tracking/summary', methods=['GET'])
@require_auth
def api_tracking_summary():
    try:
        uid = request.current_user['user_id']; days = int(request.args.get('days', 30))
        today = datetime.date.today()
        this_w = [(today - datetime.timedelta(days=i)).isoformat() for i in range(7)]
        habits = db_mgr.get_habits(uid); habit_logs = db_mgr.get_habit_logs(uid, days=days)
        log_set = {(l['habit_id'], l['logged_date']) for l in habit_logs}
        scans = db_mgr.get_scan_history(uid, limit=1)
        return jsonify({"success": True, "score_trend": db_mgr.get_score_trend(uid, days=days), "habits": habits, "habit_logs": habit_logs, "streaks": db_mgr.get_habit_streaks(uid), "completion": db_mgr.get_habit_completion_rate(uid, days=days), "goals": db_mgr.get_goals(uid), "journal": db_mgr.get_journal(uid, limit=7), "products": db_mgr.get_products(uid), "latest_concerns": scans[0]['concerns'] if scans else {}, "today_done": sum(1 for h in habits if (h['id'], today.isoformat()) in log_set), "today_total": len(habits), "this_week": this_w})
    except Exception as e:
        traceback.print_exc(); return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/tracking/habits', methods=['GET'])
@require_auth
def api_get_habits():
    uid = request.current_user['user_id']
    return jsonify({"success": True, "habits": db_mgr.get_habits(uid), "streaks": db_mgr.get_habit_streaks(uid), "logs": db_mgr.get_habit_logs(uid, days=30)})

@app.route('/api/tracking/habits', methods=['POST'])
@require_auth
def api_create_habit():
    uid = request.current_user['user_id']; data = request.json or {}
    name = (data.get('name') or '').strip()
    if not name: return jsonify({"success": False, "error": "Habit name required"}), 400
    hid = db_mgr.create_habit(uid, name, data.get('emoji','✨').strip(), data.get('category','routine').strip())
    return jsonify({"success": True, "habit_id": hid}), 201

@app.route('/api/tracking/habits/<int:habit_id>', methods=['DELETE'])
@require_auth
def api_delete_habit(habit_id):
    db_mgr.delete_habit(habit_id, request.current_user['user_id']); return jsonify({"success": True})

@app.route('/api/tracking/habits/<int:habit_id>/log', methods=['POST'])
@require_auth
def api_log_habit(habit_id):
    uid = request.current_user['user_id']; data = request.json or {}
    db_mgr.log_habit(habit_id, uid, data.get('date') or datetime.date.today().isoformat(), data.get('note',''))
    return jsonify({"success": True})

@app.route('/api/tracking/habits/<int:habit_id>/log', methods=['DELETE'])
@require_auth
def api_unlog_habit(habit_id):
    uid = request.current_user['user_id']
    db_mgr.unlog_habit(habit_id, uid, (request.json or {}).get('date') or datetime.date.today().isoformat())
    return jsonify({"success": True})

@app.route('/api/tracking/goals', methods=['GET'])
@require_auth
def api_get_goals(): return jsonify({"success": True, "goals": db_mgr.get_goals(request.current_user['user_id'])})

@app.route('/api/tracking/goals', methods=['POST'])
@require_auth
def api_create_goal():
    uid = request.current_user['user_id']; data = request.json or {}
    title = (data.get('title') or '').strip()
    if not title: return jsonify({"success": False, "error": "Goal title required"}), 400
    gid = db_mgr.create_goal(uid, title=title, description=data.get('description',''), target_score=float(data.get('target_score',80)), target_date=data.get('target_date',''), concern_key=data.get('concern_key',''))
    return jsonify({"success": True, "goal_id": gid}), 201

@app.route('/api/tracking/goals/<int:goal_id>', methods=['PATCH'])
@require_auth
def api_update_goal(goal_id):
    db_mgr.update_goal_status(goal_id, request.current_user['user_id'], (request.json or {}).get('status','active'))
    return jsonify({"success": True})

@app.route('/api/tracking/journal', methods=['GET'])
@require_auth
def api_get_journal(): return jsonify({"success": True, "entries": db_mgr.get_journal(request.current_user['user_id'], limit=30)})

@app.route('/api/tracking/journal', methods=['POST'])
@require_auth
def api_save_journal():
    uid = request.current_user['user_id']; data = request.json or {}
    eid = db_mgr.save_journal(uid, entry_date=data.get('date') or datetime.date.today().isoformat(), mood=data.get('mood',''), skin_feel=data.get('skin_feel',''), notes=data.get('notes',''), products_used=data.get('products_used',''))
    return jsonify({"success": True, "entry_id": eid})

@app.route('/api/tracking/products', methods=['GET'])
@require_auth
def api_get_products(): return jsonify({"success": True, "products": db_mgr.get_products(request.current_user['user_id'])})

@app.route('/api/tracking/products', methods=['POST'])
@require_auth
def api_add_product():
    uid = request.current_user['user_id']; data = request.json or {}
    name = (data.get('name') or '').strip()
    if not name: return jsonify({"success": False, "error": "Product name required"}), 400
    pid = db_mgr.add_product(uid, name=name, category=data.get('category','Other'), rating=int(data.get('rating',0)), notes=data.get('notes',''))
    return jsonify({"success": True, "product_id": pid}), 201

@app.route('/api/tracking/products/<int:product_id>', methods=['PATCH'])
@require_auth
def api_update_product(product_id):
    uid = request.current_user['user_id']; data = request.json or {}
    db_mgr.update_product(product_id, uid, rating=int(data.get('rating',0)), notes=data.get('notes',''), active=int(data.get('active',1)))
    return jsonify({"success": True})

@app.route('/api/tracking/concern-trend', methods=['GET'])
@require_auth
def api_concern_trend():
    uid = request.current_user['user_id']
    return jsonify({"success": True, "trend": db_mgr.get_concern_trend(uid, request.args.get('concern','acne'), int(request.args.get('days',90)))})


# ── RULE PROFILE BUILDER ──────────────────────────────────────────────────────
def _build_rule_profile(p: dict):
    if not RULE_ENGINE_AVAILABLE: return None
    age_map = {"Teens (13-19)":"teens","teens":"teens","20s":"20s","30s":"30s","40s":"40s_plus","50s+":"40s_plus","40s_plus":"40s_plus"}
    age = age_map.get(p.get("age_group","30s"), "30s")
    sun_h = float(p.get("sun_exposure_hours", 2)); sun = "high" if sun_h >= 4 else "low" if sun_h <= 1 else "moderate"
    stress_v = int(p.get("stress_level", 5)); stress = "high" if stress_v >= 7 else "low" if stress_v <= 3 else "moderate"
    sleep_h = float(p.get("sleep_hours", 7)); sleep = "less_than_6" if sleep_h < 6 else "8_plus" if sleep_h >= 8 else "6_to_8"
    diet_tags = p.get("diet_tags", [])
    diet = "good" if "Balanced whole foods" in str(diet_tags) else "poor" if any(t in str(diet_tags) for t in ["sugar","processed","dairy","irregular","Alcohol"]) else "average"
    water = "low" if "Low water intake" in str(diet_tags) else "high" if "Good hydration" in str(diet_tags) else "moderate"
    allergies_text = (p.get("allergies","") or "").lower()
    known_allergies = []
    for key, kws in {"fragrance":["fragrance","parfum"],"nuts":["nut","almond","shea"],"coconut":["coconut"],"aspirin":["aspirin","salicylate"],"benzoyl_peroxide":["benzoyl peroxide"],"retinoids":["retinoid","retinol"],"essential_oils":["essential oil","tea tree"]}.items():
        if any(kw in allergies_text for kw in kws): known_allergies.append(key)
    meds_text = (p.get("past_prescriptions","") or "").lower()
    medications = []
    for key, kws in {"tetracyclines":["doxycycline","tetracycline","minocycline"],"isotretinoin":["isotretinoin","accutane","roaccutane"],"warfarin":["warfarin","blood thinner"]}.items():
        if any(kw in meds_text for kw in kws): medications.append(key)
    climate_map = {"Hot & humid":"humid","Hot & dry":"dry","Cold & dry":"cold","Cold & wet":"cold","Mild & temperate":"temperate","Mostly air-conditioned":"dry"}
    climate  = climate_map.get(p.get("climate",""), "temperate")
    concerns = [c.lower().replace(" & ","_").replace(" ","_").replace("/","_") for c in p.get("concerns",[])]
    return RuleProfile(skin_type=p.get("skin_type","normal").lower(), concerns=concerns, allergies=known_allergies, medical_conditions=[], medications=medications, age_range=age, pregnancy_status="pregnant" in allergies_text or p.get("pregnant",False), breastfeeding=p.get("breastfeeding",False), sun_exposure=sun, routine_status=p.get("routine_status","basic"), diet_quality=diet, sleep_hours=sleep, stress_level=stress, water_intake=water, smoker=p.get("smoker",False), prescription_notes=p.get("past_prescriptions",None), climate=climate)


# ── APPOINTMENTS ──────────────────────────────────────────────────────────────
ALL_SLOTS = [
    "09:00","09:30","10:00","10:30","11:00","11:30",
    "12:00","14:00","14:30","15:00","15:30","16:00",
    "16:30","17:00","17:30","18:00"
]

@app.route('/api/appointments/availability', methods=['GET'])
def api_availability():
    date_str = request.args.get('date', '')
    if not date_str:
        return jsonify({'success': False, 'error': 'date param required'}), 400
    booked = db_mgr.get_booked_slots(date_str)
    available = [s for s in ALL_SLOTS if s not in booked]
    return jsonify({'success': True, 'date': date_str, 'available': available, 'booked': booked, 'all': ALL_SLOTS})

@app.route('/api/appointments', methods=['POST'])
def api_book_appointment():
    ip = _get_client_ip()
    if not _check_rate(ip, max_req=10, window_sec=60):
        return jsonify({'success': False, 'error': 'Too many requests. Please wait.'}), 429
    try:
        data  = request.json or {}
        name  = (data.get('name') or '').strip()
        email = (data.get('email') or '').strip().lower()
        phone = (data.get('phone') or '').strip()
        date  = (data.get('date') or '').strip()
        time  = (data.get('time') or '').strip()
        if not all([name, email, phone, date, time]):
            return jsonify({'success': False, 'error': 'All fields are required.'}), 400
        if '@' not in email or '.' not in email:
            return jsonify({'success': False, 'error': 'Please enter a valid email address.'}), 400
        import re
        if not re.match(r'^[\d\s\+\-\(\)]{7,15}$', phone):
            return jsonify({'success': False, 'error': 'Please enter a valid phone number.'}), 400
        today = datetime.date.today().isoformat()
        if date < today:
            return jsonify({'success': False, 'error': 'Please select a future date.'}), 400
        if time not in ALL_SLOTS:
            return jsonify({'success': False, 'error': 'Invalid time slot.'}), 400
        appt_id = db_mgr.create_appointment(name=name, email=email, phone=phone, date=date, time=time)
        return jsonify({
            'success': True,
            'message': f'Your appointment has been booked successfully! Appointment #{appt_id} — {date} at {time}.',
            'appointment_id': appt_id
        }), 201
    except ValueError as e:
        if 'SLOT_TAKEN' in str(e):
            return jsonify({'success': False, 'error': 'This time slot is already booked. Please choose another.'}), 409
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/appointments', methods=['GET'])
def api_admin_appointments():
    token = request.headers.get('X-Admin-Token', '')
    if token != os.environ.get('ADMIN_TOKEN', 'youthalchemy_admin_2024'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    appts = db_mgr.get_all_appointments()
    return jsonify({'success': True, 'appointments': appts, 'total': len(appts)})

@app.route('/api/appointments/<int:appt_id>/status', methods=['PATCH'])
def api_update_appt_status(appt_id):
    token = request.headers.get('X-Admin-Token', '')
    if token != os.environ.get('ADMIN_TOKEN', 'youthalchemy_admin_2024'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    status = (request.json or {}).get('status', 'pending')
    db_mgr.update_appointment_status(appt_id, status)
    return jsonify({'success': True})


# ── EDIT 4: Auto Image Cleanup Scheduler (Privacy — 24h retention) ───────────
def _start_image_cleanup_scheduler():
    def _cleanup_loop():
        while True:
            try:
                count = db_mgr.auto_expire_old_images(hours=24)
                if count > 0:
                    print(f"[Privacy Cleanup] Auto-expired {count} image(s) older than 24h.")
            except Exception as _e:
                print(f"[Privacy Cleanup] Error during cleanup: {_e}")
            time.sleep(3600)  # run every hour

    t = threading.Thread(target=_cleanup_loop, daemon=True)
    t.name = "ImageCleanupThread"
    t.start()
    print("[Privacy Cleanup] Auto image cleanup scheduler started (24h retention).")

_start_image_cleanup_scheduler()


# ── ENTRY POINT ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("\n" + "="*55)
    print("  Youth Alchemy — AI Skincare Web App")
    print("="*55)
    print(f"  Pages       : /  |  /progress  |  /tracking")
    print(f"  PDFs loaded : {pdf_rag.get_topics()}")
    print(f"  Rule engine : {RULE_ENGINE_AVAILABLE}")
    print(f"  Auth        : JWT + bcrypt")
    print(f"  Database    : SQLite  (youthalchemy.db)")
    print(f"  Features    : Disclaimer | Privacy | Quality | Feedback")
    print(f"  Open        : http://localhost:5000")
    print("="*55 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=False)