# ReadDraw

ReadDraw 是一个使用 Python + Flet 开发的本地 PDF / EPUB 阅读与绘画批注工具。

## 功能

- 导入并管理本地 PDF / EPUB
- 通过“打开文件”按钮导入 PDF / EPUB
- 记录每本书的阅读页码
- 画笔、颜色、线条粗细、橡皮擦、撤销和恢复
- 半透明荧光笔和文字批注，按书籍与页码保存；荧光笔支持颜色、粗细、撤销、橡皮擦和 PNG 导出
- 插入图片附件并合成到页面导出图
- 鼠标模式下可拖动已插入图片；按住 Alt + 鼠标滚轮可以放大或缩小页面
- 画笔使用实时矢量图层，拖动时立即显示笔迹和笔刷位置
- 可通过侧边栏“设置”更换阅读背景，并迁移 SQLite、附件和导出文件
- 启动 FastAPI 局域网同步服务，默认 `8765` 端口
- SQLite 本地保存，支持当前页 PNG 导出

## 运行

### v0.0.6 图片拖动修复

- 图片拖动按鼠标在窗口中的绝对位置计算，避免局部坐标随图片移动而造成回跳。
- 显示保留亚像素精度，松开鼠标后保存最终位置；拖动时不反复写入数据库。
- `python tools/verify_attachment_drag.py` 会在隔离的 Windows 测试窗口中模拟连续和反向拖动，将事件记录与截图保存到 `.build-deps/attachment-drag-verification`，不访问个人书库。

```powershell
python -m pip install -r requirements.txt
python main.py
```

数据默认保存到 Windows 的 `%APPDATA%\ReadDraw`。可以在侧边栏点击“设置”，在设置面板中更换阅读背景或选择一个空文件夹迁移数据。程序会先复制数据库和附件并校验后切换；原目录不会删除。背景有浅灰、暖白、浅蓝、深灰四种，保存后重启仍生效。默认目录不可写时，开发环境会回退到项目下的 `.readdraw-data`，打包程序会回退到 exe 同级的 `.readdraw-data`。设置和运行日志保留在默认目录，其中运行日志是 `logs\ReadDraw.log`，本机组件崩溃日志是 `logs\native-crash.log`。

## 代码结构

- `main.py`：Flet 页面和交互事件编排
- `readdraw/config.py`：应用目录与渲染配置
- `readdraw/models.py`：书籍、文字标注和附件模型
- `readdraw/storage.py`：SQLite、本地附件和同步快照
- `readdraw/pdf.py`：PDF 打开和页面渲染
- `readdraw/epub.py`：EPUB 文本解析和分页渲染
- `readdraw/reader.py`：PDF / EPUB 统一阅读器接口
- `readdraw/drawing.py`：笔迹、图片合成和导出
- `readdraw/canvas_view.py`：页面图片、实时笔迹和手势图层
- `readdraw/desktop_view.py`：桌面版阅读布局和工具栏
- `readdraw/settings_view.py`：阅读背景和数据位置设置面板
- `readdraw/data_location.py`：数据迁移与附件路径重写
- `readdraw/sync_server.py`：FastAPI 局域网同步接口
- `tests/test_core.py`：核心服务测试
- `tests/test_app.py`：模拟 Flet 会话的打开文件、设置与数据迁移回归测试

## 同步接口

启动桌面端工具栏的局域网按钮后，同一局域网设备可以访问：

- `GET http://电脑IP:8765/health`
- `GET http://电脑IP:8765/api/snapshot`
- `POST http://电脑IP:8765/api/snapshot`

快照包含书籍、阅读进度、绘画笔迹、文字标注和图片附件。当前版本采用整包快照，后续可继续加入增量同步和冲突合并。

## Windows 打包

```powershell
.\build_windows.ps1 -Version v0.0.6
```

脚本会生成 `dist\ReadDraw.exe`，并在 `release` 目录生成带版本号的 exe、SHA256 校验文件和 `update.json`。如果希望生成便于分发的文件夹版本：

Windows 版暂时停用资源管理器拖入功能，避免向 Flet 原生窗口注入 DLL 引发崩溃；请使用“打开文件”按钮导入文档。

如果系统安装了 NSIS，脚本还会生成 `release\ReadDraw-Setup-v0.0.6.exe` 安装包。安装包会创建桌面快捷方式，并将程序安装到当前用户目录，不需要管理员权限。

桌面包排除了可选的 `pymupdf.layout` / ONNX 布局分析组件，PDF 显示和文字搜索使用 MuPDF。这样可以避免不必要的模型加载和相关本机组件启动崩溃。

```powershell
.\build_windows.ps1 -Version v0.0.6 -OneDir
```

## 远程更新发布

推送 `v0.0.6` 形式的 tag 后，GitHub Actions 会在 Windows runner 上构建桌面程序，并自动创建 GitHub Release，上传 exe、SHA256 和 `update.json`。桌面端点击“检查更新”会读取仓库的最新 Release；发现新版本后，在打包运行模式下可下载 exe、替换当前程序并重启。

```powershell
git add .
git commit -m "Prepare ReadDraw v0.0.6"
git push origin main
git tag v0.0.6
git push origin v0.0.6
```

GitHub Actions 文件位于 `.github/workflows/release.yml`。源码运行时只支持检查版本，不会替换 Python 环境。
