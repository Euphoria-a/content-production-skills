# 面试官阅读指南

## 推荐阅读顺序

### 1. creative-image-studio

最适合作为第一展示项目。

看点：

- 用 providers.json 抽象外部图片平台，不把供应商逻辑写死。
- 根据平台声明的能力选择生成、编辑、遮罩或 Data URI 传输。
- API Key 只从环境变量读取，错误信息和日志会脱敏。
- AI 只生成位图素材；准确中文保留为 SVG 真实文字。
- 项目包含稳定图层 ID、版本资产、哈希、修改历史和导出验证。
- 13 项自动测试覆盖 HTTP 错误脱敏、不同响应格式、遮罩语义和 SVG 定向修改。

建议打开：

- .agents/skills/creative-image-studio/SKILL.md
- .agents/skills/creative-image-studio/scripts/provider_client.py
- .agents/skills/creative-image-studio/scripts/svg_project.py
- .agents/skills/creative-image-studio/scripts/tests/test_studio.py

### 2. video-copy-splitter

最能体现数据一致性和失败安全。

看点：

- P/S/V/M/MOD/SHOT 构成可追溯的数据模型。
- 读音替换仅进入配音文本，不污染字幕和分镜原文。
- SHA-256、事务 ID、完成标记和内核锁共同防止半成品与并发覆盖。
- 字幕同时满足逐字还原、语义边界和 13 字硬上限。
- 53 项测试覆盖编码、事务、冲突映射、回滚和边界条件。

建议打开：

- .agents/skills/video-copy-splitter/SKILL.md
- .agents/skills/video-copy-splitter/references/transaction-and-delivery.md
- .agents/skills/video-copy-splitter/scripts/split_text.py
- .agents/skills/video-copy-splitter/scripts/test_split_text.py

### 3. create-public-course-poster

最能体现“生成式素材 + 确定性排版 + 视觉 QA”的结合。

看点：

- 背景、人物、文案、字体和版式分别建立契约。
- 不生成新人物，用户照片抠图后进行脸框、边缘和透明度检查。
- 对背景密度、接缝、标题对比度和人物位置进行量化验证。
- 渲染器输出 layout manifest、素材来源、人物证明图和审计报告。
- 独立验证器重新核对最终文件，不直接信任渲染过程。

局限：

- 精确成品依赖用户提供已授权的标题字体和照片。
- 主渲染器较长，未来可继续拆分为输入、视觉分析、排版和审计模块。

### 4. artifact-template-v4

一个边界清晰的模板型 Skill。它展示如何把非结构化旅行资料映射到固定字段、固定卡片顺序和确定性 Pillow 渲染器。适合展示“设计不变量”和占位失败策略。

### 5. create-travel-video-cover

范围较窄但完成度高，适合补充展示系列一致性、文案断行规则、无字素材门禁和批量缩略图。代码量小于前三项，不建议作为首个项目。

### 6. create-senior-video-scripts

领域流程最完整，但主要价值在知识工程而非大量代码。重构后使用简洁入口和三份按需参考，并增加旁白分析器，能够检查字数、时长、乱码、夸张表达、连续短句和地点覆盖。

局限：

- 事实核验仍依赖联网检索和人工/专家判断，不能被单元测试完全替代。
- DOCX/XLSX 的最终视觉质量依赖宿主文档工具。

## 统一质量证据

- tools/validate_repo.py：独立于 Codex 内部环境的仓库结构与隐私校验。
- tools/run_tests.py：一个命令运行全部测试套件。
- .github/workflows/validate.yml：在每次 push 和 pull request 上使用 Python 3.11/3.12 验证。
- PUBLICATION_CHECKLIST.md：公开发布前后的隐私与许可清单。

## 面试时可以怎么介绍

“我把 Skill 当作可维护的软件组件，而不是一段很长的提示词。入口描述负责精确触发，SKILL.md 负责共享流程，references 做渐进式披露，scripts 承担可重复和高风险逻辑，tests 与 CI 证明关键不变量。对于无法自动化的事实、授权和视觉判断，我会明确保留人工门禁，而不是让自动测试制造虚假的确定性。”
