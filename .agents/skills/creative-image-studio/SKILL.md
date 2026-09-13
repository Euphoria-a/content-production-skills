---
name: creative-image-studio
description: 通过用户已配置的 OpenAI-compatible 图片接口生成或编辑位图，并制作可编辑的分层SVG。用于用户明确选择外部图片平台、多平台路由或精确SVG排版工作流；普通内置生图请求不应触发本Skill。
---

# 创意文生图工作室

通过 OpenAI-compatible 图片接口生成视觉素材，并把可编辑成果保存为带版本的位图资产或分层 SVG 项目。默认把面向读者的文字保留为 SVG 中可编辑的真实文本。

## 不可违反的规则

- 用户明确选择本 Skill 的外部平台流程时，只使用工作区已配置的 HTTP 平台。用户改为指定宿主内置生图工具时，退出本 Skill 的平台路由并遵循用户选择。
- 不索要、不打印、不记录、不保存 API Key；只读取平台配置指定的环境变量。
- 没有可用平台时，不声称已生成图片；改为保存可直接使用的生产级提示词并进入顾问模式。
- 不把海报准确文案压进 AI 底图。先生成无文字、预留排版区的视觉底图，再用 SVG 精确排版。
- 不覆盖已选资产。新资产使用版本号保存，并记录修改历史。
- 编辑时重申不变量，只修改指定图层或遮罩区域。
- 用户明确拒绝的模型不得推荐、写入配置或用于回退。

## 工作流程

1. 把请求归类为 `generate`、`edit`、`layer-change` 或 `prompt-advisor`，并确认是单张还是系列资产。
2. 读取工作区 `.image-studio/providers.json`。若不存在，只把 `assets/providers.example.json` 当作配置模板，不得当作可用配置。
3. 按以下顺序选平台：用户点名的平台、已配置的 `default_provider`、唯一符合能力要求的平台。若仍有多个候选，询问用户。细则见 `references/provider-profiles.md`。
4. 从 `references/recipes-index.md` 选择一个分类，只加载该分类文件；把配方当作脚手架，不机械照抄全部字段。
5. 按 `references/prompting.md` 规范化需求。保留逐字文案，标注每张输入图的角色，并列出编辑不变量。
6. 实际请求前，把最终提示词保存到任务目录的 `prompts/`；无文字底图必须附加 `assets/anti-text-template.md` 的约束并记录重试次数。
7. 使用 `scripts/provider_client.py` 执行生成或编辑；收到 URL、Base64 或直接图片响应后立即保存到任务目录。
8. 海报、封面或含准确文案的版式，使用 `scripts/svg_project.py` 创建或更新分层 SVG，再用 `scripts/render_svg.py` 渲染。
9. 制作海报时读取 `references/poster-review-checklist.md`，按 `S -> H/T/C -> A -> P -> W/CT/R/A11y` 顺序审校；确认是单张海报时可跳过 `S`。
10. 用 `scripts/validate_project.py` 验证 SVG、素材路径、图层映射、安全区、文字度量和导出图；用内部 `scripts/export_project.py` 生成 PNG、JPG、25% 预览图及元数据副本，再做 100% 与 25% 视觉检查。
11. 一次只做一个有明确目标的修改。报告保存路径、平台配置名、模型、最终提示词、校验结果和未解决的审校代码。

## 平台行为

- 平台配置中的能力标记是唯一依据，不试探性发送未声明支持的字段。
- 支持标准 `/images/generations` JSON 请求和 `/images/edits` multipart 请求。
- 当配置声明 `json_data_uri` 编辑时，把本地输入图编码为 Data URI，写入配置指定的嵌套 JSON 字段；日志中不得出现图片字节或密钥。
- 接受 `data[].b64_json`、`data[].url` 或直接 `image/*` 响应。
- 指定平台不支持遮罩编辑时，只能切换到另一个已配置且具备能力的平台，或请求用户选择；不得把整图重生成伪装成局部编辑。
- 没有任何已配置且有密钥的平台时，进入提示词顾问模式并明确说明未生成图片。

## 分层 SVG 行为

- `project.svg` 是版式唯一来源；`project.json` 只保存平台、提示词、图层映射、哈希和历史。
- 每个可编辑单元使用稳定的 `<g id="...">`；文字使用 `<text>/<tspan>`，位图使用项目内相对路径。
- AI 图片、人物、产品、Logo、遮罩、提示词、历史和导出物分别存放。
- 修改文字、颜色或位置时，只更新目标 SVG 图层并重渲染，不调用图片 API。
- 替换独立位图图层时，保存带版本的新资产，仅更新该图层的 `href`；旧资产复制到 `assets/_failed/` 留档并保留哈希。
- 局部改底图时，内部统一使用“白色表示编辑”的遮罩；按平台语义转换后调用编辑端点，再用原始遮罩合成，保证遮罩外像素来自上一版本。
- 需要 Logo、组织方、二维码或 CTA 而用户未提供时，保留占位并询问，不得静默省略或虚构。

创建或修改分层项目之前读取 `references/svg-project.md`；最终交付前读取 `references/quality-gates.md`。海报和海报系列还要在排版前、交付前各读取一次 `references/poster-review-checklist.md`。

## 输出约定

除非用户指定其他位置，输出到 `output/creative-image-studio/<task-slug>/`：

```text
project.svg
project.json
assets/
assets/_failed/
masks/
prompts/
history/
exports/
```

稳定文件名后加 `-v2`、`-v3` 等版本号。项目名优先采用 `<主题拼音>-poster-NN-<主题关键词>`。最终交付物不得只留在远程 URL。

## 参考导航

- 平台配置与路由：`references/provider-profiles.md`
- 提示词结构与编辑不变量：`references/prompting.md`
- 90 个配方的分类导航：`references/recipes-index.md`
- SVG 图层契约与局部修改：`references/svg-project.md`
- 验收门槛与失败处理：`references/quality-gates.md`
- 海报设计与分阶段审校：`references/poster-review-checklist.md`
- 架构参考与许可证：`references/sources.md`
