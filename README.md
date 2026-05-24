# DermIQ — AI Skin Analyzer
### Full-Stack Web App: Webcam + Auth + CV Scan + AI Plan

---

## 🗂 Project Structure

```
dermiq/
├── run.py                  ← Single entry point  (python run.py)
├── requirements.txt
├── .env.example            ← Copy → .env
├── dermiq.db               ← SQLite (auto-created on first run)
│
├── backend/
│   ├── app.py              ← Flask app + all API routes
│   ├── auth/
│   │   └── auth_manager.py ← JWT + bcrypt
│   └── database/
│       └── db_manager.py   ← SQLite layer
│
├── frontend/
│   └── index_web.html      ← Full UI (auth + webcam + scan + plan)
│
│   ── AI Engine files (copy from original project) ──
├── skin_analyzer.py        ← OpenCV face + skin analysis
├── ai_engine.py            ← Ollama AI wrapper
├── pdf_rag.py              ← PDF knowledge retrieval
└── pdfs/                   ← (optional) PDF knowledge base
```

---

## ⚡ Quick Start — Windows (VS Code)

### Step 1 — Prerequisites
- Python 3.10+ — https://python.org/downloads
- VS Code — https://code.visualstudio.com
- Git (optional) — https://git-scm.com

### Step 2 — Set up project

```bash
# Open VS Code terminal (Ctrl + `)

# 1. Navigate to the project folder
cd path\to\dermiq

# 2. Create virtual environment
python -m venv venv

# 3. Activate it (Windows)
venv\Scripts\activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. (Optional) install dotenv for .env support
pip install python-dotenv
```

### Step 3 — Copy your original engine files

Copy these files into the `dermiq/` root (same level as `run.py`):
- `skin_analyzer.py`
- `ai_engine.py`
- `pdf_rag.py`
- `pdfs/` folder (if you have the PDFs)

### Step 4 — Copy the frontend

Copy the `index_web.html` into the `dermiq/` root:
- `index_web.html`  ← This is the complete integrated UI

### Step 5 — Configure environment

```bash
# Copy env example
copy .env.example .env

# Edit .env and change DERMIQ_SECRET_KEY to something random
```

### Step 6 — Start Ollama (for AI plan generation)

```bash
# In a separate terminal:
ollama serve

# Then pull a model if you haven't:
ollama pull llama3.2
```

### Step 7 — Run DermIQ

```bash
# Make sure venv is active
python run.py
```

Open browser: **http://localhost:5000**

---

## 🔌 API Reference

All protected endpoints require:
```
Authorization: Bearer <jwt_token>
```

### POST /api/signup
Create a new account.

**Request:**
```json
{ "name": "Jane Doe", "email": "jane@example.com", "password": "secret123" }
```

**Response (201):**
```json
{ "success": true, "token": "eyJ...", "user": { "id": 1, "name": "Jane Doe", "email": "jane@example.com" } }
```

---

### POST /api/login
Authenticate and get JWT.

**Request:**
```json
{ "email": "jane@example.com", "password": "secret123" }
```

**Response (200):**
```json
{ "success": true, "token": "eyJ...", "user": { ... } }
```

---

### POST /api/scan  🔒
Scan a face image. Accepts `multipart/form-data` with `image` field.

**Headers:** `Authorization: Bearer <token>`

**Response:**
```json
{
  "success": true,
  "scan": {
    "scan_id": 42,
    "face_detected": true,
    "overall_score": 74.2,
    "overall_grade": "B",
    "concerns": { "acne": { "name": "Acne", "severity": 32.1, "grade": "C", ... } },
    "annotated_image": "<base64>"
  }
}
```

---

### POST /api/generate  🔒
Generate AI skincare plan.

**Headers:** `Authorization: Bearer <token>`

**Request:**
```json
{
  "scan": { ...scan result from /api/scan... },
  "profile": {
    "skin_type": "oily",
    "age_group": "30s",
    "climate": "Hot & humid",
    "current_routine": "basic",
    "sleep_hours": 7,
    "stress_level": 5,
    "sun_exposure_hours": 3,
    "uses_sunscreen": "sometimes",
    "concerns": ["Acne", "Dark Circles"],
    "diet_tags": ["High sugar"],
    "allergies": "fragrance",
    "past_prescriptions": "",
    "extra_notes": ""
  }
}
```

**Response:**
```json
{ "success": true, "plan": "## WHAT YOUR SCAN FOUND...", "rule_output": {...} }
```

---

### GET /api/profile  🔒
Get current user profile + scan history.

**Response:**
```json
{
  "success": true,
  "user": { "id": 1, "name": "Jane Doe", "email": "jane@example.com", "created_at": "..." },
  "scan_history": [
    { "id": 42, "created_at": "...", "overall_score": 74.2, "overall_grade": "B", "face_detected": 1, "has_plan": 1, "concerns": {...} }
  ]
}
```

---

### GET /api/health
Health check — no auth required.

---

## 🧪 Testing with curl / Postman

```bash
# 1. Sign up
curl -X POST http://localhost:5000/api/signup \
  -H "Content-Type: application/json" \
  -d '{"name":"Test User","email":"test@test.com","password":"test1234"}'

# 2. Login
curl -X POST http://localhost:5000/api/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","password":"test1234"}'
# → copy the token from the response

# 3. Scan (replace TOKEN and path to image)
curl -X POST http://localhost:5000/api/scan \
  -H "Authorization: Bearer TOKEN" \
  -F "image=@/path/to/face.jpg"

# 4. Get profile + history
curl http://localhost:5000/api/profile \
  -H "Authorization: Bearer TOKEN"
```

---

## 🗄 Database Schema (SQLite — dermiq.db)

```sql
-- Users table
CREATE TABLE users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL,
  email         TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Scans table (linked to users via FK)
CREATE TABLE scans (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  overall_score REAL,
  overall_grade TEXT,
  face_detected INTEGER DEFAULT 0,
  concerns_json TEXT,    -- JSON blob
  profile_json  TEXT,    -- JSON blob
  plan_text     TEXT,    -- AI-generated plan
  image_b64     TEXT     -- annotated image (capped at ~50KB)
);
```

---

## 🔒 Security Notes

- Passwords are hashed with **bcrypt** (12 rounds) — never stored in plaintext
- JWTs are signed with **HS256** using your `DERMIQ_SECRET_KEY`
- Tokens expire after 72 hours by default
- All scan endpoints check JWT before processing
- **Change `DERMIQ_SECRET_KEY`** before deploying to production!

---

## 🚨 Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: flask_cors` | `pip install flask-cors` |
| `ModuleNotFoundError: bcrypt` | `pip install bcrypt` |
| `ModuleNotFoundError: jwt` | `pip install PyJWT` |
| Camera shows black screen | Ensure HTTPS or localhost; check browser permissions |
| Ollama timeout | Run `ollama serve` in separate terminal |
| `ModuleNotFoundError: cv2` | `pip install opencv-python` |
| DB locked error | Stop any other running instances |

---

## 📱 User Flow

1. **Landing page** → Click "Get Started"
2. **Auth overlay** → Sign up or log in
3. **App modal opens** → Camera panel appears
4. **Click "Open Camera"** → Browser asks for webcam permission
5. **Click "Capture & Scan"** → Frame captured from live video
6. **Click "Analyse Skin"** → Image sent to `/api/scan` with JWT
7. **Results shown** → Score + concern breakdown
8. **Continue to Skin Profile** → Fill questionnaire
9. **Generate My Plan** → AI generates personalized plan via Ollama
10. **View History** → Past scans shown from database

---

*Built with Flask · SQLite · OpenCV · bcrypt · PyJWT · Ollama*
