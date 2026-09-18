import cv2
import numpy as np
from PIL import Image
from pathlib import Path
from typing import List, Tuple
from app.models import Region


# Color palette per region type (BGR for OpenCV)
REGION_COLORS = {
    "title": (0, 0, 255),       # Red
    "paragraph": (255, 0, 0),   # Blue
    "text": (255, 0, 0),        # Blue
    "table": (0, 165, 255),     # Orange
    "figure": (0, 255, 0),      # Green
    "chart": (0, 255, 255),     # Yellow
    "image": (0, 255, 0),       # Green
    "equation": (255, 0, 255),  # Magenta
    "header": (128, 128, 128),  # Gray
    "footer": (128, 128, 128),  # Gray
    "list": (255, 128, 0),      # Deep Sky Blue
    "caption": (128, 0, 128),   # Purple
    "other": (200, 200, 200),   # Light Gray
}


def draw_layout_overlay(page_image: Image.Image, regions: List[Region], save_path: Path) -> Image.Image:
    """
    Draws colored polygon / bounding box overlays and region reading-order labels onto page_image.
    Saves to save_path.
    """
    img_np = np.array(page_image.convert("RGB"))
    # Convert RGB to BGR for OpenCV
    img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
    overlay = img_bgr.copy()

    for r in regions:
        r_type = r.region_type.lower()
        color = REGION_COLORS.get(r_type, (200, 200, 200))
        label_str = f"[{r.reading_order} {r_type.upper()}]"

        # Draw polygon if available
        if r.polygon and len(r.polygon) >= 3:
            pts = np.array(r.polygon, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(overlay, [pts], isClosed=True, color=color, thickness=2)
            # Fill subtle semi-transparent background
            cv2.fillPoly(overlay, [pts], color=color)
        else:
            # Draw bounding box rectangle
            bbox = r.bbox
            cv2.rectangle(overlay, (bbox.x1, bbox.y1), (bbox.x2, bbox.y2), color=color, thickness=2)

        # Draw text label box
        x_label = r.bbox.x1
        y_label = max(15, r.bbox.y1 - 5)

        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.5
        thickness = 1
        (text_w, text_h), baseline = cv2.getTextSize(label_str, font, font_scale, thickness)

        cv2.rectangle(
            overlay,
            (x_label, y_label - text_h - 4),
            (x_label + text_w + 6, y_label + 2),
            color,
            -1
        )
        cv2.putText(
            overlay,
            label_str,
            (x_label + 3, y_label - 2),
            font,
            font_scale,
            (255, 255, 255),
            thickness,
            cv2.LINE_AA
        )

    # Blend overlay with original image (alpha 0.75 for original, 0.25 for overlay fill)
    blended = cv2.addWeighted(img_bgr, 0.75, overlay, 0.25, 0)

    # Convert BGR back to RGB PIL Image
    img_rgb = cv2.cvtColor(blended, cv2.COLOR_BGR2RGB)
    result_img = Image.fromarray(img_rgb)

    try:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        result_img.save(save_path, format="PNG")
    except Exception as e:
        print(f"Error saving layout overlay image to {save_path}: {e}")

    return result_img
