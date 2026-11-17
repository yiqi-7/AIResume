# AIResume

面向应届生和校招生的简历编辑工具。上传 DOCX、粘贴目标岗位 JD，查看引用依据、逐条核对和编辑建议，最后预览并下载可继续编辑的 Word 文档。

## 当前状态

本仓库包含可本地运行的 MVP。开发模式明确使用进程内元数据，不连接云模型前端无法产生站方分析；可在模型设置中填写用户自己的 DeepSeek、通义千问或智谱 Key，或者先查看不调用模型的虚构示例。测试模型只存在于测试/本地 QA fixture，生产服务不会自动使用它。

产品域名规划为 `key123456.online`。当前实现不配置 DNS、证书、不改变服务器或现有 Sub2API。服务商数据处理地区和保留策略需要运营方在启用模型前确认。

## 项目文档

- [产品需求 PRD](PRD.md)
- [技术栈方案](TECH-STACK.md)
- [实现状态、设计参考与测试](IMPLEMENTATION.md)
- [团队协作规范](CONTRIBUTING.md)
- [AI 协作约定](AGENTS.md)

## 技术栈

- Web：Astro 静态站、React、TypeScript、Tailwind CSS 工具链、自有 CSS、Radix Dialog、Lucide。
- API：Python 3.12、FastAPI、Uvicorn、Pydantic、HTTPX、Redis。
- Word 文档：python-docx 与 A4 可编辑模板；不承诺与 Word 一致的分页预览。
- 临时会话内容只在私有本地目录保存；Redis 只用于非正文会话元数据、限额和聚合计数。
- 模型：站方 OpenAI-compatible HTTPS 接口配置或用户选择服务商的 BYOK；后端不会保存 BYOK。

## 开发环境

Node.js 24、npm 11，Python 3.12 与 uv。第一次安装前后端依赖：

```powershell
cd web
npm ci
cd ..\api
uv sync --group dev
```

复制 `api/.env.example` 为 `api/.env` 仅用于本地配置，不要提交该文件。默认本地开发使用 memory 元数据后端，无 Redis 或站方模型时仍可打开产品和虚构示例。

分别启动 API 和 Web 开发服务器：

```powershell
# 终端 1，仓库根目录
./scripts/dev.ps1 api

# 终端 2，仓库根目录
./scripts/dev.ps1 web
```

Web 地址为 `http://127.0.0.1:4321`，API 为 `http://127.0.0.1:8010`，本地 API 文档为 `http://127.0.0.1:8010/api/docs`。开发服务器不应暴露到公网。

## 验证

```powershell
cd api
uv run ruff check app tests
uv run pytest -q
cd ..\web
npm run check
npm run build
```

需要完整浏览器测试时，安装 Playwright Python 包并配置本机 Chrome，然后在仓库根目录运行 `python scripts/browser_qa.py`。这会启动隔离端口上的临时 API 与 Web 服务、写入被 Git 忽略的 `.local/qa`、使用显式 mocked model 走通页面工作流，不会访问真实云模型。

## 部署

部署样例位于 `deploy/`。它们是人工执行前待核对的配置样例，不表示服务器已配置或上线。生成 nginx 对 Cloudflare 源站 IP 的信任/访问规则前，先阅读 `deploy/nginx.conf.example` 与 `deploy/generate_cloudflare_nginx.py`。人工检查生成的规则、确认 Cloudflare 橙云代理、证书路径、现有 nginx 虚拟主机与 Redis 连接之后，才可以部署。项目服务监听回环地址、单 Uvicorn worker，避免读取未受信任的 X-Forwarded-For。

生产变量样例位于 `deploy/api.env.example`；不要把生产变量或任何 Token 放入仓库。`deploy/airesume-cleanup.timer` 是应用补充清理任务，不替代进程内清理或目录权限。不得在没有单独确认的情况下修改用户服务器、DNS、证书、nginx、Redis 或其他线上服务。

## 协作与版本

功能以独立 Conventional Commit 记录，并写明改动和实际验证结果。同步目标仓库为 GitHub `yiqi-7/AIResume`。不要提交密钥、本地配置、真实简历、测试会话或导出文件。
