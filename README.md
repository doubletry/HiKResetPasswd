# HiKResetPasswd

海康威视摄像头密码重置工具 / Hikvision Camera Password Reset Tool

通过 SADP 生成的二维码截图，在浏览器中获取重置密钥，无需手机拍照。

Get the password reset key from your browser by uploading a screenshot of the SADP QR code — no phone camera required.

---

## 文档 / Documentation

| 语言 / Language | 链接 / Link |
|----------------|-------------|
| 🇨🇳 中文 | [docs/README_zh.md](docs/README_zh.md) |
| 🇬🇧 English | [docs/README_en.md](docs/README_en.md) |

---

## 快速上手 / Quick Start

```bash
# 复制环境变量配置（可选）/ Copy env config (optional)
cp .env.example .env

# 一键启动 / One-click start
./start.sh

# 生产模式（单端口访问）/ Production mode (single port)
./start.sh --prod
```

**开发模式 / Dev mode:**
- 前端 Frontend: http://localhost:5173  
- 后端 API Backend: http://localhost:8000  

**生产模式 / Prod mode (`--prod`):**
- 统一入口 Single port: http://localhost:8000  

- API 文档 Swagger Docs: http://localhost:8000/docs

---

## 技术栈 / Tech Stack

- **Backend**: Python 3.12 · FastAPI · Poetry · python-dotenv
- **Frontend**: Vue 3 · TypeScript · Vite
- **QR Decoding**: OpenCV (pure Python, no system libs)

## ⚠️ 免责声明 / Disclaimer

本工具仅供授权人员在自己负责管理的设备上使用。  
This tool is for authorized personnel to use on devices they manage only.
