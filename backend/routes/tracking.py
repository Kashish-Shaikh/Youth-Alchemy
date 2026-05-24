# backend/routes/tracking.py
# NEW FILE — registers the /api/scan-history endpoint on the existing Flask app.
# Import and call register(app, db_mgr, require_auth) from app.py to activate.

import json
import traceback
from flask import request, jsonify


def register(app, db_mgr, require_auth):
    """
    Attach the /api/scan-history route to the existing Flask app.
    Call once from app.py after auth helpers are defined.
    """

    @app.route('/api/scan-history', methods=['GET'])
    @require_auth
    def api_scan_history():
        """
        GET /api/scan-history
        Returns all scans for the logged-in user, oldest first,
        with per-concern severity broken out for graphing.

        Query params:
          ?limit=N    — cap result count (default 120)
          ?days=N     — only scans within last N days (default all)
        """
        try:
            uid   = request.current_user['user_id']
            limit = int(request.args.get('limit', 120))
            days  = int(request.args.get('days', 0))   # 0 = all

            # Fetch from existing db_mgr (newest-first from DB)
            raw = db_mgr.get_scan_history(uid, limit=limit)

            # Optional date filter
            if days > 0:
                import datetime
                cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
                raw = [s for s in raw if (s.get('created_at') or '') >= cutoff]

            # Reverse to oldest-first for charting (frontend may also sort)
            scans = list(reversed(raw))

            # Compute per-scan concern severities as a flat dict for easy graphing
            enriched = []
            for s in scans:
                concern_severities = {}
                for key, c in (s.get('concerns') or {}).items():
                    concern_severities[key] = {
                        'severity': round(c.get('severity', 0), 1),
                        'grade':    c.get('grade', 'A'),
                        'name':     c.get('name', key),
                    }

                enriched.append({
                    'id':            s['id'],
                    'created_at':    s['created_at'],
                    'overall_score': round(s.get('overall_score') or 0, 1),
                    'overall_grade': s.get('overall_grade') or 'A',
                    'face_detected': bool(s.get('face_detected')),
                    'has_plan':      bool(s.get('has_plan')),
                    'concerns':      concern_severities,
                })

            # Compute improvement stats
            stats = {}
            if len(enriched) >= 2:
                first  = enriched[0]
                latest = enriched[-1]
                delta  = latest['overall_score'] - first['overall_score']
                stats = {
                    'first_score':  first['overall_score'],
                    'latest_score': latest['overall_score'],
                    'delta':        round(delta, 1),
                    'pct_change':   round((delta / max(first['overall_score'], 1)) * 100, 1),
                    'total_scans':  len(enriched),
                    'best_score':   max(s['overall_score'] for s in enriched),
                    'worst_score':  min(s['overall_score'] for s in enriched),
                    'avg_score':    round(sum(s['overall_score'] for s in enriched) / len(enriched), 1),
                }

            return jsonify({
                'success': True,
                'scans':   enriched,
                'stats':   stats,
                'total':   len(enriched),
            })

        except Exception as e:
            traceback.print_exc()
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/progress')
    def progress_page():
        """Serve the standalone progress tracking page."""
        import os
        from flask import send_from_directory
        ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return send_from_directory(ROOT, 'progress.html')
