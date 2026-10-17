# 构建和发布

## 本地构建

使用 Python 3.12+ 与 `requirements-lock.txt` 中的已验证版本。分别在 Linux 和 Windows 本机运行，不使用交叉编译。

```bash
python -m pip install -r requirements-lock.txt
python -m pip install --no-deps -e .
python -m pytest -q
python scripts/build.py
python scripts/smoke_bundle.py
```

仅重建本地可执行程序、暂不生成安装包时，运行 `python scripts/build.py --freeze-only`。
它会更新 `dist/PhotoCraft/PhotoCraft`（Windows 为 `PhotoCraft.exe`），无 Git 信息时显示「未标记源码」。
构建后需退出正在运行的旧程序，再启动该路径；已安装到系统目录的副本不会自动更新。

Linux 上需 `dpkg-deb`；Debian/Ubuntu 的 Qt 平台运行库：

```bash
sudo apt install libgl1 libegl1 libopengl0 libxkbcommon0 libxkbcommon-x11-0 \
  libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
  libxcb-render-util0 libxcb-shape0 libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1 \
  libdbus-1-3 libfontconfig1 libglib2.0-0 fonts-noto-cjk
```

Windows 上安装 Inno Setup 6，脚本会从 PATH 或默认安装位置寻找 `ISCC.exe`。

构建脚本自动从 Git 获取版本，无需填写版本号：

- 当前 HEAD 恰好对应 `vMAJOR.MINOR.PATCH`（可含 alpha / beta / rc）且工作区干净时，应用与安装包使用该 tag。
- 其他提交使用 12 位 commit 哈希；有未提交改动时附加 `-dirty`，不会冒充已发布的 tag。
- Python 包版本、Debian 版本、Windows 数字版本按各平台格式从同一 Git 身份生成；数字字段仅用于安装器兼容。
- 构建期间自动生成并打包 `assets/build-info.json`，结束后恢复源码目录；安装后的应用无需 Git。`--skip-freeze` 会核对现有程序的身份，拒绝混用其他提交的冻结程序。
- 无 Git 元数据且无有效构建记录的源码可运行，显示「未标记源码」，构建脚本会拒绝生成虚假版本。

由 SVG 生成多尺寸 PNG / ICO，使用 PyInstaller 冻结，再制作本机安装包。以下以 tag `v1.2.3` 为例；普通提交的名称会用 commit 哈希代替 tag：

| 平台 | 输出 |
| --- | --- |
| Linux x86_64 | `PhotoCraft-v1.2.3-linux-amd64.deb` |
| Linux x86_64 | `PhotoCraft-v1.2.3-linux-amd64.tar.gz` |
| Windows x64 | `PhotoCraft-v1.2.3-windows-x64-setup.exe` |
| Windows x64 | `PhotoCraft-v1.2.3-windows-x64-portable.zip` |
| 各平台 | `SHA256SUMS-linux.txt` / `SHA256SUMS-windows.txt` |

产物位于 `artifacts/`。安装包自带 Python 和依赖，终端用户无需安装 Python。
Linux `.deb` 安装到 `/opt/photocraft`，注册桌面启动项、MIME 类型和 hicolor 图标；`photocraft` 命令也可直接启动。
Windows 为当前用户安装，无需管理员权限，创建开始菜单入口并可选桌面快捷方式；EXE、任务栏与卸载入口使用同一 Logo。

## Git tag 发布

1. 在有写权限的真实 Git 仓库中提交源码、锁定依赖和工作流，并关联 GitHub remote。
2. 确认普通 CI 在 Linux / Windows 均通过。
3. 推送 `vMAJOR.MINOR.PATCH` 或 `vMAJOR.MINOR.PATCH-rc.N` / `-beta.N` / `-alpha.N`。
4. `release.yml` 的双平台任务测试源码、生成本机包，并启动冻结后的 GUI，执行「演示图 → 证件照裁剪 → 编码 → 保存 → 重新解码」冒烟验证。
5. 两个平台全部成功后才创建 GitHub Release；预发布 tag 标记为 prerelease。只在发布 job 开放 `contents: write`。

```bash
git tag v1.2.3
git push origin v1.2.3
```

手动运行 `workflow_dispatch` 自动使用所选分支 / 提交的 Git 身份，只上传 Actions artifacts，不创建 Release。失败的版本可删除失败的 Release 后重新运行；脚本不会覆写已有远程 Release。
GitHub 仓库需允许 Actions 运行及发布 job 使用内置 `GITHUB_TOKEN` 写入 Releases。

## 验证安装

Linux：`sudo apt install ./artifacts/PhotoCraft-v1.2.3-linux-amd64.deb`，随后从应用菜单或命令行打开，检查任务栏 Logo 和导出。
Windows：运行 setup EXE，检查开始菜单/桌面快捷方式和任务栏图标，打开一张中文路径图片并导出到中文目录；再从「已安装的应用」卸载。

当前自动测试使用 offscreen Qt，不能替代真实桌面上的鼠标手感、系统文件选择器、任务栏分组、Windows 安装/卸载验证。工作目录若不是 Ubuntu 22.04，构建出的 Linux 包可能要求更高 glibc；正式 Linux 发布应使用工作流锁定的 Ubuntu 22.04 runner。
Windows 代码签名未配置。Android 未纳入构建矩阵。
