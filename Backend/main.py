
from pathlib import Path
from io import BytesIO
from uuid import uuid4
import os
import json

from google import genai
from dotenv import load_dotenv
from pydantic import BaseModel
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

# Load environment variables
load_dotenv()

gemini_client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

# Import APIs and pipeline functions
from scene_explainer import explain_scene
from pipeline import prepare_analysis

app = FastAPI(title="Vision Assistant API")

# Project directories
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "Frontend"
UPLOAD_DIR = BASE_DIR / "uploads"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def clear_uploads():
    for file_path in UPLOAD_DIR.iterdir():
        if file_path.is_file():
            file_path.unlink()


# Check frontend directory
if not FRONTEND_DIR.is_dir():
    raise RuntimeError(
        f"Frontend folder not found: {FRONTEND_DIR}"
    )


# API: Test backend
@app.get("/api/health")
def health():
    return {"message": "API is working fine"}


# API: Receive and save camera frames
@app.post("/api/upload")
async def upload_frame(file: UploadFile = File(...)):
    image_bytes = await file.read()

    if not image_bytes:
        raise HTTPException(
            status_code=400,
            detail="Empty image"
        )

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image_format = image.format
            width, height = image.size
            image.load()

    except (UnidentifiedImageError, OSError):
        raise HTTPException(
            status_code=400,
            detail="Invalid image"
        )

    extensions = {
        "JPEG": ".jpg",
        "PNG": ".png",
        "WEBP": ".webp",
    }

    if image_format not in extensions:
        raise HTTPException(
            status_code=400,
            detail="Unsupported image format"
        )

    filename = f"frame_{uuid4().hex}{extensions[image_format]}"
    save_path = UPLOAD_DIR / filename
    save_path.write_bytes(image_bytes)

    print(f"Saved frame: {filename}")

    return {
        "message": "Frame received and saved",
        "filename": filename,
        "width": width,
        "height": height,
        "size_bytes": len(image_bytes),
    }


# API: Explain the latest scene
@app.get("/api/explain-scene/latest")
def explain_latest_scene():
    try:
        return explain_scene()

    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error)
        )

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error)
        )

    except RuntimeError:
        raise HTTPException(
            status_code=500,
            detail="Scene explanation failed. Check backend logs."
        )

    except Exception:
        import logging
        logging.exception("Scene explanation failed")

        raise HTTPException(
            status_code=502,
            detail="Scene explanation failed. Check backend logs."
        )


# Request model for voice questions
class AskRequest(BaseModel):
    question: str


# API: Classify and answer voice questions
@app.post("/api/ask")
async def ask(request: AskRequest):
    question = request.question.strip()

    if not question:
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty."
        )

    if len(question) > 500:
        raise HTTPException(
            status_code=400,
            detail="Question must be 500 characters or fewer."
        )

    print(f"\n[Voice Question] {question}", flush=True)

    try:
        system_prompt = """
You are Vision Assistant, an AI assistant designed to help
blind and visually impaired users.

The live camera represents the user's point of view.
The user may ask questions such as:
- What is in front of me?
- What is this?
- Where is a particular object?
- What is the expiry date of this medicine?

Handle references to objects in front of the camera appropriately.

Classify the user's question into exactly one category:

- ocr: The user wants to read or extract text from an image.
- object_detection: The user wants to find, locate, or identify a specific object.
- scene_explanation: The user wants a description of a scene or surroundings.
- normal: Any general question that does not require visual analysis.

If the category is normal, answer the user's question.

For normal answers:
- Be clear, concise, and accurate.
- Use natural language suitable for speaking aloud.
- Avoid unnecessary formatting and special symbols.
- Never claim to see the user's surroundings unless an image
  has actually been provided.

Return a JSON object with exactly these two keys:
{
    "category": "normal",
    "answer": "Your answer here"
}

For ocr, object_detection, and scene_explanation,
set "answer" to an empty string.

Return valid JSON only, without markdown code fences.
"""

        response = gemini_client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=f"""
{system_prompt}

User's question: {question}
"""
        )

        result = json.loads(response.text.strip())

        category = result.get("category", "normal").strip().lower()
        answer = result.get("answer", "").strip()

        if category not in {
            "ocr",
            "object_detection",
            "scene_explanation"
        } and category != "normal":
            category = "normal"
            answer = ""

        # Route visual questions to the analysis pipeline
        if category != "normal":
            clear_uploads()

            return {
                "question": question,
                "category": category,
                "action": "capture_image",
                "answer": ""
            }

        print(f"[Question Category] {category}", flush=True)
        print(f"[Assistant Answer] {answer}\n", flush=True)

        return {
            "question": question,
            "category": category,
            "action": "none",
            "answer": answer
        }

    except Exception as e:
        print(f"[Gemini API Error] {e}", flush=True)

        raise HTTPException(
            status_code=502,
            detail="Failed to get a response from the AI service."
        )


# Request model for visual analysis
class AnalysisRequest(BaseModel):
    category: str
    question: str


# API: Analyze the newly captured image
@app.post("/api/analyze")
async def analyze(request: AnalysisRequest):
    category = request.category.strip().lower()
    question = request.question.strip()

    if category not in {
        "ocr",
        "object_detection",
        "scene_explanation"
    }:
        raise HTTPException(
            status_code=400,
            detail="Invalid visual analysis category."
        )

    if not question:
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty."
        )

    try:
        # Runs after the frontend uploads a fresh image.
        answer = prepare_analysis(category, question)

        print(f"[Analysis Category] {category}", flush=True)
        print(f"[Analysis Answer] {answer}", flush=True)

        return {
            "category": category,
            "answer": answer
        }

    except Exception:
        import logging
        logging.exception("Visual analysis failed")

        raise HTTPException(
            status_code=502,
            detail="Visual analysis failed. Check backend logs."
        )


# Serve frontend files at the root URL.
# Keep this AFTER all API routes.
app.mount(
    "/",
    StaticFiles(directory=str(FRONTEND_DIR), html=True),
    name="frontend",
)
