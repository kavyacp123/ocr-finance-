import sys
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.engine.layout_detector import LayoutDetector
from app.engine.cropper import RegionCropper
from app.engine.visualization import draw_layout_overlay


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_layout.py <image_path>")
        sys.exit(1)

    image_path = Path(sys.argv[1])
    if not image_path.exists():
        print(f"File not found: {image_path}")
        sys.exit(1)

    print(f"Testing layout detection on: {image_path}")
    img = Image.open(image_path).convert("RGB")

    detector = LayoutDetector()
    detector.initialize()

    regions = detector.detect(page_num=1, image=img)

    print(f"\nDetected {len(regions)} regions:")
    for r in regions:
        print(f"  [{r.reading_order}] Region ID: {r.id:10s} Type: {r.region_type:12s} BBox: ({r.bbox.x1}, {r.bbox.y1}) -> ({r.bbox.x2}, {r.bbox.y2})")

    output_dir = Path(settings.OUTPUT_DIR) / "test_layout"
    overlay_path = output_dir / "overlay_page_001.png"
    draw_layout_overlay(img, regions, overlay_path)
    print(f"\nOverlay saved to: {overlay_path}")

    cropper = RegionCropper()
    for r in regions:
        crop_path = output_dir / "crops" / f"{r.id}_{r.region_type}.png"
        cropper.crop_region(img, r, save_path=crop_path)

    print(f"Crops saved to: {output_dir / 'crops'}")


if __name__ == "__main__":
    main()
