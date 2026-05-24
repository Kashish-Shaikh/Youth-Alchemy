"""
intelligence_layer.py — Youth Alchemy AI Intelligence Bridge
============================================================
Connects the new RAG + Rule + Ingredient + Orchestrator engine
into the existing Flask backend (backend/app.py).

Role:
  - Takes scan results + user profile from the existing pipeline
  - Builds a structured UserProfile for the rule engine
  - Retrieves knowledge from the markdown KB + PDFs via RAGEngine
  - Runs the full rule engine safety filter
  - Runs lifestyle tips engine
  - Enriches the AI prompt BEFORE it goes to Ollama
  - Returns enhanced context: rule output, rag chunks, lifestyle tips

This is an ADDITIVE layer — it does NOT replace anything in app.py.
It is called from app.py's /api/generate endpoint.
"""

import os
import sys
import json
from typing import Dict, Any, Optional, List

# ── Path setup ────────────────────────────────────────────────
_THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR  = os.path.dirname(_THIS_DIR)
_KB_DIR    = os.path.join(_ROOT_DIR, "knowledge_base")
_PDF_DIR   = os.path.join(_ROOT_DIR, "pdfs")

sys.path.insert(0, _ROOT_DIR)
sys.path.insert(0, _THIS_DIR)

# ── Lazy imports (graceful fallback if missing) ───────────────
try:
    from engine.rag_engine import RAGEngine
    from engine.rule_engine import RuleEngine, UserProfile
    from engine.ingredient_product_engine import IngredientEngine
    from engine.orchestrator import LifestyleTipsEngine
    _ENGINE_AVAILABLE = True
except Exception as _e:
    print(f"[IntelligenceLayer] Engine import warning: {_e}")
    _ENGINE_AVAILABLE = False


# ── Singleton instances (built once, reused) ─────────────────
_rag:        Optional["RAGEngine"]         = None
_rule:       Optional["RuleEngine"]        = None
_ingredient: Optional["IngredientEngine"] = None
_lifestyle:  Optional["LifestyleTipsEngine"] = None
_initialized = False


def _init_engines() -> bool:
    """Lazy-initialize all engine components once."""
    global _rag, _rule, _ingredient, _lifestyle, _initialized
    if _initialized:
        return True
    if not _ENGINE_AVAILABLE:
        return False
    try:
        _rag = RAGEngine(_KB_DIR)
        _rag.build()
        _rule       = RuleEngine()
        _ingredient = IngredientEngine()
        _lifestyle  = LifestyleTipsEngine()
        _initialized = True
        print("[IntelligenceLayer] All engines initialized.")
        return True
    except Exception as e:
        print(f"[IntelligenceLayer] Init failed: {e}")
        return False


# ── Profile builder (maps app.py's flat dict → UserProfile) ──

def _map_age(age_group: str) -> str:
    """Convert age_group from app.py format to rule engine format."""
    mapping = {
        "Teens (13-19)": "teens", "teens": "teens",
        "20s": "20s",
        "30s": "30s",
        "40s": "40s_plus", "50s+": "40s_plus", "40s_plus": "40s_plus",
    }
    return mapping.get(age_group, "30s")


def _map_sun(hours: float) -> str:
    if hours >= 4:  return "high"
    if hours <= 1:  return "low"
    return "moderate"


def _map_stress(val: int) -> str:
    if val >= 7: return "high"
    if val <= 3: return "low"
    return "moderate"


def _map_sleep(hours: float) -> str:
    if hours < 6:  return "less_than_6"
    if hours >= 8: return "8_plus"
    return "6_to_8"


def _map_water(diet_tags: List[str]) -> str:
    tags_str = " ".join(diet_tags).lower()
    if "low water" in tags_str:    return "low"
    if "good hydration" in tags_str: return "high"
    return "moderate"


def _extract_allergies(text: str) -> List[str]:
    """Parse free-text allergy field into known allergy keys."""
    text = text.lower()
    mapping = {
        "fragrance": ["fragrance", "parfum"],
        "essential_oils": ["essential oil", "tea tree", "lavender", "eucalyptus"],
        "aspirin": ["aspirin", "salicylate"],
        "nuts": ["nut", "almond", "shea"],
        "tree_nuts": ["tree nut", "almond", "macadamia", "hazelnut"],
        "coconut": ["coconut"],
        "oat": ["oat", "oatmeal"],
        "latex": ["latex", "rubber"],
        "benzoyl_peroxide": ["benzoyl peroxide"],
        "retinoids": ["retinoid", "retinol", "tretinoin"],
        "chemical_sunscreen": ["chemical sunscreen", "oxybenzone", "avobenzone"],
        "propylene_glycol": ["propylene glycol"],
        "vitamin_c": ["vitamin c", "ascorbic acid"],
    }
    found = []
    for key, keywords in mapping.items():
        if any(kw in text for kw in keywords):
            found.append(key)
    return found


def _extract_medications(text: str) -> List[str]:
    """Parse free-text prescription field into known medication keys."""
    text = text.lower()
    mapping = {
        "tetracyclines":   ["doxycycline", "tetracycline", "minocycline"],
        "isotretinoin":    ["isotretinoin", "accutane", "roaccutane"],
        "warfarin":        ["warfarin", "blood thinner"],
        "fluoroquinolones":["fluoroquinolone", "ciprofloxacin", "levofloxacin"],
    }
    found = []
    for key, keywords in mapping.items():
        if any(kw in text for kw in keywords):
            found.append(key)
    return found


def build_user_profile(profile: dict, scan_result: dict) -> "UserProfile":
    """
    Build a rule-engine UserProfile from app.py's profile dict.
    profile = questionnaire data from /api/generate
    scan_result = CV scan output
    """
    allergies_text    = profile.get("allergies", "") or ""
    prescriptions_text = profile.get("past_prescriptions", "") or ""
    diet_tags = profile.get("diet_tags", [])
    concerns  = [c.lower().replace(" & ", "_").replace(" ", "_").replace("/", "_")
                 for c in profile.get("concerns", [])]
    # Merge scan-detected concerns
    scan_concerns = list(scan_result.get("concerns", {}).keys())
    for sc in scan_concerns:
        if sc not in concerns:
            concerns.append(sc)

    climate_map = {
        "Hot & humid": "humid", "Hot & dry": "dry",
        "Cold & dry": "cold", "Cold & wet": "cold",
        "Mild & temperate": "temperate", "Mostly air-conditioned": "dry",
    }

    return UserProfile(
        skin_type    = profile.get("skin_type", "normal").lower(),
        concerns     = concerns,
        allergies    = _extract_allergies(allergies_text),
        medical_conditions = [],
        medications  = _extract_medications(prescriptions_text),
        age_range    = _map_age(profile.get("age_group", "30s")),
        pregnancy_status = "pregnant" in allergies_text.lower() or profile.get("pregnant", False),
        breastfeeding    = profile.get("breastfeeding", False),
        budget           = profile.get("budget", "$$"),
        sun_exposure     = _map_sun(float(profile.get("sun_exposure_hours", 2))),
        routine_status   = profile.get("current_routine", "basic"),
        diet_quality     = ("good" if "Balanced whole foods" in str(diet_tags)
                            else "poor" if any(t in str(diet_tags) for t in ["sugar", "Alcohol", "dairy"])
                            else "average"),
        sleep_hours      = _map_sleep(float(profile.get("sleep_hours", 7))),
        exercise_frequency = "sometimes",
        stress_level     = _map_stress(int(profile.get("stress_level", 5))),
        water_intake     = _map_water(diet_tags),
        smoker           = profile.get("smoker", False),
        prescription_notes = prescriptions_text or None,
        climate          = climate_map.get(profile.get("climate", ""), "temperate"),
        environment      = "urban",
    )


# ── RAG retrieval from markdown KB ───────────────────────────

def _build_rag_query(user_profile: "UserProfile", scan_result: dict) -> str:
    """Build a rich retrieval query from profile + scan."""
    parts = [f"{user_profile.skin_type} skin"]
    parts.extend(user_profile.concerns[:4])
    if user_profile.allergies:
        parts.append(f"allergy {' '.join(user_profile.allergies[:2])}")
    if user_profile.pregnancy_status:
        parts.append("pregnancy safe skincare")
    if user_profile.medications:
        parts.extend(user_profile.medications[:2])
    parts.append(f"sun {user_profile.sun_exposure}")
    parts.append(f"age {user_profile.age_range}")
    # Add scan-detected concerns
    for concern_key, concern_data in scan_result.get("concerns", {}).items():
        if concern_data.get("severity", 0) > 20:
            parts.append(concern_key)
    return " ".join(parts)


def _retrieve_kb_context(user_profile: "UserProfile", scan_result: dict,
                          top_k: int = 6) -> str:
    """Retrieve relevant knowledge base chunks as formatted context string."""
    if not _rag:
        return ""
    try:
        query = _build_rag_query(user_profile, scan_result)
        results_by_type = _rag.retrieve_by_type(
            query=query,
            knowledge_types=["skin_types", "concerns", "ingredients",
                             "allergies", "medical", "products"],
            top_k=top_k
        )
        sections = []
        for ktype, results in results_by_type.items():
            for rr in results[:2]:   # top-2 per type
                chunk = rr.chunk
                if not chunk.structured_fields:
                    continue
                label = chunk.section.replace("SKIN_TYPE:", "").replace("INGREDIENT:", "")\
                                     .replace("CONCERN:", "").replace("PRODUCT:", "").strip()
                # Extract the most useful structured fields as context
                fields = chunk.structured_fields
                lines = [f"[{ktype.upper()} — {label}]"]
                for key in ["Benefits", "Best_For", "Evidence_Based_Treatments",
                            "Ingredients_Best_For", "Recommended_Routine_AM",
                            "Recommended_Routine_PM", "Healthcare_Tips", "Anti_Aging_Tips",
                            "Notes", "Safe_Alternatives", "Avoid_If"]:
                    val = fields.get(key)
                    if val:
                        if isinstance(val, list):
                            val = ", ".join(str(v) for v in val)
                        lines.append(f"  {key}: {val}")
                if len(lines) > 1:
                    sections.append("\n".join(lines))
        return "\n\n".join(sections)
    except Exception as e:
        print(f"[IntelligenceLayer] RAG retrieval error: {e}")
        return ""


# ── Main public function ──────────────────────────────────────

def enhance_generation_context(
    profile: dict,
    scan_result: dict,
    existing_rule_output: dict
) -> Dict[str, Any]:
    """
    PUBLIC API called from backend/app.py's /api/generate endpoint.

    Parameters
    ----------
    profile          : questionnaire dict from the frontend
    scan_result      : dict from /api/scan (concerns, score, grade, etc.)
    existing_rule_output : rule output already computed in app.py (may be {})

    Returns
    -------
    {
      "rule_output"     : enriched rule engine output (ingredients removed/flagged)
      "lifestyle_tips"  : structured healthcare + anti-aging tips
      "kb_context"      : retrieved markdown knowledge base context string
      "ingredient_boosts": list of lifestyle-prioritized ingredients
      "mandatory_notes" : list of mandatory safety additions
      "engine_available": bool
    }
    """
    result = {
        "rule_output":      existing_rule_output or {},
        "lifestyle_tips":   {},
        "kb_context":       "",
        "ingredient_boosts":[],
        "mandatory_notes":  [],
        "engine_available": False,
    }

    if not _init_engines():
        return result

    try:
        user_profile = build_user_profile(profile, scan_result)

        # ── 1. Rule Engine — safety filter ──────────────
        concern_ings = []
        for concern in user_profile.concerns:
            concern_ings.extend(
                _ingredient.CONCERN_INGREDIENT_MAP.get(concern.lower(), [])
            )
        skin_ings = _ingredient.SKIN_TYPE_BASE_INGREDIENTS.get(
            user_profile.skin_type.lower(), []
        )
        all_candidate_ings = list(set(concern_ings + skin_ings))

        rule_result = _rule.apply_all_rules(
            profile=user_profile,
            candidate_ingredients=all_candidate_ings,
            candidate_products=[]
        )

        # Merge with any existing rule output from app.py
        merged_rule = dict(existing_rule_output or {})
        merged_removed = dict(merged_rule.get("removed_ingredients", {}))
        merged_removed.update(rule_result.get("removed_ingredients", {}))
        merged_cautions = list(set(
            merged_rule.get("caution_notes", []) +
            rule_result.get("caution_notes", [])
        ))
        merged_preg = list(set(
            merged_rule.get("pregnancy_notes", []) +
            (["Pregnancy mode — retinoids & hydroquinone removed"] if user_profile.pregnancy_status else [])
        ))
        result["rule_output"] = {
            "removed_ingredients": merged_removed,
            "caution_notes":       merged_cautions,
            "pregnancy_notes":     merged_preg,
            "avoid_list":          rule_result.get("avoid_list", []),
            "safe_ingredients":    rule_result.get("safe_ingredients", []),
        }

        # ── 2. Lifestyle Tips Engine ─────────────────────
        lifestyle = _lifestyle.generate(user_profile)
        result["lifestyle_tips"]    = lifestyle
        result["ingredient_boosts"] = list(lifestyle.get("ingredient_boosts", set()))

        # ── 3. Mandatory additions ────────────────────────
        mandatory = _rule.get_mandatory_additions(user_profile)
        result["mandatory_notes"] = mandatory

        # ── 4. RAG — KB context retrieval ────────────────
        result["kb_context"] = _retrieve_kb_context(user_profile, scan_result)

        result["engine_available"] = True

    except Exception as e:
        print(f"[IntelligenceLayer] enhance_generation_context error: {e}")
        import traceback; traceback.print_exc()

    return result


def format_intelligence_for_prompt(enhanced: Dict[str, Any]) -> str:
    """
    Format the enhanced context into a string block
    that gets injected into the Ollama prompt in ai_engine.py.

    This enriches the prompt with:
    - Safety rules (removed/flagged ingredients)
    - Lifestyle tips & anti-aging tips
    - Evidence-based KB knowledge
    - Ingredient boost priorities
    """
    if not enhanced.get("engine_available"):
        return ""

    lines = ["\n=== INTELLIGENCE LAYER — YOUTH ALCHEMY ENGINE ===\n"]

    # Rule output
    rule = enhanced.get("rule_output", {})
    removed = rule.get("removed_ingredients", {})
    if removed:
        lines.append("SAFETY — REMOVED INGREDIENTS (DO NOT RECOMMEND THESE):")
        for ing, reason in list(removed.items())[:10]:
            lines.append(f"  ✗ {ing}: {reason}")
        lines.append("")

    cautions = rule.get("caution_notes", [])
    if cautions:
        lines.append("SAFETY — CAUTIONS:")
        for c in cautions[:6]:
            lines.append(f"  ⚠ {c}")
        lines.append("")

    preg = rule.get("pregnancy_notes", [])
    if preg:
        lines.append("PREGNANCY NOTES:")
        for n in preg:
            lines.append(f"  🤰 {n}")
        lines.append("")

    # Mandatory additions
    mandatory = enhanced.get("mandatory_notes", [])
    if mandatory:
        lines.append("MANDATORY ADDITIONS:")
        for m in mandatory:
            lines.append(f"  ★ {m.get('ingredient','')}: {m.get('reason','')}")
        lines.append("")

    # Lifestyle tips
    lt = enhanced.get("lifestyle_tips", {})
    hc_tips = lt.get("healthcare_tips", [])
    aa_tips = lt.get("anti_aging_tips", [])
    if hc_tips:
        lines.append("EVIDENCE-BASED HEALTHCARE TIPS (use these in your HEALTHCARE TIPS section):")
        for tip in hc_tips[:6]:
            lines.append(f"  • {tip}")
        lines.append("")
    if aa_tips:
        lines.append("ANTI-AGING TIPS (use these in your ANTI-AGING STRATEGY section):")
        for tip in aa_tips[:5]:
            lines.append(f"  • {tip}")
        lines.append("")

    # Ingredient boosts
    boosts = enhanced.get("ingredient_boosts", [])
    if boosts:
        lines.append(f"LIFESTYLE-PRIORITIZED INGREDIENTS: {', '.join(boosts[:6])}")
        lines.append("  → Prioritize these in your routines based on lifestyle analysis.\n")

    # KB context
    kb = enhanced.get("kb_context", "")
    if kb:
        lines.append("KNOWLEDGE BASE — RETRIEVED EVIDENCE (PRIMARY SOURCE OF TRUTH):")
        lines.append("Use this to support and ground every recommendation with evidence:\n")
        lines.append(kb[:3000])   # cap at 3000 chars to stay within context window
        lines.append("")

    lines.append("=== END INTELLIGENCE LAYER ===\n")
    return "\n".join(lines)
