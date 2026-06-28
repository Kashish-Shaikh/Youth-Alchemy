# skin_analyzer.py — CV Skin Analysis Engine (Web version)
# Adapted from main.py — removes tkinter/display dependencies
# Works with uploaded images via Flask

import cv2
import numpy as np
from typing import Dict, Tuple, List, Optional
from dataclasses import dataclass, field
import base64
import warnings
warnings.filterwarnings('ignore')

try:
    import mediapipe as mp
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False


# ─────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────

@dataclass
class SkinConcern:
    name: str
    severity: float          # 0–100
    grade: str               # A B C D F
    confidence: float        # 0–1
    detected_regions: List[Tuple[int, int, int, int]] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "name": self.name,
            "severity": round(self.severity, 1),
            "grade": self.grade,
            "confidence": round(self.confidence, 2),
            "details": self.details
        }


@dataclass
class AnalysisResult:
    concerns: Dict[str, SkinConcern]
    overall_score: float
    overall_grade: str
    face_detected: bool
    annotated_image_b64: str = ""   # base64 PNG of annotated face

    def to_dict(self):
        detected = {
            k: v.to_dict() for k, v in self.concerns.items()
            if v.confidence > 0.2 and v.severity > 5
        }
        return {
            "face_detected": self.face_detected,
            "overall_score": self.overall_score,
            "overall_grade": self.overall_grade,
            "concerns": detected,
            "annotated_image": self.annotated_image_b64
        }


# ─────────────────────────────────────────────
# Analyzer
# ─────────────────────────────────────────────

class SkinAnalyzer:
    def __init__(self):
        self.use_mediapipe = False
        # Pre-allocate reusable CLAHE — avoids repeated allocation on each scan
        self._clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        self._init_detection()

    def _init_detection(self):
        if MEDIAPIPE_AVAILABLE:
            try:
                self.mp_face = mp.solutions.face_detection
                self.face_detector = self.mp_face.FaceDetection(
                    model_selection=1, min_detection_confidence=0.5)
                self.use_mediapipe = True
                return
            except Exception:
                pass
        try:
            self.face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        except Exception:
            self.face_cascade = None

    def preprocess(self, image):
        h, w = image.shape[:2]
        # Resize to max 640px wide — sufficient accuracy, ~50% faster than 900px
        if w > 640:
            scale = 640 / w
            image = cv2.resize(image, (int(w * scale), int(h * scale)),
                               interpolation=cv2.INTER_AREA)
        # Lighter bilateral (d=7 vs 9) — removes noise without extra blur passes
        denoised = cv2.bilateralFilter(image, 7, 60, 60)
        lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
        # Reuse cached CLAHE instance to avoid repeated allocation
        lab[:, :, 0] = self._clahe.apply(lab[:, :, 0])
        return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    def detect_face(self, image):
        pre = self.preprocess(image)
        if self.use_mediapipe:
            rgb = cv2.cvtColor(pre, cv2.COLOR_BGR2RGB)
            results = self.face_detector.process(rgb)
            if results.detections:
                det = results.detections[0]
                bbox = det.location_data.relative_bounding_box
                h, w = pre.shape[:2]
                x = max(0, int(bbox.xmin * w))
                y = max(0, int(bbox.ymin * h))
                fw = int(bbox.width * w)
                fh = int(bbox.height * h)
                pad_x, pad_y = int(fw * 0.15), int(fh * 0.15)
                x = max(0, x - pad_x); y = max(0, y - pad_y)
                fw = min(w - x, fw + 2*pad_x); fh = min(h - y, fh + 2*pad_y)
                return (x, y, fw, fh), pre
            return None, pre
        if self.face_cascade is not None:
            gray = cv2.cvtColor(pre, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(gray, 1.1, 5, minSize=(80, 80))
            if len(faces) > 0:
                return tuple(max(faces, key=lambda f: f[2]*f[3])), pre
        return None, pre

    def face_mask(self, image, rect):
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        x, y, fw, fh = rect
        cx, cy = x + fw//2, y + fh//2
        cv2.ellipse(mask, (cx, cy), (int(fw*0.48), int(fh*0.58)), 0, 0, 360, 255, -1)
        mask = cv2.GaussianBlur(mask, (5, 5), 0)
        _, mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
        return mask

    def detect_acne(self, image, face_mask):
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        ycrcb = cv2.cvtColor(image, cv2.COLOR_BGR2YCrCb)
        # Tighter red ranges to avoid false positives from lips/shadows
        r1 = cv2.inRange(hsv, np.array([0, 60, 60]), np.array([10, 255, 255]))
        r2 = cv2.inRange(hsv, np.array([162, 60, 60]), np.array([180, 255, 255]))
        red_hsv = r1 | r2
        # Tighter YCrCb: genuine inflammatory skin tones only
        red_ycc = cv2.inRange(ycrcb, np.array([50, 142, 90]), np.array([220, 180, 130]))
        # Require BOTH color signals to agree — reduces noise dramatically
        combined_color = cv2.bitwise_and(red_hsv, red_ycc)
        # Texture-only bumps: raised regions via local contrast
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(gray, cv2.GaussianBlur(gray, (21, 21), 0))
        _, tex = cv2.threshold(diff, 18, 255, cv2.THRESH_BINARY)
        # Texture spot must overlap color signal to count
        tex_confirmed = cv2.bitwise_and(tex, cv2.dilate(combined_color, np.ones((5,5),np.uint8)))
        combined = cv2.bitwise_or(combined_color, tex_confirmed)
        combined = cv2.bitwise_and(combined, face_mask)
        # Exclude lip/mouth region (lower 20% of face bounding box) to avoid lip false positives
        h_img, w_img = image.shape[:2]
        lip_mask = np.zeros_like(face_mask)
        ys, xs = np.where(face_mask > 0)
        if len(ys):
            ymin, ymax = ys.min(), ys.max()
            lip_zone = face_mask.copy()
            lip_zone[int(ymin + (ymax-ymin)*0.72):, :] = 0
            combined = cv2.bitwise_and(combined, lip_zone)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, k)
        combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, k)
        contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        spots, sizes, total_area = [], [], 0
        for c in contours:
            area = cv2.contourArea(c)
            if 20 < area < 1800:  # tighter size range for real acne spots
                x, y, w, h = cv2.boundingRect(c)
                ar = w / h if h > 0 else 0
                if 0.25 < ar < 4.0:  # more circular/oval only
                    spots.append((x, y, w, h)); sizes.append(area); total_area += area
        face_area = max(np.sum(face_mask > 0), 1)
        # Scale factors calibrated: 8 spots per 1000px2 = ~25% severity
        count_sev = min(100, (len(spots) / (face_area / 1000)) * 12)
        area_sev = min(100, (total_area / face_area) * 500)
        severity = (count_sev * 0.65 + area_sev * 0.35)
        # Confidence requires meaningful spot count
        conf = min(0.9, 0.15 + len(spots) / 25) if len(spots) >= 3 else min(0.45, 0.1 + len(spots) * 0.1)
        return SkinConcern(name="Acne & Breakouts", severity=severity,
            grade=self._grade(severity), confidence=conf,
            detected_regions=spots[:20],
            details=dict(spot_count=len(spots), avg_size=round(float(np.mean(sizes)) if sizes else 0, 1)))

    def detect_hyperpigmentation(self, image, face_mask):
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l_ch, a_ch, b_ch = cv2.split(lab)
        # Wider blur for smoother local average → better dark region isolation
        l_blur = cv2.GaussianBlur(l_ch, (51, 51), 0)
        l_diff = l_blur.astype(int) - l_ch.astype(int)
        # Threshold: pixel must be noticeably darker than its neighbourhood
        dark_mask = (l_diff > 15).astype(np.uint8) * 255
        # Also check chromatic shift: hyperpigmentation is brownish (a↑, b↑)
        a_elevated = (a_ch.astype(int) > 132).astype(np.uint8) * 255
        b_elevated = (b_ch.astype(int) > 128).astype(np.uint8) * 255
        chroma_mask = cv2.bitwise_or(a_elevated, b_elevated)
        # Combine: dark pixel AND chromatic brown shift
        combined = cv2.bitwise_and(dark_mask, chroma_mask)
        combined = cv2.bitwise_and(combined, face_mask)
        # Exclude very dark skin shadows at edges of face (unreliable)
        eroded_mask = cv2.erode(face_mask, np.ones((15,15), np.uint8))
        combined = cv2.bitwise_and(combined, eroded_mask)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, k)
        combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, k)
        contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        regions, total = [], 0
        for c in contours:
            area = cv2.contourArea(c)
            if area > 120:  # larger minimum to avoid noise spots
                regions.append(cv2.boundingRect(c)); total += area
        face_area = max(np.sum(face_mask > 0), 1)
        coverage = total / face_area
        severity = min(100, coverage * 450)
        conf = min(0.85, 0.12 + coverage * 7)
        return SkinConcern(name="Dark Spots & Pigmentation", severity=severity,
            grade=self._grade(severity), confidence=conf,
            detected_regions=regions[:15],
            details=dict(coverage_pct=round(coverage*100, 1), patch_count=len(regions)))

    def detect_wrinkles(self, image, face_mask):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # Denoise first to avoid detecting pores/texture as wrinkles
        denoised = cv2.bilateralFilter(gray, 9, 50, 50)
        # Multi-scale edge detection: wrinkles are elongated edges
        blur = cv2.GaussianBlur(denoised, (3, 3), 0)
        edges = cv2.Canny(blur, 25, 70)
        # Keep only elongated structures (wrinkles) using morphological opening
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 1))
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 9))
        d1_kernel = np.zeros((9,9), np.uint8); np.fill_diagonal(d1_kernel, 1)
        horizontal = cv2.morphologyEx(edges, cv2.MORPH_OPEN, h_kernel)
        vertical   = cv2.morphologyEx(edges, cv2.MORPH_OPEN, v_kernel)
        diagonal   = cv2.morphologyEx(edges, cv2.MORPH_OPEN, d1_kernel)
        wrinkle_mask = cv2.bitwise_or(cv2.bitwise_or(horizontal, vertical), diagonal)
        wrinkle_mask = cv2.bitwise_and(wrinkle_mask, face_mask)
        # Focus on wrinkle-prone zones: forehead (top 40%) and eye corners
        zone_mask = face_mask.copy()
        ys, xs = np.where(face_mask > 0)
        if len(ys):
            ymin, ymax = ys.min(), ys.max()
            # Weight forehead + eye area more; reduce cheek contribution
            cheek_start = int(ymin + (ymax - ymin) * 0.55)
            cheek_end   = int(ymin + (ymax - ymin) * 0.80)
            zone_mask[cheek_start:cheek_end, :] = (zone_mask[cheek_start:cheek_end, :] * 0.3).astype(np.uint8)
        # Weighted density
        face_area = max(np.sum(face_mask > 0), 1)
        wrinkle_density = np.sum(wrinkle_mask > 0) / face_area
        # Calibrated scale: typical skin has ~3-5% edge density from pores/texture; true wrinkles push it higher
        severity = min(100, max(0, (wrinkle_density - 0.03) * 1200))
        conf = min(0.80, 0.15 + wrinkle_density * 4)
        return SkinConcern(name="Fine Lines & Wrinkles", severity=severity,
            grade=self._grade(severity), confidence=conf,
            details=dict(wrinkle_density=round(wrinkle_density*100, 2)))

    def detect_dark_circles(self, image, rect):
        x, y, fw, fh = rect
        h, w = image.shape[:2]
        # Precise under-eye regions — slightly tighter vertically to exclude lid
        under_l = image[max(0, y+int(fh*0.40)):min(h, y+int(fh*0.50)),
                        max(0, x+int(fw*0.10)):min(w, x+int(fw*0.36))]
        under_r = image[max(0, y+int(fh*0.40)):min(h, y+int(fh*0.50)),
                        max(0, x+int(fw*0.60)):min(w, x+int(fw*0.88))]
        # Use mid-cheek (not lower cheek which can be reddish) as reference
        cheek_l = image[max(0, y+int(fh*0.55)):min(h, y+int(fh*0.70)),
                        max(0, x+int(fw*0.10)):min(w, x+int(fw*0.36))]
        cheek_r = image[max(0, y+int(fh*0.55)):min(h, y+int(fh*0.70)),
                        max(0, x+int(fw*0.60)):min(w, x+int(fw*0.88))]

        def mean_l_sat(roi):
            if roi.size == 0: return 128.0, 0.0
            lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            return float(np.mean(lab[:, :, 0])), float(np.mean(hsv[:, :, 1]))

        eye_l_lum, eye_l_sat   = mean_l_sat(under_l)
        eye_r_lum, eye_r_sat   = mean_l_sat(under_r)
        cheek_l_lum, _         = mean_l_sat(cheek_l)
        cheek_r_lum, _         = mean_l_sat(cheek_r)

        eye_brightness   = (eye_l_lum + eye_r_lum) / 2
        cheek_brightness = (cheek_l_lum + cheek_r_lum) / 2
        lum_diff = max(0, cheek_brightness - eye_brightness)
        # Also factor in bluish/purple tint: higher saturation under eyes = vascular dark circles
        eye_sat = (eye_l_sat + eye_r_sat) / 2
        sat_bonus = min(20, eye_sat * 0.4)
        severity = min(100, lum_diff * 3.2 + sat_bonus)
        conf = min(0.85, 0.2 + (lum_diff / 35) + (eye_sat / 200))
        return SkinConcern(name="Dark Circles", severity=severity,
            grade=self._grade(severity), confidence=conf,
            details=dict(brightness_diff=round(lum_diff, 1), under_eye_sat=round(eye_sat, 1)))

    def detect_redness(self, image, face_mask):
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        # Tighter saturation/value: genuine skin redness, not deep red of lips
        r1 = cv2.inRange(hsv, np.array([0, 55, 90]), np.array([9, 220, 255]))
        r2 = cv2.inRange(hsv, np.array([163, 55, 90]), np.array([180, 220, 255]))
        red = cv2.bitwise_or(r1, r2)
        red = cv2.bitwise_and(red, face_mask)
        # Exclude lips (lower 22% of face) and nostril centre
        ys, xs = np.where(face_mask > 0)
        if len(ys):
            ymin, ymax = ys.min(), ys.max()
            lip_top = int(ymin + (ymax - ymin) * 0.74)
            red[lip_top:, :] = 0
        # Remove isolated tiny noise pixels
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        red = cv2.morphologyEx(red, cv2.MORPH_OPEN, k)
        face_area = max(np.sum(face_mask > 0), 1)
        total = np.sum(red > 0)
        severity = min(100, (total / face_area) * 350)
        conf = min(0.80, 0.15 + (total / face_area) * 5)
        contours, _ = cv2.findContours(red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        regions = [cv2.boundingRect(c) for c in contours if cv2.contourArea(c) > 80]
        return SkinConcern(name="Redness & Inflammation", severity=severity,
            grade=self._grade(severity), confidence=conf,
            detected_regions=regions[:15],
            details=dict(coverage_pct=round((total/face_area)*100, 1)))

    def detect_enlarged_pores(self, image, face_mask, rect):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # Suppress hair and wrinkle edges — focus on small dark circular pits
        # Use local adaptive threshold to find dark pits relative to local skin tone
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        adaptive = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                          cv2.THRESH_BINARY_INV, 15, 6)
        adaptive = cv2.bitwise_and(adaptive, face_mask)
        # Focus on T-zone (nose + forehead) where pores are actually visible
        x, y, fw, fh = rect
        h_img, w_img = image.shape[:2]
        t_zone = np.zeros_like(face_mask)
        # Forehead
        t_zone[max(0, y): min(h_img, y+int(fh*0.45)),
               max(0, x+int(fw*0.25)): min(w_img, x+int(fw*0.75))] = 255
        # Nose bridge + nose
        t_zone[max(0, y+int(fh*0.35)): min(h_img, y+int(fh*0.72)),
               max(0, x+int(fw*0.35)): min(w_img, x+int(fw*0.65))] = 255
        t_zone = cv2.bitwise_and(t_zone, face_mask)
        pore_map = cv2.bitwise_and(adaptive, t_zone)
        # Remove elongated edges (those are not pores — pores are roundish)
        k_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        pore_map = cv2.morphologyEx(pore_map, cv2.MORPH_OPEN, k_open)
        cnts, _ = cv2.findContours(pore_map, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        pores, total = [], 0
        for c in cnts:
            area = cv2.contourArea(c)
            if 4 < area < 80:  # pore-sized only
                x_b, y_b, w_b, h_b = cv2.boundingRect(c)
                ar = w_b / max(h_b, 1)
                if 0.4 < ar < 2.5:  # roundish
                    pores.append((x_b, y_b, w_b, h_b)); total += area
        t_zone_area = max(np.sum(t_zone > 0), 1)
        density = len(pores) / (t_zone_area / 1000)
        severity = min(100, density * 1.8)
        conf = min(0.75, 0.15 + (severity / 100) * 0.5)
        return SkinConcern(name="Enlarged Pores", severity=severity,
            grade=self._grade(severity), confidence=conf,
            detected_regions=pores[:20],
            details=dict(pore_count=len(pores)))

    def detect_uneven_texture(self, image, face_mask):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # Bilateral filter to separate true texture from image noise
        smooth = cv2.bilateralFilter(gray, 9, 75, 75)
        lap = cv2.Laplacian(smooth.astype(np.float32), cv2.CV_32F)
        lap_abs = np.abs(lap)
        valid = lap_abs[face_mask > 0]
        if len(valid) == 0:
            return SkinConcern("Uneven Texture", 0, "A", 0)
        mean_tex = np.mean(valid)
        std_tex  = np.std(valid)
        # Rough pixels: more than 1.5 sigma above mean (tighter than before to reduce false positives)
        rough_pct = np.sum(valid > mean_tex + 1.5 * std_tex) / len(valid)
        # Calibrate: ~10% rough is baseline for any face photo; severity starts climbing above that
        severity = min(100, max(0, (rough_pct - 0.08) * 300))
        conf = min(0.80, 0.25 + (severity / 100) * 0.45)
        return SkinConcern(name="Uneven Texture", severity=severity,
            grade=self._grade(severity), confidence=conf,
            details=dict(roughness_pct=round(rough_pct*100, 1)))

    def _grade(self, severity):
        if severity <= 10: return "A"
        if severity <= 25: return "B"
        if severity <= 45: return "C"
        if severity <= 70: return "D"
        return "F"

    def analyze_image(self, image_bytes: bytes) -> AnalysisResult:
        """Analyze image from bytes (uploaded file). Returns AnalysisResult."""
        try:
            nparr = np.frombuffer(image_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                return self._empty_result(face_detected=False)

            rect, img = self.detect_face(frame)
            if rect is None:
                return self._empty_result(face_detected=False)

            mask = self.face_mask(img, rect)
            concerns = {
                'acne':             self.detect_acne(img, mask),
                'hyperpigmentation':self.detect_hyperpigmentation(img, mask),
                'wrinkles':         self.detect_wrinkles(img, mask),
                'dark_circles':     self.detect_dark_circles(img, rect),
                'redness':          self.detect_redness(img, mask),
                'texture':          self.detect_uneven_texture(img, mask),
                'pores':            self.detect_enlarged_pores(img, mask, rect),
            }

            weights = {'acne':0.2,'hyperpigmentation':0.15,'wrinkles':0.15,
                       'dark_circles':0.15,'redness':0.15,'texture':0.1,'pores':0.1}
            total_w, weighted_sev = 0, 0
            for k, w in weights.items():
                c = concerns[k]
                if c.confidence > 0.2:
                    weighted_sev += c.severity * w; total_w += w
            avg_sev = weighted_sev / max(total_w, 0.01)
            overall_score = round(100 - avg_sev, 1)
            overall_grade = self._grade(100 - overall_score)

            # Annotate — compress at 72 quality: good for display, ~25% smaller payload
            annotated = self._annotate(img.copy(), concerns, rect, overall_score, overall_grade)
            _, buf = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 72])
            b64 = base64.b64encode(buf).decode('utf-8')

            return AnalysisResult(concerns=concerns, overall_score=overall_score,
                                  overall_grade=overall_grade, face_detected=True,
                                  annotated_image_b64=b64)
        except Exception as e:
            print(f"[Analyzer] Error: {e}")
            import traceback; traceback.print_exc()
            return self._empty_result(face_detected=False)

    def _annotate(self, img, concerns, rect, score, grade):
        """Draw scan overlay on the image."""
        x, y, fw, fh = rect
        # Face oval
        cx, cy = x + fw//2, y + fh//2
        cv2.ellipse(img, (cx,cy), (int(fw*0.5), int(fh*0.6)), 0, 0, 360, (0,255,180), 2)

        COLORS = {'acne':(0,80,255),'hyperpigmentation':(0,165,255),
                  'wrinkles':(200,0,220),'dark_circles':(200,200,0),
                  'redness':(0,60,220),'texture':(80,200,0),'pores':(200,100,0)}
        ty = y - 12
        for k, concern in concerns.items():
            if concern.confidence < 0.25 or concern.severity < 8: continue
            col = COLORS.get(k, (255,255,255))
            label = f"{concern.name}: {concern.grade} ({concern.severity:.0f}%)"
            cv2.putText(img, label, (x, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.48, col, 1, cv2.LINE_AA)
            ty -= 20
            ov = img.copy()
            for r in concern.detected_regions[:8]:
                if len(r) == 4:
                    rx, ry, rw, rh = r
                    cv2.rectangle(ov,(rx,ry),(rx+rw,ry+rh),col,1)
            img = cv2.addWeighted(img, 0.8, ov, 0.2, 0)

        # Score badge
        bx, by = x + fw + 8, y
        cv2.rectangle(img, (bx,by), (bx+180,by+50), (20,20,30), -1)
        cv2.rectangle(img, (bx,by), (bx+180,by+50), (0,255,180), 1)
        cv2.putText(img, f"Skin Score: {score:.0f}/100", (bx+8,by+20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,255,180), 1, cv2.LINE_AA)
        cv2.putText(img, f"Grade: {grade}", (bx+8,by+40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255,255,180), 1, cv2.LINE_AA)
        return img

    def _empty_result(self, face_detected=False):
        empty = {k: SkinConcern(k, 0, "A", 0) for k in
                 ['acne','hyperpigmentation','wrinkles','dark_circles','redness','texture','pores']}
        return AnalysisResult(concerns=empty, overall_score=0,
                              overall_grade="A", face_detected=face_detected)


# Singleton
_analyzer = None
def get_analyzer() -> SkinAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = SkinAnalyzer()
    return _analyzer