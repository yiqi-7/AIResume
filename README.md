# AIResume · 叙职

上传 Word（DOC / DOCX，含文本框）或可复制文字的 PDF 与目标岗位描述，核对建议、编辑简历并导出 Word 文档。

模型设置支持内置服务和自定义 API。每个浏览器最多长期保存 3 组自定义配置，可编辑、删除、切换，支持 OpenAI Chat Completions / Responses 协议、获取模型目录与手动填写模型 ID。自定义地址须为公网 HTTPS；Key 保存在当前浏览器，调用时临时传递给后端，不写入服务端会话、文件或日志。免注册版本按浏览器限制数量，不跨设备同步。

需要 Node.js 24、Python 3.12 和 uv。

```powershell
cd web
npm ci
cd ../api
uv sync --group dev
```

在仓库根目录的两个终端分别运行：

```powershell
./scripts/dev.ps1 api
./scripts/dev.ps1 web
```

打开 `http://127.0.0.1:4321`。模型配置参考 `api/.env.example`，或在页面内设置自己的 Key；未配置时可查看虚构示例。

真实上传还需要 Linux 隔离排版服务：安装 LibreOffice Writer、Noto CJK 字体，创建独立 `airesume-render` 用户/组，使用 `deploy/airesume-pagecheck.socket` 与 `.service`（默认代码路径 `/opt/airesume`，SocketGroup 为 API 的 `airesume` 组）。渲染用户不要加入 API 组；API 配置与会话须禁止其他用户读取。安装两个 unit 后启用 socket。服务限制单并发、384 MB 内存、无 swap、96 MB 临时内存盘和 30 秒任务时限；生产发布前需验证目标机器资源余量。

Word 页数以服务器 LibreOffice 的完整排版为准，可能与本机 Word 不同；PDF 读取原文件页数与文字层，不支持扫描件或图片型 PDF。两者均上限 8 页、5 MB。旧版 DOC 转换及 PDF 提取在同一受限隔离进程中运行。隔离服务缺失或校验失败时不保存上传。Windows 本地可查看虚构示例；浏览器 QA 使用模拟页数服务，真实隔离服务由 Ubuntu 集成测试验证。

```powershell
cd api
uv run ruff check app tests
uv run pytest -q
cd ../web
npm run check
npm run build
```
