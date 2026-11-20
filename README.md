# 叙职 · AIResume

**对照目标岗位，逐条修改简历。** 面向应届生和校招生。查看每条建议对应的简历原文与岗位要求，确认修改符合自己的经历后，再导出可编辑的 Word 文件。

[用示例试一遍](https://key123456.online/app/?demo=1) · [修改我的简历](https://key123456.online/app/) · [English](README.en.md)

## 先试一条修改

1. 在示例工作台选择「让个人行动更容易被看见」。
2. 对照原句和岗位要求，勾选「确认改写符合我的经历」，再点击「采纳这条修改」。
3. 切到「简历预览」，在项目经历中查看改写后的校园二手交易项目描述。

示例使用虚构数据，无需注册、上传文件或配置模型。试完后，可用自己的简历和职位描述分析、修改并导出 DOCX。

## 文件与隐私

- **上传**支持 DOC、DOCX 和可选中文字的 PDF，每份最多 **5 MB、8 页**。扫描件需先转成带文字层的文件。
- **导出**采用统一版式。服务器发出 Word 文件后会自动清理本次会话，也可在工作台主动清除。
- **分析**会把简历内容和职位描述发送给当前选用的模型。可使用站方模型、DeepSeek Key 或公网 HTTPS 自定义 API，支持 OpenAI Chat Completions、OpenAI Responses 和 Anthropic Messages。自定义配置保存在当前浏览器。[数据处理说明](https://key123456.online/privacy/)

## 本地运行

用 Node.js 24 和 PowerShell 启动示例页面。

```powershell
git clone https://github.com/yiqi-7/AIResume.git
cd AIResume
npm --prefix web ci
.\scripts\dev.ps1 web
```

打开[本地示例](http://127.0.0.1:4321/app/?demo=1)，应看到「逐条修改」和「简历预览」。

需要 API 时，在另一个终端从仓库根目录运行以下命令。后端需要 Python 3.12 和 uv。

```powershell
cd api
uv sync --locked --group dev
cd ..
.\scripts\dev.ps1 api
```

[API 健康检查](http://127.0.0.1:8010/healthz)应返回 `{"status":"ok"}`。模型与本地配置见 [api/.env.example](api/.env.example)。

## 部署和开发

实际上传需要 Linux 上的独立文档处理服务，以及 LibreOffice Writer 和 Noto CJK 字体。生产环境使用 Redis。部署时保持文档处理用户与 API 用户隔离。配置参考 [生产环境变量](deploy/api.env.example)、[systemd 服务](deploy/airesume-pagecheck.service)和 [socket](deploy/airesume-pagecheck.socket)。

在 `web/` 运行 `npm run check` 和 `npm run build`。在 `api/` 运行 `uv run ruff check app tests` 和 `uv run pytest -q`。[完整验收流程](.github/workflows/checks.yml)

[反馈问题](https://github.com/yiqi-7/AIResume/issues)时请使用虚构简历，并提供复现步骤。仓库目前没有项目级许可证。随前端分发的字体遵循 [OFL](web/public/OFL.txt)。
