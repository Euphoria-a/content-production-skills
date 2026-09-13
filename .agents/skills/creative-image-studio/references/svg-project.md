# 分层 SVG 项目契约

## 权威来源

- `project.svg` 是版式唯一来源。
- `project.json` 保存画布、平台与模型、提示词路径、稳定图层 ID、资产哈希、版本和历史。
- 位图资产与遮罩保持独立，用项目内相对路径引用。
- 工作区 `.image-studio/design-tokens.json` 是系列颜色、字体、间距和遮罩透明度的集中来源；项目只记录令牌引用与必要的兼容回退值。

## SVG 图层

每个可编辑单元使用 `<g id="稳定标识" data-layer-type="..." data-bounds="x,y,w,h">` 包裹。

支持 `raster`、`text`、`shape` 和 `group`。用户文案必须使用真实 `<text>/<tspan>`，不得转路径。位图图层使用 `<image preserveAspectRatio="xMidYMid slice">`。

`data-bounds` 表示可编辑和安全排版框。所有素材路径必须为项目内相对路径。

## 局部修改

- 文字：先快照，只修改目标组，再渲染、校验并记录哈希。
- 独立图片：复制带版本的新资产，只更新一个 `href`，其余图层不变；旧资产复制到 `_failed` 留档。
- 局部重绘：建立“白色表示编辑”的遮罩；按平台语义转换；请求编辑；用原始遮罩合成；只替换目标位图层。

每次变更记录 `before_sha256` 和 `after_sha256`，并保留未修改位图资产的哈希以检测回归。

## 文字排版

- 标题字体栈：`Noto Serif SC, Source Han Serif SC, Microsoft YaHei, serif`。
- 正文字体栈：`Noto Sans SC, Source Han Sans SC, Microsoft YaHei, sans-serif`。
- 中英混排的西文字体栈：`Inter, Source Sans Pro, Calibri, sans-serif`，并做基线视觉检查。
- 标题大于等于 80 px 时，字距默认约为字号的 8%；标题行高为 0.9–1.2 倍，导语 1.4 倍，正文 1.5 倍。
- 换行必须依据图层实际宽度、字号和字距计算；超出时自动换行或缩小字号，不得把文字溢出留白区。

## 渲染

优先使用 `resvg` 或 `rsvg-convert`；否则使用 Chromium、Chrome 或 Edge 无头渲染，设备缩放为 1。需要 JPG 时，由已验证的 PNG 通过 Pillow 转换。没有渲染器时保留 SVG，并明确报告缺少的依赖。
