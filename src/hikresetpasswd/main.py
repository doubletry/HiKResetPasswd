"""
海康威视密码重置工具 - 后端主应用
Hikvision Password Reset Tool - Backend Main Application

FastAPI 应用，提供以下功能 / FastAPI app providing:
  1. 接收并解码 QR 码图片 / Accept and decode QR code images
  2. 从 QR 内容中尝试获取重置密钥 / Attempt to obtain reset key from QR content
  3. 支持旧设备的离线密钥生成 / Support offline key generation for older devices
"""

import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import settings
from .qr_decoder import QRCodeDecodeError, decode_qr_from_bytes
from .service import generate_key_offline, process_qr_content

# 根据配置设置日志级别 / Set log level from config
logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理 / Application lifespan handler."""
    logger.info(
        "Starting Hikvision Password Reset Backend on %s:%s",
        settings.host,
        settings.port,
    )
    yield
    logger.info("Shutting down Hikvision Password Reset Backend")


app = FastAPI(
    title="Hikvision Password Reset Tool",
    description=(
        "海康威视摄像头密码重置工具 / "
        "A tool to help reset Hikvision camera passwords by processing "
        "SADP-generated QR codes and obtaining reset keys."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 中间件：允许来自前端的跨域请求
# CORS middleware: allow cross-origin requests from the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic 模型 / Pydantic models
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """健康检查响应 / Health check response."""

    status: str
    message: str


class KeyRequest(BaseModel):
    """离线密钥生成请求体 / Offline key generation request body."""

    serial: str = Field(..., description="Device serial number from SADP / SADP 中的设备序列号")
    date: str = Field(
        ...,
        description=(
            "Device date from SADP in YYYYMMDD or YYYY-MM-DD format / "
            "SADP 中显示的设备日期，格式 YYYYMMDD 或 YYYY-MM-DD"
        ),
        examples=["20240315", "2024-03-15"],
    )


class QRContentRequest(BaseModel):
    """已解码 QR 内容请求体 / Pre-decoded QR content request body."""

    qr_content: str = Field(..., description="Raw QR code content string / QR 码原始文本内容")


class KeyResponse(BaseModel):
    """密钥响应体 / Key response body."""

    key: str | None = Field(None, description="Reset key if successfully obtained / 获取到的重置密钥")
    qr_content: str | None = Field(None, description="Decoded QR code content / 解码后的 QR 内容")
    method: str | None = Field(None, description="Method used to obtain the key / 获取密钥的方式")
    error: str | None = Field(None, description="Error message if key could not be obtained / 错误信息")
    raw_response: str | None = Field(None, description="Raw response from server if applicable / 服务器原始响应")


# ---------------------------------------------------------------------------
# API 端点 / API endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """
    健康检查端点。
    Health check endpoint.
    """
    return HealthResponse(status="ok", message="Hikvision Password Reset Backend is running")


@app.post("/api/qr/upload", response_model=KeyResponse)
async def upload_qr_image(file: UploadFile = File(...)):
    """
    上传 QR 码截图，解码并尝试获取重置密钥。
    Upload a QR code screenshot, decode it, and attempt to get the reset key.

    支持的图片格式 / Supported image formats: PNG, JPEG, BMP, GIF, TIFF 等
    """
    # 验证上传文件是图片 / Validate uploaded file is an image
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail=f"File must be an image. Got: {file.content_type}",
        )

    image_bytes = await file.read()
    if len(image_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    # 1. 解码 QR 码 / Decode the QR code
    try:
        qr_content = decode_qr_from_bytes(image_bytes)
    except QRCodeDecodeError as exc:
        return KeyResponse(error=str(exc))

    # 2. 处理 QR 内容，尝试获取密钥 / Process QR content to get the key
    result = await process_qr_content(qr_content)
    return KeyResponse(**result.to_dict())


@app.post("/api/qr/content", response_model=KeyResponse)
async def process_qr_content_endpoint(request: QRContentRequest):
    """
    处理已解码的 QR 文本内容，尝试获取重置密钥。
    Process pre-decoded QR text content and attempt to get the reset key.

    适用于已通过其他工具解码 QR 码的场景。
    Useful when the QR code has already been decoded by another tool.
    """
    if not request.qr_content.strip():
        raise HTTPException(status_code=400, detail="QR content cannot be empty")

    result = await process_qr_content(request.qr_content)
    return KeyResponse(**result.to_dict())


@app.post("/api/key/offline", response_model=KeyResponse)
async def generate_offline_key(request: KeyRequest):
    """
    使用离线算法生成重置密钥（适用于旧设备）。
    Generate a reset key using the offline algorithm (for older devices).

    适用于 2017 年以前的设备（固件版本 < 5.3.0）。
    Works for older Hikvision devices (firmware < 5.3.0, manufactured before ~2017).

    注意：密钥仅对 SADP 中显示的特定日期有效。
    Note: The key is only valid for the specific date shown in SADP.
    """
    if not request.serial.strip():
        raise HTTPException(status_code=400, detail="Serial number cannot be empty")
    if not request.date.strip():
        raise HTTPException(status_code=400, detail="Date cannot be empty")

    result = await generate_key_offline(request.serial.strip(), request.date.strip())
    return KeyResponse(**result.to_dict())


# ---------------------------------------------------------------------------
# 程序入口（通过 __main__ 直接运行）
# Entry point (when run directly via __main__)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "hikresetpasswd.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
    )
