
from pathlib import Path

import pytesseract
from PIL import Image, ImageOps, ImageFilter


# Paths are relative to this script's location.
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_FILE = BASE_DIR / "final_text.txt"

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def extract_text(image_path: Path) -> str:
    """Extract English text from one image."""
    with Image.open(image_path) as image:
        image = ImageOps.exif_transpose(image)
        image = image.convert("L")
        image = ImageOps.autocontrast(image)
        image = image.filter(ImageFilter.SHARPEN)

        text = pytesseract.image_to_string(
            image,
            lang="eng",
            config="--psm 6",
        )

    return text.strip()


def combine_texts(text_blocks: list[str]) -> str:
    """Combine OCR results and remove exact duplicate lines."""
    combined_lines = []
    seen_lines = set()

    for block in text_blocks:
        for line in block.splitlines():
            line = " ".join(line.split())

            if not line:
                continue

            # Case-insensitive duplicate detection.
            key = line.casefold()

            if key not in seen_lines:
                seen_lines.add(key)
                combined_lines.append(line)

    return "\n".join(combined_lines)


def main():
    if not UPLOAD_DIR.exists():
        print(f"Uploads directory not found: {UPLOAD_DIR}")
        return

    # Sort by file modification time, oldest first.
    image_paths = sorted(
        (
            path
            for path in UPLOAD_DIR.iterdir()
            if path.is_file()
            and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ),
        key=lambda path: path.stat().st_mtime,
    )

    if not image_paths:
        print("No images found in the uploads directory.")
        return

    print(f"Found {len(image_paths)} images.\n")

    text_blocks = []

    for index, image_path in enumerate(image_paths, start=1):
        print(f"[{index}/{len(image_paths)}] Reading {image_path.name}...")

        try:
            text = extract_text(image_path)

            if text:
                text_blocks.append(text)
                print(f"Extracted {len(text)} characters.")
            else:
                print("No text detected.")

        except Exception as error:
            print(f"Could not process {image_path.name}: {error}")

    final_text = combine_texts(text_blocks)

    OUTPUT_FILE.write_text(final_text + "\n", encoding="utf-8")

    print("\n========== FINAL EXTRACTED TEXT ==========\n")
    print(final_text or "No text could be extracted.")
    print("\n==========================================")
    print(f"\nSaved final text to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
