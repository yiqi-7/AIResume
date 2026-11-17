# AIResume · 叙职

上传 DOCX 与目标岗位描述，核对建议、编辑简历并导出 Word 文档。

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

```powershell
cd api
uv run ruff check app tests
uv run pytest -q
cd ../web
npm run check
npm run build
```
