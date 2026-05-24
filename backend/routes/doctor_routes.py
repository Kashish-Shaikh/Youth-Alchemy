# backend/routes/doctor_routes.py
# All doctor-side API endpoints — mount into app.py via register_doctor_routes()

import os
import datetime
import traceback
from flask import Blueprint, request, jsonify

doctor_bp = Blueprint('doctor', __name__)

# ── These are injected at registration time ───────────
_auth_mgr = None
_db_mgr   = None
_mailer   = None   # optional email helper (see email_service.py)


def register_doctor_routes(app, auth_mgr, db_mgr, mailer=None):
    global _auth_mgr, _db_mgr, _mailer
    _auth_mgr = auth_mgr
    _db_mgr   = db_mgr
    _mailer   = mailer
    app.register_blueprint(doctor_bp, url_prefix='/api/doctor')


# ── Auth helpers ─────────────────────────────────────

def _get_doctor():
    """Verify doctor JWT. Returns (doctor_payload, None) or (None, error)."""
    h = request.headers.get('Authorization', '')
    if not h.startswith('Bearer '):
        return None, 'Missing Authorization header'
    payload, err = _auth_mgr.verify_doctor_token(h.split(' ', 1)[1])
    return (payload, None) if not err else (None, err)


def require_doctor(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        doctor, err = _get_doctor()
        if err:
            return jsonify({'success': False, 'error': err}), 401
        request.doctor = doctor
        return f(*args, **kwargs)
    return decorated


# ════════════════════════════════════════════════════
#  AUTH
# ════════════════════════════════════════════════════

@doctor_bp.route('/register', methods=['POST'])
def doctor_register():
    """
    POST /api/doctor/register
    Body: { name, email, password, specialty?, bio? }
    Protected by DOCTOR_REGISTER_KEY env var (set a secret key — not public)
    """
    reg_key = os.environ.get('DOCTOR_REGISTER_KEY', 'youthalchemy-doctor-2025')
    provided = request.headers.get('X-Register-Key', '')
    if provided != reg_key:
        return jsonify({'success': False, 'error': 'Unauthorized registration'}), 403

    data = request.json or {}
    name  = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    pwd   = (data.get('password') or '').strip()
    if not name or not email or not pwd:
        return jsonify({'success': False, 'error': 'name, email, password required'}), 400
    if len(pwd) < 8:
        return jsonify({'success': False, 'error': 'Password must be at least 8 characters'}), 400
    if _db_mgr.get_doctor_by_email(email):
        return jsonify({'success': False, 'error': 'Email already registered'}), 409

    hashed = _auth_mgr.hash_password(pwd)
    doc_id = _db_mgr.create_doctor(
        name=name, email=email, password_hash=hashed,
        specialty=data.get('specialty', 'Dermatology'),
        bio=data.get('bio', '')
    )
    token = _auth_mgr.create_doctor_token(doctor_id=doc_id, email=email, name=name)
    return jsonify({'success': True, 'token': token, 'doctor': {'id': doc_id, 'name': name, 'email': email}}), 201


@doctor_bp.route('/login', methods=['POST'])
def doctor_login():
    """
    POST /api/doctor/login
    Body: { email, password }
    """
    data  = request.json or {}
    email = (data.get('email') or '').strip().lower()
    pwd   = (data.get('password') or '').strip()
    if not email or not pwd:
        return jsonify({'success': False, 'error': 'Email and password required'}), 400

    doctor = _db_mgr.get_doctor_by_email(email)
    if not doctor or not _auth_mgr.verify_password(pwd, doctor['password_hash']):
        return jsonify({'success': False, 'error': 'Invalid credentials'}), 401

    token = _auth_mgr.create_doctor_token(
        doctor_id=doctor['id'], email=doctor['email'], name=doctor['name']
    )
    return jsonify({
        'success': True, 'token': token,
        'doctor': {'id': doctor['id'], 'name': doctor['name'],
                   'email': doctor['email'], 'specialty': doctor['specialty']}
    })


@doctor_bp.route('/me', methods=['GET'])
@require_doctor
def doctor_me():
    doc = _db_mgr.get_doctor_by_id(request.doctor['doctor_id'])
    if not doc:
        return jsonify({'success': False, 'error': 'Doctor not found'}), 404
    return jsonify({'success': True, 'doctor': doc})


# ════════════════════════════════════════════════════
#  AVAILABILITY (weekly schedule)
# ════════════════════════════════════════════════════

@doctor_bp.route('/availability', methods=['GET'])
@require_doctor
def get_availability():
    """GET /api/doctor/availability — returns doctor's weekly schedule."""
    avail = _db_mgr.get_availability(request.doctor['doctor_id'])
    return jsonify({'success': True, 'availability': avail})


@doctor_bp.route('/availability', methods=['POST'])
@require_doctor
def set_availability():
    """
    POST /api/doctor/availability
    Body: { schedule: [ { day_of_week, start_time, end_time, slot_duration } ] }
    Replaces the full weekly schedule.
    """
    data = request.json or {}
    schedule = data.get('schedule', [])
    if not schedule:
        return jsonify({'success': False, 'error': 'schedule array required'}), 400

    doc_id = request.doctor['doctor_id']
    DOW_VALID = range(7)
    SLOT_DURATIONS = {15, 30, 60}

    for entry in schedule:
        dow  = entry.get('day_of_week')
        st   = (entry.get('start_time') or '').strip()
        et   = (entry.get('end_time') or '').strip()
        dur  = int(entry.get('slot_duration', 30))

        if dow not in DOW_VALID:
            return jsonify({'success': False, 'error': f'Invalid day_of_week: {dow}'}), 400
        if not _valid_time(st) or not _valid_time(et):
            return jsonify({'success': False, 'error': f'Invalid times for day {dow}'}), 400
        if st >= et:
            return jsonify({'success': False, 'error': f'start_time must be before end_time for day {dow}'}), 400
        if dur not in SLOT_DURATIONS:
            return jsonify({'success': False, 'error': f'slot_duration must be 15, 30, or 60'}), 400

        entry['available'] = bool(entry.get('available', True))
        if entry['available']:
            _db_mgr.set_availability(doc_id, dow, st, et, dur)
        else:
            _db_mgr.delete_availability(doc_id, dow)

    return jsonify({'success': True, 'message': 'Schedule updated'})


@doctor_bp.route('/availability/<int:day>', methods=['DELETE'])
@require_doctor
def remove_day_availability(day):
    """DELETE /api/doctor/availability/<day> — marks a day as unavailable."""
    if day not in range(7):
        return jsonify({'success': False, 'error': 'day must be 0-6'}), 400
    _db_mgr.delete_availability(request.doctor['doctor_id'], day)
    return jsonify({'success': True})


# ════════════════════════════════════════════════════
#  EMERGENCY OVERRIDES
# ════════════════════════════════════════════════════

@doctor_bp.route('/override', methods=['GET'])
@require_doctor
def list_overrides():
    """GET /api/doctor/override — future overrides for this doctor."""
    overrides = _db_mgr.get_all_overrides(request.doctor['doctor_id'])
    return jsonify({'success': True, 'overrides': overrides})


@doctor_bp.route('/override', methods=['POST'])
@require_doctor
def create_override():
    """
    POST /api/doctor/override
    Body: { date, is_day_off?, start_time?, end_time?, reason? }

    is_day_off=true  → entire day blocked
    is_day_off=false → custom hours for that date only
    """
    data = request.json or {}
    date_str   = (data.get('date') or '').strip()
    is_day_off = bool(data.get('is_day_off', False))
    start_t    = (data.get('start_time') or '').strip() or None
    end_t      = (data.get('end_time') or '').strip() or None
    reason     = (data.get('reason') or '').strip()

    if not date_str:
        return jsonify({'success': False, 'error': 'date required (YYYY-MM-DD)'}), 400
    if date_str < datetime.date.today().isoformat():
        return jsonify({'success': False, 'error': 'Cannot override past dates'}), 400
    if not is_day_off:
        if not start_t or not end_t:
            return jsonify({'success': False, 'error': 'start_time and end_time required when not a day off'}), 400
        if not _valid_time(start_t) or not _valid_time(end_t) or start_t >= end_t:
            return jsonify({'success': False, 'error': 'Invalid time range'}), 400

    doc_id = request.doctor['doctor_id']
    oid = _db_mgr.set_override(doc_id, date_str, start_t, end_t, is_day_off, reason)

    # Notify affected patients if day_off or time change on a date with existing bookings
    _notify_affected_patients(doc_id, date_str, is_day_off, start_t, end_t, reason)

    return jsonify({'success': True, 'override_id': oid, 'message': 'Override set successfully'})


@doctor_bp.route('/override/<int:oid>', methods=['DELETE'])
@require_doctor
def delete_override(oid):
    """DELETE /api/doctor/override/<id> — remove an emergency override."""
    _db_mgr.delete_override(oid, request.doctor['doctor_id'])
    return jsonify({'success': True})


# ════════════════════════════════════════════════════
#  APPOINTMENTS (doctor view)
# ════════════════════════════════════════════════════

@doctor_bp.route('/appointments', methods=['GET'])
@require_doctor
def doctor_appointments():
    """
    GET /api/doctor/appointments?from=YYYY-MM-DD&to=YYYY-MM-DD
    Returns all appointments for this doctor in date range.
    """
    date_from = request.args.get('from')
    date_to   = request.args.get('to')
    appts = _db_mgr.get_appointments_for_doctor(
        doctor_id=request.doctor['doctor_id'],
        date_from=date_from, date_to=date_to
    )
    return jsonify({'success': True, 'appointments': appts, 'total': len(appts)})


@doctor_bp.route('/appointments/<int:appt_id>/status', methods=['PATCH'])
@require_doctor
def update_appt_status(appt_id):
    """PATCH /api/doctor/appointments/<id>/status — confirm/cancel/complete."""
    status = (request.json or {}).get('status', 'pending')
    VALID  = {'pending', 'confirmed', 'cancelled', 'completed'}
    if status not in VALID:
        return jsonify({'success': False, 'error': f'status must be one of {VALID}'}), 400

    _db_mgr.update_appointment_status(appt_id, status, doctor_id=request.doctor['doctor_id'])

    # Email patient on status change
    appt = _db_mgr.get_appointment(appt_id)
    if appt and _mailer:
        try:
            _mailer.send_status_update(appt, status)
        except Exception as e:
            print(f'[EMAIL] Failed to send status update: {e}')

    return jsonify({'success': True})


@doctor_bp.route('/appointments/<int:appt_id>/notes', methods=['PATCH'])
@require_doctor
def add_notes(appt_id):
    """PATCH /api/doctor/appointments/<id>/notes — add consultation notes."""
    notes = (request.json or {}).get('notes', '').strip()
    _db_mgr.add_doctor_notes(appt_id, request.doctor['doctor_id'], notes)
    return jsonify({'success': True})


# ════════════════════════════════════════════════════
#  PATIENT HISTORY (doctor view)
# ════════════════════════════════════════════════════

@doctor_bp.route('/patient/<int:user_id>/history', methods=['GET'])
@require_doctor
def patient_history(user_id):
    """
    GET /api/doctor/patient/<user_id>/history
    Returns full skin history, journal, products for a patient.
    Only accessible if doctor has at least one appointment with this user.
    """
    doc_id = request.doctor['doctor_id']

    # Security gate — doctor must have had an appointment with this patient
    appts = _db_mgr.get_appointments_for_doctor(doc_id)
    patient_ids = {a['user_id'] for a in appts if a.get('user_id')}
    if user_id not in patient_ids:
        return jsonify({'success': False, 'error': 'Access denied — no appointment with this patient'}), 403

    history = _db_mgr.get_patient_full_history(user_id)
    if not history:
        return jsonify({'success': False, 'error': 'Patient not found'}), 404
    return jsonify({'success': True, 'history': history})


@doctor_bp.route('/patient/<int:user_id>/scan/<int:scan_id>/image', methods=['GET'])
@require_doctor
def patient_scan_image(user_id, scan_id):
    """
    GET /api/doctor/patient/<uid>/scan/<sid>/image
    Returns base64 skin scan image — gated to doctor who has appointment with patient.
    """
    doc_id = request.doctor['doctor_id']
    appts  = _db_mgr.get_appointments_for_doctor(doc_id)
    patient_ids = {a['user_id'] for a in appts if a.get('user_id')}
    if user_id not in patient_ids:
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    image = _db_mgr.get_patient_scan_image(scan_id, user_id)
    if image is None:
        return jsonify({'success': False, 'error': 'Scan not found'}), 404
    return jsonify({'success': True, 'image_b64': image})


# ════════════════════════════════════════════════════
#  PUBLIC — doctor list + available slots (for booking UI)
# ════════════════════════════════════════════════════

@doctor_bp.route('/list', methods=['GET'])
def doctor_list():
    """GET /api/doctor/list — public list of active doctors."""
    return jsonify({'success': True, 'doctors': _db_mgr.get_all_doctors()})


@doctor_bp.route('/<int:doctor_id>/slots', methods=['GET'])
def doctor_slots(doctor_id):
    """
    GET /api/doctor/<id>/slots?date=YYYY-MM-DD
    Public endpoint — returns available slots for booking UI.
    """
    date_str = request.args.get('date', '').strip()
    if not date_str:
        return jsonify({'success': False, 'error': 'date param required (YYYY-MM-DD)'}), 400
    try:
        datetime.date.fromisoformat(date_str)
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid date format'}), 400

    result = _db_mgr.get_available_slots(doctor_id, date_str)
    result['success'] = True
    result['doctor_id'] = doctor_id
    result['date'] = date_str
    return jsonify(result)


# ════════════════════════════════════════════════════
#  INTERNAL HELPERS
# ════════════════════════════════════════════════════

def _valid_time(t: str) -> bool:
    """Validate 'HH:MM' 24-hr format."""
    try:
        parts = t.split(':')
        if len(parts) != 2: return False
        h, m = int(parts[0]), int(parts[1])
        return 0 <= h <= 23 and m in (0, 15, 30, 45)
    except Exception:
        return False


def _notify_affected_patients(doctor_id: int, date_str: str,
                               is_day_off: bool, start_t, end_t, reason: str):
    """Email patients who have bookings on the affected date."""
    if not _mailer:
        return
    try:
        appts = _db_mgr.get_appointments_for_doctor(doctor_id, date_from=date_str, date_to=date_str)
        active = [a for a in appts if a['status'] not in ('cancelled', 'completed')]
        for appt in active:
            try:
                if is_day_off:
                    _mailer.send_cancellation_notice(appt, reason)
                else:
                    _mailer.send_reschedule_notice(appt, date_str, start_t, end_t, reason)
            except Exception as e:
                print(f'[EMAIL] Failed for appt {appt["id"]}: {e}')
    except Exception as e:
        print(f'[EMAIL] _notify_affected_patients error: {e}')
