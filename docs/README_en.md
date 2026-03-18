# Hikvision Camera Password Reset Tool - English Documentation

A web tool to help reset Hikvision camera passwords. Upload a screenshot of the SADP QR code to get the reset key — no phone camera needed.

---

## Table of Contents

1. [Features](#features)
2. [Project Structure](#project-structure)
3. [Requirements](#requirements)
4. [Quick Start (One-click)](#quick-start-one-click)
5. [Manual Startup](#manual-startup)
6. [Environment Variable Configuration](#environment-variable-configuration)
7. [How to Use](#how-to-use)
8. [API Reference](#api-reference)
9. [Running Tests](#running-tests)
10. [Compile to Executable](#compile-to-executable)
11. [Production Deployment](#production-deployment)
12. [Disclaimer](#disclaimer)

---

## Features

| Feature | Description |
|---------|-------------|
| 📷 QR Screenshot Upload | Upload or paste a SADP password-reset QR code screenshot |
| ⌨️ Ctrl+V Paste | Paste screenshots directly into the upload area — no file saving needed |
| 🔍 Automatic Decoding | Backend automatically decodes QR codes (pure OpenCV — no system libs needed) |
| 🌐 Online Key Retrieval | If the QR contains a server URL, automatically fetches the key from Hikvision servers |
| ⚙️ Offline Key Generation | Supports older devices (pre-2017, firmware < 5.3.0) via offline MD5 algorithm |
| 📝 Manual QR Content Input | Paste pre-decoded QR text directly |
| 🔒 SSRF Protection | URL fetching strictly restricted to a Hikvision domain allowlist |

---

## Project Structure

```
HiKResetPasswd/
├── src/
│   └── hikresetpasswd/        # Python backend package
│       ├── __init__.py
│       ├── __main__.py        # Entry point (direct run or Nuitka compilation)
│       ├── config.py          # Environment-based configuration (python-dotenv)
│       ├── main.py            # FastAPI application
│       ├── keygen.py          # Key generation algorithm
│       ├── qr_decoder.py      # QR code decoding module
│       └── service.py         # Business logic service layer
├── tests/                     # Backend unit tests
│   ├── test_api.py
│   ├── test_config.py
│   ├── test_keygen.py
│   ├── test_qr_decoder.py
│   └── test_service.py
├── frontend/                  # Vue 3 + TypeScript frontend
│   ├── src/
│   ├── package.json
│   └── vite.config.ts
├── docs/
│   ├── README_zh.md           # Chinese documentation
│   └── README_en.md           # This file (English)
├── .github/
│   └── workflows/
│       └── test.yml           # CI automated tests (triggered on PRs)
├── .env.example               # Example environment variable file
├── pyproject.toml             # Python project config (Poetry)
├── poetry.lock                # Dependency lockfile
├── start.sh                   # One-click startup script
├── build_nuitka.sh            # Nuitka compilation script
└── README.md                  # Project overview
```

---

## Requirements

| Dependency | Minimum Version | Notes |
|-----------|-----------------|-------|
| Python | 3.12+ | Backend language |
| Poetry | Any | Python dependency manager |
| Node.js | 20+ | Frontend build toolchain |

No system-level libraries are required for QR code decoding — the backend uses pure OpenCV (`opencv-python-headless`), which is installed automatically as a Python package.

---

## Quick Start (One-click)

```bash
# Clone the repository
git clone https://github.com/doubletry/HiKResetPasswd.git
cd HiKResetPasswd

# (Optional) Copy and edit the environment config
cp .env.example .env

# Start both backend and frontend in development mode
./start.sh
```

Once started, open:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- Interactive API Docs (Swagger): http://localhost:8000/docs

### Startup Options

```bash
./start.sh              # Start both backend and frontend (development mode, default)
./start.sh --backend    # Start backend only
./start.sh --frontend   # Start frontend only
./start.sh --prod       # Production mode (build frontend + multi-worker backend)
```

---

## Manual Startup

If you prefer not to use `start.sh`, you can start each component separately:

### Backend

```bash
# Install Python dependencies
poetry install

# Development mode (with hot reload)
poetry run uvicorn hikresetpasswd.main:app --reload --host 0.0.0.0 --port 8000

# Or run the module directly
poetry run python -m hikresetpasswd
```

### Frontend

```bash
cd frontend

# Install Node dependencies
npm install

# Development mode
npm run dev
```

---

## Environment Variable Configuration

Copy `.env.example` to `.env` and edit as needed:

```bash
cp .env.example .env
```

Available environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Backend bind address |
| `PORT` | `8000` | Backend port |
| `LOG_LEVEL` | `info` | Log level: `debug` / `info` / `warning` / `error` |
| `ALLOWED_ORIGINS` | `*` | CORS allowed origins, comma-separated for multiple values |
| `FRONTEND_PORT` | `5173` | Frontend dev server port |

> **Security note**: In production, set `ALLOWED_ORIGINS` to your specific frontend URL instead of `*`.

The backend uses `python-dotenv` to automatically load `.env`. System environment variables always take precedence over `.env` values.

---

## How to Use

### Method 1: Upload a QR Code Screenshot

1. Open the SADP tool, locate the camera whose password you need to reset
2. Click "Forgot Password", choose the QR code method, and wait for the QR to appear
3. Take a screenshot of the QR code (Windows: `Win+Shift+S`, macOS: `Cmd+Shift+4`)
4. Open the tool at http://localhost:5173
5. Upload the screenshot or paste it directly with `Ctrl+V` into the upload area
6. The system automatically decodes it and attempts to retrieve the reset key
7. Enter the key in SADP to set a new password

### Method 2: Paste Pre-decoded QR Content

If you already have the decoded QR text from another tool:

1. Switch to the "Manual Input" tab
2. Paste the QR code text
3. Click "Get Key"

### Method 3: Enter Serial Number Directly (Older Devices)

For devices manufactured before 2017 (firmware < 5.3.0):

1. Switch to the "Offline Generation" tab
2. Enter the device serial number (visible in the SADP device list)
3. Enter the device's current date as shown in SADP
4. Click "Generate Key"

> **Note**: The offline key is only valid for the specific date shown in SADP and changes daily.

---

## API Reference

Once the backend is running, visit http://localhost:8000/docs for the full interactive Swagger API documentation.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check — confirm the backend is running |
| `POST` | `/api/qr/upload` | Upload a QR code image; auto-decode and retrieve key |
| `POST` | `/api/qr/content` | Submit pre-decoded QR text; retrieve key |
| `POST` | `/api/key/offline` | Generate key offline from serial number and date |

### Request / Response Examples

**Upload image (POST /api/qr/upload)**

```bash
curl -X POST http://localhost:8000/api/qr/upload \
  -F "file=@/path/to/qr_screenshot.png"
```

**Offline key generation (POST /api/key/offline)**

```bash
curl -X POST http://localhost:8000/api/key/offline \
  -H "Content-Type: application/json" \
  -d '{"serial": "DS-2CD2T47G2-L", "date": "20240315"}'
```

**Response format**

```json
{
  "key": "A1B2C3D4",
  "qr_content": "Serial: DS-2CD2T47G2-L, Date: 20240315",
  "method": "offline_v1",
  "error": null,
  "raw_response": null
}
```

#### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `key` | `string \| null` | The reset key, if successfully obtained |
| `qr_content` | `string \| null` | The decoded QR code content |
| `method` | `string \| null` | How the key was obtained: `offline_v1`, `url_fetch`, or `raw` |
| `error` | `string \| null` | Error message if the key could not be obtained |
| `raw_response` | `string \| null` | Raw server response body (first 2000 chars), if a URL was fetched |

---

## Running Tests

```bash
# Run all tests
poetry run pytest tests/ -v

# With coverage report
poetry run pytest tests/ -v --cov=src --cov-report=term-missing

# Run a specific test file
poetry run pytest tests/test_keygen.py -v
```

Tests cover:
- **`test_api.py`** — FastAPI endpoint integration tests
- **`test_config.py`** — Environment variable configuration tests
- **`test_keygen.py`** — Offline key generation algorithm tests
- **`test_qr_decoder.py`** — QR code decoding tests
- **`test_service.py`** — Business logic and SSRF protection tests

GitHub Actions automatically runs the full test suite on every pull request targeting `main`. See `.github/workflows/test.yml`.

---

## Compile to Executable

Use Nuitka to compile the backend into a standalone native executable (no Python required on the target machine):

```bash
# Default: standalone mode (output to dist/ directory)
./build_nuitka.sh

# Single-file mode (easier to distribute, slightly slower startup)
./build_nuitka.sh --onefile
```

After a successful build:
- **Standalone mode**: Copy the entire `dist/__main__.dist/` directory to the target machine and run `hikresetpasswd` inside it
- **Onefile mode**: Single executable `dist/hikresetpasswd` — copy and run directly

> **Note**: No additional system libraries required — QR decoding is handled entirely by `opencv-python-headless` (a pure Python wheel).

---

## Production Deployment

### Backend (multi-worker)

```bash
# Configure production settings in .env
echo "HOST=0.0.0.0" >> .env
echo "PORT=8000" >> .env
echo "LOG_LEVEL=warning" >> .env
echo "ALLOWED_ORIGINS=http://your-frontend-domain.com" >> .env

# Start in production mode
./start.sh --prod
# Or manually
poetry run uvicorn hikresetpasswd.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Frontend (static files)

```bash
cd frontend
npm run build
# Serve the dist/ directory with a static web server (e.g. nginx)
```

### nginx Configuration Example

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # Serve frontend static files
    root /path/to/HiKResetPasswd/frontend/dist;
    index index.html;

    # Vue Router history mode fallback
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Reverse proxy to backend API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## Disclaimer

⚠️ **This tool is intended solely for authorized personnel to use on devices they are responsible for managing.**

Before using this tool, ensure that:
- You have legitimate authorization to reset the device's password
- You comply with all applicable laws and regulations in your jurisdiction
- You do not use this tool to gain unauthorized access to others' devices

The author assumes no liability for any misuse of this tool.
