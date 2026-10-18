
from pathlib import Path
from io import BytesIO
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError

app = FastAPI(title="Live Text Reader API")

UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"message": "Live Text Reader API is running"}

@app.post("/api/upload")
async def upload_frame(file: UploadFile = File(...)):
    image_bytes = await file.read()

    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty image")

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image_format = image.format
            width, height = image.size
            image.load()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=400, detail="Invalid image")

    extensions = {
        "JPEG": ".jpg",
        "PNG": ".png",
        "WEBP": ".webp",
    }

    if image_format not in extensions:
        raise HTTPException(
            status_code=400,
            detail="Unsupported image format",
        )

    filename = f"frame_{uuid4().hex}{extensions[image_format]}"
    save_path = UPLOAD_DIR / filename
    save_path.write_bytes(image_bytes)

    print(f"Saved: {filename}")

    return {
        "message": "Frame received and saved",
        "filename": filename,
        "width": width,
        "height": height,
        "size_bytes": len(image_bytes),
    }
