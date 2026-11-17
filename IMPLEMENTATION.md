# MVP 实现与验证记录

本文件区分仓库中的真实实现、mock 测试和仍需人工完成的线上配置。

## 已实现

- `/`：面向用户的介绍页与虚构简历批注示例；`/privacy/` 描述实际数据流和剩余核验事项。
- `/app/`：DOCX 上传与 JD 提交，用户复核提取内容后再调用模型；三维度分析、依据展示、事实补充问答、逐条编辑/采纳/跳过、版式预览、DOCX 导出。
- 桌面、移动布局；首页与工作台的不同导航/状态；弹出模型设置；示例模式明确标记虚构并且不调用模型。
- 会话依赖高熵 HttpOnly cookie、空闲 2 小时与硬上限 6 小时；个人内容只写私有会话目录，不写 Redis、localStorage、访问日志或模型 Key 存储。
- Redis 使用 `ro:` 前缀，只处理非正文状态、活动会话标识、原子计数和限额。仅开发配置允许 memory 元数据后端。
- DOCX 校验解包大小、文件数、压缩、文本框和表格顺序；导出会创建可继续编辑的 A4 单栏 DOCX，并清除源文件作者信息。
- BYOK Key 只有用户勾选时才保存于当前浏览器 localStorage；分析请求经 HTTPS header 发给后端。来源仅允许服务商 allowlist，用户不能填写任意 endpoint。
- 三个分析维度并行，每维度最多一次共享校验重试。已有建议会校验原文引用和 JD 引用，并拒绝改写中未经输入支持的数字；用户仍须人工确认改写的事实正确性。
- 失败分析只重试未完成维度并保留已完成维度结果与用户决定；后台清理和补充 systemd 清理任务共享应用锁。
- 站方默认配置为空。没有站方模型或 BYOK 时，真实会话不会伪装产生成功分析结果。

## 本次验证

- Python 3.12：`uv run ruff check app tests` 通过；完整 pytest 覆盖 DOCX 安全边界、导出 round-trip、会话鉴权/到期/清理、额度原子性、模型引用校验、部分失败重试及 HTTPX ASGI 端到端流程。
- 浏览器：`python scripts/browser_qa.py` 在本地 1440px、390px Chrome viewport 验证首页、虚构示例、解析复核、mock 上游分析、采纳、事实补充、预览缩放、下载 DOCX 和会话清理；脚本断言 CJK 字体成功载入、没有水平视口溢出和没有浏览器运行时异常。QA 页面和输出在 `.local/qa/`，忽略于 Git。
- Web：`npm run check` 与 `npm run build`。
- 视觉方向记录于 `DESIGN-RECORD.md`。Noto Sans SC 使用 SIL OFL 1.1，许可证随 Web 静态资产一同发布。

## 未验证与上线门槛

- 未调用任何真实云模型，未提供运营方模型 endpoint / Key，因而未验证生产模型兼容性、生成质量、token 定价或供应商隐私条款。
- 本机浏览器覆盖了 mocked API 工作流；没有在目标 Ubuntu、真实 Redis、nginx、Cloudflare DNS/代理、TLS 或当前 Sub2API 服务环境里部署或验证。
- `deploy/` 是配置模板。人工配置时须按 Cloudflare 当前发布 IP 生成 nginx real-IP/allow include，检查站点冲突，`nginx -t` 并由维护者决定 reload。普通来源不能伪造 CF-Connecting-IP 穿越 trusted proxy 的访问规则。
- `python-docx` 不计算原始 Word 页数；预览与 Word 的精确分页/字体可能不同，且复杂文本框被明确拒绝。页数元数据只能当估计。
- Chrome 截图和测试 DOCX/PDF 为本机 QA 产物，只保存在被忽略的 `.local/qa/`，不包含真实用户数据。
