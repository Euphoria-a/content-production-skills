# Content Production Skills

[![Validate skills](https://github.com/Euphoria-a/content-production-skills/actions/workflows/validate.yml/badge.svg)](https://github.com/Euphoria-a/content-production-skills/actions/workflows/validate.yml)

一组经过脱敏、可执行并带自动验证的 Codex Skills，覆盖中文内容生产、事实核验、视频后期数据、图像平台路由、分层 SVG 和固定模板海报。

这个仓库不只是提示词集合。每个复杂工作流都把“模型判断”和“确定性机制”分开：Skill 负责意图、边界和路由；Python 负责字段校验、哈希、事务、排版或可重复测试。

## 建议优先查看

1. [creative-image-studio](.agents/skills/creative-image-studio/SKILL.md)：多平台能力路由、密钥脱敏、生成/编辑请求、遮罩外像素锁定、分层 SVG 和 13 项测试。
2. [video-copy-splitter](.agents/skills/video-copy-splitter/SKILL.md)：不可变文本模型、读音替换隔离、语义字幕、原子目录事务和 53 项测试。
3. [create-public-course-poster](.agents/skills/create-public-course-poster/SKILL.md)：授权素材约束、人物真实性、量化版式校验、审计报告和独立验证器。

完整的面试阅读顺序、每个 Skill 的优势与局限见 [PORTFOLIO_GUIDE.md](PORTFOLIO_GUIDE.md)。

## 六个 Skills

| Skill | 解决的问题 | 工程化证据 |
| --- | --- | --- |
| creative-image-studio | 外部图片接口生成/局部编辑与可编辑 SVG | 平台能力路由、密钥脱敏、资产哈希、13 项测试 |
| video-copy-splitter | 旁白转配音、字幕和分镜三件套 | 不可变 ID、SHA-256、事务锁、53 项测试 |
| create-public-course-poster | 固定 1024×1536 公益课海报 | 字段契约、背景/人物检查、审计与独立验证 |
| artifact-template-v4 | 固定 1080×2568 旅行长海报 | 结构化输入、确定性渲染、参考图和冒烟测试 |
| create-travel-video-cover | 系列化 3:4 文旅视频封面 | 文案约束、无字素材门禁、批量输出与单元测试 |
| create-senior-video-scripts | 适老旁白策划、核验和文档交付 | 渐进式参考、双状态证据模型、自动文案分析 |

## 设计原则

- 精确触发：描述同时说明适用场景和排除项，避免 Skill 误触发。
- 渐进式加载：入口只保留共享流程，细节拆入按需读取的 references。
- 可验证执行：重复、脆弱或高风险逻辑进入 scripts，而不是依赖模型记忆。
- 数据不变量：原文、事实、配音替换、视觉素材和导出物使用明确边界。
- 失败安全：缺少授权、字体、证据、平台能力或输出校验时停止，不伪造成功。
- 隐私优先：公开包不含真实姓名、机构名、电话、密钥、客户文件、付费字体或可识别人像。

## 本地验证

需要 Python 3.10+ 和 Pillow：

    python -m pip install -r requirements-dev.txt
    python tools/validate_repo.py
    python tools/run_tests.py

仓库级校验器会检查 Skill/目录命名、YAML 元数据、默认调用提示、资源链接、UTF-8、JSON、Python 语法、缓存文件和常见敏感信息。GitHub Actions 在 Python 3.11 与 3.12 上自动执行同一套验证。

## 目录结构

    .agents/skills/
      <skill-name>/
        SKILL.md
        agents/openai.yaml
        scripts/
        references/
        assets/
        tests/
    tools/
      validate_repo.py
      run_tests.py
    .github/workflows/validate.yml

只有任务真正需要时才创建 scripts、references、assets 或 tests；不存在仅为了显得完整而保留的空目录。

## 运行依赖

- Python 3.10 或更高版本。
- Pillow，用于位图渲染和图像校验。
- 能生成 DOCX/XLSX 的宿主工具，用于文案与分镜交付。
- Edge 或 Chrome，用于 SVG 渲染。
- 用户自行提供并具备使用权的字体、照片和其他素材。

## 隐私与许可

这是用于作品集展示的公开仓库。仓库不包含真实机构或个人标识、联系电话、客户交付档案、API Key、付费字体文件或真实人物示例。

当前未授予开源复用或再分发许可。第三方字体和图片仍受各自许可约束。
