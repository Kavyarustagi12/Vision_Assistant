import os
from pathlib import Path
from typing import Literal

import cv2
import pytesseract
from dotenv import load_dotenv
from google import genai
from PIL import Image


# --------------------------------------------------
# 1. CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"

load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = (
    os.getenv("GEMINI_API_KEY")
    or os.getenv("GOOGLE_API_KEY")
)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

Category = Literal[
    "ocr",
    "object_detection",
    "scene_explanation",
]

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

CATEGORY_PROMPTS = {
    "ocr": (
        "Read and extract the visible text from the image. "
        "Preserve the meaning and structure where possible."
    ),
    "object_detection": (
        "Identify the important visible objects in the image. "
        "Describe their locations and relevant visual details."
    ),
    "scene_explanation": (
        "Explain the scene shown in the image, including the "
        "important objects, surroundings, and visible activities."
    ),
}


# --------------------------------------------------
# 2. SCORE AN IMAGE
# --------------------------------------------------

def score_image(path: Path) -> dict:
    """Score an image using sharpness, contrast, resolution and OCR."""

    image = cv2.imread(str(path))

    if image is None:
        raise ValueError(f"Cannot read image: {path.name}")

    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Image quality metrics
    sharpness = cv2.Laplacian(
        gray, cv2.CV_64F
    ).var()

    contrast = float(gray.std())
    resolution = width * height

    # Normalize image-quality metrics
    sharpness_score = min(sharpness / 500.0, 1.0)
    contrast_score = min(contrast / 80.0, 1.0)
    resolution_score = min(resolution / (1920 * 1080), 1.0)

    # OCR confidence; useful especially for images containing text
    try:
        ocr_data = pytesseract.image_to_data(
            gray,
            output_type=pytesseract.Output.DICT,
            config="--psm 11",
        )

        confidences = [
            float(conf)
            for text, conf in zip(
                ocr_data["text"],
                ocr_data["conf"],
            )
            if text.strip() and conf.strip() not in ("-1", "")
        ]

        ocr_score = (
            sum(confidences) / len(confidences) / 100.0
            if confidences
            else 0.0
        )
    except Exception:
        ocr_score = 0.0

    # Combined quality score
    total_score = (
        0.35 * sharpness_score
        + 0.20 * contrast_score
        + 0.20 * resolution_score
        + 0.25 * ocr_score
    )

    return {
        "path": path,
        "score": total_score,
    }


# --------------------------------------------------
# 3. SELECT THE BEST SAVED IMAGE
# --------------------------------------------------

def prepare_analysis(
    category: Category,
    question: str,
) -> dict:
    """
    Accept exactly two parameters.
    Select the highest-scoring supported image in uploads/.
    Does not call Gemini.
    """

    if category not in CATEGORY_PROMPTS:
        raise ValueError(
            "category must be 'ocr', 'object_detection', "
            "or 'scene_explanation'."
        )

    if not question.strip():
        raise ValueError("Question cannot be empty.")

    if not UPLOAD_DIR.exists():
        raise FileNotFoundError(
            f"Uploads directory does not exist: {UPLOAD_DIR}"
        )

    images = [
        path
        for path in UPLOAD_DIR.iterdir()
        if path.is_file()
        and path.suffix.lower() in SUPPORTED
    ]

    if not images:
        raise FileNotFoundError(
            f"No supported images found in {UPLOAD_DIR}"
        )

    candidates = []

    for path in images:
        try:
            candidates.append(score_image(path))
        except Exception as exc:
            print(f"Skipping {path.name}: {exc}")

    if not candidates:
        raise RuntimeError(
            "No images could be scored. Check image files "
            "and the Tesseract installation."
        )

    best = max(candidates, key=lambda item: item["score"])

    answer=ask_gemini(
         best["path"],
         category,
         question
    )
    return answer


# --------------------------------------------------
# 4. SEND THE SELECTED IMAGE TO GEMINI
# --------------------------------------------------

def ask_gemini(
    path: Path,
    category: Category,
    question: str,
) -> str:
    """Call Gemini with the selected image and return its answer."""

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY or GOOGLE_API_KEY is missing "
            "from the .env file."
        )

    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
You are a helpful vision assistant.

Task:
{CATEGORY_PROMPTS[category]}

User's question:
{question}

Instructions:
- if the image is not containing the answer and if you think that changing the camera angle or zooming or taking a closer picture or turning the object something like that can bring the answer in frame then suggest that instead of randomly guessing
- remember we are making it for blind people so suggest accordingly if you are not sure that changing this will bring things in frame don't say just tell honestly
- Answer the user's question directly.
- Use the image as the source of visual information.
- Be concise, clear, and accurate.
- Do not invent details that are not visible.
- Return only the main answer, without headings such as
  "Answer:" or unnecessary introductory text.
  
"""

    with Image.open(path) as source_image:
        image = source_image.convert("RGB")

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[prompt, image],
        )

    answer = (response.text or "").strip()

    if not answer:
        raise RuntimeError("Gemini returned an empty answer.")

    return answer


