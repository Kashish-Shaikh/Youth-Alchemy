"""
Ingredient Engine — Extract, normalize, merge, generate final safe set
Product Engine — Map safe ingredients to products, filter, recommend
Skincare AI
"""

import re
from typing import List, Dict, Set, Optional, Tuple, Any
from dataclasses import dataclass, field


# ─────────────────────────────────────────────
# INGREDIENT NORMALIZATION
# ─────────────────────────────────────────────

INGREDIENT_ALIASES: Dict[str, str] = {
    "vitamin c": "vitamin_c",
    "l-ascorbic acid": "vitamin_c",
    "ascorbic acid": "vitamin_c",
    "vitamin b3": "niacinamide",
    "niacin": "niacinamide",
    "bha": "salicylic_acid",
    "aha": "glycolic_acid",
    "glycolic": "glycolic_acid",
    "salicylic": "salicylic_acid",
    "hyaluronic": "hyaluronic_acid",
    "ha": "hyaluronic_acid",
    "retinoid": "retinol",
    "cica": "centella_asiatica",
    "gotu kola": "centella_asiatica",
    "tea tree": "tea_tree_oil",
    "spf": "sunscreen_spf",
    "sunscreen": "sunscreen_spf",
    "ceramide": "ceramides",
    "peptide": "peptides",
    "azelaic": "azelaic_acid",
    "alpha arbutin": "alpha_arbutin",
    "kojic": "kojic_acid",
    "tranexamic": "tranexamic_acid",
    "bakuchiol": "bakuchiol",
    "colloidal oat": "colloidal_oatmeal",
    "oatmeal": "colloidal_oatmeal",
    "zinc": "zinc",
    "benzoyl peroxide": "benzoyl_peroxide",
    "bp": "benzoyl_peroxide",
    "adapalene": "adapalene",
    "retinol": "retinol",
    "squalane": "squalane",
    "glycerin": "glycerin",
    "allantoin": "allantoin",
}

# Canonical ingredient metadata (display names, categories)
INGREDIENT_METADATA: Dict[str, Dict] = {
    "vitamin_c": {"display": "Vitamin C (L-Ascorbic Acid)", "category": "Antioxidant/Brightener", "time": "AM"},
    "niacinamide": {"display": "Niacinamide (Vitamin B3)", "category": "Multi-functional", "time": "AM/PM"},
    "retinol": {"display": "Retinol", "category": "Retinoid", "time": "PM"},
    "adapalene": {"display": "Adapalene 0.1%", "category": "Retinoid", "time": "PM"},
    "salicylic_acid": {"display": "Salicylic Acid (BHA)", "category": "Exfoliant", "time": "PM or AM"},
    "glycolic_acid": {"display": "Glycolic Acid (AHA)", "category": "Exfoliant", "time": "PM"},
    "azelaic_acid": {"display": "Azelaic Acid", "category": "Multi-functional", "time": "AM/PM"},
    "hyaluronic_acid": {"display": "Hyaluronic Acid", "category": "Humectant", "time": "AM/PM"},
    "ceramides": {"display": "Ceramides", "category": "Barrier Repair", "time": "AM/PM"},
    "centella_asiatica": {"display": "Centella Asiatica (Cica)", "category": "Soothing", "time": "AM/PM"},
    "tea_tree_oil": {"display": "Tea Tree Oil", "category": "Antimicrobial", "time": "PM"},
    "benzoyl_peroxide": {"display": "Benzoyl Peroxide", "category": "Antibacterial", "time": "AM or PM"},
    "alpha_arbutin": {"display": "Alpha Arbutin", "category": "Brightener", "time": "AM/PM"},
    "tranexamic_acid": {"display": "Tranexamic Acid", "category": "Brightener", "time": "AM/PM"},
    "kojic_acid": {"display": "Kojic Acid", "category": "Brightener", "time": "PM"},
    "peptides": {"display": "Peptide Complex", "category": "Anti-aging", "time": "AM/PM"},
    "squalane": {"display": "Squalane", "category": "Emollient", "time": "PM"},
    "glycerin": {"display": "Glycerin", "category": "Humectant", "time": "AM/PM"},
    "colloidal_oatmeal": {"display": "Colloidal Oatmeal", "category": "Soothing", "time": "AM/PM"},
    "zinc": {"display": "Zinc PCA", "category": "Oil Control", "time": "AM/PM"},
    "sunscreen_spf": {"display": "Broad-Spectrum SPF 50+", "category": "Photoprotection", "time": "AM (final step)"},
    "allantoin": {"display": "Allantoin", "category": "Soothing", "time": "AM/PM"},
    "bakuchiol": {"display": "Bakuchiol", "category": "Plant Retinol Alt.", "time": "AM/PM"},
    "hydroquinone": {"display": "Hydroquinone", "category": "Depigmenting", "time": "PM"},
}


# ─────────────────────────────────────────────
# INGREDIENT ENGINE
# ─────────────────────────────────────────────

@dataclass
class IngredientRecommendation:
    ingredient_id: str
    display_name: str
    category: str
    use_time: str                    # AM, PM, AM/PM
    reason: str                      # Why recommended
    evidence_level: str
    concerns_addressed: List[str]
    concentration_note: Optional[str] = None
    caution_note: Optional[str] = None
    is_mandatory: bool = False       # e.g., SPF

    def to_dict(self) -> Dict:
        return {
            "ingredient": self.display_name,
            "category": self.category,
            "use_time": self.use_time,
            "reason": self.reason,
            "evidence_level": self.evidence_level,
            "concerns_addressed": self.concerns_addressed,
            "concentration": self.concentration_note or "",
            "caution": self.caution_note or "",
            "mandatory": self.is_mandatory
        }


class IngredientEngine:
    """
    Extracts relevant ingredients from retrieved knowledge chunks,
    normalizes them, merges from multiple sources,
    and builds the final safe ingredient set.
    """

    # Maps concern -> best ingredients (ordered by evidence)
    CONCERN_INGREDIENT_MAP: Dict[str, List[str]] = {
        "acne": ["salicylic_acid", "benzoyl_peroxide", "niacinamide", "retinol",
                 "azelaic_acid", "adapalene", "zinc", "tea_tree_oil"],
        "acne_vulgaris": ["salicylic_acid", "benzoyl_peroxide", "niacinamide", "retinol",
                          "azelaic_acid", "adapalene", "zinc"],
        "hyperpigmentation": ["vitamin_c", "niacinamide", "azelaic_acid", "alpha_arbutin",
                              "kojic_acid", "tranexamic_acid", "glycolic_acid", "retinol"],
        "anti_aging": ["retinol", "vitamin_c", "peptides", "glycolic_acid",
                       "niacinamide", "hyaluronic_acid", "ceramides"],
        "rosacea": ["azelaic_acid", "niacinamide", "centella_asiatica",
                    "ceramides", "allantoin"],
        "eczema": ["ceramides", "colloidal_oatmeal", "hyaluronic_acid",
                   "glycerin", "allantoin", "centella_asiatica"],
        "dehydration": ["hyaluronic_acid", "glycerin", "ceramides", "squalane"],
        "dark_circles": ["vitamin_c", "peptides", "caffeine", "retinol"],
        "sensitive": ["centella_asiatica", "ceramides", "niacinamide",
                      "hyaluronic_acid", "allantoin"],
        "perioral_dermatitis": ["azelaic_acid", "niacinamide"],
        "oily": ["niacinamide", "salicylic_acid", "zinc", "retinol"],
        "dry": ["hyaluronic_acid", "ceramides", "squalane", "glycerin"],
        "combination": ["niacinamide", "hyaluronic_acid", "ceramides"],
        "mature": ["retinol", "peptides", "vitamin_c", "hyaluronic_acid",
                   "niacinamide", "ceramides"],
    }

    # Maps skin type -> base routine ingredients
    SKIN_TYPE_BASE_INGREDIENTS: Dict[str, List[str]] = {
        "oily": ["niacinamide", "hyaluronic_acid", "sunscreen_spf"],
        "dry": ["hyaluronic_acid", "ceramides", "squalane", "sunscreen_spf"],
        "sensitive": ["ceramides", "centella_asiatica", "hyaluronic_acid", "sunscreen_spf"],
        "combination": ["niacinamide", "hyaluronic_acid", "ceramides", "sunscreen_spf"],
        "normal": ["niacinamide", "hyaluronic_acid", "ceramides", "sunscreen_spf"],
        "acne_prone": ["niacinamide", "hyaluronic_acid", "sunscreen_spf"],
        "mature": ["hyaluronic_acid", "ceramides", "peptides", "sunscreen_spf"],
        "eczema": ["ceramides", "colloidal_oatmeal", "glycerin", "sunscreen_spf"],
        "rosacea": ["ceramides", "centella_asiatica", "niacinamide", "sunscreen_spf"],
    }

    INGREDIENT_EVIDENCE: Dict[str, str] = {
        "retinol": "High — Gold standard for anti-aging and acne",
        "vitamin_c": "High — Antioxidant, photoprotection, brightening",
        "niacinamide": "High — Multi-benefit, universally tolerated",
        "salicylic_acid": "High — Proven BHA for acne and pores",
        "glycolic_acid": "High — Proven AHA for texture and aging",
        "azelaic_acid": "High — Proven for rosacea, acne, pigmentation",
        "hyaluronic_acid": "High — Humectant, hydration",
        "ceramides": "High — Barrier repair, eczema",
        "benzoyl_peroxide": "High — Kills C. acnes bacteria",
        "adapalene": "High — OTC retinoid for acne/anti-aging",
        "alpha_arbutin": "Moderate-High — Tyrosinase inhibitor",
        "tranexamic_acid": "Moderate-High — Melasma, pigmentation",
        "peptides": "Moderate — Collagen support",
        "centella_asiatica": "Moderate — Soothing, wound healing",
        "colloidal_oatmeal": "High — FDA-recognized skin protectant",
        "sunscreen_spf": "Very High — #1 anti-aging and cancer prevention",
    }

    def extract_from_chunks(self, retrieved_chunks: List) -> Set[str]:
        """Extract and normalize ingredient names from retrieved knowledge chunks."""
        extracted = set()
        for result in retrieved_chunks:
            chunk = result.chunk if hasattr(result, 'chunk') else result
            fields = chunk.structured_fields if hasattr(chunk, 'structured_fields') else {}
            for field_name in ["Best_For", "Ingredients_Best_For", "Ingredients_Key",
                                "Evidence_Based_Treatments"]:
                items = fields.get(field_name, [])
                if isinstance(items, list):
                    for item in items:
                        normalized = self.normalize(item)
                        if normalized:
                            extracted.add(normalized)
                elif isinstance(items, str):
                    normalized = self.normalize(items)
                    if normalized:
                        extracted.add(normalized)
        return extracted

    def normalize(self, ingredient_text: str) -> Optional[str]:
        """Normalize an ingredient name to canonical form."""
        cleaned = ingredient_text.lower().strip()
        cleaned = re.sub(r'[_\-]', ' ', cleaned).strip()
        # Check aliases
        if cleaned in INGREDIENT_ALIASES:
            return INGREDIENT_ALIASES[cleaned]
        # Check direct match
        restored = cleaned.replace(' ', '_')
        if restored in INGREDIENT_METADATA:
            return restored
        # Partial match
        for alias, canonical in INGREDIENT_ALIASES.items():
            if alias in cleaned:
                return canonical
        return restored if len(restored) > 3 else None

    def build_ingredient_set(self, profile, safe_from_rules: List[str],
                              removed: Dict[str, str]) -> List[IngredientRecommendation]:
        """
        Build the final recommended ingredient set for a profile.
        Merges: skin-type base + concern-specific + safe list.
        Excludes removed. Deduplicates.
        """
        recommended_ids: Set[str] = set()

        # Base from skin type
        base = self.SKIN_TYPE_BASE_INGREDIENTS.get(profile.skin_type.lower(), [])
        recommended_ids.update(base)

        # From concerns
        for concern in profile.concerns:
            concern_ings = self.CONCERN_INGREDIENT_MAP.get(concern.lower(), [])
            recommended_ids.update(concern_ings)

        # SPF always
        recommended_ids.add("sunscreen_spf")

        # Remove blocked
        removed_normalized = {self.normalize(r) for r in removed.keys()}
        recommended_ids -= removed_normalized

        # Build recommendation objects
        recommendations = []
        for ing_id in recommended_ids:
            meta = INGREDIENT_METADATA.get(ing_id, {
                "display": ing_id.replace('_', ' ').title(),
                "category": "Active",
                "time": "AM/PM"
            })
            concerns_addressed = [
                c for c in profile.concerns
                if ing_id in self.CONCERN_INGREDIENT_MAP.get(c.lower(), [])
            ]
            if not concerns_addressed and ing_id in base:
                concerns_addressed = [f"{profile.skin_type} skin maintenance"]

            rec = IngredientRecommendation(
                ingredient_id=ing_id,
                display_name=meta["display"],
                category=meta["category"],
                use_time=meta["time"],
                reason=self._build_reason(ing_id, profile),
                evidence_level=self.INGREDIENT_EVIDENCE.get(ing_id, "Moderate"),
                concerns_addressed=concerns_addressed,
                is_mandatory=(ing_id == "sunscreen_spf")
            )
            recommendations.append(rec)

        # Sort: mandatory first, then by evidence
        recommendations.sort(key=lambda r: (not r.is_mandatory, r.evidence_level != "Very High",
                                             r.evidence_level != "High"))
        return recommendations

    def _build_reason(self, ing_id: str, profile) -> str:
        reasons = []
        skin_type = profile.skin_type
        skin_base = self.SKIN_TYPE_BASE_INGREDIENTS.get(skin_type.lower(), [])
        if ing_id in skin_base:
            reasons.append(f"Foundational for {skin_type} skin")
        for concern in profile.concerns:
            if ing_id in self.CONCERN_INGREDIENT_MAP.get(concern.lower(), []):
                reasons.append(f"Addresses {concern.replace('_', ' ')}")
        return "; ".join(reasons) if reasons else "Beneficial for your skin profile"


# ─────────────────────────────────────────────
# PRODUCT ENGINE
# ─────────────────────────────────────────────

@dataclass
class ProductRecommendation:
    name: str
    brand: str
    product_type: str
    price_range: str
    key_ingredients: List[str]
    why_recommended: str
    concerns_addressed: List[str]
    skin_types_suitable: List[str]
    pregnancy_safe: Any
    fragrance_free: bool
    caution_note: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "brand": self.brand,
            "type": self.product_type,
            "price_range": self.price_range,
            "key_ingredients": self.key_ingredients,
            "why_recommended": self.why_recommended,
            "concerns_addressed": self.concerns_addressed,
            "pregnancy_safe": self.pregnancy_safe,
            "fragrance_free": self.fragrance_free,
            "caution": self.caution_note or ""
        }


class ProductEngine:
    """
    Maps safe ingredients to real products.
    Hard-removes products containing allergens or unsafe ingredients.
    Recommends best-fit products for the user's full profile.
    """

    # Product type priority for routine building
    ROUTINE_TYPES = [
        "Cleanser", "Exfoliant_Toner", "Vitamin_C_Serum", "Brightening_Serum",
        "Treatment_Serum", "Retinol_Serum", "Retinoid", "Moisturizer", "Sunscreen"
    ]

    def filter_products(self, all_products: List[Dict], profile,
                        rule_result: Dict) -> Tuple[List[Dict], List[Dict]]:
        """
        Returns (safe_products, removed_products).
        HARD removes products that:
        1. Contain allergens
        2. Are pregnancy-unsafe when profile is pregnant
        3. Have skin type contraindication
        """
        safe = []
        removed = []
        removed_names = set(rule_result.get("removed_products", {}).keys())

        for product in all_products:
            name = product.get("name", product.get("PRODUCT", "Unknown"))
            if name in removed_names:
                product["_removal_reasons"] = rule_result["removed_products"].get(name, [])
                removed.append(product)
                continue

            # Check allergens directly
            allergen_fail = False
            for allergy in profile.allergies:
                contains = product.get("Allergens_Contains", [])
                if any(allergy.lower() in c.lower() for c in contains):
                    product["_removal_reasons"] = [f"Contains {allergy} allergen"]
                    removed.append(product)
                    allergen_fail = True
                    break

            if not allergen_fail:
                # Pregnancy check
                if profile.pregnancy_status:
                    preg_safe = product.get("Pregnancy_Safe", "UNKNOWN")
                    if preg_safe is False or str(preg_safe).upper() == "FALSE":
                        product["_removal_reasons"] = ["Unsafe in pregnancy"]
                        removed.append(product)
                        continue

                # Budget check
                if profile.budget:
                    prod_price = product.get("Price_Range", "$")
                    if len(prod_price) > len(profile.budget):
                        # Don't remove — just don't prioritize
                        pass

                safe.append(product)

        return safe, removed

    def recommend_products(self, safe_products: List[Dict], profile,
                           safe_ingredients: List[IngredientRecommendation]) -> List[ProductRecommendation]:
        """
        Select best products for each routine step.
        Prioritize products that address most of the user's concerns.
        """
        recommendations = []
        safe_ing_ids = {r.ingredient_id for r in safe_ingredients}
        covered_types: Set[str] = set()

        for product in safe_products:
            prod_type = product.get("Type", "")
            name = product.get("name", product.get("PRODUCT", "Unknown"))
            brand = product.get("Brand", "")
            key_ings = product.get("Ingredients_Key", [])

            # Score product by overlap with needed ingredients
            overlap = [k for k in key_ings
                       if any(k.lower().replace(' ', '_') in sid
                              or sid in k.lower().replace(' ', '_')
                              for sid in safe_ing_ids)]

            concerns_addressed = []
            for concern in profile.concerns:
                suitable = product.get("Concern_Suitable", [])
                if any(concern.lower() in s.lower() for s in suitable):
                    concerns_addressed.append(concern)

            skin_suitable = product.get("Skin_Type_Suitable", [])
            if profile.skin_type.lower() not in [s.lower() for s in skin_suitable] and \
               "all" not in [s.lower() for s in skin_suitable]:
                continue  # Not suitable for skin type

            why = self._build_product_reason(product, profile, overlap, concerns_addressed)

            rec = ProductRecommendation(
                name=name,
                brand=brand,
                product_type=prod_type,
                price_range=product.get("Price_Range", "$"),
                key_ingredients=[k if isinstance(k, str) else str(k) for k in key_ings[:4]],
                why_recommended=why,
                concerns_addressed=concerns_addressed,
                skin_types_suitable=skin_suitable,
                pregnancy_safe=product.get("Pregnancy_Safe", "Unknown"),
                fragrance_free=product.get("Fragrance_Free", False),
            )

            # Add caution note if needed
            if profile.pregnancy_status:
                preg_safe = product.get("Pregnancy_Safe", "UNKNOWN")
                if str(preg_safe).upper() == "CAUTION":
                    rec.caution_note = "Consult physician before use in pregnancy"

            recommendations.append(rec)

        # Sort: more concerns addressed = higher priority
        recommendations.sort(key=lambda r: len(r.concerns_addressed), reverse=True)
        return recommendations

    def _build_product_reason(self, product: Dict, profile,
                               overlap: List, concerns: List) -> str:
        parts = []
        if concerns:
            parts.append(f"Addresses: {', '.join(c.replace('_', ' ') for c in concerns[:3])}")
        if product.get("Fragrance_Free"):
            parts.append("fragrance-free")
        if profile.pregnancy_status and str(product.get("Pregnancy_Safe", "")).upper() == "TRUE":
            parts.append("pregnancy-safe")
        if profile.skin_type.lower() in [s.lower() for s in product.get("Skin_Type_Suitable", [])]:
            parts.append(f"suited for {profile.skin_type} skin")
        return "; ".join(parts) if parts else "Suitable for your profile"

    def build_routine(self, recommendations: List[ProductRecommendation]) -> Dict[str, List]:
        """Organize recommendations into AM and PM routines."""
        am_routine = []
        pm_routine = []

        am_types = ["Cleanser", "Vitamin_C_Serum", "Brightening_Serum",
                    "Treatment_Serum", "Moisturizer", "Sunscreen"]
        pm_types = ["Cleanser", "Exfoliant_Toner", "Treatment_Serum",
                    "Retinol_Serum", "Retinoid", "Moisturizer"]

        seen_types_am: Set[str] = set()
        seen_types_pm: Set[str] = set()

        for rec in recommendations:
            ptype = rec.product_type
            if ptype in am_types and ptype not in seen_types_am:
                am_routine.append(rec)
                seen_types_am.add(ptype)
            if ptype in pm_types and ptype not in seen_types_pm:
                pm_routine.append(rec)
                seen_types_pm.add(ptype)

        # Sort by application order
        def am_order(r):
            order = ["Cleanser", "Exfoliant_Toner", "Vitamin_C_Serum",
                     "Brightening_Serum", "Treatment_Serum", "Moisturizer", "Sunscreen"]
            return order.index(r.product_type) if r.product_type in order else 99

        def pm_order(r):
            order = ["Cleanser", "Exfoliant_Toner", "Treatment_Serum",
                     "Retinol_Serum", "Retinoid", "Moisturizer"]
            return order.index(r.product_type) if r.product_type in order else 99

        am_routine.sort(key=am_order)
        pm_routine.sort(key=pm_order)

        return {"morning": am_routine, "evening": pm_routine}