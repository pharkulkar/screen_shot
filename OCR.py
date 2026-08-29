import os
import cv2
import json
import re
import numpy as np
from statistics import median
from paddleocr import PaddleOCR


class SmartQuestionOCR:

    # ==========================================================
    # INITIALIZATION
    # ==========================================================

    def __init__(self):

        print("\nLoading PaddleOCR models...")

        self.ocr = PaddleOCR(
            use_doc_orientation_classify=True,
            use_doc_unwarping=True,
            use_textline_orientation=True,
            lang="en"
        )

    # ==========================================================
    # TEXT CLEANING
    # ==========================================================

    @staticmethod
    def clean_text(text):

        if text is None:
            return ""

        text = str(text)

        text = re.sub(
            r"\s+",
            " ",
            text
        )

        return text.strip()

    # ==========================================================
    # BOX HELPERS
    # ==========================================================

    @staticmethod
    def get_box(item):

        box = item.get("box", [0, 0, 0, 0])

        return (
            int(box[0]),
            int(box[1]),
            int(box[2]),
            int(box[3])
        )

    def get_height(self, item):

        _, y1, _, y2 = self.get_box(item)

        return max(1, y2 - y1)

    # ==========================================================
    # IMAGE PREPROCESSING
    # ==========================================================

    def preprocess_image(self, image_path):

        # Check path before loading
        if not os.path.exists(image_path):

            raise FileNotFoundError(
                f"\nImage not found:\n{image_path}\n\n"
                f"Please verify the absolute image path."
            )

        image = cv2.imread(image_path)

        if image is None:

            raise ValueError(
                f"\nUnable to load image:\n{image_path}"
            )

        height, width = image.shape[:2]

        print(
            f"Original image size: "
            f"{width} x {height}"
        )

        # Upscale only relatively small images
        if width < 1200:

            scale = 2

            image = cv2.resize(
                image,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_CUBIC
            )

            print(
                f"Upscaled image size: "
                f"{image.shape[1]} x "
                f"{image.shape[0]}"
            )

        # Light denoising
        # Keep image in BGR format for PaddleOCR
        image = cv2.bilateralFilter(
            image,
            7,
            50,
            50
        )

        return image

    # ==========================================================
    # OCR EXTRACTION
    # ==========================================================

    def extract_ocr_items(
        self,
        image_path,
        min_confidence=0.50
    ):

        image = self.preprocess_image(
            image_path
        )

        print("\nPerforming OCR...")

        results = self.ocr.predict(
            image
        )

        items = []

        for page in results:

            # --------------------------------------------------
            # Convert PaddleOCR result into dictionary
            # --------------------------------------------------

            if hasattr(page, "json"):

                page_data = page.json

            elif isinstance(page, dict):

                page_data = page

            else:

                continue

            # Some versions return JSON string
            if isinstance(page_data, str):

                try:

                    page_data = json.loads(
                        page_data
                    )

                except json.JSONDecodeError:

                    continue

            if not isinstance(page_data, dict):

                continue

            # PaddleOCR result
            res = page_data.get(
                "res",
                {}
            )

            texts = res.get(
                "rec_texts",
                []
            )

            scores = res.get(
                "rec_scores",
                []
            )

            boxes = res.get(
                "rec_boxes",
                []
            )

            # --------------------------------------------------
            # Create OCR items
            # --------------------------------------------------

            for text, score, box in zip(
                texts,
                scores,
                boxes
            ):

                text = self.clean_text(
                    text
                )

                if not text:
                    continue

                try:

                    score = float(score)

                except (TypeError, ValueError):

                    score = 0.0

                if score < min_confidence:
                    continue

                try:

                    box = [
                        int(value)
                        for value in box
                    ]

                except Exception:

                    continue

                if len(box) != 4:
                    continue

                items.append({

                    "text": text,

                    "confidence": score,

                    "box": box

                })

        # Sort from top to bottom
        items.sort(
            key=lambda item: (
                self.get_box(item)[1],
                self.get_box(item)[0]
            )
        )

        return items

    # ==========================================================
    # UI NOISE DETECTION
    # ==========================================================

    def is_ui_noise(self, text):

        text = self.clean_text(text)

        lower = text.lower()

        patterns = [

            # Input fields
            r"^type your answer.*$",
            r"^enter your answer.*$",
            r"^write your answer.*$",

            # Navigation
            r"^(next|previous|submit|finish|back|continue)$",

            # Assessment state
            r"^(answered|not answered)$",

            # Progress
            r"^\d+\s*/\s*\d+$",

            # Timer
            r"^\d{1,2}:\d{2}$",

            # Single OCR garbage characters
            r"^[a-z]{1,2}$"
        ]

        for pattern in patterns:

            if re.match(
                pattern,
                lower,
                re.IGNORECASE
            ):

                return True

        return False

    # ==========================================================
    # EXPLICIT QUESTION ANCHOR
    # ==========================================================

    def is_question_anchor(self, text):

        text = self.clean_text(text)

        patterns = [

            # Q1
            r"^Q\s*\d+$",

            # Q.1
            r"^Q\.\s*\d+$",

            # Question 1
            r"^Question\s+\d+$",

            # Question 1.
            r"^Question\s+\d+[\.\):]?$"
        ]

        for pattern in patterns:

            if re.match(
                pattern,
                text,
                re.IGNORECASE
            ):

                return True

        return False

    # ==========================================================
    # EXPLICIT OPTION DETECTION
    # ==========================================================

    def is_explicit_option(self, text):

        text = self.clean_text(text)

        patterns = [
            # A. Option / OA. Option / OB.$0.05 / O A. Option
            r"^(?:O|0|○|◯|●)?\s*\(?[A-Ha-h]\)?[\.\):]\s*.+$",

            # (A) Option
            r"^\([A-Ha-h]\)\s*.+$",

            # 1. Option
            r"^\d+[\.\)]\s*.+$"
        ]

        for pattern in patterns:

            if re.match(
                pattern,
                text,
                re.IGNORECASE
            ):

                return True

        return False

    # ==========================================================
    # OPTION CONTAMINATION DETECTION
    # ==========================================================

    def contains_embedded_option(self, text):

        text = self.clean_text(text)

        if not text:
            return False

        patterns = [
            # "...? A. answer", "...? OA. answer", "...? OB.$0.05"
            r"\s+(?:O|0|○|◯|●)?\s*\(?[A-Ha-h]\)?[\.\):]\s*(?=\S)",

            # "...? 1. answer"
            r"\s+\d+[\.\)]\s*(?=\S)"
        ]

        for pattern in patterns:

            for match in re.finditer(
                pattern,
                text,
                re.IGNORECASE
            ):

                # Only an option AFTER existing question text is contamination.
                if match.start() > 0:

                    return True

        return False

    # ==========================================================
    # QUESTION TEXT CLEANUP
    # ==========================================================

    def clean_question_candidate(self, text):

        text = self.clean_text(text)

        if not text:
            return ""

        patterns = [
            r"\s+(?:O|0|○|◯|●)?\s*\(?[A-Ha-h]\)?[\.\):]\s*.+$",
            r"\s+\d+[\.\)]\s*.+$"
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE
            )

            if match and match.start() > 0:

                text = text[:match.start()]
                break

        return self.clean_text(text)

    # ==========================================================
    # CALCULATE DYNAMIC LAYOUT METRICS
    # ==========================================================

    def calculate_layout_metrics(self, items):

        if not items:

            return {

                "median_height": 30,

                "x_threshold": 50,

                "max_vertical_gap": 200,

                "line_gap_limit": 100
            }

        heights = []

        for item in items:

            height = self.get_height(item)

            if height > 0:

                heights.append(height)

        if not heights:

            median_height = 30

        else:

            median_height = median(
                heights
            )

        return {

            "median_height":
                median_height,

            "x_threshold":
                max(
                    25,
                    median_height * 1.5
                ),

            "max_vertical_gap":
                max(
                    120,
                    median_height * 6
                ),

            "line_gap_limit":
                max(
                    80,
                    median_height * 4
                )
        }

    # ==========================================================
    # DETECT OPTION GROUPS USING LEFT ALIGNMENT
    #
    # Example:
    #
    # What is Angular?       x = 0
    #
    # A CSS preprocessor     x = 94
    # A JavaScript library   x = 95
    # A framework...         x = 93
    # A programming...       x = 91
    # ==========================================================

    def detect_layout_option_groups(
        self,
        items,
        metrics
    ):

        if len(items) < 3:

            return []

        sorted_items = sorted(
            items,
            key=lambda item: (
                self.get_box(item)[1],
                self.get_box(item)[0]
            )
        )

        x_threshold = metrics[
            "x_threshold"
        ]

        max_vertical_gap = metrics[
            "max_vertical_gap"
        ]

        x_clusters = []

        # ------------------------------------------------------
        # STEP 1:
        # Cluster text having similar left alignment
        # ------------------------------------------------------

        for item in sorted_items:

            text = self.clean_text(
                item["text"]
            )

            if self.is_ui_noise(text):
                continue

            x1, _, _, _ = self.get_box(
                item
            )

            added_to_cluster = False

            for cluster in x_clusters:

                x_values = [

                    self.get_box(
                        cluster_item
                    )[0]

                    for cluster_item in cluster
                ]

                median_x = float(
                    np.median(x_values)
                )

                if abs(
                    x1 - median_x
                ) <= x_threshold:

                    cluster.append(item)

                    added_to_cluster = True

                    break

            if not added_to_cluster:

                x_clusters.append(
                    [item]
                )

        # ------------------------------------------------------
        # STEP 2:
        # Split clusters based on vertical distance
        # ------------------------------------------------------

        valid_groups = []

        for cluster in x_clusters:

            if len(cluster) < 3:
                continue

            cluster.sort(
                key=lambda item:
                    self.get_box(item)[1]
            )

            current_group = [
                cluster[0]
            ]

            previous_item = cluster[0]

            for item in cluster[1:]:

                _, previous_y1, _, _ = (
                    self.get_box(
                        previous_item
                    )
                )

                _, current_y1, _, _ = (
                    self.get_box(
                        item
                    )
                )

                vertical_gap = (
                    current_y1 - previous_y1
                )

                if (
                    vertical_gap > 0
                    and vertical_gap <= max_vertical_gap
                ):

                    current_group.append(
                        item
                    )

                else:

                    if len(current_group) >= 3:

                        valid_groups.append(
                            current_group
                        )

                    current_group = [
                        item
                    ]

                previous_item = item

            # Save final group
            if len(current_group) >= 3:

                valid_groups.append(
                    current_group
                )

        return valid_groups

    # ==========================================================
    # DETECT EXPLICIT OPTION GROUPS
    #
    # Example:
    #
    # A. Something
    # B. Something
    # C. Something
    # D. Something
    # ==========================================================

    def detect_explicit_option_groups(
        self,
        items,
        metrics
    ):

        option_items = []

        for item in items:

            if self.is_explicit_option(
                item["text"]
            ):

                option_items.append(
                    item
                )

        if len(option_items) < 2:

            return []

        option_items.sort(
            key=lambda item:
                self.get_box(item)[1]
        )

        groups = []

        current_group = [
            option_items[0]
        ]

        previous_item = option_items[0]

        max_gap = (
            metrics[
                "max_vertical_gap"
            ] * 1.5
        )

        for item in option_items[1:]:

            _, previous_y1, _, _ = (
                self.get_box(
                    previous_item
                )
            )

            _, current_y1, _, _ = (
                self.get_box(item)
            )

            vertical_gap = (
                current_y1 - previous_y1
            )

            if (
                vertical_gap > 0
                and vertical_gap <= max_gap
            ):

                current_group.append(
                    item
                )

            else:

                if len(current_group) >= 2:

                    groups.append(
                        current_group
                    )

                current_group = [
                    item
                ]

            previous_item = item

        if len(current_group) >= 2:

            groups.append(
                current_group
            )

        return groups

    # ==========================================================
    # REMOVE DUPLICATE GROUPS
    # ==========================================================

    def remove_duplicate_groups(self, groups):

        unique_groups = []

        seen = set()

        for group in groups:

            group_key = tuple(
                sorted(
                    id(item)
                    for item in group
                )
            )

            if group_key in seen:
                continue

            seen.add(
                group_key
            )

            unique_groups.append(
                group
            )

        return unique_groups

    # ==========================================================
    # EXTRACT QUESTION ABOVE OPTION GROUP
    # ==========================================================

    def extract_question_before_options(
        self,
        items,
        option_groups,
        metrics
    ):

        questions = []

        for group in option_groups:

            if not group:
                continue

            group = sorted(
                group,
                key=lambda item:
                    self.get_box(item)[1]
            )

            first_option = group[0]

            _, option_y1, _, _ = (
                self.get_box(
                    first_option
                )
            )

            candidates = []

            max_question_distance = max(
                350,
                metrics[
                    "median_height"
                ] * 15
            )

            # --------------------------------------------------
            # Find meaningful text above first option
            # --------------------------------------------------

            for item in items:

                if item in group:
                    continue

                text = self.clean_text(
                    item["text"]
                )

                if not text:
                    continue

                if self.is_ui_noise(text):
                    continue

                _, y1, _, y2 = self.get_box(
                    item
                )

                # Must be above first option
                if y2 > option_y1:
                    continue

                distance = (
                    option_y1 - y2
                )

                if distance > max_question_distance:
                    continue

                candidates.append(
                    item
                )

            if not candidates:
                continue

            # --------------------------------------------------
            # Closest text above options
            # --------------------------------------------------

            candidates.sort(
                key=lambda item:
                    self.get_box(item)[3],
                reverse=True
            )

            closest_item = candidates[0]

            selected_items = [
                closest_item
            ]

            _, current_top_y, _, _ = (
                self.get_box(
                    closest_item
                )
            )

            # --------------------------------------------------
            # Detect wrapped lines above the closest line
            # --------------------------------------------------

            other_candidates = [

                item

                for item in candidates

                if item is not closest_item
            ]

            other_candidates.sort(
                key=lambda item:
                    self.get_box(item)[1],
                reverse=True
            )

            for item in other_candidates:

                _, y1, _, y2 = self.get_box(
                    item
                )

                if y2 > current_top_y:
                    continue

                vertical_gap = (
                    current_top_y - y2
                )

                if vertical_gap <= metrics[
                    "line_gap_limit"
                ]:

                    selected_items.append(
                        item
                    )

                    current_top_y = y1

                else:

                    break

            # --------------------------------------------------
            # Restore reading order
            # --------------------------------------------------

            selected_items.sort(
                key=lambda item: (
                    self.get_box(item)[1],
                    self.get_box(item)[0]
                )
            )

            question_text = " ".join(

                self.clean_text(
                    item["text"]
                )

                for item in selected_items

            )

            question_text = self.clean_text(
                question_text
            )

            if len(question_text) < 3:
                continue

            questions.append({

                "possible_question":
                    question_text,

                "confidence":
                    0.88,

                "detection_method":
                    "question_before_option_group"
            })

        return questions

    # ==========================================================
    # EXTRACT QUESTIONS WITH Q1 / Q2 / QUESTION 1
    # ==========================================================

    def extract_numbered_questions(
        self,
        items,
        metrics
    ):

        questions = []

        anchors = []

        for item in items:

            if self.is_question_anchor(
                item["text"]
            ):

                anchors.append(
                    item
                )

        anchors.sort(
            key=lambda item:
            self.get_box(item)[1]
        )

        sorted_items = sorted(
            items,
            key=lambda item: (
                self.get_box(item)[1],
                self.get_box(item)[0]
            )
        )

        for index, anchor in enumerate(
            anchors
        ):

            _, anchor_y1, _, _ = self.get_box(
                anchor
            )

            if index + 1 < len(anchors):

                _, next_y1, _, _ = self.get_box(
                    anchors[index + 1]
                )

            else:

                next_y1 = float("inf")

            content_items = []

            for item in sorted_items:

                if item is anchor:
                    continue

                text = self.clean_text(
                    item["text"]
                )

                if not text:
                    continue

                if self.is_ui_noise(text):
                    continue

                _, y1, _, _ = self.get_box(
                    item
                )

                if y1 < anchor_y1:
                    continue

                if y1 >= next_y1:
                    break

                # IMPORTANT FIX:
                # Stop at the first answer option instead of continuing
                # and accidentally appending it to the question.
                # This handles OCR such as "OB.$0.05".
                if self.is_explicit_option(text):
                    break

                # Extra protection if a single OCR line contains both
                # question text and the beginning of an answer option.
                if self.contains_embedded_option(text):

                    cleaned = self.clean_question_candidate(
                        text
                    )

                    if cleaned:

                        item_copy = dict(item)
                        item_copy["text"] = cleaned

                        content_items.append(
                            item_copy
                        )

                    break

                content_items.append(
                    item
                )

            if not content_items:
                continue

            question_text = " ".join(

                self.clean_text(
                    item["text"]
                )

                for item in content_items

            )

            # Final safety cleanup.
            question_text = self.clean_question_candidate(
                question_text
            )

            if len(question_text) < 3:
                continue

            questions.append({

                "possible_question":
                    question_text,

                "confidence":
                    0.95,

                "detection_method":
                    "question_anchor"
            })

        return questions

    # ==========================================================
    # REMOVE DUPLICATE QUESTIONS
    # ==========================================================

    def remove_duplicate_questions(
        self,
        questions
    ):

        grouped_questions = {}

        for question in questions:

            original_text = self.clean_text(
                question.get(
                    "possible_question",
                    ""
                )
            )

            if not original_text:
                continue

            # Clean any answer option accidentally appended to the candidate.
            text = self.clean_question_candidate(
                original_text
            )

            if not text:
                continue

            question_copy = dict(question)
            question_copy["possible_question"] = text

            normalized = re.sub(
                r"[^a-z0-9]",
                "",
                text.lower()
            )

            if not normalized:
                continue

            grouped_questions.setdefault(
                normalized,
                []
            ).append(
                question_copy
            )

        final_questions = []

        method_priority = {

            # Prefer option-boundary extraction because it naturally
            # ends exactly before the answer group.
            "question_before_option_group": 2,

            "question_anchor": 1
        }

        for candidates in grouped_questions.values():

            candidates.sort(
                key=lambda question: (

                    # Clean candidates first.
                    1
                    if not self.contains_embedded_option(
                        question["possible_question"]
                    )
                    else 0,

                    method_priority.get(
                        question.get(
                            "detection_method",
                            ""
                        ),
                        0
                    ),

                    float(
                        question.get(
                            "confidence",
                            0
                        )
                    ),

                    len(
                        question["possible_question"]
                    )
                ),
                reverse=True
            )

            final_questions.append(
                candidates[0]
            )

        return final_questions

    # ==========================================================
    # DETECT ALL POSSIBLE QUESTIONS
    # ==========================================================

    def detect_possible_questions(
        self,
        items
    ):

        # Remove obvious UI noise
        valid_items = []

        for item in items:

            text = self.clean_text(
                item["text"]
            )

            if not text:
                continue

            if self.is_ui_noise(text):
                continue

            valid_items.append(
                item
            )

        # ------------------------------------------------------
        # Calculate dynamic metrics
        # ------------------------------------------------------

        metrics = self.calculate_layout_metrics(
            valid_items
        )

        print("\nLayout metrics:")

        print(
            json.dumps(
                metrics,
                indent=4
            )
        )

        # ------------------------------------------------------
        # METHOD 1:
        # Q1 / Q2 / Question 1
        # ------------------------------------------------------

        numbered_questions = (
            self.extract_numbered_questions(
                valid_items,
                metrics
            )
        )

        # ------------------------------------------------------
        # METHOD 2:
        # A/B/C/D explicit options
        # ------------------------------------------------------

        explicit_option_groups = (
            self.detect_explicit_option_groups(
                valid_items,
                metrics
            )
        )

        # ------------------------------------------------------
        # METHOD 3:
        # Plain vertically aligned options
        # ------------------------------------------------------

        layout_option_groups = (
            self.detect_layout_option_groups(
                valid_items,
                metrics
            )
        )

        print(
            f"\nExplicit option groups: "
            f"{len(explicit_option_groups)}"
        )

        print(
            f"Layout option groups: "
            f"{len(layout_option_groups)}"
        )

        # ------------------------------------------------------
        # Combine option groups
        # ------------------------------------------------------

        all_option_groups = (
            explicit_option_groups
            +
            layout_option_groups
        )

        all_option_groups = (
            self.remove_duplicate_groups(
                all_option_groups
            )
        )

        # ------------------------------------------------------
        # Extract questions above options
        # ------------------------------------------------------

        layout_questions = (
            self.extract_question_before_options(
                valid_items,
                all_option_groups,
                metrics
            )
        )

        # ------------------------------------------------------
        # Combine all question detection methods
        # ------------------------------------------------------

        all_questions = (
            numbered_questions
            +
            layout_questions
        )

        all_questions = (
            self.remove_duplicate_questions(
                all_questions
            )
        )

        return all_questions

    # ==========================================================
    # MAIN PROCESS IMAGE METHOD
    # ==========================================================

    def process_image(
        self,
        image_path
    ):

        print("\n" + "=" * 70)

        print(
            "SMART QUESTION OCR"
        )

        print("=" * 70)

        # ------------------------------------------------------
        # STEP 1: OCR
        # ------------------------------------------------------

        items = self.extract_ocr_items(
            image_path
        )

        print(
            f"\nOCR items detected: "
            f"{len(items)}"
        )

        # ------------------------------------------------------
        # STEP 2: QUESTION DETECTION
        # ------------------------------------------------------

        print(
            "\nDetecting possible questions..."
        )

        possible_questions = (
            self.detect_possible_questions(
                items
            )
        )

        print(
            f"\nPossible questions detected: "
            f"{len(possible_questions)}"
        )

        # ------------------------------------------------------
        # IMPORTANT
        #
        # This exact result will be used both for:
        #
        # 1. Terminal output
        # 2. JSON file
        # ------------------------------------------------------

        return {

            "possible_questions":
                possible_questions,

            "raw_items":
                items
        }


# ==============================================================
# MAIN PROGRAM
# ==============================================================

if __name__ == "__main__":

    # ==========================================================
    # IMAGE PATH
    # ==========================================================

    image_path = (
        "./screenshots/2026-08-28/"
        # "screenshot-2026-08-29T15-05-27-962334.png"
        # "screenshot-2026-08-28T16-00-59-615254.png"
        "screenshot-2026-08-28T15-59-59-616281.png"
    )

    # ==========================================================
    # OUTPUT JSON PATH
    #
    # Saves JSON in the SAME folder as this Python file.
    # ==========================================================

    script_directory = os.path.dirname(
        os.path.abspath(__file__)
    )

    output_file = os.path.join(
        script_directory,
        "question_ocr_output.json"
    )

    # ==========================================================
    # CREATE OCR ENGINE
    # ==========================================================

    smart_ocr = SmartQuestionOCR()

    # ==========================================================
    # PROCESS IMAGE
    # ==========================================================

    result = smart_ocr.process_image(
        image_path
    )

    # ==========================================================
    # PRINT POSSIBLE QUESTIONS
    # ==========================================================

    print("\n\n" + "=" * 70)

    print(
        "POSSIBLE QUESTIONS"
    )

    print("=" * 70)

    print(
        json.dumps(
            result["possible_questions"],
            indent=4,
            ensure_ascii=False
        )
    )

    # ==========================================================
    # PRINT RAW OCR ITEMS
    # ==========================================================

    print("\n\n" + "=" * 70)

    print(
        "RAW OCR ITEMS"
    )

    print("=" * 70)

    print(
        json.dumps(
            result["raw_items"],
            indent=4,
            ensure_ascii=False
        )
    )

    # ==========================================================
    # SAVE THE EXACT SAME RESULT TO JSON
    # ==========================================================

    print("\n" + "=" * 70)

    print(
        "SAVING JSON FILE"
    )

    print("=" * 70)

    # IMPORTANT:
    # We save `result` directly.
    #
    # No separate old `questions` variable.
    # No old `lines` structure.
    #
    # Therefore terminal and JSON will always match.

    with open(
        output_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            result,
            file,
            indent=4,
            ensure_ascii=False
        )

    # ==========================================================
    # VERIFY JSON WAS ACTUALLY WRITTEN
    # ==========================================================

    if os.path.exists(output_file):

        print(
            "\nJSON saved successfully."
        )

        print(
            f"\nExact JSON path:\n"
            f"{output_file}"
        )

        print(
            f"\nQuestions saved: "
            f"{len(result['possible_questions'])}"
        )

        print(
            f"Raw OCR items saved: "
            f"{len(result['raw_items'])}"
        )

    else:

        print(
            "\nERROR: JSON file was not created."
        )