# ai_engine.py — AI engine for DermIQ Web (Ollama local only)
# Uses RAG context from PDFs + rule engine safety filter

import os, json, urllib.request, urllib.error
from typing import Optional
from dotenv import load_dotenv
load_dotenv()
# Single provider: Ollama (fully local, no API key needed)
PROVIDERS = {
    "ollama": {
        "name": "Ollama (Local — no key needed)",
        "free_tier": "Fully local, free",
        "get_key_url": "https://ollama.ai",
        "key_env": "",
    },
}

SYSTEM_PROMPT = """You are a Youth Alchemy AI skincare specialist with access to a curated evidence-based knowledge base.
You have access to a curated PDF knowledge base of proven skincare solutions.
Use the knowledge base information to make recommendations specific, accurate, and evidence-based.
Every recommendation must be tied to the actual scan data or profile details provided.
Never give generic advice — always explain WHY a recommendation suits THIS specific person.
Flag any conflicts with allergies, pregnancy, or medications immediately.
Be direct, thorough, and actionable. Format with clear ## headers and bullet points."""

PLAN_PROMPT = """
{scan_summary}

{profile_summary}

{rule_engine_output}

{knowledge_context}

Generate a comprehensive personalized skincare plan. Be specific and reference the data above.

## WHAT YOUR SCAN FOUND
Describe each detected concern, its severity, what it means for this person.

## YOUR SKIN PROFILE SUMMARY
2-3 sentences synthesizing scan + lifestyle factors.

## ⚠️ SAFETY ALERTS
Flag any allergy conflicts, pregnancy considerations, medication interactions. If none, say "No safety conflicts detected."

## MORNING ROUTINE (Step by Step)
Number each step. For each: exact product type, key active ingredient, why it suits this person, how to apply.

## EVENING ROUTINE (Step by Step)
Number each step. Include warnings about retinoid/active interactions.

## TARGETED TREATMENTS
Top 2-3 detected concerns: specific treatment from knowledge base, application method, frequency, expected timeline.

## NATURAL REMEDIES (From Knowledge Base)
Specific home remedies from the PDF knowledge base matched to this person's concerns and skin type.

## INGREDIENTS TO SEEK & AVOID
Seek: specific actives with reasons tied to scan findings.
Avoid: based on allergies, pregnancy, medications, skin type.

## ANTI-AGING STRATEGY
Age-group specific with reference to what was detected in the scan.

## LIFESTYLE PRESCRIPTION
Sleep, diet, sun, stress — each tied to a specific scan finding or profile detail.

## HEALTHCARE TIPS
Evidence-based preventive care specific to their detected concerns and lifestyle factors.

## START THIS WEEK
3-5 concrete first steps they can take immediately, ranked by importance.

## 3-MONTH ROADMAP
Month 1: Foundation. Month 2: Add actives. Month 3: Reassess + optimize.

Reference the knowledge base. Every recommendation earns its place by being tied to this person's actual data."""


def http_post(url, headers, body, timeout=90):
    data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise Exception(f"HTTP {e.code}: {e.read().decode('utf-8')[:300]}")
    except urllib.error.URLError as e:
        raise Exception(f"Network error: {e.reason}")



def call_groq(prompt):
    import requests
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise Exception("GROQ_API_KEY environment variable is not set.")

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama3-8b-8192",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 1024
            },
            timeout=30
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[Groq Error] {e}")
        raise

class AIEngine:
    def __init__(self, provider: str, api_key: str, pdf_folder: str):
        self.provider = provider
        self.api_key = api_key
        self.pdf_folder = pdf_folder
    def __init__(self, provider: str, api_key: str, pdf_folder: str):
        self.provider = provider
        self.api_key = api_key
        self.pdf_folder = pdf_folder
        print(f"[DEBUG] GROQ_API_KEY present: {bool(os.environ.get('GROQ_API_KEY'))}")
    def generate(self, scan_result: dict, profile: dict,
                 rule_output: dict, pdf_context: str,
                 image_b64: str = None) -> str:
        """Generate full personalized plan from all inputs — enhanced with Intelligence Layer."""

        scan_summary    = self._fmt_scan(scan_result)
        profile_summary = self._fmt_profile(profile)
        rule_section    = self._fmt_rules(rule_output)

        # ── Intelligence Layer enrichment ──────────────────────
        intelligence_context = ""
        try:
            import sys, os
            _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if _root not in sys.path:
                sys.path.insert(0, _root)
            from engine.intelligence_layer import (
                enhance_generation_context,
                format_intelligence_for_prompt
            )
            enhanced = enhance_generation_context(
                profile=profile,
                scan_result=scan_result,
                existing_rule_output=rule_output
            )
            intelligence_context = format_intelligence_for_prompt(enhanced)
            # Replace rule_section with the enriched one from intelligence layer
            if enhanced.get("engine_available") and enhanced.get("rule_output"):
                rule_section = self._fmt_rules(enhanced["rule_output"])
        except Exception as _il_err:
            print(f"[AIEngine] Intelligence layer skipped: {_il_err}")
        # ─────────────────────────────────────────────────────────

        combined_context = (pdf_context + "\n\n" + intelligence_context)[:6000]  # hard cap

        prompt = PLAN_PROMPT.format(
             scan_summary=scan_summary,
             profile_summary=profile_summary,
             rule_engine_output=rule_section,
             knowledge_context=combined_context
            )

        try:
            return call_groq(prompt)
        except Exception as e:
            return (f"## WHAT YOUR SCAN FOUND\n\nCould not generate plan: {str(e)}\n\n"
                    f"## YOUR SKIN PROFILE SUMMARY\n\nPlease check your GROQ_API_KEY is set correctly.")

    def _fmt_scan(self, scan: dict) -> str:
        lines = ["=== CV SCAN RESULTS ===",
                 f"Overall Score: {scan.get('overall_score',0)}/100  Grade: {scan.get('overall_grade','?')}",
                 f"Face Detected: {scan.get('face_detected', False)}", ""]
        for k, c in scan.get("concerns", {}).items():
            lines.append(f"[{c['name']}]  Severity: {c['severity']}%  Grade: {c['grade']}  Confidence: {c['confidence']}")
            for dk, dv in c.get("details", {}).items():
                lines.append(f"  {dk.replace('_',' ').title()}: {dv}")
            lines.append("")
        return "\n".join(lines)

    def _fmt_profile(self, p: dict) -> str:
        lines = ["=== USER PROFILE ===",
                 f"Skin Type: {p.get('skin_type','?')}",
                 f"Age Group: {p.get('age_group','?')}",
                 f"Concerns (self-reported): {', '.join(p.get('concerns',[]))}",
                 f"Climate: {p.get('climate','?')}",
                 f"Daily Sun Exposure: {p.get('sun_exposure_hours',2)}h",
                 f"Sunscreen: {p.get('uses_sunscreen','?')}",
                 f"Sleep: {p.get('sleep_hours',7)}h/night",
                 f"Stress Level: {p.get('stress_level',5)}/10",
                 f"Diet: {', '.join(p.get('diet_tags',[])) or 'Not specified'}",
                 f"Current Routine: {p.get('current_routine','?')}",
                 f"Allergies/Sensitivities: {p.get('allergies','None') or 'None'}",
                 f"Past Prescriptions: {p.get('past_prescriptions','None') or 'None'}",
                 f"Current Products: {p.get('current_products','None') or 'None'}",
                 f"Extra Notes: {p.get('extra_notes','') or 'None'}"]
        return "\n".join(lines)

    def _fmt_rules(self, rule: dict) -> str:
        if not rule:
            return "=== SAFETY RULES === No safety flags.\n"
        lines = ["=== SAFETY RULE ENGINE OUTPUT ==="]
        removed = rule.get("removed_ingredients", {})
        if removed:
            lines.append(f"REMOVED INGREDIENTS ({len(removed)}):")
            for ing, reason in removed.items():
                lines.append(f"  ✗ {ing}: {reason}")
        cautions = rule.get("caution_notes", [])
        if cautions:
            lines.append("CAUTIONS:")
            for c in cautions[:5]:
                lines.append(f"  ⚠ {c}")
        preg_notes = rule.get("pregnancy_notes", [])
        if preg_notes:
            lines.append("PREGNANCY NOTES:")
            for n in preg_notes:
                lines.append(f"  🤰 {n}")
        lines.append("You MUST NOT recommend any removed ingredients above.")
        return "\n".join(lines)

    def _no_key(self):
        p = PROVIDERS.get(self.provider, {})
        return (f"No API key for {p.get('name',self.provider)}.\n\n"
                f"Get your FREE key at: {p.get('get_key_url','')}\n"
                f"Free tier: {p.get('free_tier','')}\n\n"
                f"Enter it in the API Key field above and regenerate.")