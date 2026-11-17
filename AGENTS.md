# AIResume 仓库协作说明

## 项目与授权范围

- 远程仓库：yiqi-7/AIResume。
- 先读 README.md、CONTRIBUTING.md、PRD.md、TECH-STACK.md 和当前 Issue。
- 用户已要求后续项目修改同步 GitHub：在授权任务完成后，负责验证、提交、推送任务分支并创建 / 更新 PR；用户指定只读、暂不提交等边界时以当次指令为准。
- 合并、发布、生产配置修改和回滚需相应负责人另行授权；不能把“同步 GitHub”解释为自动合并或自动上线。
- 每个任务先创建 Issue，从最新 main 创建“类型/Issue编号-简短描述”分支，不直接向 main 推送项目改动。

## 修改与验证

- 按 Issue 的“做什么 / 不做什么 / 验收标准”限定修改。
- 只提交当前任务文件；检查 git status、git diff 和暂存区。
- 不提交密钥、口令、本地环境配置、真实简历或会话数据。
- 不编造运行结果；未验证项写清原因。
- 文档中的规划不是已实现能力；按实际代码和证据更新状态。

## 提交与审查

- 提交格式：feat:、fix:、docs:、chore: 等类型 + 具体改动。
- PR 按 .github/pull_request_template.md 填写，用 Refs #编号关联 Issue。
- 按 CONTRIBUTING.md 使用新的 AI 会话或独立审查 Agent，检查 Issue、实际 Diff 和相关文件，记录结论对应的提交号。
- 独立 AI 审查不能替代非作者成员的人工批准。
- 维护者确认后使用 Squash and merge，主线验收后关闭 Issue；不强推改写共享历史。

## 技术与前端工作

- 主线：Astro 静态站 + React / TypeScript；Python 3.12 + FastAPI；Redis；python-docx。
- 前端新页面或大幅改版遵循工作区的 frontend-visual-workflow 和前端案例库流程；当前技术文档不视为视觉设计已经完成。
- 第三方代码须核对实际条目许可证、依赖和访问条件，保存必要声明。
