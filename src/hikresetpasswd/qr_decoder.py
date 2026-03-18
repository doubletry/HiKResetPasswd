"""
QR 码解码模块
QR Code Decoder Module

纯 OpenCV 实现，无需任何系统级外部库（已移除 pyzbar/libzbar 依赖）。
Pure-OpenCV implementation — no system-level external libraries required
(pyzbar / libzbar dependency removed).

解码策略（按优先级） / Decoding strategy (by priority):
  1. cv2.QRCodeDetectorAruco — 高精度 Aruco-based 检测器 / high-accuracy Aruco detector
  2. cv2.QRCodeDetector     — 标准内置检测器 / standard built-in detector
  以上两种检测器分别对多种 OpenCV 预处理变体图像进行尝试。
  Both detectors are tried on multiple OpenCV-preprocessed image variants.
"""

import io
import logging
from typing import Optional

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


class QRCodeDecodeError(Exception):
    """QR 码无法从图片中解码时抛出 / Raised when QR code cannot be decoded from image."""


def decode_qr_from_bytes(image_bytes: bytes) -> str:
    """
    从原始图片字节数据中解码 QR 码。
    Decode a QR code from raw image bytes.

    使用纯 OpenCV 实现，无需安装 libzbar 等系统依赖。
    Uses pure OpenCV — no system dependencies like libzbar required.

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

    # 转换为 OpenCV BGR 格式 / Convert to OpenCV BGR format
    cv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

    result = _try_opencv_preprocessing(cv_image)
    if result:
        return result

    raise QRCodeDecodeError(
        "No QR code found in the image. Please ensure the image contains a clear QR code."
    )


def _try_opencv_preprocessing(cv_image: np.ndarray) -> Optional[str]:
    """
    尝试多种 OpenCV 预处理方式来帮助识别 QR 码。
    Try various OpenCV preprocessing methods to help decode the QR code.
    """
    # 生成多种预处理版本 / Generate multiple preprocessed variants
    preprocessed_images = [
        cv_image,                                    # 原图 / original
        cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY),  # 灰度图 / grayscale
        _adaptive_threshold(cv_image),               # 自适应二值化 / adaptive threshold
        _scale_image(cv_image, 2.0),                 # 2 倍放大 / 2x upscale
        _scale_image(cv_image, 3.0),                 # 3 倍放大 / 3x upscale
    ]

    # 优先使用 Aruco-based 检测器（精度更高）/ Prefer the Aruco-based detector (more accurate)
    aruco_detector: Optional[cv2.QRCodeDetectorAruco] = None
    try:
        aruco_detector = cv2.QRCodeDetectorAruco()
    except Exception:
        pass  # 老版本 OpenCV 不支持 / older OpenCV versions may not have it

    standard_detector = cv2.QRCodeDetector()

    for img in preprocessed_images:
        if aruco_detector is not None:
            result = _try_cv2_qr_detector(aruco_detector, img)
            if result:
                return result
        result = _try_cv2_qr_detector(standard_detector, img)
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


def _try_cv2_qr_detector(
    detector: cv2.QRCodeDetector,  # also accepts QRCodeDetectorAruco
    img: np.ndarray,
) -> Optional[str]:
    """
    使用 OpenCV QR 码检测器尝试解码（兼容标准和 Aruco-based 检测器）。
    Try to decode using an OpenCV QR detector (works with both standard and Aruco detectors).
    """
    try:
        data, _, _ = detector.detectAndDecode(img)
        if data:
            return data
    except Exception as exc:
        logger.debug("cv2 QR detector failed: %s", exc)
    return None
