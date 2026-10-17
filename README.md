# PhotoCraft Web

一个可自行部署的图片工作台。浏览器负责交互，Python 服务负责完整分辨率的图像处理，网页与后端一起打包为 Docker 镜像。

![PhotoCraft Web 工作台](docs/screenshots/web/workspace.png)

图片只发送至你连接的 PhotoCraft 服务，不调用第三方图片处理服务。本机部署时图片不离开本机；部署到服务器后，图片会上传至该服务器。网页不依赖 CDN，服务运行后无需连接外网。

## 启动

安装 Docker 与 Docker Compose，在项目目录运行：

```bash
docker compose build --build-arg VCS_REF="$(git rev-parse HEAD)"
docker compose up -d
```

打开 **http://localhost:8000**。默认只监听本机，网页、接口与图片下载使用同一个地址，无需单独启动前端或安装 Node.js、Qt。

```bash
docker compose logs -f
docker compose down
```

配置保存在命名卷 `photocraft-config`，正常停止或重建不会清除。照片、预览和撤销记录仅保留在服务内存中；刷新页面或重启服务后，需要重新打开图片。

也可以用构建脚本自动带入当前 Git commit、tag 与工作区状态：

```bash
python scripts/build_image.py --tag photocraft:local
docker compose up -d --no-build
```

镜像构建和运行方式见 [部署说明](docs/RELEASING.md)。

## 使用

1. 点击欢迎页选择图片，或将一张图片拖入页面。`Ctrl+O` 也可打开，支持 JPG、PNG、WEBP、BMP、TIFF。
2. 在左侧选择工具。裁剪、背景色、旋转、水印和压缩会先生成预览，点击上方统一的「应用」后才进入当前结果。图片增强调整即应用，画笔松开即应用。
3. 底部「预览」展示当前草稿的实测信息；「当前」展示已应用、可保存的结果。所有工具的预览信息都集中在这里。
4. 点击「保存图片」或按 `Ctrl+S`，下载当前结果。**未应用的预览不会被保存。** 保存复用服务端已经编码的字节，不重新执行已经应用的图像操作。
5. 使用 `Ctrl+Z` 撤销、`Ctrl+Shift+Z` 重做。滚轮缩放，空格拖动平移，`Ctrl+0` 适应窗口。按住「查看原图」完整显示原图，松开恢复之前的视图。

顶部「帮助」提供使用说明和快捷键对照；macOS 使用 ⌘ Command 替代 Ctrl。

## 功能

| 功能 | 行为 |
| --- | --- |
| 裁剪 | 常用证件照模板、自由裁剪、自定义比例；按比例默认 16:9。自由裁剪的像素输入与画布联动。 |
| 模板 | 使用管理员预设的裁剪规格；网页不提供新增或修改模板。 |
| 缩放控制 | 默认不允许缩放，模板取景框保持指定像素大小、只能移动。像素不足时应用会报错；勾选后才允许缩放。放大可能模糊，缩小会损失细节。 |
| 背景色 | 为透明和半透明区域填色，不自动抠图。完全不透明的照片会明确提示，可先用橡皮擦擦除背景。 |
| 旋转翻转 | 90°旋转、任意角度、水平和垂直翻转，可扩展画布。 |
| 画笔与局部处理 | 绘制、透明擦除、马赛克、局部模糊；画笔大小 1–100 px，参数使用滑块。 |
| 文字水印 | 整页倾斜重复平铺；字体来自服务端，镜像内置中文字体。统一颜色面板提供 16 种预定义颜色、十六进制色值和 RGB 滑块；支持不透明度、角度、行列间距和实时预览。最多 50 字，默认替换已有水印，可选叠加，最多 10 组。 |
| 图片增强 | 亮度、对比度、饱和度、锐度、色温、伽马、降噪与明暗均衡；自动对比度和白平衡与对应手动项互斥。一段连续滑动合并为一次撤销。 |
| 图像压缩 | JPEG、PNG、WEBP、BMP、TIFF；仅调整格式、画质、透明和元数据设置，不更改图片尺寸，不限制或搜索目标文件体积。 |

JPEG / WEBP 的画质会影响文件体积与细节，质量 100 仍然使用有损编码。PNG、BMP、TIFF 使用无损编码；不支持透明的格式会填充背景色，并在信息中标明透明信息损失。未修改的图片直接下载原文件字节，避免隐式重新编码。

预览显示图最长边限制为 1600 px，下载仍使用完整分辨率。连续调整会合并请求，过期预览不会覆盖新状态；应用时复用有效预览的完整结果。每张照片拥有独立会话，不同浏览器页面的图像和撤销记录互不混用。

更多界面：[欢迎页](docs/screenshots/web/welcome.png) · [裁剪](docs/screenshots/web/crop.png) · [文字水印](docs/screenshots/web/watermark.png) · [深色主题](docs/screenshots/web/dark.png) · [手机布局](docs/screenshots/web/mobile.png) · [颜色面板](docs/screenshots/web/colors.png)。

## 浏览器与通信

面向当前 Chrome、Firefox 与 Safari。CI 使用 Chromium、Firefox、WebKit 三种引擎验证打开、预览、颜色选择、编辑、下载及手机布局。WebKit 自动化是 Safari 引擎的回归检查，不等于 macOS / iOS Safari 实机测试；上线前应在目标设备补验。

前后端使用同源 HTTP API，通过 JSON 传递操作、HTTP 传输图片，不使用 WebSocket。反向代理启用 HTTPS 后，浏览器与服务之间使用 HTTPS。每次预览请求返回处理完成的实测结果；滑动调整会防抖并合并待处理请求。

服务会保留完整分辨率的当前结果、最多 2 个预览和有预算的撤销历史，以便应用与保存复用，不能在每次请求结束后清空。应用或撤销后清除旧预览；会话默认闲置 1 小时过期，每分钟定期回收，并在请求时检查。正常离开页面会尽力通知服务释放；浏览器崩溃、断网等情况由过期回收兜底。详细限制见 [配置说明](docs/CONFIGURATION.md)。

## 配置

云端页面不提供菜单、配置管理或新增模板，也没有对应的配置读取和修改 HTTP 接口。部署管理员可编辑容器持久卷内的 `/data/PhotoCraft.conf`（UTF-8 TOML），重启服务后生效。预设模板、默认颜色等由服务共享；图片编辑参数仅影响各自会话，主题可在浏览器单独切换。

源码运行可通过 `PHOTOCRAFT_CONFIG_DIR` 指定目录；未指定时，Linux 使用 `~/.config/PhotoCraft`，Windows 使用 `%APPDATA%\PhotoCraft`。示例见 [examples/PhotoCraft.conf](examples/PhotoCraft.conf)，详情见 [配置说明](docs/CONFIGURATION.md)。

## 源码运行

需要 Python 3.12+：

```bash
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell：.venv\Scripts\Activate.ps1
python -m pip install -r requirements-lock.txt
python -m pip install --no-deps -e .
python -m photocraft --host 127.0.0.1 --port 8000
```

源码运行时从服务所在系统读取字体；Linux 可安装 `fontconfig` 与 `fonts-noto-cjk` 获得中文水印字体，Docker 镜像已包含。前端是随包分发的 HTML、CSS、JavaScript，不需要 npm 构建。

## 运行边界

- 这是单个可信工作台服务，不提供账号、多人协作或项目文件保存。对外部署时应在反向代理设置 HTTPS 与访问控制；默认 Compose 端口仅对本机开放。
- 默认最多同时保留 4 个会话；单张图片上限 40 MB、2400 万像素。闲置会话 1 小时过期，后台定期释放。单个会话的撤销缓存有内存预算。
- 图片重启后不保留；配置卷保留。服务没有将用户照片保存到持久卷，上传解析产生的临时文件会及时删除。
- 保存位置、下载文件名确认和覆盖行为由浏览器处理，网页不会直接改写用户的原文件。
- 没有自动人像分割、AI 超分或 AI 去噪；多帧 TIFF / 动图只处理第一帧。
- 旧 Qt 界面和原生打包脚本保留为可选的历史入口，不属于 Web 镜像依赖；当前 CI 和 tag 发布以 Web 服务与镜像为主，不再发布 deb / Windows 安装器。

项目许可见 [LICENSE](LICENSE)，依赖与字体说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
