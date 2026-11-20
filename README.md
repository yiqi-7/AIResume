# 叙职 · AIResume

AIResume 是面向应届生和校招生的在线简历编辑工具：上传简历和目标岗位描述，对照原文逐条采纳、跳过或调整建议，最后导出可编辑的 Word 简历。界面和分析提示以中文为主。

[先用示例体验](https://key123456.online/app/?demo=1) · [English](README.en.md)

## 快速开始：完成一次修改

示例使用虚构简历，无需注册、上传材料或配置模型；可以验证修改与预览流程，不会调用模型，也不能导出文件。

1. 打开[示例工作台](https://key123456.online/app/?demo=1)，选择「让个人行动更容易被看见」。
2. 对照简历原句和岗位要求，勾选「确认改写符合我的经历」，点击「采纳这条修改」。
3. 切到「简历预览」，查看「校园二手交易平台」的项目经历。

**成功时**：项目描述会从「访谈同学并整理需求……」改为「围绕校园二手交易场景，访谈同学并整理需求……」。

## 继续使用自己的简历

准备 DOC、DOCX 或可选中文字的 PDF，每份最多 **5 MB、8 页**。扫描件需先转成带文字层的文件。实际分析需要可用的模型服务，可使用站方模型，或在工作台右上角配置自己的 DeepSeek Key、自定义 API。

打开[在线工作台](https://key123456.online/app/)，上传简历并粘贴职位描述。先核对读取结果，再开始分析；确认建议符合自己的经历后，预览并导出 DOCX。

- **导出采用统一版式**，不会保留原文件的图片和复杂排版。服务器发出 Word 文件后会清理本次会话，请先完成修改；也可主动清除资料。
- **分析会向所选模型发送简历与职位描述**。自定义 API 配置和 Key 保存在当前浏览器，调用时经本站转发。使用前查看[数据处理说明](https://key123456.online/privacy/)。

## 开发与部署（可选）

<details>
<summary>本地启动、检查与生产配置</summary>

### 只运行示例

需要 Node.js 24（含 npm）、Git 和 PowerShell。从新终端运行：

```powershell
git clone https://github.com/yiqi-7/AIResume.git
cd AIResume
npm --prefix web ci
.\scripts\dev.ps1 web
```

打开[本地示例](http://127.0.0.1:4321/app/?demo=1)，按上面的修改步骤确认预览结果。示例不依赖后端。

### 启动 API

另外需要 Python 3.12 和 uv。在另一个终端，从仓库根目录运行：

```powershell
cd api
uv sync --locked --group dev
cd ..
.\scripts\dev.ps1 api
```

[健康检查](http://127.0.0.1:8010/healthz)应返回 `{"status":"ok"}`。开发与模型配置见 [api/.env.example](api/.env.example)。

实际上传还需要 Linux 上的独立文档处理服务、LibreOffice Writer 和 Noto CJK 字体；仅启动 API 不足以处理真实文件。生产环境使用 Redis，并将文档处理用户与 API 用户隔离。部署参考[环境变量](deploy/api.env.example)、[文档处理服务](deploy/airesume-pagecheck.service)及其 [socket](deploy/airesume-pagecheck.socket)。

### 运行检查

在 `web/` 运行 `npm run check` 和 `npm run build`；在 `api/` 运行 `uv run ruff check app tests` 和 `uv run pytest -q`。完整步骤与 Linux 集成环境见[验收工作流](.github/workflows/checks.yml)。

</details>

[反馈问题](https://github.com/yiqi-7/AIResume/issues)时请使用虚构简历，并附上复现步骤。仓库尚无项目级许可证；随前端分发的字体遵循 [OFL](web/public/OFL.txt)。
