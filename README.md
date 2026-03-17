# 海康威视摄像头密码重置工具 (Hikvision Camera Password Reset Tool)

一个帮助重置海康威视摄像头密码的网页工具。无需手机拍照，通过截图上传二维码即可获取重置密钥。

A web tool to help reset Hikvision camera passwords. Upload a screenshot of the SADP QR code to get the reset key without needing a phone camera.

## 功能特性 (Features)

- 📷 **QR 码截图上传** - 上传或粘贴 SADP 生成的密码重置二维码截图
- 🔍 **自动解码** - 后端自动识别二维码内容
- 🌐 **在线获取密钥** - 如果二维码包含服务器地址，自动请求获取密钥
- ⚙️ **离线密钥生成** - 支持旧设备（2017年前，固件 < 5.3.0）的离线算法
- 📝 **手动输入** - 支持直接输入已解码的二维码内容
- 🔒 **安全** - 仅用于授权人员的设备密码重置

## 技术栈 (Tech Stack)

- **Backend**: Python 3.12 + FastAPI + Poetry
- **Frontend**: Vue 3 + TypeScript + Vite
- **QR Decoding**: pyzbar + OpenCV

## 快速开始 (Quick Start)

### 环境要求

- Python 3.12+
- Node.js 18+
- Poetry
- libzbar (系统库)

#### 安装 libzbar

```bash
# Ubuntu/Debian
sudo apt-get install libzbar0

# macOS
brew install zbar

# CentOS/RHEL
sudo yum install zbar
```

### 启动后端

```bash
cd backend
poetry install
poetry run uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端将在 http://localhost:5173 运行，后端在 http://localhost:8000。

### 生产部署

#### 后端

```bash
cd backend
poetry install --only main
poetry run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 4
```

#### 前端

```bash
cd frontend
npm run build
# 将 dist/ 目录部署到 Web 服务器
```

## API 文档

启动后端后，访问 http://localhost:8000/docs 查看 Swagger API 文档。

### 主要接口

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/qr/upload` | 上传二维码图片 |
| POST | `/api/qr/content` | 处理二维码文本内容 |
| POST | `/api/key/offline` | 离线生成密钥 |

## 使用说明 (How to Use)

1. 在 SADP 工具中找到需要重置密码的摄像头
2. 点击"忘记密码"，选择二维码方式
3. 截图保存二维码
4. 打开本工具，上传截图（或直接 Ctrl+V 粘贴）
5. 系统自动解码并尝试获取重置密钥
6. 将密钥输入 SADP 中，设置新密码

### 关于新设备

对于 2017 年以后的新设备，密钥通过海康威视官方服务器获取。如果二维码包含服务器地址（URL），工具会自动尝试获取。

如果自动获取失败，您需要：
1. 确认网络可以访问海康威视服务器
2. 或联系海康威视技术支持

### 关于旧设备

对于 2017 年以前的设备（固件 < 5.3.0），使用"离线密钥生成"功能：
- 输入设备序列号（在 SADP 中可以看到）
- 输入 SADP 中显示的设备当前日期
- 点击生成

## 运行测试

```bash
cd backend
poetry run pytest tests/ -v --cov=src
```

## ⚠️ 免责声明

本工具仅供授权人员在自己负责管理的设备上使用。请确保：
- 您有权限重置该设备的密码
- 遵守当地法律法规
- 不用于未授权访问他人设备
