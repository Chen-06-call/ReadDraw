# ReadDraw

ReadDraw 是一个使用 Python + Flet 开发的本地 PDF / EPUB 阅读与绘画批注工具。

## 功能

- 导入并管理本地 PDF / EPUB
- 通过“打开文件”按钮导入 PDF / EPUB
- 记录每本书的阅读页码
- 点击页码旁的书签图标添加 / 删除当前页书签；右侧书签目录按页码排列，点击即可跳页，重启后保留
- 画笔、颜色、线条粗细、橡皮擦、撤销和恢复；可一键清除本页笔迹并撤销恢复
- 半透明荧光笔和文字批注，按书籍与页码保存；荧光笔支持颜色、粗细、撤销、橡皮擦和 PNG 导出
- 插入图片附件并合成到页面导出图；选中图片后可拖动、等比例缩放或删除
- 按住 Alt + 鼠标滚轮可以放大或缩小阅读页面
- 画笔使用实时矢量图层，拖动时立即显示笔迹和笔刷位置
- 支持压感设备：压力越大笔迹越粗；普通鼠标按移动速度模拟压感，慢画偏粗、快画偏细
- 可通过侧边栏“设置”更换阅读背景，并迁移 SQLite、附件和导出文件
- 启动 FastAPI 局域网同步服务，默认 `8765` 端口
- SQLite 本地保存，支持当前页 PNG 导出

## 运行

### v0.1.3 清除本页笔迹与滚轮修复

- 工具栏新增“清除本页笔迹”，清除后可通过撤销恢复；文字批注和图片附件不受影响。
- 滚轮监听移至阅读区域外层；后续版本进一步避免翻页时整页刷新。

### v0.1.4 页面导航与滚轮焦点修复

- 增加回到首页和去到末尾页按钮，切换绘画工具时以阴影标出当前选项。
- 缩放后翻页改为局部更新书页和导航控件，保持滚轮监听持续挂载。

### v0.1.5 常用形状批注

- 工具栏“形状”按钮可选择直线、波浪线、圆形、方框、箭头、三角形和菱形；按住鼠标拖动绘制，过程实时预览。
- 形状按普通笔迹保存，支持现有撤销、橡皮擦和 PNG 导出。

### v0.1.8 页面书签

- 工具栏书签图标切换当前页的收藏状态，未打开书籍时禁用。
- 右侧新增可滚动书签目录，按页码排列并突出当前页，点击书签保存笔迹后跳转。
- 书签保存到本地 SQLite，包含在数据迁移和同步快照中；同步删除标记可防止旧快照恢复已删书签。
- 展示控件封装在 `readdraw/bookmark_view.py`，存储和业务逻辑分开，新增部分使用中文注释。

### v0.1.7 形状绘制优化

- 三角形可根据拖动方向绘制正三角形或倒三角形。
- 方框与正方形合并为同一工具；按住 Ctrl 绘制正方形。圆形工具不按 Ctrl 绘制椭圆，按住 Ctrl 绘制正圆。
- 形状按钮改为下拉菜单，状态提示说明 Ctrl 约束和三角形方向。

### v0.1.6 形状几何修复

- 修复连续拖动时形状起点漂移；圆形与正方形保持等宽等高，并区分方框和正方形。

### v0.1.2 连续绘画与滚轮修复

- 修复手势事件没有等待异步笔迹回调、拖动画线时只留下起笔点的问题。
- 缩放和翻页时减少重复整页刷新，避免滚轮处理后丢失鼠标响应。

### v0.1.1 鼠标模拟压感

- 鼠标绘画按移动速度模拟压力，慢画逐渐加粗、快画逐渐变细，并平滑线宽变化。
- 压感笔仍优先使用设备提供的真实压力数据；两种压力值都会随笔迹保存并用于 PNG 导出。

### v0.1.0 画笔压感

- 接入 Flet 压感事件，压感设备绘制时会实时调整笔迹粗细。
- 压感值会随笔迹保存，撤销、重开书籍和 PNG 导出保持一致。
- 普通鼠标和不提供压力数据的设备继续使用固定粗细，不影响原有绘画。

### v0.0.14 翻页与放大拖动

- 阅读区滚轮覆盖书页和图片附件区域；每次滚动按当前页方向翻一页。
- 鼠标工具下放大页面可按住左键拖动，页面边缘不会露出空白；光标会显示抓取状态。
- 滚轮或左右箭头翻页后恢复适合窗口的比例与居中位置。
- `python -m unittest discover -s tests` 覆盖上述翻页、缩放和页面拖动行为。

### v0.0.13 桌面布局自适应修复

- 桌面窗口启动时最大化，并降低最小尺寸限制，适配不同分辨率和 Windows 缩放比例。
- 根布局直接挂载到页面，避免键盘监听控件改变 Flet 的窗口布局约束。
- Windows 在滚轮事件发生时读取 Alt 即时状态，松开后恢复普通翻页。
- `python tools/verify_desktop_layout.py` 使用独立测试书库，检查最大化与还原窗口的实际阅读区尺寸并保存截图。

### v0.0.11 滚轮与键盘翻页

- 普通鼠标滚轮向下进入下一页、向上返回上一页，和当前工具无关。
- 按住 `Alt` 加鼠标滚轮缩放书页，画笔、荧光笔、橡皮擦和鼠标模式都可使用。
- 阅读区任意位置（包括插入图片上）都能用滚轮翻页；鼠标工具下放大页面可按住左键拖动，翻页后恢复适合窗口。
- 键盘 `左箭头` / `右箭头` 翻页。

### v0.0.10 图片角点拖拽缩放

- 选中插入图片后，拖动右下角手柄即可按比例调整大小，松开鼠标后保存。
- 图片工具条保留删除操作，移除加减缩放按钮。
- 安装程序、免安装主程序、SHA-256 校验文件和更新清单沿用固定文件名。

### v0.0.9 图片编辑与发布文件整理

- 选中插入图片后可拖动、等比例放大缩小或删除；尺寸会保存并用于 PNG 导出。
- 发布文件固定命名为 `ReadDraw-Setup.exe`、`ReadDraw.exe` 和 `ReadDraw.exe.sha256`；每次成功构建后清除旧的版本号命名文件。

### v0.0.8 图片插入与发布修复

- Windows 图片选择框在独立的辅助进程运行，避免文件选择插件或外壳扩展异常带走主程序；关闭应用时会结束未完成的选择。
- 图片完整解码、修正照片方向并转为标准 PNG 后再保存。取消、损坏图片和选择窗口异常会在状态栏反馈。
- 插入图片仅更新附件图层，保留当前书页、笔迹和撤销记录。
- 图片选中后会显示独立工具条，可等比例放大、缩小或删除；尺寸与删除结果同步保存。
- GitHub Actions 显式安装 `requirements-build.txt`，包含 Flet CLI、桌面运行时和 PyInstaller，不依赖开发电脑上已有的包。
- `python tools/verify_image_insert.py` 打开隔离书库，供实际操作系统选择框验证；加 `--pick-now` 自动调用工具栏的同一插入回调。记录和截图在 `.build-deps/image-insert-verification`。

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
- `readdraw/file_dialogs.py`：系统图片选择窗口及独立辅助进程生命周期
- `readdraw/image_import.py`：图片附件校验与标准 PNG 编码
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
python -m pip install -r requirements-build.txt
.\build_windows.ps1 -Version v0.1.8
```

脚本会生成 `dist\ReadDraw.exe`，并在 `release` 目录生成固定名称的 `ReadDraw.exe`、`ReadDraw.exe.sha256` 和 `update.json`。每次成功构建后会清理旧的版本号命名产物，避免误上传过期文件。如果希望生成便于分发的文件夹版本：

Windows 版暂时停用资源管理器拖入功能，避免向 Flet 原生窗口注入 DLL 引发崩溃；请使用“打开文件”按钮导入文档。

如果系统安装了 NSIS，脚本还会生成固定名称 `release\ReadDraw-Setup.exe` 安装包。安装包会创建桌面快捷方式，并将程序安装到当前用户目录，不需要管理员权限。发布构建使用 `-RequireInstaller`，NSIS 缺失时会明确报错。脚本保留 UTF-8 BOM，以兼容 Windows PowerShell 5.1 中的中文注释。

桌面包排除了可选的 `pymupdf.layout` / ONNX 布局分析组件，PDF 显示和文字搜索使用 MuPDF。这样可以避免不必要的模型加载和相关本机组件启动崩溃。

```powershell
.\build_windows.ps1 -Version v0.1.8 -OneDir
```

## 远程更新发布

推送 `v0.1.8` 形式的 tag 后，GitHub Actions 会在 Windows runner 上构建桌面程序，并自动创建 GitHub Release，上传 exe、SHA256 和 `update.json`。标签版本须与 `readdraw/version.py` 的默认版本一致，否则构建会拒绝发布。桌面端点击“检查更新”会读取仓库的最新 Release；发现新版本后，在打包运行模式下可下载 exe、替换当前程序并重启。

```powershell
git add .
git commit -m "Prepare ReadDraw v0.1.8"
git push origin main
git tag v0.1.8
git push origin v0.1.8
```

GitHub Actions 文件位于 `.github/workflows/release.yml`。源码运行时只支持检查版本，不会替换 Python 环境。

也可以先把本次修改推送到默认分支，再在 GitHub 网页打开 **Actions → Build and release ReadDraw → Run workflow**，选择包含修复的分支，版本填写 `v0.1.8`。重跑旧标签的失败任务仍然使用旧提交，不会自动包含新的依赖修复。

如需手动在 Release 中上传，请使用本次构建产生的以下四个文件，发布标签填写对应版本（本次为 `v0.1.8`）：

- `release/ReadDraw-Setup.exe`：安装包，供首次安装。
- `release/ReadDraw.exe`：主程序，供免安装运行与自动更新。
- `release/ReadDraw.exe.sha256`：主程序校验文件。
- `release/update.json`：版本及 SHA256 清单，必须与同次构建的主程序配套。
