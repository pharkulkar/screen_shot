# [OCR-FILE-DISABLED] Entire file commented out (local OCR removed; app is vision-only).
# [OCR-FILE-DISABLED] Restore: sed -i '' 's/^# \[OCR-DISABLED\] //' OCR.py  (then delete these 3 header lines)
# [OCR-FILE-DISABLED] Blank lines were left as-is; every other line is prefixed with '# [OCR-DISABLED] '.
# [OCR-DISABLED] import os
# [OCR-DISABLED] import cv2
# [OCR-DISABLED] import json
# [OCR-DISABLED] import re
# [OCR-DISABLED] import numpy as np
# [OCR-DISABLED] from statistics import median
# [OCR-DISABLED] from paddleocr import PaddleOCR


# [OCR-DISABLED] class SmartQuestionOCR:

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # INITIALIZATION
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     def __init__(self):

# [OCR-DISABLED]         print("\nLoading PaddleOCR models...")

# [OCR-DISABLED]         self.ocr = PaddleOCR(
# [OCR-DISABLED]             use_doc_orientation_classify=True,
# [OCR-DISABLED]             use_doc_unwarping=True,
# [OCR-DISABLED]             use_textline_orientation=True,
# [OCR-DISABLED]             lang="en"
# [OCR-DISABLED]         )

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # TEXT CLEANING
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     @staticmethod
# [OCR-DISABLED]     def clean_text(text):

# [OCR-DISABLED]         if text is None:
# [OCR-DISABLED]             return ""

# [OCR-DISABLED]         text = str(text)

# [OCR-DISABLED]         text = re.sub(
# [OCR-DISABLED]             r"\s+",
# [OCR-DISABLED]             " ",
# [OCR-DISABLED]             text
# [OCR-DISABLED]         )

# [OCR-DISABLED]         return text.strip()

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # BOX HELPERS
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     @staticmethod
# [OCR-DISABLED]     def get_box(item):

# [OCR-DISABLED]         box = item.get("box", [0, 0, 0, 0])

# [OCR-DISABLED]         return (
# [OCR-DISABLED]             int(box[0]),
# [OCR-DISABLED]             int(box[1]),
# [OCR-DISABLED]             int(box[2]),
# [OCR-DISABLED]             int(box[3])
# [OCR-DISABLED]         )

# [OCR-DISABLED]     def get_height(self, item):

# [OCR-DISABLED]         _, y1, _, y2 = self.get_box(item)

# [OCR-DISABLED]         return max(1, y2 - y1)

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # IMAGE PREPROCESSING
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     def preprocess_image(self, image_path):

# [OCR-DISABLED]         # Check path before loading
# [OCR-DISABLED]         if not os.path.exists(image_path):

# [OCR-DISABLED]             raise FileNotFoundError(
# [OCR-DISABLED]                 f"\nImage not found:\n{image_path}\n\n"
# [OCR-DISABLED]                 f"Please verify the absolute image path."
# [OCR-DISABLED]             )

# [OCR-DISABLED]         image = cv2.imread(image_path)

# [OCR-DISABLED]         if image is None:

# [OCR-DISABLED]             raise ValueError(
# [OCR-DISABLED]                 f"\nUnable to load image:\n{image_path}"
# [OCR-DISABLED]             )

# [OCR-DISABLED]         height, width = image.shape[:2]

# [OCR-DISABLED]         print(
# [OCR-DISABLED]             f"Original image size: "
# [OCR-DISABLED]             f"{width} x {height}"
# [OCR-DISABLED]         )

# [OCR-DISABLED]         # Upscale only relatively small images
# [OCR-DISABLED]         if width < 1200:

# [OCR-DISABLED]             scale = 2

# [OCR-DISABLED]             image = cv2.resize(
# [OCR-DISABLED]                 image,
# [OCR-DISABLED]                 None,
# [OCR-DISABLED]                 fx=scale,
# [OCR-DISABLED]                 fy=scale,
# [OCR-DISABLED]                 interpolation=cv2.INTER_CUBIC
# [OCR-DISABLED]             )

# [OCR-DISABLED]             print(
# [OCR-DISABLED]                 f"Upscaled image size: "
# [OCR-DISABLED]                 f"{image.shape[1]} x "
# [OCR-DISABLED]                 f"{image.shape[0]}"
# [OCR-DISABLED]             )

# [OCR-DISABLED]         # Light denoising
# [OCR-DISABLED]         # Keep image in BGR format for PaddleOCR
# [OCR-DISABLED]         image = cv2.bilateralFilter(
# [OCR-DISABLED]             image,
# [OCR-DISABLED]             7,
# [OCR-DISABLED]             50,
# [OCR-DISABLED]             50
# [OCR-DISABLED]         )

# [OCR-DISABLED]         return image

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # OCR EXTRACTION
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     def extract_ocr_items(
# [OCR-DISABLED]         self,
# [OCR-DISABLED]         image_path,
# [OCR-DISABLED]         min_confidence=0.50
# [OCR-DISABLED]     ):

# [OCR-DISABLED]         image = self.preprocess_image(
# [OCR-DISABLED]             image_path
# [OCR-DISABLED]         )

# [OCR-DISABLED]         print("\nPerforming OCR...")

# [OCR-DISABLED]         results = self.ocr.predict(
# [OCR-DISABLED]             image
# [OCR-DISABLED]         )

# [OCR-DISABLED]         items = []

# [OCR-DISABLED]         for page in results:

# [OCR-DISABLED]             # --------------------------------------------------
# [OCR-DISABLED]             # Convert PaddleOCR result into dictionary
# [OCR-DISABLED]             # --------------------------------------------------

# [OCR-DISABLED]             if hasattr(page, "json"):

# [OCR-DISABLED]                 page_data = page.json

# [OCR-DISABLED]             elif isinstance(page, dict):

# [OCR-DISABLED]                 page_data = page

# [OCR-DISABLED]             else:

# [OCR-DISABLED]                 continue

# [OCR-DISABLED]             # Some versions return JSON string
# [OCR-DISABLED]             if isinstance(page_data, str):

# [OCR-DISABLED]                 try:

# [OCR-DISABLED]                     page_data = json.loads(
# [OCR-DISABLED]                         page_data
# [OCR-DISABLED]                     )

# [OCR-DISABLED]                 except json.JSONDecodeError:

# [OCR-DISABLED]                     continue

# [OCR-DISABLED]             if not isinstance(page_data, dict):

# [OCR-DISABLED]                 continue

# [OCR-DISABLED]             # PaddleOCR result
# [OCR-DISABLED]             res = page_data.get(
# [OCR-DISABLED]                 "res",
# [OCR-DISABLED]                 {}
# [OCR-DISABLED]             )

# [OCR-DISABLED]             texts = res.get(
# [OCR-DISABLED]                 "rec_texts",
# [OCR-DISABLED]                 []
# [OCR-DISABLED]             )

# [OCR-DISABLED]             scores = res.get(
# [OCR-DISABLED]                 "rec_scores",
# [OCR-DISABLED]                 []
# [OCR-DISABLED]             )

# [OCR-DISABLED]             boxes = res.get(
# [OCR-DISABLED]                 "rec_boxes",
# [OCR-DISABLED]                 []
# [OCR-DISABLED]             )

# [OCR-DISABLED]             # --------------------------------------------------
# [OCR-DISABLED]             # Create OCR items
# [OCR-DISABLED]             # --------------------------------------------------

# [OCR-DISABLED]             for text, score, box in zip(
# [OCR-DISABLED]                 texts,
# [OCR-DISABLED]                 scores,
# [OCR-DISABLED]                 boxes
# [OCR-DISABLED]             ):

# [OCR-DISABLED]                 text = self.clean_text(
# [OCR-DISABLED]                     text
# [OCR-DISABLED]                 )

# [OCR-DISABLED]                 if not text:
# [OCR-DISABLED]                     continue

# [OCR-DISABLED]                 try:

# [OCR-DISABLED]                     score = float(score)

# [OCR-DISABLED]                 except (TypeError, ValueError):

# [OCR-DISABLED]                     score = 0.0

# [OCR-DISABLED]                 if score < min_confidence:
# [OCR-DISABLED]                     continue

# [OCR-DISABLED]                 try:

# [OCR-DISABLED]                     box = [
# [OCR-DISABLED]                         int(value)
# [OCR-DISABLED]                         for value in box
# [OCR-DISABLED]                     ]

# [OCR-DISABLED]                 except Exception:

# [OCR-DISABLED]                     continue

# [OCR-DISABLED]                 if len(box) != 4:
# [OCR-DISABLED]                     continue

# [OCR-DISABLED]                 items.append({

# [OCR-DISABLED]                     "text": text,

# [OCR-DISABLED]                     "confidence": score,

# [OCR-DISABLED]                     "box": box

# [OCR-DISABLED]                 })

# [OCR-DISABLED]         # Sort from top to bottom
# [OCR-DISABLED]         items.sort(
# [OCR-DISABLED]             key=lambda item: (
# [OCR-DISABLED]                 self.get_box(item)[1],
# [OCR-DISABLED]                 self.get_box(item)[0]
# [OCR-DISABLED]             )
# [OCR-DISABLED]         )

# [OCR-DISABLED]         return items

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # UI NOISE DETECTION
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     def is_ui_noise(self, text):

# [OCR-DISABLED]         text = self.clean_text(text)

# [OCR-DISABLED]         lower = text.lower()

# [OCR-DISABLED]         patterns = [

# [OCR-DISABLED]             # Input fields
# [OCR-DISABLED]             r"^type your answer.*$",
# [OCR-DISABLED]             r"^enter your answer.*$",
# [OCR-DISABLED]             r"^write your answer.*$",

# [OCR-DISABLED]             # Navigation
# [OCR-DISABLED]             r"^(next|previous|submit|finish|back|continue)$",

# [OCR-DISABLED]             # Assessment state
# [OCR-DISABLED]             r"^(answered|not answered)$",

# [OCR-DISABLED]             # Progress
# [OCR-DISABLED]             r"^\d+\s*/\s*\d+$",

# [OCR-DISABLED]             # Timer
# [OCR-DISABLED]             r"^\d{1,2}:\d{2}$",

# [OCR-DISABLED]             # Single OCR garbage characters
# [OCR-DISABLED]             r"^[a-z]{1,2}$"
# [OCR-DISABLED]         ]

# [OCR-DISABLED]         for pattern in patterns:

# [OCR-DISABLED]             if re.match(
# [OCR-DISABLED]                 pattern,
# [OCR-DISABLED]                 lower,
# [OCR-DISABLED]                 re.IGNORECASE
# [OCR-DISABLED]             ):

# [OCR-DISABLED]                 return True

# [OCR-DISABLED]         return False

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # EXPLICIT QUESTION ANCHOR
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     def is_question_anchor(self, text):

# [OCR-DISABLED]         text = self.clean_text(text)

# [OCR-DISABLED]         patterns = [

# [OCR-DISABLED]             # Q1
# [OCR-DISABLED]             r"^Q\s*\d+$",

# [OCR-DISABLED]             # Q.1
# [OCR-DISABLED]             r"^Q\.\s*\d+$",

# [OCR-DISABLED]             # Question 1
# [OCR-DISABLED]             r"^Question\s+\d+$",

# [OCR-DISABLED]             # Question 1.
# [OCR-DISABLED]             r"^Question\s+\d+[\.\):]?$"
# [OCR-DISABLED]         ]

# [OCR-DISABLED]         for pattern in patterns:

# [OCR-DISABLED]             if re.match(
# [OCR-DISABLED]                 pattern,
# [OCR-DISABLED]                 text,
# [OCR-DISABLED]                 re.IGNORECASE
# [OCR-DISABLED]             ):

# [OCR-DISABLED]                 return True

# [OCR-DISABLED]         return False

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # EXPLICIT OPTION DETECTION
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     def is_explicit_option(self, text):

# [OCR-DISABLED]         text = self.clean_text(text)

# [OCR-DISABLED]         patterns = [
# [OCR-DISABLED]             # A. Option / OA. Option / OB.$0.05 / O A. Option
# [OCR-DISABLED]             r"^(?:O|0|○|◯|●)?\s*\(?[A-Ha-h]\)?[\.\):]\s*.+$",

# [OCR-DISABLED]             # (A) Option
# [OCR-DISABLED]             r"^\([A-Ha-h]\)\s*.+$",

# [OCR-DISABLED]             # 1. Option
# [OCR-DISABLED]             r"^\d+[\.\)]\s*.+$"
# [OCR-DISABLED]         ]

# [OCR-DISABLED]         for pattern in patterns:

# [OCR-DISABLED]             if re.match(
# [OCR-DISABLED]                 pattern,
# [OCR-DISABLED]                 text,
# [OCR-DISABLED]                 re.IGNORECASE
# [OCR-DISABLED]             ):

# [OCR-DISABLED]                 return True

# [OCR-DISABLED]         return False

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # OPTION CONTAMINATION DETECTION
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     def contains_embedded_option(self, text):

# [OCR-DISABLED]         text = self.clean_text(text)

# [OCR-DISABLED]         if not text:
# [OCR-DISABLED]             return False

# [OCR-DISABLED]         patterns = [
# [OCR-DISABLED]             # "...? A. answer", "...? OA. answer", "...? OB.$0.05"
# [OCR-DISABLED]             r"\s+(?:O|0|○|◯|●)?\s*\(?[A-Ha-h]\)?[\.\):]\s*(?=\S)",

# [OCR-DISABLED]             # "...? 1. answer"
# [OCR-DISABLED]             r"\s+\d+[\.\)]\s*(?=\S)"
# [OCR-DISABLED]         ]

# [OCR-DISABLED]         for pattern in patterns:

# [OCR-DISABLED]             for match in re.finditer(
# [OCR-DISABLED]                 pattern,
# [OCR-DISABLED]                 text,
# [OCR-DISABLED]                 re.IGNORECASE
# [OCR-DISABLED]             ):

# [OCR-DISABLED]                 # Only an option AFTER existing question text is contamination.
# [OCR-DISABLED]                 if match.start() > 0:

# [OCR-DISABLED]                     return True

# [OCR-DISABLED]         return False

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # QUESTION TEXT CLEANUP
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     def clean_question_candidate(self, text):

# [OCR-DISABLED]         text = self.clean_text(text)

# [OCR-DISABLED]         if not text:
# [OCR-DISABLED]             return ""

# [OCR-DISABLED]         patterns = [
# [OCR-DISABLED]             r"\s+(?:O|0|○|◯|●)?\s*\(?[A-Ha-h]\)?[\.\):]\s*.+$",
# [OCR-DISABLED]             r"\s+\d+[\.\)]\s*.+$"
# [OCR-DISABLED]         ]

# [OCR-DISABLED]         for pattern in patterns:

# [OCR-DISABLED]             match = re.search(
# [OCR-DISABLED]                 pattern,
# [OCR-DISABLED]                 text,
# [OCR-DISABLED]                 re.IGNORECASE
# [OCR-DISABLED]             )

# [OCR-DISABLED]             if match and match.start() > 0:

# [OCR-DISABLED]                 text = text[:match.start()]
# [OCR-DISABLED]                 break

# [OCR-DISABLED]         return self.clean_text(text)

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # CALCULATE DYNAMIC LAYOUT METRICS
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     def calculate_layout_metrics(self, items):

# [OCR-DISABLED]         if not items:

# [OCR-DISABLED]             return {

# [OCR-DISABLED]                 "median_height": 30,

# [OCR-DISABLED]                 "x_threshold": 50,

# [OCR-DISABLED]                 "max_vertical_gap": 200,

# [OCR-DISABLED]                 "line_gap_limit": 100
# [OCR-DISABLED]             }

# [OCR-DISABLED]         heights = []

# [OCR-DISABLED]         for item in items:

# [OCR-DISABLED]             height = self.get_height(item)

# [OCR-DISABLED]             if height > 0:

# [OCR-DISABLED]                 heights.append(height)

# [OCR-DISABLED]         if not heights:

# [OCR-DISABLED]             median_height = 30

# [OCR-DISABLED]         else:

# [OCR-DISABLED]             median_height = median(
# [OCR-DISABLED]                 heights
# [OCR-DISABLED]             )

# [OCR-DISABLED]         return {

# [OCR-DISABLED]             "median_height":
# [OCR-DISABLED]                 median_height,

# [OCR-DISABLED]             "x_threshold":
# [OCR-DISABLED]                 max(
# [OCR-DISABLED]                     25,
# [OCR-DISABLED]                     median_height * 1.5
# [OCR-DISABLED]                 ),

# [OCR-DISABLED]             "max_vertical_gap":
# [OCR-DISABLED]                 max(
# [OCR-DISABLED]                     120,
# [OCR-DISABLED]                     median_height * 6
# [OCR-DISABLED]                 ),

# [OCR-DISABLED]             "line_gap_limit":
# [OCR-DISABLED]                 max(
# [OCR-DISABLED]                     80,
# [OCR-DISABLED]                     median_height * 4
# [OCR-DISABLED]                 )
# [OCR-DISABLED]         }

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # DETECT OPTION GROUPS USING LEFT ALIGNMENT
# [OCR-DISABLED]     #
# [OCR-DISABLED]     # Example:
# [OCR-DISABLED]     #
# [OCR-DISABLED]     # What is Angular?       x = 0
# [OCR-DISABLED]     #
# [OCR-DISABLED]     # A CSS preprocessor     x = 94
# [OCR-DISABLED]     # A JavaScript library   x = 95
# [OCR-DISABLED]     # A framework...         x = 93
# [OCR-DISABLED]     # A programming...       x = 91
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     def detect_layout_option_groups(
# [OCR-DISABLED]         self,
# [OCR-DISABLED]         items,
# [OCR-DISABLED]         metrics
# [OCR-DISABLED]     ):

# [OCR-DISABLED]         if len(items) < 3:

# [OCR-DISABLED]             return []

# [OCR-DISABLED]         sorted_items = sorted(
# [OCR-DISABLED]             items,
# [OCR-DISABLED]             key=lambda item: (
# [OCR-DISABLED]                 self.get_box(item)[1],
# [OCR-DISABLED]                 self.get_box(item)[0]
# [OCR-DISABLED]             )
# [OCR-DISABLED]         )

# [OCR-DISABLED]         x_threshold = metrics[
# [OCR-DISABLED]             "x_threshold"
# [OCR-DISABLED]         ]

# [OCR-DISABLED]         max_vertical_gap = metrics[
# [OCR-DISABLED]             "max_vertical_gap"
# [OCR-DISABLED]         ]

# [OCR-DISABLED]         x_clusters = []

# [OCR-DISABLED]         # ------------------------------------------------------
# [OCR-DISABLED]         # STEP 1:
# [OCR-DISABLED]         # Cluster text having similar left alignment
# [OCR-DISABLED]         # ------------------------------------------------------

# [OCR-DISABLED]         for item in sorted_items:

# [OCR-DISABLED]             text = self.clean_text(
# [OCR-DISABLED]                 item["text"]
# [OCR-DISABLED]             )

# [OCR-DISABLED]             if self.is_ui_noise(text):
# [OCR-DISABLED]                 continue

# [OCR-DISABLED]             x1, _, _, _ = self.get_box(
# [OCR-DISABLED]                 item
# [OCR-DISABLED]             )

# [OCR-DISABLED]             added_to_cluster = False

# [OCR-DISABLED]             for cluster in x_clusters:

# [OCR-DISABLED]                 x_values = [

# [OCR-DISABLED]                     self.get_box(
# [OCR-DISABLED]                         cluster_item
# [OCR-DISABLED]                     )[0]

# [OCR-DISABLED]                     for cluster_item in cluster
# [OCR-DISABLED]                 ]

# [OCR-DISABLED]                 median_x = float(
# [OCR-DISABLED]                     np.median(x_values)
# [OCR-DISABLED]                 )

# [OCR-DISABLED]                 if abs(
# [OCR-DISABLED]                     x1 - median_x
# [OCR-DISABLED]                 ) <= x_threshold:

# [OCR-DISABLED]                     cluster.append(item)

# [OCR-DISABLED]                     added_to_cluster = True

# [OCR-DISABLED]                     break

# [OCR-DISABLED]             if not added_to_cluster:

# [OCR-DISABLED]                 x_clusters.append(
# [OCR-DISABLED]                     [item]
# [OCR-DISABLED]                 )

# [OCR-DISABLED]         # ------------------------------------------------------
# [OCR-DISABLED]         # STEP 2:
# [OCR-DISABLED]         # Split clusters based on vertical distance
# [OCR-DISABLED]         # ------------------------------------------------------

# [OCR-DISABLED]         valid_groups = []

# [OCR-DISABLED]         for cluster in x_clusters:

# [OCR-DISABLED]             if len(cluster) < 3:
# [OCR-DISABLED]                 continue

# [OCR-DISABLED]             cluster.sort(
# [OCR-DISABLED]                 key=lambda item:
# [OCR-DISABLED]                     self.get_box(item)[1]
# [OCR-DISABLED]             )

# [OCR-DISABLED]             current_group = [
# [OCR-DISABLED]                 cluster[0]
# [OCR-DISABLED]             ]

# [OCR-DISABLED]             previous_item = cluster[0]

# [OCR-DISABLED]             for item in cluster[1:]:

# [OCR-DISABLED]                 _, previous_y1, _, _ = (
# [OCR-DISABLED]                     self.get_box(
# [OCR-DISABLED]                         previous_item
# [OCR-DISABLED]                     )
# [OCR-DISABLED]                 )

# [OCR-DISABLED]                 _, current_y1, _, _ = (
# [OCR-DISABLED]                     self.get_box(
# [OCR-DISABLED]                         item
# [OCR-DISABLED]                     )
# [OCR-DISABLED]                 )

# [OCR-DISABLED]                 vertical_gap = (
# [OCR-DISABLED]                     current_y1 - previous_y1
# [OCR-DISABLED]                 )

# [OCR-DISABLED]                 if (
# [OCR-DISABLED]                     vertical_gap > 0
# [OCR-DISABLED]                     and vertical_gap <= max_vertical_gap
# [OCR-DISABLED]                 ):

# [OCR-DISABLED]                     current_group.append(
# [OCR-DISABLED]                         item
# [OCR-DISABLED]                     )

# [OCR-DISABLED]                 else:

# [OCR-DISABLED]                     if len(current_group) >= 3:

# [OCR-DISABLED]                         valid_groups.append(
# [OCR-DISABLED]                             current_group
# [OCR-DISABLED]                         )

# [OCR-DISABLED]                     current_group = [
# [OCR-DISABLED]                         item
# [OCR-DISABLED]                     ]

# [OCR-DISABLED]                 previous_item = item

# [OCR-DISABLED]             # Save final group
# [OCR-DISABLED]             if len(current_group) >= 3:

# [OCR-DISABLED]                 valid_groups.append(
# [OCR-DISABLED]                     current_group
# [OCR-DISABLED]                 )

# [OCR-DISABLED]         return valid_groups

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # DETECT EXPLICIT OPTION GROUPS
# [OCR-DISABLED]     #
# [OCR-DISABLED]     # Example:
# [OCR-DISABLED]     #
# [OCR-DISABLED]     # A. Something
# [OCR-DISABLED]     # B. Something
# [OCR-DISABLED]     # C. Something
# [OCR-DISABLED]     # D. Something
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     def detect_explicit_option_groups(
# [OCR-DISABLED]         self,
# [OCR-DISABLED]         items,
# [OCR-DISABLED]         metrics
# [OCR-DISABLED]     ):

# [OCR-DISABLED]         option_items = []

# [OCR-DISABLED]         for item in items:

# [OCR-DISABLED]             if self.is_explicit_option(
# [OCR-DISABLED]                 item["text"]
# [OCR-DISABLED]             ):

# [OCR-DISABLED]                 option_items.append(
# [OCR-DISABLED]                     item
# [OCR-DISABLED]                 )

# [OCR-DISABLED]         if len(option_items) < 2:

# [OCR-DISABLED]             return []

# [OCR-DISABLED]         option_items.sort(
# [OCR-DISABLED]             key=lambda item:
# [OCR-DISABLED]                 self.get_box(item)[1]
# [OCR-DISABLED]         )

# [OCR-DISABLED]         groups = []

# [OCR-DISABLED]         current_group = [
# [OCR-DISABLED]             option_items[0]
# [OCR-DISABLED]         ]

# [OCR-DISABLED]         previous_item = option_items[0]

# [OCR-DISABLED]         max_gap = (
# [OCR-DISABLED]             metrics[
# [OCR-DISABLED]                 "max_vertical_gap"
# [OCR-DISABLED]             ] * 1.5
# [OCR-DISABLED]         )

# [OCR-DISABLED]         for item in option_items[1:]:

# [OCR-DISABLED]             _, previous_y1, _, _ = (
# [OCR-DISABLED]                 self.get_box(
# [OCR-DISABLED]                     previous_item
# [OCR-DISABLED]                 )
# [OCR-DISABLED]             )

# [OCR-DISABLED]             _, current_y1, _, _ = (
# [OCR-DISABLED]                 self.get_box(item)
# [OCR-DISABLED]             )

# [OCR-DISABLED]             vertical_gap = (
# [OCR-DISABLED]                 current_y1 - previous_y1
# [OCR-DISABLED]             )

# [OCR-DISABLED]             if (
# [OCR-DISABLED]                 vertical_gap > 0
# [OCR-DISABLED]                 and vertical_gap <= max_gap
# [OCR-DISABLED]             ):

# [OCR-DISABLED]                 current_group.append(
# [OCR-DISABLED]                     item
# [OCR-DISABLED]                 )

# [OCR-DISABLED]             else:

# [OCR-DISABLED]                 if len(current_group) >= 2:

# [OCR-DISABLED]                     groups.append(
# [OCR-DISABLED]                         current_group
# [OCR-DISABLED]                     )

# [OCR-DISABLED]                 current_group = [
# [OCR-DISABLED]                     item
# [OCR-DISABLED]                 ]

# [OCR-DISABLED]             previous_item = item

# [OCR-DISABLED]         if len(current_group) >= 2:

# [OCR-DISABLED]             groups.append(
# [OCR-DISABLED]                 current_group
# [OCR-DISABLED]             )

# [OCR-DISABLED]         return groups

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # REMOVE DUPLICATE GROUPS
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     def remove_duplicate_groups(self, groups):

# [OCR-DISABLED]         unique_groups = []

# [OCR-DISABLED]         seen = set()

# [OCR-DISABLED]         for group in groups:

# [OCR-DISABLED]             group_key = tuple(
# [OCR-DISABLED]                 sorted(
# [OCR-DISABLED]                     id(item)
# [OCR-DISABLED]                     for item in group
# [OCR-DISABLED]                 )
# [OCR-DISABLED]             )

# [OCR-DISABLED]             if group_key in seen:
# [OCR-DISABLED]                 continue

# [OCR-DISABLED]             seen.add(
# [OCR-DISABLED]                 group_key
# [OCR-DISABLED]             )

# [OCR-DISABLED]             unique_groups.append(
# [OCR-DISABLED]                 group
# [OCR-DISABLED]             )

# [OCR-DISABLED]         return unique_groups

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # EXTRACT QUESTION ABOVE OPTION GROUP
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     def extract_question_before_options(
# [OCR-DISABLED]         self,
# [OCR-DISABLED]         items,
# [OCR-DISABLED]         option_groups,
# [OCR-DISABLED]         metrics
# [OCR-DISABLED]     ):

# [OCR-DISABLED]         questions = []

# [OCR-DISABLED]         for group in option_groups:

# [OCR-DISABLED]             if not group:
# [OCR-DISABLED]                 continue

# [OCR-DISABLED]             group = sorted(
# [OCR-DISABLED]                 group,
# [OCR-DISABLED]                 key=lambda item:
# [OCR-DISABLED]                     self.get_box(item)[1]
# [OCR-DISABLED]             )

# [OCR-DISABLED]             first_option = group[0]

# [OCR-DISABLED]             _, option_y1, _, _ = (
# [OCR-DISABLED]                 self.get_box(
# [OCR-DISABLED]                     first_option
# [OCR-DISABLED]                 )
# [OCR-DISABLED]             )

# [OCR-DISABLED]             candidates = []

# [OCR-DISABLED]             max_question_distance = max(
# [OCR-DISABLED]                 350,
# [OCR-DISABLED]                 metrics[
# [OCR-DISABLED]                     "median_height"
# [OCR-DISABLED]                 ] * 15
# [OCR-DISABLED]             )

# [OCR-DISABLED]             # --------------------------------------------------
# [OCR-DISABLED]             # Find meaningful text above first option
# [OCR-DISABLED]             # --------------------------------------------------

# [OCR-DISABLED]             for item in items:

# [OCR-DISABLED]                 if item in group:
# [OCR-DISABLED]                     continue

# [OCR-DISABLED]                 text = self.clean_text(
# [OCR-DISABLED]                     item["text"]
# [OCR-DISABLED]                 )

# [OCR-DISABLED]                 if not text:
# [OCR-DISABLED]                     continue

# [OCR-DISABLED]                 if self.is_ui_noise(text):
# [OCR-DISABLED]                     continue

# [OCR-DISABLED]                 _, y1, _, y2 = self.get_box(
# [OCR-DISABLED]                     item
# [OCR-DISABLED]                 )

# [OCR-DISABLED]                 # Must be above first option
# [OCR-DISABLED]                 if y2 > option_y1:
# [OCR-DISABLED]                     continue

# [OCR-DISABLED]                 distance = (
# [OCR-DISABLED]                     option_y1 - y2
# [OCR-DISABLED]                 )

# [OCR-DISABLED]                 if distance > max_question_distance:
# [OCR-DISABLED]                     continue

# [OCR-DISABLED]                 candidates.append(
# [OCR-DISABLED]                     item
# [OCR-DISABLED]                 )

# [OCR-DISABLED]             if not candidates:
# [OCR-DISABLED]                 continue

# [OCR-DISABLED]             # --------------------------------------------------
# [OCR-DISABLED]             # Closest text above options
# [OCR-DISABLED]             # --------------------------------------------------

# [OCR-DISABLED]             candidates.sort(
# [OCR-DISABLED]                 key=lambda item:
# [OCR-DISABLED]                     self.get_box(item)[3],
# [OCR-DISABLED]                 reverse=True
# [OCR-DISABLED]             )

# [OCR-DISABLED]             closest_item = candidates[0]

# [OCR-DISABLED]             selected_items = [
# [OCR-DISABLED]                 closest_item
# [OCR-DISABLED]             ]

# [OCR-DISABLED]             _, current_top_y, _, _ = (
# [OCR-DISABLED]                 self.get_box(
# [OCR-DISABLED]                     closest_item
# [OCR-DISABLED]                 )
# [OCR-DISABLED]             )

# [OCR-DISABLED]             # --------------------------------------------------
# [OCR-DISABLED]             # Detect wrapped lines above the closest line
# [OCR-DISABLED]             # --------------------------------------------------

# [OCR-DISABLED]             other_candidates = [

# [OCR-DISABLED]                 item

# [OCR-DISABLED]                 for item in candidates

# [OCR-DISABLED]                 if item is not closest_item
# [OCR-DISABLED]             ]

# [OCR-DISABLED]             other_candidates.sort(
# [OCR-DISABLED]                 key=lambda item:
# [OCR-DISABLED]                     self.get_box(item)[1],
# [OCR-DISABLED]                 reverse=True
# [OCR-DISABLED]             )

# [OCR-DISABLED]             for item in other_candidates:

# [OCR-DISABLED]                 _, y1, _, y2 = self.get_box(
# [OCR-DISABLED]                     item
# [OCR-DISABLED]                 )

# [OCR-DISABLED]                 if y2 > current_top_y:
# [OCR-DISABLED]                     continue

# [OCR-DISABLED]                 vertical_gap = (
# [OCR-DISABLED]                     current_top_y - y2
# [OCR-DISABLED]                 )

# [OCR-DISABLED]                 if vertical_gap <= metrics[
# [OCR-DISABLED]                     "line_gap_limit"
# [OCR-DISABLED]                 ]:

# [OCR-DISABLED]                     selected_items.append(
# [OCR-DISABLED]                         item
# [OCR-DISABLED]                     )

# [OCR-DISABLED]                     current_top_y = y1

# [OCR-DISABLED]                 else:

# [OCR-DISABLED]                     break

# [OCR-DISABLED]             # --------------------------------------------------
# [OCR-DISABLED]             # Restore reading order
# [OCR-DISABLED]             # --------------------------------------------------

# [OCR-DISABLED]             selected_items.sort(
# [OCR-DISABLED]                 key=lambda item: (
# [OCR-DISABLED]                     self.get_box(item)[1],
# [OCR-DISABLED]                     self.get_box(item)[0]
# [OCR-DISABLED]                 )
# [OCR-DISABLED]             )

# [OCR-DISABLED]             question_text = " ".join(

# [OCR-DISABLED]                 self.clean_text(
# [OCR-DISABLED]                     item["text"]
# [OCR-DISABLED]                 )

# [OCR-DISABLED]                 for item in selected_items

# [OCR-DISABLED]             )

# [OCR-DISABLED]             question_text = self.clean_text(
# [OCR-DISABLED]                 question_text
# [OCR-DISABLED]             )

# [OCR-DISABLED]             if len(question_text) < 3:
# [OCR-DISABLED]                 continue

# [OCR-DISABLED]             questions.append({

# [OCR-DISABLED]                 "possible_question":
# [OCR-DISABLED]                     question_text,

# [OCR-DISABLED]                 "confidence":
# [OCR-DISABLED]                     0.88,

# [OCR-DISABLED]                 "detection_method":
# [OCR-DISABLED]                     "question_before_option_group"
# [OCR-DISABLED]             })

# [OCR-DISABLED]         return questions

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # EXTRACT QUESTIONS WITH Q1 / Q2 / QUESTION 1
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     def extract_numbered_questions(
# [OCR-DISABLED]         self,
# [OCR-DISABLED]         items,
# [OCR-DISABLED]         metrics
# [OCR-DISABLED]     ):

# [OCR-DISABLED]         questions = []

# [OCR-DISABLED]         anchors = []

# [OCR-DISABLED]         for item in items:

# [OCR-DISABLED]             if self.is_question_anchor(
# [OCR-DISABLED]                 item["text"]
# [OCR-DISABLED]             ):

# [OCR-DISABLED]                 anchors.append(
# [OCR-DISABLED]                     item
# [OCR-DISABLED]                 )

# [OCR-DISABLED]         anchors.sort(
# [OCR-DISABLED]             key=lambda item:
# [OCR-DISABLED]             self.get_box(item)[1]
# [OCR-DISABLED]         )

# [OCR-DISABLED]         sorted_items = sorted(
# [OCR-DISABLED]             items,
# [OCR-DISABLED]             key=lambda item: (
# [OCR-DISABLED]                 self.get_box(item)[1],
# [OCR-DISABLED]                 self.get_box(item)[0]
# [OCR-DISABLED]             )
# [OCR-DISABLED]         )

# [OCR-DISABLED]         for index, anchor in enumerate(
# [OCR-DISABLED]             anchors
# [OCR-DISABLED]         ):

# [OCR-DISABLED]             _, anchor_y1, _, _ = self.get_box(
# [OCR-DISABLED]                 anchor
# [OCR-DISABLED]             )

# [OCR-DISABLED]             if index + 1 < len(anchors):

# [OCR-DISABLED]                 _, next_y1, _, _ = self.get_box(
# [OCR-DISABLED]                     anchors[index + 1]
# [OCR-DISABLED]                 )

# [OCR-DISABLED]             else:

# [OCR-DISABLED]                 next_y1 = float("inf")

# [OCR-DISABLED]             content_items = []

# [OCR-DISABLED]             for item in sorted_items:

# [OCR-DISABLED]                 if item is anchor:
# [OCR-DISABLED]                     continue

# [OCR-DISABLED]                 text = self.clean_text(
# [OCR-DISABLED]                     item["text"]
# [OCR-DISABLED]                 )

# [OCR-DISABLED]                 if not text:
# [OCR-DISABLED]                     continue

# [OCR-DISABLED]                 if self.is_ui_noise(text):
# [OCR-DISABLED]                     continue

# [OCR-DISABLED]                 _, y1, _, _ = self.get_box(
# [OCR-DISABLED]                     item
# [OCR-DISABLED]                 )

# [OCR-DISABLED]                 if y1 < anchor_y1:
# [OCR-DISABLED]                     continue

# [OCR-DISABLED]                 if y1 >= next_y1:
# [OCR-DISABLED]                     break

# [OCR-DISABLED]                 # IMPORTANT FIX:
# [OCR-DISABLED]                 # Stop at the first answer option instead of continuing
# [OCR-DISABLED]                 # and accidentally appending it to the question.
# [OCR-DISABLED]                 # This handles OCR such as "OB.$0.05".
# [OCR-DISABLED]                 if self.is_explicit_option(text):
# [OCR-DISABLED]                     break

# [OCR-DISABLED]                 # Extra protection if a single OCR line contains both
# [OCR-DISABLED]                 # question text and the beginning of an answer option.
# [OCR-DISABLED]                 if self.contains_embedded_option(text):

# [OCR-DISABLED]                     cleaned = self.clean_question_candidate(
# [OCR-DISABLED]                         text
# [OCR-DISABLED]                     )

# [OCR-DISABLED]                     if cleaned:

# [OCR-DISABLED]                         item_copy = dict(item)
# [OCR-DISABLED]                         item_copy["text"] = cleaned

# [OCR-DISABLED]                         content_items.append(
# [OCR-DISABLED]                             item_copy
# [OCR-DISABLED]                         )

# [OCR-DISABLED]                     break

# [OCR-DISABLED]                 content_items.append(
# [OCR-DISABLED]                     item
# [OCR-DISABLED]                 )

# [OCR-DISABLED]             if not content_items:
# [OCR-DISABLED]                 continue

# [OCR-DISABLED]             question_text = " ".join(

# [OCR-DISABLED]                 self.clean_text(
# [OCR-DISABLED]                     item["text"]
# [OCR-DISABLED]                 )

# [OCR-DISABLED]                 for item in content_items

# [OCR-DISABLED]             )

# [OCR-DISABLED]             # Final safety cleanup.
# [OCR-DISABLED]             question_text = self.clean_question_candidate(
# [OCR-DISABLED]                 question_text
# [OCR-DISABLED]             )

# [OCR-DISABLED]             if len(question_text) < 3:
# [OCR-DISABLED]                 continue

# [OCR-DISABLED]             questions.append({

# [OCR-DISABLED]                 "possible_question":
# [OCR-DISABLED]                     question_text,

# [OCR-DISABLED]                 "confidence":
# [OCR-DISABLED]                     0.95,

# [OCR-DISABLED]                 "detection_method":
# [OCR-DISABLED]                     "question_anchor"
# [OCR-DISABLED]             })

# [OCR-DISABLED]         return questions

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # REMOVE DUPLICATE QUESTIONS
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     def remove_duplicate_questions(
# [OCR-DISABLED]         self,
# [OCR-DISABLED]         questions
# [OCR-DISABLED]     ):

# [OCR-DISABLED]         grouped_questions = {}

# [OCR-DISABLED]         for question in questions:

# [OCR-DISABLED]             original_text = self.clean_text(
# [OCR-DISABLED]                 question.get(
# [OCR-DISABLED]                     "possible_question",
# [OCR-DISABLED]                     ""
# [OCR-DISABLED]                 )
# [OCR-DISABLED]             )

# [OCR-DISABLED]             if not original_text:
# [OCR-DISABLED]                 continue

# [OCR-DISABLED]             # Clean any answer option accidentally appended to the candidate.
# [OCR-DISABLED]             text = self.clean_question_candidate(
# [OCR-DISABLED]                 original_text
# [OCR-DISABLED]             )

# [OCR-DISABLED]             if not text:
# [OCR-DISABLED]                 continue

# [OCR-DISABLED]             question_copy = dict(question)
# [OCR-DISABLED]             question_copy["possible_question"] = text

# [OCR-DISABLED]             normalized = re.sub(
# [OCR-DISABLED]                 r"[^a-z0-9]",
# [OCR-DISABLED]                 "",
# [OCR-DISABLED]                 text.lower()
# [OCR-DISABLED]             )

# [OCR-DISABLED]             if not normalized:
# [OCR-DISABLED]                 continue

# [OCR-DISABLED]             grouped_questions.setdefault(
# [OCR-DISABLED]                 normalized,
# [OCR-DISABLED]                 []
# [OCR-DISABLED]             ).append(
# [OCR-DISABLED]                 question_copy
# [OCR-DISABLED]             )

# [OCR-DISABLED]         final_questions = []

# [OCR-DISABLED]         method_priority = {

# [OCR-DISABLED]             # Prefer option-boundary extraction because it naturally
# [OCR-DISABLED]             # ends exactly before the answer group.
# [OCR-DISABLED]             "question_before_option_group": 2,

# [OCR-DISABLED]             "question_anchor": 1
# [OCR-DISABLED]         }

# [OCR-DISABLED]         for candidates in grouped_questions.values():

# [OCR-DISABLED]             candidates.sort(
# [OCR-DISABLED]                 key=lambda question: (

# [OCR-DISABLED]                     # Clean candidates first.
# [OCR-DISABLED]                     1
# [OCR-DISABLED]                     if not self.contains_embedded_option(
# [OCR-DISABLED]                         question["possible_question"]
# [OCR-DISABLED]                     )
# [OCR-DISABLED]                     else 0,

# [OCR-DISABLED]                     method_priority.get(
# [OCR-DISABLED]                         question.get(
# [OCR-DISABLED]                             "detection_method",
# [OCR-DISABLED]                             ""
# [OCR-DISABLED]                         ),
# [OCR-DISABLED]                         0
# [OCR-DISABLED]                     ),

# [OCR-DISABLED]                     float(
# [OCR-DISABLED]                         question.get(
# [OCR-DISABLED]                             "confidence",
# [OCR-DISABLED]                             0
# [OCR-DISABLED]                         )
# [OCR-DISABLED]                     ),

# [OCR-DISABLED]                     len(
# [OCR-DISABLED]                         question["possible_question"]
# [OCR-DISABLED]                     )
# [OCR-DISABLED]                 ),
# [OCR-DISABLED]                 reverse=True
# [OCR-DISABLED]             )

# [OCR-DISABLED]             final_questions.append(
# [OCR-DISABLED]                 candidates[0]
# [OCR-DISABLED]             )

# [OCR-DISABLED]         return final_questions

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # DETECT ALL POSSIBLE QUESTIONS
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     def detect_possible_questions(
# [OCR-DISABLED]         self,
# [OCR-DISABLED]         items
# [OCR-DISABLED]     ):

# [OCR-DISABLED]         # Remove obvious UI noise
# [OCR-DISABLED]         valid_items = []

# [OCR-DISABLED]         for item in items:

# [OCR-DISABLED]             text = self.clean_text(
# [OCR-DISABLED]                 item["text"]
# [OCR-DISABLED]             )

# [OCR-DISABLED]             if not text:
# [OCR-DISABLED]                 continue

# [OCR-DISABLED]             if self.is_ui_noise(text):
# [OCR-DISABLED]                 continue

# [OCR-DISABLED]             valid_items.append(
# [OCR-DISABLED]                 item
# [OCR-DISABLED]             )

# [OCR-DISABLED]         # ------------------------------------------------------
# [OCR-DISABLED]         # Calculate dynamic metrics
# [OCR-DISABLED]         # ------------------------------------------------------

# [OCR-DISABLED]         metrics = self.calculate_layout_metrics(
# [OCR-DISABLED]             valid_items
# [OCR-DISABLED]         )

# [OCR-DISABLED]         print("\nLayout metrics:")

# [OCR-DISABLED]         print(
# [OCR-DISABLED]             json.dumps(
# [OCR-DISABLED]                 metrics,
# [OCR-DISABLED]                 indent=4
# [OCR-DISABLED]             )
# [OCR-DISABLED]         )

# [OCR-DISABLED]         # ------------------------------------------------------
# [OCR-DISABLED]         # METHOD 1:
# [OCR-DISABLED]         # Q1 / Q2 / Question 1
# [OCR-DISABLED]         # ------------------------------------------------------

# [OCR-DISABLED]         numbered_questions = (
# [OCR-DISABLED]             self.extract_numbered_questions(
# [OCR-DISABLED]                 valid_items,
# [OCR-DISABLED]                 metrics
# [OCR-DISABLED]             )
# [OCR-DISABLED]         )

# [OCR-DISABLED]         # ------------------------------------------------------
# [OCR-DISABLED]         # METHOD 2:
# [OCR-DISABLED]         # A/B/C/D explicit options
# [OCR-DISABLED]         # ------------------------------------------------------

# [OCR-DISABLED]         explicit_option_groups = (
# [OCR-DISABLED]             self.detect_explicit_option_groups(
# [OCR-DISABLED]                 valid_items,
# [OCR-DISABLED]                 metrics
# [OCR-DISABLED]             )
# [OCR-DISABLED]         )

# [OCR-DISABLED]         # ------------------------------------------------------
# [OCR-DISABLED]         # METHOD 3:
# [OCR-DISABLED]         # Plain vertically aligned options
# [OCR-DISABLED]         # ------------------------------------------------------

# [OCR-DISABLED]         layout_option_groups = (
# [OCR-DISABLED]             self.detect_layout_option_groups(
# [OCR-DISABLED]                 valid_items,
# [OCR-DISABLED]                 metrics
# [OCR-DISABLED]             )
# [OCR-DISABLED]         )

# [OCR-DISABLED]         print(
# [OCR-DISABLED]             f"\nExplicit option groups: "
# [OCR-DISABLED]             f"{len(explicit_option_groups)}"
# [OCR-DISABLED]         )

# [OCR-DISABLED]         print(
# [OCR-DISABLED]             f"Layout option groups: "
# [OCR-DISABLED]             f"{len(layout_option_groups)}"
# [OCR-DISABLED]         )

# [OCR-DISABLED]         # ------------------------------------------------------
# [OCR-DISABLED]         # Combine option groups
# [OCR-DISABLED]         # ------------------------------------------------------

# [OCR-DISABLED]         all_option_groups = (
# [OCR-DISABLED]             explicit_option_groups
# [OCR-DISABLED]             +
# [OCR-DISABLED]             layout_option_groups
# [OCR-DISABLED]         )

# [OCR-DISABLED]         all_option_groups = (
# [OCR-DISABLED]             self.remove_duplicate_groups(
# [OCR-DISABLED]                 all_option_groups
# [OCR-DISABLED]             )
# [OCR-DISABLED]         )

# [OCR-DISABLED]         # ------------------------------------------------------
# [OCR-DISABLED]         # Extract questions above options
# [OCR-DISABLED]         # ------------------------------------------------------

# [OCR-DISABLED]         layout_questions = (
# [OCR-DISABLED]             self.extract_question_before_options(
# [OCR-DISABLED]                 valid_items,
# [OCR-DISABLED]                 all_option_groups,
# [OCR-DISABLED]                 metrics
# [OCR-DISABLED]             )
# [OCR-DISABLED]         )

# [OCR-DISABLED]         # ------------------------------------------------------
# [OCR-DISABLED]         # Combine all question detection methods
# [OCR-DISABLED]         # ------------------------------------------------------

# [OCR-DISABLED]         all_questions = (
# [OCR-DISABLED]             numbered_questions
# [OCR-DISABLED]             +
# [OCR-DISABLED]             layout_questions
# [OCR-DISABLED]         )

# [OCR-DISABLED]         all_questions = (
# [OCR-DISABLED]             self.remove_duplicate_questions(
# [OCR-DISABLED]                 all_questions
# [OCR-DISABLED]             )
# [OCR-DISABLED]         )

# [OCR-DISABLED]         return all_questions

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # MAIN PROCESS IMAGE METHOD
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     def process_image(
# [OCR-DISABLED]         self,
# [OCR-DISABLED]         image_path
# [OCR-DISABLED]     ):

# [OCR-DISABLED]         print("\n" + "=" * 70)

# [OCR-DISABLED]         print(
# [OCR-DISABLED]             "SMART QUESTION OCR"
# [OCR-DISABLED]         )

# [OCR-DISABLED]         print("=" * 70)

# [OCR-DISABLED]         # ------------------------------------------------------
# [OCR-DISABLED]         # STEP 1: OCR
# [OCR-DISABLED]         # ------------------------------------------------------

# [OCR-DISABLED]         items = self.extract_ocr_items(
# [OCR-DISABLED]             image_path
# [OCR-DISABLED]         )

# [OCR-DISABLED]         print(
# [OCR-DISABLED]             f"\nOCR items detected: "
# [OCR-DISABLED]             f"{len(items)}"
# [OCR-DISABLED]         )

# [OCR-DISABLED]         # ------------------------------------------------------
# [OCR-DISABLED]         # STEP 2: QUESTION DETECTION
# [OCR-DISABLED]         # ------------------------------------------------------

# [OCR-DISABLED]         print(
# [OCR-DISABLED]             "\nDetecting possible questions..."
# [OCR-DISABLED]         )

# [OCR-DISABLED]         possible_questions = (
# [OCR-DISABLED]             self.detect_possible_questions(
# [OCR-DISABLED]                 items
# [OCR-DISABLED]             )
# [OCR-DISABLED]         )

# [OCR-DISABLED]         print(
# [OCR-DISABLED]             f"\nPossible questions detected: "
# [OCR-DISABLED]             f"{len(possible_questions)}"
# [OCR-DISABLED]         )

# [OCR-DISABLED]         # ------------------------------------------------------
# [OCR-DISABLED]         # IMPORTANT
# [OCR-DISABLED]         #
# [OCR-DISABLED]         # This exact result will be used both for:
# [OCR-DISABLED]         #
# [OCR-DISABLED]         # 1. Terminal output
# [OCR-DISABLED]         # 2. JSON file
# [OCR-DISABLED]         # ------------------------------------------------------

# [OCR-DISABLED]         return {

# [OCR-DISABLED]             "possible_questions":
# [OCR-DISABLED]                 possible_questions,

# [OCR-DISABLED]             "raw_items":
# [OCR-DISABLED]                 items
# [OCR-DISABLED]         }


# [OCR-DISABLED] # ==============================================================
# [OCR-DISABLED] # MAIN PROGRAM
# [OCR-DISABLED] # ==============================================================

# [OCR-DISABLED] if __name__ == "__main__":

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # IMAGE PATH
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     image_path = (
# [OCR-DISABLED]         "./screenshots/2026-08-29/"
# [OCR-DISABLED]         # "screenshot-2026-08-29T15-05-27-962334.png"
# [OCR-DISABLED]         # "screenshot-2026-08-28T16-00-59-615254.png"
# [OCR-DISABLED]         # "screenshot-2026-08-28T15-59-59-616281.png"
# [OCR-DISABLED]         "screenshot-2026-08-29T18-44-43-097149.png"
# [OCR-DISABLED]     )

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # OUTPUT JSON PATH
# [OCR-DISABLED]     #
# [OCR-DISABLED]     # Saves JSON in the SAME folder as this Python file.
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     script_directory = os.path.dirname(
# [OCR-DISABLED]         os.path.abspath(__file__)
# [OCR-DISABLED]     )

# [OCR-DISABLED]     output_file = os.path.join(
# [OCR-DISABLED]         script_directory,
# [OCR-DISABLED]         "question_ocr_output.json"
# [OCR-DISABLED]     )

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # CREATE OCR ENGINE
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     smart_ocr = SmartQuestionOCR()

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # PROCESS IMAGE
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     result = smart_ocr.process_image(
# [OCR-DISABLED]         image_path
# [OCR-DISABLED]     )

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # PRINT POSSIBLE QUESTIONS
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     print("\n\n" + "=" * 70)

# [OCR-DISABLED]     print(
# [OCR-DISABLED]         "POSSIBLE QUESTIONS"
# [OCR-DISABLED]     )

# [OCR-DISABLED]     print("=" * 70)

# [OCR-DISABLED]     print(
# [OCR-DISABLED]         json.dumps(
# [OCR-DISABLED]             result["possible_questions"],
# [OCR-DISABLED]             indent=4,
# [OCR-DISABLED]             ensure_ascii=False
# [OCR-DISABLED]         )
# [OCR-DISABLED]     )

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # PRINT RAW OCR ITEMS
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     print("\n\n" + "=" * 70)

# [OCR-DISABLED]     print(
# [OCR-DISABLED]         "RAW OCR ITEMS"
# [OCR-DISABLED]     )

# [OCR-DISABLED]     print("=" * 70)

# [OCR-DISABLED]     print(
# [OCR-DISABLED]         json.dumps(
# [OCR-DISABLED]             result["raw_items"],
# [OCR-DISABLED]             indent=4,
# [OCR-DISABLED]             ensure_ascii=False
# [OCR-DISABLED]         )
# [OCR-DISABLED]     )

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # SAVE THE EXACT SAME RESULT TO JSON
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     print("\n" + "=" * 70)

# [OCR-DISABLED]     print(
# [OCR-DISABLED]         "SAVING JSON FILE"
# [OCR-DISABLED]     )

# [OCR-DISABLED]     print("=" * 70)

# [OCR-DISABLED]     # IMPORTANT:
# [OCR-DISABLED]     # We save `result` directly.
# [OCR-DISABLED]     #
# [OCR-DISABLED]     # No separate old `questions` variable.
# [OCR-DISABLED]     # No old `lines` structure.
# [OCR-DISABLED]     #
# [OCR-DISABLED]     # Therefore terminal and JSON will always match.

# [OCR-DISABLED]     with open(
# [OCR-DISABLED]         output_file,
# [OCR-DISABLED]         "w",
# [OCR-DISABLED]         encoding="utf-8"
# [OCR-DISABLED]     ) as file:

# [OCR-DISABLED]         json.dump(
# [OCR-DISABLED]             result,
# [OCR-DISABLED]             file,
# [OCR-DISABLED]             indent=4,
# [OCR-DISABLED]             ensure_ascii=False
# [OCR-DISABLED]         )

# [OCR-DISABLED]     # ==========================================================
# [OCR-DISABLED]     # VERIFY JSON WAS ACTUALLY WRITTEN
# [OCR-DISABLED]     # ==========================================================

# [OCR-DISABLED]     if os.path.exists(output_file):

# [OCR-DISABLED]         print(
# [OCR-DISABLED]             "\nJSON saved successfully."
# [OCR-DISABLED]         )

# [OCR-DISABLED]         print(
# [OCR-DISABLED]             f"\nExact JSON path:\n"
# [OCR-DISABLED]             f"{output_file}"
# [OCR-DISABLED]         )

# [OCR-DISABLED]         print(
# [OCR-DISABLED]             f"\nQuestions saved: "
# [OCR-DISABLED]             f"{len(result['possible_questions'])}"
# [OCR-DISABLED]         )

# [OCR-DISABLED]         print(
# [OCR-DISABLED]             f"Raw OCR items saved: "
# [OCR-DISABLED]             f"{len(result['raw_items'])}"
# [OCR-DISABLED]         )

# [OCR-DISABLED]     else:

# [OCR-DISABLED]         print(
# [OCR-DISABLED]             "\nERROR: JSON file was not created."
# [OCR-DISABLED]         )