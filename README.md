# AIResume · 叙职

**简体中文** | [English](README.en.md)

> 把做过的事，写得更清楚。

AIResume（叙职）是一款面向应届生与校招生的在线简历优化工具。上传已有简历、提供目标岗位描述后，你可以对照简历原文和岗位要求，逐条查看修改建议，补充真实经历，再整理成一份可继续编辑的 Word 简历。

项目围绕一次具体投递展开：从结构与阅读、经历表达、岗位相关三个维度检查简历，让每条建议都有可核对的依据。你可以采纳、跳过或调整措辞；需要补充信息时，先确认事实，再生成改写。最终采用哪些内容，由你决定。

[在线体验](https://key123456.online/app/) · [查看虚构示例](https://key123456.online/app/?demo=1) · [数据处理说明](https://key123456.online/privacy/)

当前界面和分析提示以中文为主。

## 主要功能

- **Word / PDF 读取**：支持 DOC、DOCX（含文本框）和可复制文字的 PDF，读取后展示简历内容，先核对再分析。
- **围绕目标岗位提出建议**：结合岗位描述检查简历，展示修改原因、简历原句和岗位要求。
- **逐条决定如何修改**：支持采纳、跳过、撤销选择和编辑建议；缺少经历细节时，可以补充真实信息后继续改写。
- **预览与 Word 导出**：将已采纳的修改整理为统一的简洁版式，预览后导出可编辑的 DOCX。
- **自选模型服务**：展示默认模型名称，支持内置第三方服务和自定义 API，可获取模型目录、保存多个模型并切换本次使用的模型。
- **免注册使用**：无需创建账号；提供不调用模型的虚构示例，方便先了解修改流程。
- **字号与小屏适配**：界面文字随用户字号设置缩放，标题和控件可换行；模型输入支持中文输入法确认操作。

## 使用流程

1. **准备材料**：上传 Word 或文字型 PDF，粘贴目标岗位的职责与要求。
2. **核对读取结果**：检查姓名、教育、项目和工作经历是否完整，确认后开始分析。
3. **逐条修改**：查看建议与依据，选择采纳、跳过或编辑，按需补充真实经历。
4. **预览并导出**：检查整理后的简历，确认后下载 Word 文档，并清除本次资料。

## 模型接入

在工作台右上角打开「模型设置」，可以选择默认模型、使用自己的 DeepSeek Key，或添加自定义 API 接入其他服务。添加时填写名称、API 地址和 Key，并获取或填写使用的模型；内部编号自动生成。通信协议位于「高级设置」，支持 OpenAI Chat Completions、OpenAI Responses 与 Anthropic Messages 三种协议。

每个浏览器最多长期保存 **3 组自定义 API**，支持编辑、删除和切换。同一 API 可保存多个模型，点击目录中的模型设为默认；使用时也可选择其他模型，或直接填写目录外的模型 ID。地址须为公网 HTTPS；模型目录不可用时，可以直接填写模型名称，或展开「手动添加模型」维护列表。配置与 Key 保存在当前浏览器，不跨浏览器或设备同步；调用时 Key 临时传递给后端，不写入服务端会话、文件或日志。

工作台和模型设置会显示默认模型的实际名称，普通使用界面不展示通信协议。站方可通过 `RESUME_LLM_PROTOCOL` 选择协议；前端不会获取站方的 Key 或接口地址。模型 ID 可能是服务商提供的别名，底层模型以服务商说明为准。

默认单次输出预算为 8192 token，站方可通过 `RESUME_LLM_OUTPUT_TOKENS` 调整；推理模型的思考过程也可能计入该预算。输出被截断时会明确提示，并保留原文供切换模型后重试。

对于明确支持推理强度的站方 OpenAI 兼容服务，可选配 `RESUME_LLM_REASONING_EFFORT=low`（或 `medium` / `high`）。此项默认不发送，也不会应用到用户自己的 API；模型响应时间可通过 `RESUME_LLM_TIMEOUT` 与 `RESUME_TASK_TIMEOUT` 按服务情况调整。

实际分析需要所选服务提供可用的接口、模型和访问权限。获取到模型目录不代表已获准生成；客户端限制、权限、额度和协议错误会明确提示。虚构示例无需配置 Key，也不会调用模型。

## 文件与数据处理

- 上传文件上限 **5 MB、8 页**；超过页数会明确提示精简。PDF 只读取文字层，暂不支持扫描件或图片型 PDF；复杂分栏、表格和浮动文本框需核对提取顺序。
- 导出采用统一模板，原文件的字体、图片和复杂排版不会原样保留。Word 页数以服务器 LibreOffice 的排版为准，可能与本机 Word 不同。
- 简历、岗位描述与修改状态仅在会话期间临时保存在服务端，并使用服务端密钥加密。默认空闲 2 小时或创建后 6 小时失效，以先到者为准。
- 可主动结束会话；导出响应完成后触发服务端材料清理。分析时会向所选模型服务发送简历文字、结构、岗位描述和必要的补充信息，具体处理规则见[数据处理说明](https://key123456.online/privacy/)。

## 技术栈

| 部分 | 技术 |
| --- | --- |
| 前端 | Astro、React、TypeScript、Tailwind CSS、Radix UI |
| 后端 | Python 3.12、FastAPI、Pydantic、HTTPX |
| 文档处理 | python-docx、pypdf、LibreOffice Writer |
| 会话与运行 | Redis、加密文件存储、nginx、systemd |

```text
web/       页面、简历工作台与模型设置
api/       API、模型调用、文档处理与测试
shared/    简历模板配置
deploy/    nginx、隔离读取服务与清理任务配置
scripts/   本地启动与浏览器验证脚本
```

## 本地运行

需要 Node.js 24、Python 3.12 和 uv。在仓库根目录安装依赖：

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

打开 [本地工作台](http://127.0.0.1:4321/app/)。站方模型配置参考 [api/.env.example](api/.env.example)，或直接在页面中配置自己的模型服务。无需调用模型时，可打开[本地虚构示例](http://127.0.0.1:4321/app/?demo=1)。

### 真实文件上传

真实上传需要 Linux 隔离读取与排版服务，Windows 本地可先查看虚构示例。服务部署步骤：

1. 安装 LibreOffice Writer 与 Noto CJK 字体，创建独立的 `airesume-render` 用户和组。
2. 安装 [socket](deploy/airesume-pagecheck.socket) 与 [service](deploy/airesume-pagecheck.service) 配置。默认代码路径为 `/opt/airesume`，SocketGroup 为 API 使用的 `airesume` 组。
3. 保持渲染用户与 API 用户隔离：渲染用户不要加入 API 组，API 配置与会话目录须禁止其他用户读取。
4. 启用 socket，并在目标机器验证真实上传及资源余量。

DOC 转换、Word 排版与 PDF 提取都在受限隔离进程中运行，限制单并发、384 MB 内存、无 swap、96 MB 临时内存盘和 30 秒任务时限。隔离服务缺失或校验失败时，系统不保存上传材料。

## 开发检查

在仓库根目录执行以下命令：

```powershell
cd api
uv run ruff check app tests
uv run pytest -q
cd ../web
npm run check
npm run build
```

浏览器流程验证脚本为 [scripts/browser_qa.py](scripts/browser_qa.py)，使用模拟模型与页数服务；真实隔离读取服务由 Ubuntu 集成测试验证。真实模型的可用性与生成效果需要结合所选服务单独验证。

前端实现参考 [Modern Web Guidance](https://github.com/GoogleChrome/modern-web-guidance)，按浏览器支持情况渐进增强排版、表单和无障碍体验。
