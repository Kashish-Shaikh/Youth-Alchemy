# pdf_rag.py — RAG engine that reads your 5 PDFs + .md knowledge base
# Unified retrieval for the AI prompt

import os
import re
from typing import Dict, List

# ── PDF map ──────────────────────────────────
PDF_MAP = {
    "acne":              "Acne_Solutions.pdf",
    "dark_circles":      "Dark_Circles_Solutions.pdf",
    "pimples_breakouts": "Pimple___Breaklines_Solutions.pdf",
    "open_pores":        "Open_Pores_Solutions.pdf",
    "hyperpigmentation": "Pigmentation-Hyperpigmentation_Solutions.pdf",
}

CV_TO_TOPIC = {
    "acne":              ["acne", "pimples_breakouts"],
    "hyperpigmentation": ["hyperpigmentation"],
    "wrinkles":          [],
    "dark_circles":      ["dark_circles"],
    "redness":           ["acne"],
    "texture":           ["open_pores"],
    "pores":             ["open_pores"],
}

BUNDLED = {
"acne": """ACNE – SOLUTIONS
Tea Tree Oil 1:9 diluted, apply with cotton swab 1-2x/day — antimicrobial, reduces lesions with less irritation than benzoyl peroxide.
Honey antibacterial/anti-inflammatory. Apply as mask 10-15 min.
Aloe Vera contains salicylic acid + sulfur. Apply gel 1-2x daily.
Green Tea polyphenols fight bacteria + reduce sebum. Brew, cool, apply with cotton ball.
Zinc supplements reduce inflammatory acne lesions.
Omega-3 fatty acids reduce inflammation. Take from fish/seeds or supplements.
Low glycemic diet: cut sugar, white bread, processed food — reduces insulin + sebum.
Salicylic acid cleanser 0.5-2% for acne. Benzoyl peroxide 2.5% kills P. acnes.
Niacinamide 10% reduces oil 30%, calms inflammation, shrinks pores.
Change pillowcases every 2-3 days. Never pick or squeeze pimples.
Stress increases cortisol → more sebum. Meditation + 7-8h sleep helps.
Wash face twice daily with mild cleanser. Wash face after sweating.
""",
"dark_circles": """DARK CIRCLES – SOLUTIONS
7-8 hours sleep is the most effective treatment.
Elevate head with extra pillow to prevent fluid accumulation + puffiness.
Cold compresses/chilled spoons constrict blood vessels, reduce darkness.
Cold tea bags: caffeine + antioxidants improve under-eye circulation.
Cucumber slices: high water content + Vitamin C reduce puffiness.
Caffeine eye cream 5% constricts blood vessels under thin skin.
Vitamin K cream strengthens capillaries reducing blood pooling.
Peptide eye serums support collagen and skin thickness under eyes.
Vitamin C rich foods: citrus, bell peppers, broccoli improve skin tone.
Stay hydrated — dehydration makes blood vessels more visible.
Reduce alcohol and smoking — both cause vascular damage.
SPF 30+ around eye area prevents hyperpigmentation from UV.
""",
"open_pores": """ENLARGED PORES – SOLUTIONS
Pores cannot be permanently closed but their appearance can be minimized.
Clay masks (Kaolin/Multani Mitti) absorb excess oil. Use 1-2x/week.
Cold water or ice temporarily tightens pores. Apply wrapped ice 30 seconds.
Niacinamide 2-5% serum balances oil, improves texture, makes pores appear smaller.
Salicylic acid (BHA) cleanser deep-cleans pores and controls oil production.
Retinol or Adapalene OTC unclogs pores and smooths texture.
AHA (glycolic/lactic acid) for surface texture; BHA (salicylic) for inside pores.
SPF 30+ daily prevents UV collagen damage that makes pores look larger.
Non-comedogenic lightweight moisturizer — oily skin still needs hydration.
Aloe vera hydrates without clogging pores and improves skin elasticity.
Egg white mask temporarily tightens skin and absorbs excess oil.
""",
"hyperpigmentation": """HYPERPIGMENTATION – SOLUTIONS
SPF 30+ EVERY DAY is the single most critical step — UV cancels all brightening.
Aloe vera contains aloin + aloesin (natural depigmenting compounds). Apply before bedtime.
Turmeric + milk paste: curcumin blocks melanin enzyme. Apply 15 min, rinse.
Vitamin C (L-Ascorbic Acid) 10-20%: brightens + interferes with melanin. Apply every morning.
Niacinamide 2-5%: reduces pigment transfer to skin cells.
Azelaic Acid 10% OTC: reduces inflammation + pigment; safe in pregnancy.
Alpha Arbutin: gentle tyrosinase inhibitor, very effective.
Retinol/Adapalene: increase cell turnover, fade dark spots. 2-3 nights/week.
Glycolic/Lactic Acid 5-10%: exfoliate to smooth texture + brighten.
Hydroquinone 2% (with caution): up to 3 months then break. Always combine with SPF.
Lemon juice + honey 1:1 (only at night, diluted) — Vitamin C brightener.
Potato juice: natural bleaching enzymes + Vitamin C. Apply daily 2-4 weeks.
Vitamin B12 foods: dairy, eggs, liver, mutton — deficiency causes pigmentation.
Vitamin A rich foods: spinach, carrots, broccoli, sweet potato — reduce pigmentation.
""",
"pimples_breakouts": """PIMPLES & BREAKOUTS – SOLUTIONS
Cold compress/ice reduces redness and swelling. Wrap in cloth, apply short intervals.
Warm compress for whiteheads: opens pores to let oil surface naturally.
Tea tree oil 1:9 dilution, apply with cotton swab 1-2x/day.
Benzoyl peroxide 2.5% kills bacteria. Use as spot treatment.
Honey anti-inflammatory: apply to pimple 10-15 min.
Never pop or squeeze pimples — spreads bacteria, causes scarring + dark spots.
Change pillowcases every 2-3 days. Keep phone screen clean.
Reduce sugar and dairy. Eat omega-3 rich foods. Stay hydrated.
Brewer's yeast (Hansen CBS): 1 packet + 1 tbsp lemon juice, apply 1 min, rinse.
Wash face gently twice daily with mild non-comedogenic cleanser.
"""
}


def extract_pdf_text(pdf_path: str) -> str:
    try:
        import PyPDF2
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text = ""
            for page in reader.pages:
                text += (page.extract_text() or "") + "\n"
        if text.strip():
            return text
    except Exception:
        pass
    try:
        from pdfminer.high_level import extract_text
        t = extract_text(pdf_path)
        if t and t.strip(): return t
    except Exception:
        pass
    return ""


class PDFRagEngine:
    """
    Unified RAG: reads 5 PDFs + falls back to bundled knowledge.
    retrieve() returns a context string ready to inject into AI prompt.
    """

    def __init__(self, pdf_folder: str):
        self.knowledge: Dict[str, str] = {}
        self._load(pdf_folder)

    def _load(self, pdf_folder: str):
        loaded = 0
        if os.path.isdir(pdf_folder):
            for topic, fname in PDF_MAP.items():
                path = os.path.join(pdf_folder, fname)
                if os.path.exists(path):
                    text = extract_pdf_text(path)
                    if text.strip():
                        self.knowledge[topic] = text
                        loaded += 1
                        print(f"[PDFRag] Loaded: {fname} ({len(text)} chars)")
        for topic, content in BUNDLED.items():
            if topic not in self.knowledge:
                self.knowledge[topic] = content
        print(f"[PDFRag] {loaded} PDFs loaded, {len(self.knowledge)} topics total")

    def retrieve(self, cv_concerns: List[str], profile_keywords: List[str] = None,
                 max_chars: int = 5000) -> str:
        """Return relevant knowledge for detected CV concerns."""
        seen, chunks = set(), []

        # Map CV keys → knowledge topics
        for concern_key in cv_concerns:
            ck = concern_key.lower().replace(" & ", "_").replace(" ", "_").replace("/","_")
            for cv_key, topics in CV_TO_TOPIC.items():
                if cv_key in ck or ck in cv_key:
                    for t in topics:
                        if t not in seen and t in self.knowledge:
                            seen.add(t)
                            chunks.append((t, self.knowledge[t]))

        # Fill from profile keywords
        if profile_keywords:
            for kw in profile_keywords:
                for topic, content in self.knowledge.items():
                    if topic not in seen and kw.lower() in content.lower():
                        seen.add(topic)
                        chunks.append((topic, content))

        if not chunks:
            chunks = list(self.knowledge.items())

        parts = ["=== KNOWLEDGE BASE (from PDFs) ==="]
        used = 0
        for topic, content in chunks:
            header = f"\n[{topic.upper().replace('_',' ')}]\n"
            snippet = content[:max_chars - used - len(header)]
            parts.append(header + snippet)
            used += len(header) + len(snippet)
            if used >= max_chars: break

        return "\n".join(parts)

    def get_topics(self):
        return list(self.knowledge.keys())
        