# AIResume

面向应届生和校招生的 AI 简历优化工具：上传 DOCX、粘贴目标岗位 JD、逐条确认有依据的建议，最后导出可编辑 DOCX。

**当前阶段：需求与技术选型。仓库尚无可运行的前后端应用。**

## 项目文档

- [产品需求 PRD](PRD.md)
- [技术栈方案](TECH-STACK.md)
- [团队协作规范](CONTRIBUTING.md)
- [AI 协作约定](AGENTS.md)

## 已选技术栈

- 前端：Astro 静态站、React、TypeScript、Tailwind CSS、Radix Primitives。
- 后端：Python 3.12、FastAPI、Uvicorn、uv、Pydantic。
- 数据：Redis 存状态与计数；个人会话内容仅在私有临时目录处理。
- 文档：python-docx 解析和生成，HTML 预览。
- 模型：云 API，支持站方配置与用户 BYOK。
- 部署：nginx + systemd；规划入口为 key123456.online。

供应商、依赖精确版本和部分实现参数尚待验证，以技术方案中的状态说明为准。

## 安装与启动

目前没有应用代码、依赖清单或启动命令。web/、api/ 和部署文件将在对应 Issue 的任务分支中实现后补充；不要把文档中的规划目录当作现有程序。

后续开发基线为 Node.js 24 和 Python 3.12，前端使用 npm，后端使用 uv。依赖锁文件随代码一同提交。

## 协作流程

先建 Issue，再从最新 main 创建任务分支。提交信息采用“类型: 具体改动”，完成后推送分支并按模板提交 PR。

分支示例：docs/1-project-foundation。PR 使用 Refs #编号，待独立 AI 审查和非作者成员人工批准后，由维护者 Squash and merge；主线验收后关闭 Issue。合并与生产发布需要维护者另行确认。

详见 [CONTRIBUTING.md](CONTRIBUTING.md)。不要将真实凭据、本地配置、简历和会话数据加入仓库。

## 检查与验收

当前文档任务检查 Markdown 结构、相对链接、内容一致性和暂存区，记录实际执行结果。应用实现后，再由相应任务补充安装、启动、测试与构建命令；本仓库暂不提供虚构的检查脚本。
