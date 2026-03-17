"""
QR code decoder module.

Decodes QR codes from images using pyzbar with OpenCV/Pillow for preprocessing.
"""

import io
import logging
from typing import Optional

import cv2
import numpy as np
from PIL import Image
from pyzbar import pyzbar

logger = logging.getLogger(__name__)


class QRCodeDecodeError(Exception):
    """Raised when QR code cannot be decoded from image."""


def decode_qr_from_bytes(image_bytes: bytes) -> str:
    """
    Decode a QR code from raw image bytes.

    Args:
        image_bytes: Raw bytes of the image file (PNG, JPEG, BMP, etc.)

    Returns:
        Decoded string content of the QR code

    Raises:
        QRCodeDecodeError: If no QR code found or cannot be decoded
    """
    try:
        pil_image = Image.open(io.BytesIO(image_bytes))
        pil_image = pil_image.convert("RGB")
    except Exception as exc:
        raise QRCodeDecodeError(f"Cannot open image: {exc}") from exc

    # Try pyzbar first on the PIL image
    result = _try_pyzbar(pil_image)
    if result:
        return result

    # Convert to OpenCV and try various preprocessing methods
    cv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
    result = _try_opencv_preprocessing(cv_image)
    if result:
        return result

    raise QRCodeDecodeError(
        "No QR code found in the image. Please ensure the image contains a clear QR code."
    )


def _try_pyzbar(image: Image.Image) -> Optional[str]:
    """Try to decode QR code using pyzbar directly."""
    try:
        decoded_objects = pyzbar.decode(image)
        for obj in decoded_objects:
            if obj.type in ("QRCODE", "QR_CODE"):
                return obj.data.decode("utf-8", errors="replace")
        # Also try non-QR barcodes in case it's encoded differently
        for obj in decoded_objects:
            return obj.data.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.debug("pyzbar direct decode failed: %s", exc)
    return None


def _try_opencv_preprocessing(cv_image: np.ndarray) -> Optional[str]:
    """Try various OpenCV preprocessing methods to help decode the QR code."""
    # Try different preprocessing approaches
    preprocessed_images = [
        cv_image,  # original
        cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY),  # grayscale
        _adaptive_threshold(cv_image),  # adaptive threshold
        _scale_image(cv_image, 2.0),  # 2x upscale
        _scale_image(cv_image, 3.0),  # 3x upscale
    ]

    detector = cv2.QRCodeDetector()

    for img in preprocessed_images:
        result = _try_cv2_qr_detector(detector, img)
        if result:
            return result
        result = _try_pyzbar_cv(img)
        if result:
            return result

    return None


def _adaptive_threshold(cv_image: np.ndarray) -> np.ndarray:
    """Apply adaptive thresholding for better QR code contrast."""
    gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY) if len(cv_image.shape) == 3 else cv_image
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )


def _scale_image(cv_image: np.ndarray, scale: float) -> np.ndarray:
    """Scale image by given factor."""
    h, w = cv_image.shape[:2]
    return cv2.resize(cv_image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)


def _try_cv2_qr_detector(detector: cv2.QRCodeDetector, img: np.ndarray) -> Optional[str]:
    """Try using OpenCV's built-in QR detector."""
    try:
        data, _, _ = detector.detectAndDecode(img)
        if data:
            return data
    except Exception as exc:
        logger.debug("cv2 QR detector failed: %s", exc)
    return None


def _try_pyzbar_cv(img: np.ndarray) -> Optional[str]:
    """Try pyzbar with an OpenCV image."""
    try:
        if len(img.shape) == 3:
            pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        else:
            pil_img = Image.fromarray(img)
        decoded_objects = pyzbar.decode(pil_img)
        for obj in decoded_objects:
            return obj.data.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.debug("pyzbar cv decode failed: %s", exc)
    return None
