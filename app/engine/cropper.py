import cv2
import numpy as np
from PIL import Image
from pathlib import Path
from typing import Optional, Tuple, List
from app.config import settings
from app.models import Region, BoundingBox
from app.utils.logging import logger


class RegionCropper:
    """
    Crops region bounding boxes or polygons from page images with configurable padding
    and polygon masking. Filters invalid/tiny regions.
    """

    def __init__(self, padding: int = settings.CROP_PADDING):
        self.padding = padding

    def crop_region(
        self,
        page_image: Image.Image,
        region: Region,
        save_path: Optional[Path] = None
    ) -> Optional[Image.Image]:
        """
        Crops a region from page_image. Applies padding and polygon mask if present.
        If crop is too small or invalid, marks region.processing_status = "skipped" and returns None.
        """
        width, height = page_image.size
        bbox = region.bbox

        # 1. Apply padding and clamp
        x1 = max(0, bbox.x1 - self.padding)
        y1 = max(0, bbox.y1 - self.padding)
        x2 = min(width, bbox.x2 + self.padding)
        y2 = min(height, bbox.y2 + self.padding)

        crop_w = x2 - x1
        crop_h = y2 - y1

        # 2. Check empty/tiny region protection (Section 15)
        if crop_w <= 2 or crop_h <= 2 or (crop_w * crop_h) <= 4:
            logger.warning(f"CROP_SKIPPED: Region {region.id} is too small ({crop_w}x{crop_h}).")
            region.processing_status = "skipped"
            region.error = f"Tiny/empty region ({crop_w}x{crop_h})"
            return None

        # Update region bbox with padded coordinates for accuracy if helpful
        # 3. Crop base rectangle
        crop_rect = page_image.crop((x1, y1, x2, y2))

        # 4. If polygon available, apply polygon mask filled with white outside region
        if region.polygon and len(region.polygon) >= 3:
            try:
                crop_rect = self._apply_polygon_mask(crop_rect, region.polygon, x1, y1)
            except Exception as e:
                logger.warning(f"Polygon mask error for region {region.id}: {e}. Falling back to bbox crop.")

        # Save crop file if path provided
        if save_path:
            try:
                save_path.parent.mkdir(parents=True, exist_ok=True)
                crop_rect.save(save_path, format="PNG")
                region.crop_path = str(save_path)
            except Exception as e:
                logger.error(f"Failed to save crop image to {save_path}: {e}")

        return crop_rect

    def _apply_polygon_mask(
        self,
        crop_img: Image.Image,
        polygon: List[List[int]],
        offset_x: int,
        offset_y: int
    ) -> Image.Image:
        """
        Creates a white background image and masks the crop to only include pixels within the polygon.
        """
        crop_np = np.array(crop_img)
        h, w, c = crop_np.shape

        # Shift polygon points to crop coordinate space
        pts = np.array([[p[0] - offset_x, p[1] - offset_y] for p in polygon], dtype=np.int32)
        pts = pts.reshape((-1, 1, 2))

        # Create binary mask (255 inside polygon, 0 outside)
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(mask, [pts], 255)

        # Create solid white image
        white_bg = np.ones_like(crop_np) * 255

        # Combine crop image inside polygon with white background outside
        masked_np = np.where(mask[:, :, None] == 255, crop_np, white_bg)

        return Image.fromarray(masked_np)
