# Web 服务镜像与部署

现在的主要交付物是带网页资源的 Python 后端镜像，前后端由同一服务提供。运行镜像不需要 Qt、图形桌面、Node.js 或宿主机 Python。镜像基于 Python 3.12 Debian slim，包含中文水印字体，并以 UID/GID 10001 运行。

## 构建

```bash
python scripts/build_image.py --tag photocraft:local
```

脚本自动读取 Git commit、tag 和 dirty 状态，通过 build arguments 写入镜像。镜像不包含 `.git`。服务的版本文字与 Python 包版本都来自这份构建记录。

也可以直接构建：

```bash
docker build --build-arg VCS_REF="$(git rev-parse HEAD)" -t photocraft:local .
```

若构建发布 tag，可额外传 `--build-arg VERSION_TAG=v1.2.3`，必须同时提供完整 commit。无 Git 身份的手动构建显示「未标记源码」，不会伪造版本号。普通 commit 使用短哈希，带未提交修改时脚本会附加 `-dirty`。

## 运行

```bash
docker run -d --name photocraft \
  -p 127.0.0.1:8000:8000 \
  -v photocraft-config:/data \
  --restart unless-stopped photocraft:local
```

打开 http://localhost:8000。也可使用根目录 `compose.yml`，运行 `docker compose up -d --no-build`。默认端口只允许本机访问；需要对外部署时调整映射或接入反向代理，并由代理提供 HTTPS 和访问控制。

服务和接口使用同源根路径 `/`。健康检查为 `GET /api/health`。图像处理与只读预设接口位于 `/api/`；静态资源不从公网 CDN 加载。

持久卷只保存配置。图像、编码结果和撤销记录属于内存会话，服务重启会释放。绑定宿主目录代替命名卷时，需要确保 UID 10001 有写入权限。

## 本地验证

```bash
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps -e .
ruff check .
python -m pytest -q
python scripts/smoke_web.py --spawn
```

默认测试目标为 Web API 与通用图像处理代码，不安装或导入 Qt。浏览器检查需要开发依赖：

```bash
npm ci
npx playwright install --with-deps chromium firefox webkit
# 先启动服务，再运行：
npm run test:web
```

可以通过 `PHOTOCRAFT_BASE_URL` 指定服务地址，通过 `PHOTOCRAFT_SCREENSHOT_DIR` 指定截图目录。默认顺序运行三种引擎，可用 `PHOTOCRAFT_BROWSERS=webkit` 等选择单一引擎。WebKit 是 Safari 引擎检查，上线前仍应在目标 macOS / iOS Safari 验证。完整的浏览器检查涵盖草稿隔离、裁剪缩放拒绝、应用、画笔、增强、压缩、下载、原图比较、撤销、颜色弹窗、配置接口禁用与移动布局。

## CI 和 tag 发布

`ci.yml` 在 Linux / Windows 验证 Python API 与通用处理逻辑，并在 Linux 实际构建镜像、运行 HTTP 检查和 Chromium、Firefox 和 WebKit 交互检查。Windows 客户端可直接用浏览器访问服务；Windows 上运行容器需要 Docker 的 Linux 容器模式。

推送合法 tag 后，`release.yml` 先检查源码，再构建并验证镜像，最后推送到 GitHub Container Registry：

- `ghcr.io/<owner>/<repo>:v1.2.3`
- `ghcr.io/<owner>/<repo>:sha-<commit前12位>`
- 稳定 tag 额外更新 `latest`，预发布 tag 不更新 `latest`。

```bash
git tag v1.2.3
git push origin v1.2.3
```

发布 job 使用内置 `GITHUB_TOKEN` 的 `packages: write` 权限。首次发布后的镜像可见性由仓库的 GitHub Packages 设置控制。手动触发仅构建并验证，不推送镜像。当前发布镜像针对 `linux/amd64`，不再生成 deb、Windows 安装器或便携桌面包。

## 历史桌面入口

Qt 界面与 `scripts/build.py`、`packaging/windows.iss` 保留供需要历史桌面版本的开发者使用。可选环境见 `requirements-desktop.txt`，启动入口为 `photocraft-desktop`，这些组件不进入 Web 的运行依赖和发布流程。
