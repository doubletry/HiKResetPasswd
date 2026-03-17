"""
QR 码解码模块
QR Code Decoder Module

使用 pyzbar 配合 OpenCV/Pillow 预处理从图片中解码 QR 码。
Decodes QR codes from images using pyzbar with OpenCV/Pillow preprocessing.

解码策略（按优先级） / Decoding strategy (by priority):
  1. pyzbar 直接解码原始 PIL 图片 / pyzbar direct decode on raw PIL image
  2. OpenCV 多种预处理方式 + pyzbar / OpenCV preprocessing variants + pyzbar
  3. OpenCV 内置 QRCodeDetector / OpenCV built-in QRCodeDetector
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
    """QR 码无法从图片中解码时抛出 / Raised when QR code cannot be decoded from image."""


def decode_qr_from_bytes(image_bytes: bytes) -> str:
    """
    从原始图片字节数据中解码 QR 码。
    Decode a QR code from raw image bytes.

    Args:
        image_bytes: 图片文件的原始字节（PNG、JPEG、BMP 等）
                     Raw bytes of the image file (PNG, JPEG, BMP, etc.)

    Returns:
        QR 码解码后的字符串内容 / Decoded string content of the QR code

    Raises:
        QRCodeDecodeError: 未找到 QR 码或无法解码时抛出
                           If no QR code found or cannot be decoded
    """
    try:
        pil_image = Image.open(io.BytesIO(image_bytes))
        pil_image = pil_image.convert("RGB")
    except Exception as exc:
        raise QRCodeDecodeError(f"Cannot open image: {exc}") from exc

    # 优先使用 pyzbar 直接解码 / Try pyzbar first on the PIL image
    result = _try_pyzbar(pil_image)
    if result:
        return result

    # 转换为 OpenCV 格式并尝试多种预处理方式
    # Convert to OpenCV and try various preprocessing methods
    cv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
    result = _try_opencv_preprocessing(cv_image)
    if result:
        return result

    raise QRCodeDecodeError(
        "No QR code found in the image. Please ensure the image contains a clear QR code."
    )


def _try_pyzbar(image: Image.Image) -> Optional[str]:
    """使用 pyzbar 直接解码 QR 码 / Try to decode QR code using pyzbar directly."""
    try:
        decoded_objects = pyzbar.decode(image)
        for obj in decoded_objects:
            # 优先返回 QRCODE 类型 / Prefer QRCODE type
            if obj.type in ("QRCODE", "QR_CODE"):
                return obj.data.decode("utf-8", errors="replace")
        # 回退：返回任何能解码的条码 / Fallback: return any decodable barcode
        for obj in decoded_objects:
            return obj.data.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.debug("pyzbar direct decode failed: %s", exc)
    return None


def _try_opencv_preprocessing(cv_image: np.ndarray) -> Optional[str]:
    """
    尝试多种 OpenCV 预处理方式来帮助识别 QR 码。
    Try various OpenCV preprocessing methods to help decode the QR code.
    """
    # 生成多种预处理版本 / Generate multiple preprocessed versions
    preprocessed_images = [
        cv_image,                                    # 原图 / original
        cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY),  # 灰度图 / grayscale
        _adaptive_threshold(cv_image),               # 自适应二值化 / adaptive threshold
        _scale_image(cv_image, 2.0),                 # 2 倍放大 / 2x upscale
        _scale_image(cv_image, 3.0),                 # 3 倍放大 / 3x upscale
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
    """
    应用自适应阈值以提高 QR 码对比度。
    Apply adaptive thresholding for better QR code contrast.
    """
    gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY) if len(cv_image.shape) == 3 else cv_image
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )


def _scale_image(cv_image: np.ndarray, scale: float) -> np.ndarray:
    """
    按指定倍数缩放图片。
    Scale image by given factor.
    """
    h, w = cv_image.shape[:2]
    return cv2.resize(cv_image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)


def _try_cv2_qr_detector(detector: cv2.QRCodeDetector, img: np.ndarray) -> Optional[str]:
    """
    使用 OpenCV 内置 QR 码检测器尝试解码。
    Try using OpenCV's built-in QR detector.
    """
    try:
        data, _, _ = detector.detectAndDecode(img)
        if data:
            return data
    except Exception as exc:
        logger.debug("cv2 QR detector failed: %s", exc)
    return None


def _try_pyzbar_cv(img: np.ndarray) -> Optional[str]:
    """
    将 OpenCV 格式图片转换后用 pyzbar 尝试解码。
    Try pyzbar with an OpenCV image.
    """
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
