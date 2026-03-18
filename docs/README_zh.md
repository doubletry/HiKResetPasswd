# 海康威视摄像头密码重置工具 - 中文文档

一个帮助重置海康威视摄像头密码的网页工具。无需使用手机拍照，通过截图上传二维码即可获取重置密钥。

---

## 目录

1. [功能特性](#功能特性)
2. [项目结构](#项目结构)
3. [环境要求](#环境要求)
4. [快速开始（一键启动）](#快速开始一键启动)
5. [手动启动](#手动启动)
6. [环境变量配置](#环境变量配置)
7. [使用说明](#使用说明)
8. [API 接口文档](#api-接口文档)
9. [运行测试](#运行测试)
10. [编译为可执行文件](#编译为可执行文件)
11. [生产部署](#生产部署)
12. [免责声明](#免责声明)

---

## 功能特性

| 功能 | 说明 |
|------|------|
| 📷 QR 码截图上传 | 上传或粘贴 SADP 生成的密码重置二维码截图 |
| ⌨️ Ctrl+V 粘贴 | 直接粘贴截图，无需保存文件 |
| 🔍 自动解码 | 后端自动识别二维码内容（纯 OpenCV，无需系统级外部库） |
| 🌐 在线获取密钥 | 如果二维码包含服务器地址，自动请求海康威视官方服务 |
| ⚙️ 离线密钥生成 | 支持旧设备（2017年前，固件 < 5.3.0）的离线 MD5 算法 |
| 📝 手动 QR 内容输入 | 支持直接粘贴已解码的二维码文本 |
| 🔒 SSRF 防护 | URL 请求严格限制在海康威视域名白名单内 |

---

## 项目结构

```
HiKResetPasswd/
├── src/
│   └── hikresetpasswd/        # Python 后端包
│       ├── __init__.py
│       ├── __main__.py        # 程序入口（可直接运行或 Nuitka 编译）
│       ├── config.py          # 环境变量配置（使用 python-dotenv）
│       ├── main.py            # FastAPI 应用
│       ├── keygen.py          # 密钥生成算法
│       ├── qr_decoder.py      # QR 码解码模块
│       └── service.py         # 业务逻辑服务层
├── tests/                     # 后端单元测试
│   ├── test_api.py
│   ├── test_config.py
│   ├── test_keygen.py
│   ├── test_qr_decoder.py
│   └── test_service.py
├── frontend/                  # Vue 3 + TypeScript 前端
│   ├── src/
│   ├── package.json
│   └── vite.config.ts
├── docs/
│   ├── README_zh.md           # 本文档（中文）
│   └── README_en.md           # 英文文档
├── .github/
│   └── workflows/
│       └── test.yml           # CI 自动测试（PR 时触发）
├── .env.example               # 环境变量示例文件
├── pyproject.toml             # Python 项目配置（Poetry）
├── poetry.lock                # 依赖锁定文件
├── start.sh                   # 一键启动脚本
├── build_nuitka.sh            # Nuitka 编译脚本
└── README.md                  # 项目简介
```

---

## 环境要求

| 依赖 | 最低版本 | 说明 |
|------|----------|------|
| Python | 3.12+ | 后端语言 |
| Poetry | 任意版本 | Python 依赖管理 |
| Node.js | 20+ | 前端构建工具 |

QR 码解码完全由 `opencv-python-headless`（Python 纯轮子包）完成，**无需安装任何系统级外部库**。

---

## 快速开始（一键启动）

```bash
# 克隆仓库
git clone https://github.com/doubletry/HiKResetPasswd.git
cd HiKResetPasswd

# （可选）复制并修改环境变量配置
cp .env.example .env

# 一键启动（后端 + 前端开发模式）
./start.sh
```

启动后访问：
- 前端：http://localhost:5173
- 后端 API：http://localhost:8000
- API 文档（Swagger）：http://localhost:8000/docs

### 启动选项

```bash
./start.sh              # 同时启动后端和前端（开发模式，默认）
./start.sh --backend    # 仅启动后端
./start.sh --frontend   # 仅启动前端
./start.sh --prod       # 生产模式（构建前端 + 单端口后端托管）
```

---

## 手动启动

如果不使用 `start.sh`，也可以分别手动启动：

### 后端

```bash
# 安装 Python 依赖
poetry install

# 开发模式启动（热重载）
poetry run uvicorn hikresetpasswd.main:app --reload --host 0.0.0.0 --port 8000

# 或者直接运行模块
poetry run python -m hikresetpasswd
```

### 前端

```bash
cd frontend

# 安装 Node 依赖
npm install

# 开发模式启动
npm run dev
```

---

## 环境变量配置

将 `.env.example` 复制为 `.env`，按需修改：

```bash
cp .env.example .env
```

`.env` 文件内容说明：

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `HOST` | `0.0.0.0` | 后端监听地址 |
| `PORT` | `8000` | 后端监听端口 |
| `LOG_LEVEL` | `info` | 日志级别：`debug` / `info` / `warning` / `error` |
| `ALLOWED_ORIGINS` | `*` | CORS 允许的前端地址，多个用逗号分隔 |
| `FRONTEND_PORT` | `5173` | 前端开发服务端口 |

> **安全提示**：生产环境中请将 `ALLOWED_ORIGINS` 设置为具体的前端地址，不要使用 `*`。

后端代码使用 `python-dotenv` 自动加载 `.env` 文件，也可以通过系统环境变量覆盖。

---

## 使用说明

### 方式一：上传 QR 码截图

1. 打开 SADP 工具，找到需要重置密码的摄像头
2. 点击"忘记密码"，选择二维码方式，等待二维码显示
3. 截图保存二维码（Windows: `Win+Shift+S`，macOS: `Cmd+Shift+4`）
4. 打开本工具页面（http://localhost:5173）
5. 上传截图或直接 `Ctrl+V` 粘贴到上传区域
6. 系统自动解码并尝试获取重置密钥
7. 将密钥输入 SADP 中，设置新密码

### 方式二：手动输入 QR 内容

如果您已经通过其他方式解码了二维码：

1. 切换到"手动输入"标签页
2. 粘贴二维码文本内容
3. 点击"获取密钥"

### 方式三：直接输入序列号（旧设备）

适用于 2017 年以前的设备（固件版本 < 5.3.0）：

1. 切换到"离线生成"标签页
2. 输入设备序列号（在 SADP 设备列表中可以看到）
3. 输入 SADP 中显示的设备当前日期
4. 点击"生成密钥"

> **注意**：离线密钥仅对 SADP 中显示的特定日期有效，每天变化。

---

## API 接口文档

后端启动后，访问 http://localhost:8000/docs 查看完整的交互式 Swagger API 文档。

### 主要接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/health` | 健康检查，确认后端运行正常 |
| `POST` | `/api/qr/upload` | 上传 QR 码图片，自动解码并获取密钥 |
| `POST` | `/api/qr/content` | 提交已解码的 QR 文本，获取密钥 |
| `POST` | `/api/key/offline` | 根据序列号和日期离线生成密钥 |

### 请求/响应示例

**上传图片（POST /api/qr/upload）**

```bash
curl -X POST http://localhost:8000/api/qr/upload \
  -F "file=@/path/to/qr_screenshot.png"
```

**离线生成密钥（POST /api/key/offline）**

```bash
curl -X POST http://localhost:8000/api/key/offline \
  -H "Content-Type: application/json" \
  -d '{"serial": "DS-2CD2T47G2-L", "date": "20240315"}'
```

**响应格式**

```json
{
  "key": "A1B2C3D4",
  "qr_content": "Serial: DS-2CD2T47G2-L, Date: 20240315",
  "method": "offline_v1",
  "error": null,
  "raw_response": null
}
```

---

## 运行测试

```bash
# 运行所有测试
poetry run pytest tests/ -v

# 带覆盖率报告
poetry run pytest tests/ -v --cov=src --cov-report=term-missing

# 仅运行特定测试文件
poetry run pytest tests/test_keygen.py -v
```

每次向 `main` 分支提交 PR 时，GitHub Actions 会自动运行测试（参见 `.github/workflows/test.yml`）。

---

## 编译为可执行文件

使用 Nuitka 将后端编译为独立的原生可执行文件（无需目标机器安装 Python）：

```bash
# 默认：standalone 模式（输出到 dist/ 目录）
./build_nuitka.sh

# 单文件模式（更易分发，启动略慢）
./build_nuitka.sh --onefile
```

编译成功后：
- **standalone 模式**：将 `dist/__main__.dist/` 整个目录复制到目标机器，运行其中的 `hikresetpasswd`
- **onefile 模式**：单个可执行文件 `dist/hikresetpasswd`，直接复制运行

> **注意**：无需安装任何额外系统库 — QR 码解码完全由 `opencv-python-headless` 处理（纯 Python 轮子包，`poetry install` 时自动安装）。

---

## 生产部署

### 一键部署（单端口）

`./start.sh --prod` 会先构建前端（`npm run build`），然后启动后端。后端自动检测 `frontend/dist/` 目录并托管前端静态文件，**所有请求通过后端端口（默认 8000）统一访问**，无需额外 Web 服务器。

```bash
# 通过 .env 文件配置生产参数
echo "HOST=0.0.0.0" >> .env
echo "PORT=8000" >> .env
echo "LOG_LEVEL=warning" >> .env

# 生产启动（单端口访问 http://HOST:PORT）
./start.sh --prod
# 或手动
cd frontend && npm run build && cd ..
poetry run uvicorn hikresetpasswd.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 使用 nginx 反向代理（可选）

如需 HTTPS 或域名绑定，可在前面加一层 nginx：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 前端静态文件
    root /path/to/HiKResetPasswd/frontend/dist;
    index index.html;

    # 前端路由（Vue Router history 模式）
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 后端 API 反向代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 免责声明

⚠️ **本工具仅供授权人员在自己负责管理的设备上使用。**

使用本工具前请确保：
- 您有合法权限重置该设备的密码
- 遵守所在地区的相关法律法规
- 不用于未授权访问他人设备

作者不对任何滥用行为承担责任。
