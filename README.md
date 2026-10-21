# ReadDraw

ReadDraw 是一个使用 Python + Flet 开发的本地 PDF / EPUB 阅读与绘画批注工具。

## 功能

- 导入并管理本地 PDF / EPUB
- 记录每本书的阅读页码
- 画笔、颜色、线条粗细、橡皮擦、撤销和恢复
- 文字高亮和文字批注，按书籍与页码保存
- 插入图片附件并合成到页面导出图
- 启动 FastAPI 局域网同步服务，默认 `8765` 端口
- SQLite 本地保存，支持当前页 PNG 导出

## 运行

```powershell
python -m pip install -r requirements.txt
python main.py
```

数据默认保存到 Windows 的 `%APPDATA%\ReadDraw`。如果该目录不可写，开发环境会回退到项目下的 `.readdraw-data`。

## 代码结构

- `main.py`：Flet 页面和交互事件编排
- `readdraw/config.py`：应用目录与渲染配置
- `readdraw/models.py`：书籍、文字标注和附件模型
- `readdraw/storage.py`：SQLite、本地附件和同步快照
- `readdraw/pdf.py`：PDF 打开和页面渲染
- `readdraw/epub.py`：EPUB 文本解析和分页渲染
- `readdraw/reader.py`：PDF / EPUB 统一阅读器接口
- `readdraw/drawing.py`：笔迹、图片合成和导出
- `readdraw/sync_server.py`：FastAPI 局域网同步接口
- `tests/test_core.py`：核心服务测试

## 同步接口

启动桌面端工具栏的局域网按钮后，同一局域网设备可以访问：

- `GET http://电脑IP:8765/health`
- `GET http://电脑IP:8765/api/snapshot`
- `POST http://电脑IP:8765/api/snapshot`

快照包含书籍、阅读进度、绘画笔迹、文字标注和图片附件。当前版本采用整包快照，后续可继续加入增量同步和冲突合并。

## Windows 打包

```powershell
.\build_windows.ps1 -Version v0.0.0
```

脚本会生成 `dist\ReadDraw.exe`，并在 `release` 目录生成带版本号的 exe、SHA256 校验文件和 `update.json`。如果希望生成便于分发的文件夹版本：

```powershell
.\build_windows.ps1 -Version v0.0.0 -OneDir
```

## 远程更新发布

推送 `v0.0.0` 形式的 tag 后，GitHub Actions 会在 Windows runner 上构建桌面程序，并自动创建 GitHub Release，上传 exe、SHA256 和 `update.json`。桌面端点击“检查更新”会读取仓库的最新 Release；发现新版本后，在打包运行模式下可下载 exe、替换当前程序并重启。

```powershell
git add .
git commit -m "Prepare ReadDraw v0.0.0"
git push origin main
git tag v0.0.0
git push origin v0.0.0
```

GitHub Actions 文件位于 `.github/workflows/release.yml`。源码运行时只支持检查版本，不会替换 Python 环境。
