"""
Hikvision Password Reset Web Application - Backend

FastAPI application that:
1. Accepts QR code images (upload or base64)
2. Decodes the QR code
3. Attempts to obtain the reset key from the QR content
4. Supports offline key generation for older devices
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .qr_decoder import QRCodeDecodeError, decode_qr_from_bytes
from .service import generate_key_offline, process_qr_content

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Hikvision Password Reset Backend")
    yield
    logger.info("Shutting down Hikvision Password Reset Backend")


app = FastAPI(
    title="Hikvision Password Reset Tool",
    description=(
        "A tool to help reset Hikvision camera passwords by processing "
        "SADP-generated QR codes and obtaining reset keys."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Allow CORS from the Vue frontend (development and production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HealthResponse(BaseModel):
    status: str
    message: str


class KeyRequest(BaseModel):
    serial: str = Field(..., description="Device serial number from SADP")
    date: str = Field(
        ...,
        description="Device date from SADP in YYYYMMDD or YYYY-MM-DD format",
        examples=["20240315", "2024-03-15"],
    )


class QRContentRequest(BaseModel):
    qr_content: str = Field(..., description="Raw QR code content string")


class KeyResponse(BaseModel):
    key: str | None = Field(None, description="Reset key if successfully obtained")
    qr_content: str | None = Field(None, description="Decoded QR code content")
    method: str | None = Field(None, description="Method used to obtain the key")
    error: str | None = Field(None, description="Error message if key could not be obtained")
    raw_response: str | None = Field(None, description="Raw response from server if applicable")


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(status="ok", message="Hikvision Password Reset Backend is running")


@app.post("/api/qr/upload", response_model=KeyResponse)
async def upload_qr_image(file: UploadFile = File(...)):
    """
    Upload a QR code image to decode and attempt to get the reset key.

    Accepts any image format (PNG, JPEG, BMP, etc.) containing a Hikvision
    SADP password reset QR code.

    The backend will:
    1. Decode the QR code from the image
    2. If the QR contains a URL, fetch it to get the key
    3. If the QR contains device data, attempt offline key generation
    4. Return the key or the raw QR content for manual processing
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail=f"File must be an image. Got: {file.content_type}",
        )

    image_bytes = await file.read()
    if len(image_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    # Decode the QR code
    try:
        qr_content = decode_qr_from_bytes(image_bytes)
    except QRCodeDecodeError as exc:
        return KeyResponse(error=str(exc))

    # Process the QR content to get the key
    result = await process_qr_content(qr_content)
    return KeyResponse(**result.to_dict())


@app.post("/api/qr/content", response_model=KeyResponse)
async def process_qr_content_endpoint(request: QRContentRequest):
    """
    Process raw QR code content (already decoded) to get the reset key.

    Useful when the QR code has already been decoded by another tool.
    """
    if not request.qr_content.strip():
        raise HTTPException(status_code=400, detail="QR content cannot be empty")

    result = await process_qr_content(request.qr_content)
    return KeyResponse(**result.to_dict())


@app.post("/api/key/offline", response_model=KeyResponse)
async def generate_offline_key(request: KeyRequest):
    """
    Generate a reset key using the offline algorithm.

    This works for older Hikvision devices (firmware < 5.3.0, manufactured before ~2017).
    Requires the device serial number and the date shown in SADP.

    Note: The key is only valid for the specific date shown in SADP.
    """
    if not request.serial.strip():
        raise HTTPException(status_code=400, detail="Serial number cannot be empty")
    if not request.date.strip():
        raise HTTPException(status_code=400, detail="Date cannot be empty")

    result = await generate_key_offline(request.serial.strip(), request.date.strip())
    return KeyResponse(**result.to_dict())
