"""
Skincare AI — Main Recommendation Orchestrator v2
Adds: lifestyle tips, anti-aging tips, healthcare tips, prescription awareness,
sun exposure rules, age-based rules, and wellness output section.
"""

import json
import sys
import os
from typing import Dict, List, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.rag_engine import RAGEngine
from engine.rule_engine import RuleEngine, UserProfile
from engine.ingredient_product_engine import IngredientEngine, ProductEngine


# ─────────────────────────────────────────────
# LIFESTYLE TIPS ENGINE
# ─────────────────────────────────────────────

class LifestyleTipsEngine:
    """
    Generates personalized healthcare, lifestyle & anti-aging tips
    based on sun exposure, age, diet, sleep, stress, exercise, smoking,
    routine status, prescription notes, climate and environment.
    """

    def generate(self, profile: UserProfile) -> Dict[str, Any]:
        healthcare = []
        anti_aging = []
        ingredient_boosts = set()
        warnings = []

        # ── Sun Exposure ──────────────────────────────
        sun = profile.sun_exposure or "moderate"
        if sun == "high":
            healthcare += [
                "Reapply SPF 50+ every 2 hours outdoors — this is non-negotiable",
                "Wear UPF 50 clothing and a wide-brim hat during prolonged sun exposure",
                "Apply an antioxidant serum (Vitamin C + E + ferulic acid) every morning — amplifies SPF protection by up to 4×",
                "Seek shade between 10am–4pm when UV index peaks",
                "Schedule an annual full-body skin check with a dermatologist for new or changing moles",
            ]
            anti_aging += [
                "UV radiation drives 80–90% of visible skin aging — SPF is your single highest-ROI anti-aging step",
                "Antioxidants neutralize UV-induced free radicals that directly degrade collagen and elastin",
                "Niacinamide repairs UV-induced DNA damage signals in skin cells",
            ]
            ingredient_boosts.update(["vitamin_c", "niacinamide", "spf50_mineral", "ferulic_acid"])
        elif sun == "low":
            healthcare += [
                "Even indoors, UVA rays penetrate glass — SPF 30+ daily is still recommended",
                "Consider checking your Vitamin D levels — low sun exposure risks deficiency",
                "HEV (blue light) from screens may worsen pigmentation — niacinamide provides protection",
            ]
            anti_aging += [
                "Your skin is less UV-depleted — retinoids and AHA/BHA can be used more liberally at night",
                "Focus anti-aging effort on peptides and retinoids for direct collagen stimulation",
            ]
            ingredient_boosts.update(["retinol", "peptides", "aha_glycolic", "niacinamide"])
        else:
            healthcare += [
                "Daily SPF 30+ minimum — SPF 50 on outdoor days",
                "Add an antioxidant serum every morning for baseline free-radical protection",
            ]
            anti_aging += [
                "Consistent SPF use, even on cloudy days, is the most evidence-backed anti-aging strategy available",
            ]
            ingredient_boosts.update(["vitamin_c", "spf50"])

        # ── Routine Status ────────────────────────────
        routine = profile.routine_status or "basic"
        if routine == "none":
            healthcare += [
                "Start with only 3 products: a gentle cleanser, a simple moisturizer, and SPF",
                "Introduce one new product at a time — wait 2–4 weeks before adding the next",
                "Never skip SPF — it prevents the leading causes of premature aging and skin cancer",
                "Cleanse morning and evening — built-up oil and pollution damage the barrier overnight",
            ]
            anti_aging += [
                "The earlier you start SPF and antioxidants, the more aging damage you prevent — start now",
                "A simple consistent routine always outperforms an inconsistent complex one",
            ]
            warnings.append("No current routine detected — start minimal and build gradually. Never add multiple actives at once.")
        elif routine == "advanced":
            healthcare += [
                "Audit your routine for redundant or conflicting actives — more layers does not equal better results",
                "Avoid mixing AHA/BHA + retinoids on the same night unless skin is fully acclimatized",
                "Watch for over-exfoliation signs: redness, stinging, tightness, or increased breakouts",
                "Incorporate neck and décolleté into your routine — often neglected but it ages first",
            ]
            anti_aging += [
                "Alternate retinoid nights with barrier-repair nights to sustain long-term use without irritation",
                "Peptides and retinoids are complementary — using together gives synergistic collagen stimulation",
            ]

        # ── Age ───────────────────────────────────────
        age = profile.age_range or "30s"
        if age == "teens":
            healthcare += [
                "Keep the routine minimal — gentle cleanser, light moisturizer, SPF is all you need",
                "Change pillowcases at least 2× per week to reduce acne-causing bacteria",
                "Do not use prescription-strength retinoids without dermatologist guidance at this age",
                "Avoid picking or popping spots — it causes scarring and post-inflammatory hyperpigmentation",
            ]
            anti_aging += [
                "SPF from teenage years dramatically reduces cumulative UV damage — this is where prevention starts",
            ]
        elif age == "20s":
            healthcare += [
                "Your 20s are the ideal decade to establish long-term skincare habits",
                "Prioritize sleep quality — collagen synthesis peaks during deep sleep between 11pm–2am",
                "Add antioxidants (Vitamin C) to fight early environmental damage before it compounds",
            ]
            anti_aging += [
                "Collagen production begins declining at ~25 — starting retinol and peptides now is investment, not vanity",
                "Getting into a consistent SPF habit in your 20s prevents 80% of visible aging by your 40s",
                "Add an eye cream with caffeine and peptides — the eye area ages earliest and responds to early care",
            ]
            ingredient_boosts.update(["retinol", "vitamin_c", "peptides", "spf50"])
        elif age == "30s":
            healthcare += [
                "Collagen loss is now measurable — retinol becomes essential this decade",
                "Consider glycolic acid 1–2× per week for cell renewal, texture improvement and brightness",
                "Annual full-body skin exam is important now — watch for new or changing moles",
            ]
            anti_aging += [
                "Loss of facial volume begins mid-30s — hyaluronic acid helps retain moisture and maintain plumpness",
                "Neck and hands need SPF and retinol as much as the face — they are often the first to reveal age",
                "Professional treatments (chemical peels, microneedling) now offer significant returns — consult a dermatologist",
            ]
            ingredient_boosts.update(["retinol", "vitamin_c", "peptides", "glycolic_acid", "hyaluronic_acid"])
        elif age == "40s_plus":
            healthcare += [
                "Skin barrier weakens with age — balance actives with ceramide and barrier-repair products",
                "Switch from a gel moisturizer to a richer cream — sebum production declines significantly",
                "Monthly self-checks for new skin lesions are important at this stage",
                "Discuss prescription tretinoin with your dermatologist — it is the gold standard for this age group",
            ]
            anti_aging += [
                "Peptide-rich creams for face, neck, and hands — use consistently twice daily",
                "Consider silk pillowcases — they reduce friction-induced sleep lines significantly",
                "Eye area needs a dedicated retinol eye cream — fine lines and crepiness respond well to retinoids",
                "Growth factor serums or high-concentration Vitamin C offer intensive anti-aging support",
            ]
            ingredient_boosts.update(["peptides", "vitamin_c", "ceramides", "hyaluronic_acid", "glycolic_acid"])

        # ── Sleep ─────────────────────────────────────
        sleep = profile.sleep_hours or "6_to_8"
        if sleep == "less_than_6":
            healthcare += [
                "Aim for 7–9 hours of quality sleep — this is when the skin's DNA repair enzymes are most active",
                "Apply your most intensive actives (retinol, peptides, AHA) at night — cellular renewal peaks during sleep",
            ]
            anti_aging += [
                "Chronic sleep deprivation significantly accelerates skin aging — measurable in collagen density studies",
                "Growth hormone, which triggers cellular skin repair, is released primarily during deep sleep",
            ]
            warnings.append("Less than 6 hours of sleep significantly impairs skin repair and reduces effectiveness of PM actives.")
        elif sleep == "8_plus":
            healthcare += [
                "Excellent sleep duration — maximize it with a strong PM routine using peptides and retinol",
                "Change pillowcases every 2–3 days — bacteria and oil accumulate rapidly on fabric",
            ]

        # ── Diet ──────────────────────────────────────
        diet = profile.diet_quality or "average"
        if diet == "poor":
            healthcare += [
                "Reduce high-glycemic foods (white bread, sugar, soft drinks) — glycation directly ages collagen fibers",
                "Increase omega-3 rich foods (salmon, walnuts, chia seeds) — reduces skin inflammation measurably",
                "Eat antioxidant-rich foods: blueberries, spinach, green tea — fight UV-induced free radical damage",
                "Add Vitamin C-rich foods (citrus, bell peppers) — essential co-factor for collagen synthesis",
                "Zinc-rich foods (pumpkin seeds, chickpeas) help regulate sebum and acne",
            ]
            anti_aging += [
                "Refined sugar is the number one dietary collagen-killer — reducing it shows measurable skin improvement within weeks",
                "Polyphenols in green tea inhibit enzymes that break down collagen (matrix metalloproteinases)",
            ]
            warnings.append("Poor diet accelerates skin aging through glycation and inflammation — dietary changes will amplify topical results significantly.")
        elif diet == "good":
            healthcare += [
                "Your diet is supporting skin health — maintain omega-3s and antioxidant-rich foods",
                "Consider collagen peptide supplements or bone broth — moderate evidence supports their benefit",
            ]
            anti_aging += [
                "Resveratrol (red grapes, berries) activates longevity pathways — consider topical + dietary pairing",
            ]

        # ── Stress ────────────────────────────────────
        stress = profile.stress_level or "moderate"
        if stress == "high":
            healthcare += [
                "Chronic high stress elevates cortisol, which directly breaks down collagen and triggers excess sebum",
                "Mind-body practices (yoga, meditation, 10 minutes of deep breathing daily) reduce skin cortisol markers",
                "Avoid stress-touching your face — fingertips transfer bacteria and oils directly to pores",
                "Exercise 3–5× per week measurably reduces inflammatory skin markers linked to stress",
            ]
            anti_aging += [
                "Cortisol is a direct collagen-degrading hormone — stress management is a legitimate anti-aging intervention",
                "Exercise increases IL-15 production, which has been shown to rejuvenate skin cells at cellular level",
            ]
            warnings.append("High chronic stress accelerates skin aging via cortisol — consider stress management as integral to your skincare.")

        # ── Water Intake ──────────────────────────────
        water = profile.water_intake or "moderate"
        if water == "low":
            healthcare += [
                "Drink minimum 2L (8 glasses) of water daily — skin is 64% water and hydration directly affects plumpness",
                "Use a bedroom humidifier — especially important in air-conditioned or winter environments",
                "Caffeinated drinks and alcohol are diuretics — compensate with extra water intake",
            ]
            anti_aging += [
                "Chronic dehydration accelerates the visible appearance of fine lines — topical products work better on well-hydrated skin",
            ]
            warnings.append("Low water intake reduces effectiveness of all hydrating topical products.")

        # ── Exercise ──────────────────────────────────
        exercise = profile.exercise_frequency or "sometimes"
        if exercise == "regularly":
            healthcare += [
                "Cleanse skin before exercising — makeup and pollution combined with sweat clogs pores",
                "Always cleanse thoroughly after exercise — sweat residue creates a pore-clogging environment",
                "Use mineral SPF for outdoor exercise — won't run into eyes and provides clean protection",
            ]
            anti_aging += [
                "Regular aerobic exercise increases skin thickness and promotes younger cellular skin markers — well-documented in 30+ age groups",
            ]
        elif exercise == "rarely":
            healthcare += [
                "Even 20 minutes of brisk walking 3× per week measurably improves skin circulation",
            ]
            anti_aging += [
                "Exercise boosts growth hormone which supports skin cell repair — even light activity makes a difference",
            ]

        # ── Smoking ───────────────────────────────────
        if profile.smoker:
            healthcare += [
                "Smoking reduces blood flow to the skin by approximately 30%, causing dullness and impaired wound healing",
                "Nicotine depletes Vitamin C — a critical co-factor for collagen synthesis — increase supplementation",
                "Quitting smoking shows measurable skin improvement within 4–6 weeks of cessation",
            ]
            anti_aging += [
                "Smoking breaks down collagen and elastin at 10× the normal rate — it is the second biggest skin ager after UV exposure",
                "Significantly increase your antioxidant concentrations (Vitamin C serum, resveratrol) to compensate for ongoing oxidative damage",
            ]
            ingredient_boosts.update(["vitamin_c_high", "resveratrol", "niacinamide"])
            warnings.append("Smoking significantly impairs skin repair and accelerates collagen breakdown — topical actives have reduced effectiveness without addressing this.")

        # ── Prescription awareness ────────────────────
        if profile.prescription_notes and profile.prescription_notes.strip():
            healthcare += [
                "You have noted prescription medications — always consult your prescribing physician before starting new topical actives",
                "If your prescription includes any retinoid (tretinoin, tazarotene, adapalene, isotretinoin), do not add additional OTC retinol — this causes dangerous over-retinization",
                "If your prescription includes oral antibiotics, ensure strict SPF use — most antibiotics increase photosensitivity significantly",
                "Share your full skincare ingredient list with your pharmacist to screen for drug-topical interactions",
            ]
            warnings.append(f"Prescription medications noted — medication interaction review applied. Always confirm skincare routine with your physician before starting.")

        # ── Climate / Environment ─────────────────────
        if profile.climate == "dry":
            healthcare += [
                "Dry climate requires richer moisturizers and occlusives — seal in hydration with squalane or petrolatum as final PM step",
                "A bedroom humidifier is highly recommended — ambient humidity below 30% causes significant overnight moisture loss",
            ]
            ingredient_boosts.add("squalane")
        elif profile.climate == "humid":
            healthcare += [
                "Humid climate suits lighter moisturizers and gel textures — heavy creams can cause congestion and breakouts",
            ]
        elif profile.climate == "cold":
            healthcare += [
                "Cold weather damages the skin barrier — increase ceramides and rich moisturizers in winter months",
                "Avoid long hot showers in cold weather — they strip the lipid barrier significantly",
            ]
            ingredient_boosts.add("ceramides")

        if profile.environment == "urban":
            healthcare += [
                "Urban pollution (PM2.5 particles, PAHs) generates free radicals that accelerate skin aging",
                "Double cleanse in the evening with an oil cleanser followed by a foam or cream cleanser — removes pollution particles regular cleansing misses",
            ]
            anti_aging += [
                "Pollution-induced skin aging is now well-documented — niacinamide + antioxidant serums are your primary defense",
            ]
            ingredient_boosts.add("niacinamide")

        return {
            "healthcare_tips": list(dict.fromkeys(healthcare)),
            "anti_aging_tips": list(dict.fromkeys(anti_aging)),
            "ingredient_boosts": list(ingredient_boosts),
            "lifestyle_warnings": list(dict.fromkeys(warnings)),
            "lifestyle_profile": {
                "sun_exposure": sun,
                "age_group": age,
                "routine_status": routine,
                "sleep": sleep,
                "diet": diet,
                "stress": stress,
                "water": water,
                "exercise": exercise,
                "smoker": profile.smoker,
                "climate": profile.climate or "not specified",
                "environment": profile.environment or "not specified",
            }
        }


# ─────────────────────────────────────────────
# OUTPUT BUILDER
# ─────────────────────────────────────────────

def build_recommendation_output(
    profile, rule_result, ingredient_recs, product_recs,
    routine, avoid_list, caution_notes, mandatory_additions, lifestyle_output
) -> Dict[str, Any]:

    am_ingredients = [r.to_dict() for r in ingredient_recs
                      if "AM" in r.use_time or r.is_mandatory]
    pm_ingredients = [r.to_dict() for r in ingredient_recs
                      if "PM" in r.use_time and not r.is_mandatory]

    return {
        "profile_summary": {
            "skin_type": profile.skin_type,
            "concerns": profile.concerns,
            "allergies": profile.allergies,
            "medical_conditions": profile.medical_conditions,
            "medications": profile.medications,
            "pregnancy_status": profile.pregnancy_status,
            "breastfeeding": profile.breastfeeding,
            "age_range": profile.age_range,
            "sun_exposure": profile.sun_exposure,
            "routine_status": profile.routine_status,
        },
        "morning_routine": {
            "step_by_step": [
                {"step": i+1, "product": rec.name, "brand": rec.brand,
                 "type": rec.product_type, "price": rec.price_range,
                 "key_ingredients": rec.key_ingredients, "why": rec.why_recommended,
                 "caution": rec.caution_note or ""}
                for i, rec in enumerate(routine.get("morning", []))
            ],
            "key_ingredients_am": am_ingredients
        },
        "evening_routine": {
            "step_by_step": [
                {"step": i+1, "product": rec.name, "brand": rec.brand,
                 "type": rec.product_type, "price": rec.price_range,
                 "key_ingredients": rec.key_ingredients, "why": rec.why_recommended,
                 "caution": rec.caution_note or ""}
                for i, rec in enumerate(routine.get("evening", []))
            ],
            "key_ingredients_pm": pm_ingredients
        },
        "all_recommended_products": [r.to_dict() for r in product_recs[:8]],
        "avoid_list": {
            "ingredients": list(rule_result.get("removed_ingredients", {}).keys()),
            "products": list(rule_result.get("removed_products", {}).keys()),
            "reasons": rule_result.get("removed_ingredients", {})
        },
        "safety_notes": {
            "cautions": list(set(caution_notes)),
            "mandatory_additions": mandatory_additions,
            "rule_engine_log": rule_result.get("rule_log", [])
        },
        "lifestyle_tips": lifestyle_output,
        "key_ingredients": ingredient_recs,
        "explanation": _build_explanation(profile, ingredient_recs, rule_result, lifestyle_output)
    }


def _build_explanation(profile, ingredient_recs, rule_result, lifestyle_output) -> str:
    lines = []
    lines.append(f"Your personalized routine is built for {profile.skin_type} skin")
    if profile.concerns:
        lines.append(f"targeting: {', '.join(c.replace('_',' ') for c in profile.concerns)}.")
    if profile.pregnancy_status:
        lines.append("All retinoids and hydroquinone removed — safe pregnancy alternatives recommended.")
    if profile.allergies:
        lines.append(f"All {', '.join(profile.allergies)} allergens completely removed.")
    if profile.medications:
        lines.append(f"Medication interactions ({', '.join(profile.medications[:2])}) accounted for.")
    removed = rule_result.get("removed_ingredients", {})
    if removed:
        lines.append(f"{len(removed)} ingredient(s) removed for safety.")
    top_ings = [r.display_name for r in ingredient_recs[:3] if not r.is_mandatory]
    if top_ings:
        lines.append(f"Key recommended actives: {', '.join(top_ings)}.")
    boosts = lifestyle_output.get("ingredient_boosts", [])
    if boosts:
        lines.append(f"Lifestyle-prioritized ingredients: {', '.join(list(boosts)[:3])}.")
    return " ".join(lines)


# ─────────────────────────────────────────────
# ORCHESTRATOR
# ─────────────────────────────────────────────

class SkincareRecommendationEngine:
    def __init__(self, knowledge_base_dir: str):
        self.rag = RAGEngine(knowledge_base_dir)
        self.rule_engine = RuleEngine()
        self.ingredient_engine = IngredientEngine()
        self.product_engine = ProductEngine()
        self.lifestyle_engine = LifestyleTipsEngine()
        self._initialized = False

    def initialize(self) -> None:
        self.rag.build()
        self._initialized = True
        print("[SkincareAI] Engine initialized and ready.")

    def recommend(self, profile: UserProfile) -> Dict[str, Any]:
        if not self._initialized:
            self.initialize()

        print(f"\n[Pipeline] {profile.skin_type} | age={profile.age_range} | "
              f"sun={profile.sun_exposure} | concerns={profile.concerns}")

        query = self._build_query(profile)
        retrieved = self.rag.retrieve_by_type(
            query=query,
            knowledge_types=["skin_types", "concerns", "ingredients",
                              "allergies", "medical", "products"],
            top_k=5
        )

        all_retrieved = []
        for chunks in retrieved.values():
            all_retrieved.extend(chunks)
        raw_ingredients = list(self.ingredient_engine.extract_from_chunks(all_retrieved))

        all_product_chunks = self.rag.get_all_of_type("products")
        all_products = []
        for chunk in all_product_chunks:
            fields = chunk.structured_fields.copy()
            section = chunk.section
            if "PRODUCT:" in section:
                fields["name"] = section.split("PRODUCT:")[-1].strip()
            elif ":" in section:
                fields["name"] = section.split(":")[-1].strip()
            else:
                fields["name"] = section.strip()
            for lf in ["Ingredients_Key","Skin_Type_Suitable","Skin_Type_Avoid",
                       "Concern_Suitable","Allergens_Contains"]:
                val = fields.get(lf, [])
                if isinstance(val, str):
                    fields[lf] = [v.strip() for v in val.split(',')]
            all_products.append(fields)

        rule_result = self.rule_engine.apply_all_rules(
            profile=profile,
            candidate_ingredients=raw_ingredients + [
                ing for concern in profile.concerns
                for ing in self.ingredient_engine.CONCERN_INGREDIENT_MAP.get(concern.lower(), [])
            ],
            candidate_products=all_products
        )

        ingredient_recs = self.ingredient_engine.build_ingredient_set(
            profile=profile,
            safe_from_rules=rule_result["safe_ingredients"],
            removed=rule_result["removed_ingredients"]
        )

        safe_products, _ = self.product_engine.filter_products(
            all_products=all_products, profile=profile, rule_result=rule_result
        )
        product_recs = self.product_engine.recommend_products(
            safe_products=safe_products, profile=profile, safe_ingredients=ingredient_recs
        )

        routine = self.product_engine.build_routine(product_recs)
        mandatory = self.rule_engine.get_mandatory_additions(profile)
        lifestyle_output = self.lifestyle_engine.generate(profile)

        return build_recommendation_output(
            profile=profile, rule_result=rule_result,
            ingredient_recs=ingredient_recs, product_recs=product_recs,
            routine=routine, avoid_list=rule_result.get("avoid_list", []),
            caution_notes=rule_result.get("caution_notes", []),
            mandatory_additions=mandatory, lifestyle_output=lifestyle_output
        )

    def _build_query(self, profile: UserProfile) -> str:
        parts = [f"{profile.skin_type} skin"]
        if profile.concerns: parts.extend(profile.concerns)
        if profile.allergies: parts.append(f"allergy {' '.join(profile.allergies)}")
        if profile.pregnancy_status: parts.append("pregnancy safe")
        if profile.medications: parts.extend(profile.medications[:3])
        if profile.sun_exposure: parts.append(f"sun {profile.sun_exposure}")
        if profile.age_range: parts.append(f"age {profile.age_range}")
        return " ".join(parts)


if __name__ == "__main__":
    kb_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge_base")
    engine = SkincareRecommendationEngine(kb_dir)
    profile = UserProfile(
        skin_type="combination", concerns=["hyperpigmentation","anti_aging"],
        allergies=["fragrance"], medical_conditions=[], medications=[],
        age_range="30s", pregnancy_status=False, budget="$$",
        sun_exposure="high", routine_status="basic", diet_quality="average",
        sleep_hours="6_to_8", exercise_frequency="sometimes", stress_level="high",
        water_intake="moderate", smoker=False, environment="urban", climate="temperate"
    )
    result = engine.recommend(profile)
    print("\nHEALTHCARE TIPS:")
    for t in result['lifestyle_tips']['healthcare_tips'][:5]: print(f"  • {t}")
    print("\nANTI-AGING TIPS:")
    for t in result['lifestyle_tips']['anti_aging_tips'][:5]: print(f"  • {t}")