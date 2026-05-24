"""
Rule Engine — Safety Filtering & Constraint Application
Skincare AI

Executes BEFORE LLM output:
1. Remove unsafe ingredients based on allergies/sensitivities
2. Remove contraindicated ingredients (pregnancy, medical conditions, medications)
3. Apply skin-type suitability rules
4. Apply concern-specific suitability rules
5. Multi-constraint filtering
6. HARD REMOVE unsafe options — never just deprioritize
"""

from typing import List, Dict, Set, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum


# ─────────────────────────────────────────────
# USER PROFILE
# ─────────────────────────────────────────────

class SkinType(Enum):
    NORMAL = "normal"
    OILY = "oily"
    DRY = "dry"
    COMBINATION = "combination"
    SENSITIVE = "sensitive"
    ACNE_PRONE = "acne_prone"
    MATURE = "mature"


@dataclass
class UserProfile:
    skin_type: str                          # e.g. "oily", "dry"
    concerns: List[str]                     # e.g. ["acne", "hyperpigmentation"]
    allergies: List[str]                    # e.g. ["fragrance", "nuts"]
    medical_conditions: List[str]           # e.g. ["pregnant", "eczema"]
    medications: List[str]                  # free text or known names
    # ── EXTENDED FIELDS ─────────────────────────
    age_range: Optional[str] = None         # "teens","20s","30s","40s_plus"
    pregnancy_status: bool = False
    breastfeeding: bool = False
    current_products: List[str] = field(default_factory=list)
    budget: Optional[str] = None            # "$", "$$", "$$$", "$$$$"
    # Lifestyle
    sun_exposure: Optional[str] = None      # "low", "moderate", "high"
    routine_status: Optional[str] = None    # "none", "basic", "advanced"
    diet_quality: Optional[str] = None      # "poor", "average", "good"
    sleep_hours: Optional[str] = None       # "less_than_6", "6_to_8", "8_plus"
    exercise_frequency: Optional[str] = None # "rarely", "sometimes", "regularly"
    stress_level: Optional[str] = None      # "low", "moderate", "high"
    water_intake: Optional[str] = None      # "low", "moderate", "high"
    smoker: bool = False
    prescription_notes: Optional[str] = None  # free text prescription upload
    environment: Optional[str] = None       # "urban", "suburban", "rural"
    climate: Optional[str] = None           # "dry", "humid", "cold", "temperate"


# ─────────────────────────────────────────────
# SAFETY VERDICT
# ─────────────────────────────────────────────

class SafetyStatus(Enum):
    SAFE = "safe"
    UNSAFE = "unsafe"           # Hard remove
    CAUTION = "caution"         # Flag but allow with note
    NOT_APPLICABLE = "n/a"


@dataclass
class SafetyVerdict:
    status: SafetyStatus
    reasons: List[str] = field(default_factory=list)
    alternatives: List[str] = field(default_factory=list)


# ─────────────────────────────────────────────
# ALLERGY MAP
# ─────────────────────────────────────────────

ALLERGY_INGREDIENT_MAP: Dict[str, List[str]] = {
    "fragrance": [
        "fragrance", "parfum", "linalool", "limonene", "geraniol",
        "citronellol", "eugenol", "cinnamal", "coumarin", "benzyl_alcohol",
        "isoeugenol", "farnesol", "oakmoss_extract"
    ],
    "essential_oils": [
        "tea_tree_oil", "lavender_oil", "eucalyptus_oil", "peppermint_oil",
        "rosemary_oil", "bergamot_oil", "lemon_oil", "orange_oil",
        "camphor", "menthol", "ylang_ylang", "frankincense"
    ],
    "aspirin": [
        "salicylic_acid", "salicylates", "aspirin", "willow_bark_extract"
    ],
    "nuts": [
        "almond_oil", "macadamia_oil", "walnut_oil", "hazelnut_oil",
        "shea_butter", "pecan_extract"
    ],
    "tree_nuts": [
        "almond_oil", "macadamia_oil", "walnut_oil", "hazelnut_oil",
        "shea_butter", "pecan_extract", "cashew_oil"
    ],
    "coconut": [
        "coconut_oil", "caprylic_capric_triglyceride", "sodium_cocoate",
        "coco_glucoside", "cocamidopropyl_betaine", "fractionated_coconut_oil"
    ],
    "oat": [
        "colloidal_oatmeal", "avena_sativa_kernel_flour",
        "oat_extract", "oat_kernel_oil"
    ],
    "latex": [
        "natural_rubber_latex", "avocado_oil", "banana_extract"
    ],
    "methylisothiazolinone": [
        "methylisothiazolinone", "methylchloroisothiazolinone"
    ],
    "formaldehyde": [
        "formaldehyde", "dmdm_hydantoin", "imidazolidinyl_urea",
        "diazolidinyl_urea", "quaternium_15", "bronopol"
    ],
    "propylene_glycol": [
        "propylene_glycol", "butylene_glycol"
    ],
    "chemical_sunscreen": [
        "oxybenzone", "avobenzone", "octinoxate", "octisalate",
        "octocrylene", "homosalate", "ensulizole"
    ],
    "benzoyl_peroxide": ["benzoyl_peroxide"],
    "nickel": [],  # mostly metals, not topical ingredients
    "vitamin_c": [
        "l_ascorbic_acid", "ascorbyl_glucoside",
        "sodium_ascorbyl_phosphate", "ascorbyl_palmitate"
    ],
    "kojic_acid": ["kojic_acid"],
    "retinoids": [
        "retinol", "retinal", "tretinoin", "adapalene",
        "tazarotene", "isotretinoin", "granactive_retinoid"
    ],
}

ALLERGY_SAFE_ALTERNATIVES: Dict[str, List[str]] = {
    "fragrance": ["fragrance_free_products", "certified_fragrance_free"],
    "essential_oils": ["centella_asiatica", "aloe_vera", "oat_extract", "allantoin"],
    "aspirin": ["glycolic_acid", "lactic_acid", "mandelic_acid", "azelaic_acid"],
    "nuts": ["mineral_oil", "squalane", "sunflower_seed_oil", "ceramides"],
    "tree_nuts": ["mineral_oil", "squalane", "sunflower_seed_oil", "ceramides"],
    "coconut": ["sunflower_oil", "squalane", "ceramides", "mineral_oil"],
    "oat": ["centella_asiatica", "aloe_vera", "ceramides", "allantoin"],
    "chemical_sunscreen": ["zinc_oxide_mineral_spf", "titanium_dioxide_mineral_spf"],
    "benzoyl_peroxide": ["azelaic_acid", "salicylic_acid", "niacinamide"],
    "vitamin_c": ["niacinamide", "azelaic_acid", "alpha_arbutin", "tranexamic_acid"],
    "retinoids": ["bakuchiol", "peptides", "azelaic_acid"],
}

# ─────────────────────────────────────────────
# MEDICAL / PREGNANCY RULES
# ─────────────────────────────────────────────

PREGNANCY_UNSAFE: Set[str] = {
    "retinol", "retinal", "tretinoin", "adapalene", "tazarotene",
    "isotretinoin", "granactive_retinoid", "hydroquinone",
    "high_dose_salicylic_acid", "kojic_acid", "oxybenzone",
    "formaldehyde", "dmdm_hydantoin", "imidazolidinyl_urea",
    "high_conc_essential_oils", "tazarotene"
}

PREGNANCY_CAUTION: Set[str] = {
    "salicylic_acid", "benzoyl_peroxide", "glycolic_acid", "lactic_acid",
    "chemical_sunscreen_filters", "avobenzone", "octinoxate", "octisalate",
    "octocrylene", "homosalate", "tea_tree_oil"
}

PREGNANCY_SAFE_ALTERNATIVES: List[str] = [
    "azelaic_acid", "vitamin_c_topical", "hyaluronic_acid",
    "ceramides", "glycerin", "niacinamide", "alpha_arbutin",
    "tranexamic_acid", "mineral_spf_zinc_oxide", "colloidal_oatmeal",
    "centella_asiatica", "aloe_vera", "peptides", "squalane"
]

MEDICATION_RULES: Dict[str, Dict[str, List[str]]] = {
    "tetracyclines": {
        "caution": ["glycolic_acid", "salicylic_acid", "retinol"],
        "mandatory": ["spf_50"],
        "reason": "Tetracyclines increase photosensitivity — strict SPF required"
    },
    "fluoroquinolones": {
        "caution": ["aha", "bha", "retinoids"],
        "mandatory": ["spf_50"],
        "reason": "Fluoroquinolones increase photosensitivity"
    },
    "isotretinoin": {
        "unsafe": ["retinol", "retinal", "adapalene", "tretinoin",
                   "glycolic_acid", "salicylic_acid", "benzoyl_peroxide"],
        "reason": "Isotretinoin makes skin extremely fragile — no actives"
    },
    "warfarin": {
        "caution": ["vitamin_k_topical"],
        "reason": "Theoretical vitamin K interaction — monitor"
    },
    "aspirin_high_dose": {
        "caution": ["salicylic_acid"],
        "reason": "Systemic salicylate load"
    },
    "blood_thinners": {
        "caution": ["high_dose_vitamin_e"],
        "reason": "May increase bleeding risk"
    }
}

# ─────────────────────────────────────────────
# SKIN TYPE RULES
# ─────────────────────────────────────────────

SKIN_TYPE_AVOID: Dict[str, Set[str]] = {
    "oily": {
        "heavy_oils", "petrolatum", "coconut_oil", "shea_butter_heavy",
        "mineral_oil", "heavy_occlusive_creams"
    },
    "dry": {
        "alcohol_denat", "high_concentration_aha", "benzoyl_peroxide_high_strength",
        "harsh_sulfates", "acetone", "strong_retinoids_without_buffer"
    },
    "sensitive": {
        "fragrance", "essential_oils", "alcohol_denat", "high_concentration_vitamin_c",
        "benzoyl_peroxide", "strong_retinoids", "witch_hazel_high_alcohol",
        "menthol", "eucalyptus", "camphor", "sodium_lauryl_sulfate"
    },
    "acne_prone": {
        "coconut_oil", "isopropyl_myristate", "heavy_occlusive",
        "comedogenic_ingredients", "algae_extract_high"
    },
    "eczema": {
        "fragrance", "essential_oils", "sodium_lauryl_sulfate", "alcohol_denat",
        "methylisothiazolinone", "dyes", "high_acids"
    },
    "rosacea": {
        "alcohol_denat", "fragrance", "essential_oils", "menthol",
        "witch_hazel", "high_acids", "benzoyl_peroxide", "strong_retinoids",
        "physical_exfoliants", "eucalyptus"
    }
}

SKIN_TYPE_BEST_FOR: Dict[str, Set[str]] = {
    "oily": {
        "niacinamide", "salicylic_acid", "zinc", "retinol", "aha",
        "clay", "benzoyl_peroxide", "green_tea_extract", "hyaluronic_acid"
    },
    "dry": {
        "hyaluronic_acid", "ceramides", "squalane", "glycerin", "shea_butter",
        "fatty_acids", "peptides", "niacinamide"
    },
    "sensitive": {
        "centella_asiatica", "aloe_vera", "ceramides", "niacinamide",
        "peptides", "hyaluronic_acid", "azelaic_acid", "oat_extract",
        "allantoin", "bisabolol"
    },
    "acne_prone": {
        "salicylic_acid", "benzoyl_peroxide", "niacinamide", "retinol",
        "azelaic_acid", "tea_tree_oil", "zinc", "adapalene"
    },
    "mature": {
        "retinol", "peptides", "vitamin_c", "hyaluronic_acid", "niacinamide",
        "ceramides", "coq10", "resveratrol", "glycolic_acid"
    }
}


# ─────────────────────────────────────────────
# RULE ENGINE CLASS
# ─────────────────────────────────────────────

class RuleEngine:
    """
    Applies safety rules to filter ingredients and products.
    All removals are HARD — unsafe ingredients are eliminated, not deprioritized.
    """

    def __init__(self):
        self.allergy_map = ALLERGY_INGREDIENT_MAP
        self.allergy_alternatives = ALLERGY_SAFE_ALTERNATIVES
        self.pregnancy_unsafe = PREGNANCY_UNSAFE
        self.pregnancy_caution = PREGNANCY_CAUTION
        self.medication_rules = MEDICATION_RULES
        self.skin_type_avoid = SKIN_TYPE_AVOID
        self.skin_type_best_for = SKIN_TYPE_BEST_FOR

    def apply_all_rules(self, profile: UserProfile,
                        candidate_ingredients: List[str],
                        candidate_products: List[Dict]) -> Dict[str, Any]:
        """
        Master method — apply all rules and return filtered results.
        Returns:
            {
                safe_ingredients: [...],
                flagged_ingredients: {ingredient: reason},
                removed_ingredients: {ingredient: reason},
                safe_products: [...],
                removed_products: {product: [reasons]},
                caution_notes: [...],
                recommended_additions: [...],
                avoid_list: [...],
                rule_log: [...],
            }
        """
        result = {
            "safe_ingredients": [],
            "flagged_ingredients": {},
            "removed_ingredients": {},
            "safe_products": [],
            "removed_products": {},
            "caution_notes": [],
            "recommended_additions": [],
            "avoid_list": [],
            "rule_log": []
        }

        # Step 1: Get allergen-blocked ingredients
        blocked = self._get_allergen_blocked(profile)
        result["rule_log"].append(f"Allergen-blocked: {list(blocked.keys())}")

        # Step 2: Get pregnancy-blocked
        preg_blocked, preg_caution = self._get_pregnancy_rules(profile)
        result["rule_log"].append(f"Pregnancy-blocked: {list(preg_blocked.keys())}")

        # Step 3: Get medication-blocked
        med_blocked, med_caution = self._get_medication_rules(profile)
        result["rule_log"].append(f"Medication-blocked: {list(med_blocked.keys())}")

        # Step 4: Get skin-type blocked
        skin_blocked = self._get_skin_type_blocked(profile)
        result["rule_log"].append(f"Skin-type-blocked: {list(skin_blocked.keys())}")

        # Step 5: Combine all blocked
        all_blocked: Dict[str, str] = {}
        all_blocked.update(blocked)
        all_blocked.update(preg_blocked)
        all_blocked.update(med_blocked)
        all_blocked.update(skin_blocked)

        all_caution: Dict[str, str] = {}
        all_caution.update(preg_caution)
        all_caution.update(med_caution)

        # Step 6: Filter ingredients
        for ing in candidate_ingredients:
            ing_lower = ing.lower()
            if any(blocked_ing in ing_lower or ing_lower in blocked_ing
                   for blocked_ing in all_blocked):
                blocking_reason = next(
                    (r for b, r in all_blocked.items()
                     if b in ing_lower or ing_lower in b), "Safety rule"
                )
                result["removed_ingredients"][ing] = blocking_reason
                result["avoid_list"].append(ing)
            elif any(c in ing_lower or ing_lower in c for c in all_caution):
                caution_reason = next(
                    (r for c, r in all_caution.items()
                     if c in ing_lower or ing_lower in c), "Use with caution"
                )
                result["flagged_ingredients"][ing] = caution_reason
                result["safe_ingredients"].append(ing)
                result["caution_notes"].append(f"{ing}: {caution_reason}")
            else:
                result["safe_ingredients"].append(ing)

        # Step 7: Filter products
        for product in candidate_products:
            removed_reasons = []
            prod_ingredients = [i.lower() for i in product.get("Allergens_Contains", [])]
            prod_all_ings = [i.lower() for i in product.get("ingredients_full_list", [])]

            # Check allergens
            for allergy in profile.allergies:
                allergen_ings = [a.lower() for a in self.allergy_map.get(allergy, [])]
                for ai in allergen_ings:
                    if any(ai in pi for pi in prod_ingredients + prod_all_ings):
                        removed_reasons.append(f"Contains allergen ({allergy}): {ai}")

            # Check pregnancy
            if profile.pregnancy_status or profile.breastfeeding:
                preg_safe = product.get("Pregnancy_Safe", "UNKNOWN")
                if preg_safe is False or str(preg_safe).upper() == "FALSE":
                    removed_reasons.append("Not safe in pregnancy")
                elif str(preg_safe).upper() == "CAUTION":
                    result["caution_notes"].append(
                        f"{product.get('name', 'Product')}: Use with caution in pregnancy — consult physician"
                    )

            # Check skin type
            skin_avoid = product.get("Skin_Type_Avoid", [])
            if profile.skin_type in [s.lower() for s in skin_avoid]:
                removed_reasons.append(f"Not suitable for {profile.skin_type} skin")

            if removed_reasons:
                result["removed_products"][product.get("name", "Unknown")] = removed_reasons
            else:
                result["safe_products"].append(product)

        # Step 8: Recommend safe additions based on pregnancy
        if profile.pregnancy_status:
            result["recommended_additions"].extend(PREGNANCY_SAFE_ALTERNATIVES)
            result["recommended_additions"] = list(set(result["recommended_additions"]))

        # Step 9: Add alternatives for removed ingredients
        for allergy in profile.allergies:
            alts = self.allergy_alternatives.get(allergy, [])
            if alts:
                result["recommended_additions"].extend(alts)

        return result

    def _get_allergen_blocked(self, profile: UserProfile) -> Dict[str, str]:
        blocked = {}
        for allergy in profile.allergies:
            ings = self.allergy_map.get(allergy.lower(), [])
            for ing in ings:
                blocked[ing] = f"Allergen: {allergy}"
        return blocked

    def _get_pregnancy_rules(self, profile: UserProfile) -> Tuple[Dict[str, str], Dict[str, str]]:
        blocked = {}
        caution = {}
        if profile.pregnancy_status or profile.breastfeeding:
            status = "pregnancy" if profile.pregnancy_status else "breastfeeding"
            for ing in self.pregnancy_unsafe:
                blocked[ing] = f"Contraindicated in {status}"
            for ing in self.pregnancy_caution:
                caution[ing] = f"Use with caution in {status} — consult physician"
        return blocked, caution

    def _get_medication_rules(self, profile: UserProfile) -> Tuple[Dict[str, str], Dict[str, str]]:
        blocked = {}
        caution = {}
        for med in profile.medications:
            rules = self.medication_rules.get(med.lower(), {})
            reason = rules.get("reason", f"Interaction with {med}")
            for ing in rules.get("unsafe", []):
                blocked[ing] = reason
            for ing in rules.get("caution", []):
                caution[ing] = reason
        return blocked, caution

    def _get_skin_type_blocked(self, profile: UserProfile) -> Dict[str, str]:
        blocked = {}
        avoid_set = self.skin_type_avoid.get(profile.skin_type.lower(), set())
        for ing in avoid_set:
            blocked[ing] = f"Not suitable for {profile.skin_type} skin"
        # Also check concerns that have skin type implications
        for concern in profile.concerns:
            avoid_for_concern = self.skin_type_avoid.get(concern.lower(), set())
            for ing in avoid_for_concern:
                blocked[ing] = f"Avoid with {concern}"
        return blocked

    def check_ingredient(self, ingredient: str, profile: UserProfile) -> SafetyVerdict:
        """Check a single ingredient against a profile."""
        ing_lower = ingredient.lower()
        reasons = []
        alternatives = []

        # Allergy check
        for allergy in profile.allergies:
            allergen_ings = [a.lower() for a in self.allergy_map.get(allergy, [])]
            if any(a in ing_lower or ing_lower in a for a in allergen_ings):
                reasons.append(f"Allergen ({allergy})")
                alternatives.extend(self.allergy_alternatives.get(allergy, []))
                return SafetyVerdict(SafetyStatus.UNSAFE, reasons, list(set(alternatives)))

        # Pregnancy check
        if profile.pregnancy_status:
            if any(p in ing_lower or ing_lower in p for p in self.pregnancy_unsafe):
                reasons.append("Contraindicated in pregnancy")
                alternatives.extend(PREGNANCY_SAFE_ALTERNATIVES[:3])
                return SafetyVerdict(SafetyStatus.UNSAFE, reasons, alternatives)
            if any(p in ing_lower or ing_lower in p for p in self.pregnancy_caution):
                reasons.append("Use with caution in pregnancy — consult physician")
                return SafetyVerdict(SafetyStatus.CAUTION, reasons, [])

        # Medication check
        for med in profile.medications:
            rules = self.medication_rules.get(med.lower(), {})
            if any(u in ing_lower for u in rules.get("unsafe", [])):
                reasons.append(f"Contraindicated with {med}: {rules.get('reason', '')}")
                return SafetyVerdict(SafetyStatus.UNSAFE, reasons, [])
            if any(c in ing_lower for c in rules.get("caution", [])):
                reasons.append(f"Caution with {med}: {rules.get('reason', '')}")
                return SafetyVerdict(SafetyStatus.CAUTION, reasons, [])

        # Skin type check
        skin_avoids = self.skin_type_avoid.get(profile.skin_type.lower(), set())
        if any(a in ing_lower or ing_lower in a for a in skin_avoids):
            reasons.append(f"Not recommended for {profile.skin_type} skin")
            return SafetyVerdict(SafetyStatus.CAUTION, reasons, [])

        return SafetyVerdict(SafetyStatus.SAFE)

    def get_mandatory_additions(self, profile: UserProfile) -> List[Dict[str, str]]:
        """Return ingredients that should be added based on conditions."""
        additions = []

        # Photosensitizing medications always need SPF
        photosensitizing = ["tetracyclines", "fluoroquinolones", "isotretinoin"]
        if any(m in profile.medications for m in photosensitizing):
            additions.append({
                "ingredient": "SPF 50+ (mandatory)",
                "reason": f"Mandatory with photosensitizing medication"
            })

        # Pregnancy: add azelaic acid option
        if profile.pregnancy_status and "acne" in profile.concerns:
            additions.append({
                "ingredient": "azelaic_acid",
                "reason": "Pregnancy-safe acne treatment"
            })

        return additions