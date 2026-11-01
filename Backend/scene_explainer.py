
import logging
import os
from pathlib import Path

import cv2
import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image, ImageOps, UnidentifiedImageError


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"

load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

SUPPORTED_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

# Number of recent frames to evaluate
MAX_CANDIDATES = 10

# Quality-score threshold from 0 to 1
MIN_QUALITY_SCORE = 0.20

# Minimum image dimensions
MIN_WIDTH = 320
MIN_HEIGHT = 240

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --------------------------------------------------
# IMAGE QUALITY ANALYSIS
# --------------------------------------------------

def calculate_image_quality(image_path: Path) -> dict:
    """
    Validate and score an image.

    Score factors:
    - Sharpness
    - Brightness
    - Contrast

    Also rejects very small, very dark, very bright,
    and heavily blurred images.
    """

    try:
        # Verify that the file is a valid image.
        with Image.open(image_path) as pil_image:
            pil_image.verify()

        # Read image using OpenCV.
        image = cv2.imread(str(image_path))

        if image is None:
            return {
                "acceptable": False,
                "score": 0.0,
                "reason": "Image cannot be decoded",
            }

        height, width = image.shape[:2]

        if width < MIN_WIDTH or height < MIN_HEIGHT:
            return {
                "acceptable": False,
                "score": 0.0,
                "reason": f"Image too small: {width}x{height}",
            }

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Resize for more consistent and efficient scoring.
        gray = cv2.resize(
            gray,
            (320, 240),
            interpolation=cv2.INTER_AREA,
        )

        # Brightness and exposure analysis.
        brightness = float(np.mean(gray))
        dark_fraction = float(np.mean(gray < 15))
        bright_fraction = float(np.mean(gray > 245))

        if brightness < 30:
            return {
                "acceptable": False,
                "score": 0.0,
                "reason": "Image is too dark",
            }

        if brightness > 235:
            return {
                "acceptable": False,
                "score": 0.0,
                "reason": "Image is overexposed",
            }

        if dark_fraction > 0.85:
            return {
                "acceptable": False,
                "score": 0.0,
                "reason": "Most of the image is nearly black",
            }

        if bright_fraction > 0.85:
            return {
                "acceptable": False,
                "score": 0.0,
                "reason": "Most of the image is washed out",
            }

        # Sharpness: Laplacian variance.
        sharpness = float(
            cv2.Laplacian(gray, cv2.CV_64F).var()
        )

        # Contrast: grayscale standard deviation.
        contrast = float(np.std(gray))

        # Reject very blurry frames.
        if sharpness < 12:
            return {
                "acceptable": False,
                "score": 0.0,
                "reason": f"Image is too blurry ({sharpness:.1f})",
            }

        # Normalize component scores.
        sharpness_score = min(sharpness / 250.0, 1.0)
        contrast_score = min(contrast / 60.0, 1.0)

        # Brightness score: prefer a middle exposure.
        brightness_score = max(
            0.0,
            1.0 - abs(brightness - 125.0) / 125.0,
        )

        # Weighted total quality score.
        quality_score = (
            0.60 * sharpness_score
            + 0.25 * brightness_score
            + 0.15 * contrast_score
        )

        acceptable = quality_score >= MIN_QUALITY_SCORE

        return {
            "acceptable": acceptable,
            "score": round(quality_score, 3),
            "sharpness": round(sharpness, 2),
            "brightness": round(brightness, 2),
            "contrast": round(contrast, 2),
            "width": width,
            "height": height,
            "reason": (
                "Suitable image"
                if acceptable
                else "Quality score below threshold"
            ),
        }

    except (
        OSError,
        cv2.error,
        UnidentifiedImageError,
        ValueError,
    ) as error:
        return {
            "acceptable": False,
            "score": 0.0,
            "reason": f"Could not process image: {error}",
        }


# --------------------------------------------------
# SELECT ONE GOOD IMAGE
# --------------------------------------------------

def get_best_image() -> tuple[Path, dict]:
    """
    Examine the most recent uploaded images and select
    exactly one acceptable image with the highest score.
    """

    if not UPLOAD_DIR.is_dir():
        raise FileNotFoundError(
            f"Uploads directory not found: {UPLOAD_DIR}"
        )

    images = [
        path
        for path in UPLOAD_DIR.iterdir()
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_TYPES
    ]

    # Consider only recent frames, avoiding old sessions.
    images.sort(
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    images = images[:MAX_CANDIDATES]

    if not images:
        raise FileNotFoundError(
            "No supported images found in uploads."
        )

    logger.info("Evaluating %d recent images", len(images))

    best_image = None
    best_quality = None

    for image_path in images:
        quality = calculate_image_quality(image_path)

        logger.info(
            "Image=%s | score=%s | acceptable=%s | reason=%s",
            image_path.name,
            quality.get("score"),
            quality.get("acceptable"),
            quality.get("reason"),
        )

        if not quality["acceptable"]:
            continue

        if (
            best_quality is None
            or quality["score"] > best_quality["score"]
        ):
            best_image = image_path
            best_quality = quality

    if best_image is None:
        raise ValueError(
            "No sufficiently clear image found. "
            "Please hold the camera steady, improve the lighting, "
            "and capture new frames."
        )

    logger.info(
        "Selected image: %s | score: %s",
        best_image.name,
        best_quality["score"],
    )

    return best_image, best_quality


# --------------------------------------------------
# GEMINI SCENE EXPLANATION
# --------------------------------------------------

SCENE_PROMPT = """
You are a visual scene assistant for a person who is blind
or has low vision.

Explain the visible surroundings in clear, natural language
that can be read aloud.

Prioritize:
1. The overall scene and setting, if identifiable.
2. Important objects and people.
3. Spatial relationships that are actually visible.
4. Clearly visible obstacles or potential hazards.
5. Readable signs or text when relevant.

Rules:
- Describe only what the image supports.
- Do not invent distances or directions.
- Do not claim that a route is safe.
- Do not identify people by name or infer sensitive attributes.
- Mention blur, poor lighting, or uncertainty when relevant.
- Do not claim that an obstacle is absent simply because
  it is not visible in this frame.
- Use concise, accessible language.

Return these sections:

SUMMARY: Brief overview of the scene.
DETAILS: Important objects and their visible relationships.
CAUTION: Clearly visible potential obstacles, if any.
LIMITATIONS: Important uncertainty or visibility issues.

Usually use 3 to 6 sentences. Avoid generic filler.
"""


def explain_scene() -> dict:
    """
    Select the best recent image, send ONLY that image
    to Gemini, and return the scene description.
    """

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is missing. Check Backend/.env."
        )

    # Select one image only.
    image_path, quality = get_best_image()

    mime_type = SUPPORTED_TYPES[image_path.suffix.lower()]

    # Read only the selected image.
    image_bytes = image_path.read_bytes()

    if not image_bytes:
        raise ValueError("The selected image is empty.")

    logger.info(
        "Sending one image to Gemini: %s",
        image_path.name,
    )

    client = genai.Client(api_key=GEMINI_API_KEY)

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=[
            types.Part.from_bytes(
                data=image_bytes,
                mime_type=mime_type,
            ),
            SCENE_PROMPT,
        ],
        config=types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=400,
        ),
    )

    description = (response.text or "").strip()

    if not description:
        raise RuntimeError(
            "Gemini returned an empty scene description."
        )

    return {
        "image": image_path.name,
        "quality_score": quality["score"],
        "quality_details": quality,
        "model": MODEL_NAME,
        "description": description,
    }
