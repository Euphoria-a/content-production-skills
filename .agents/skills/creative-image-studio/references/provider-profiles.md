# 平台配置说明

所有平台统一使用 OpenAI-compatible HTTP 适配器，不引入供应商专用 SDK。

## 配置方法

把 `assets/providers.example.json` 复制到 `<工作区>/.image-studio/providers.json`，再填写平台元数据。密钥只能放在环境变量中。

必填字段：

- `base_url`：API 根地址，通常以 `/v1` 结尾。
- `api_key_env`：保存密钥的环境变量名，不能填写密钥本身。
- `models.generate` 与 `models.edit`：平台实际使用的生成、编辑模型标识。
- `endpoints.generate` 与 `endpoints.edit`：相对端点路径。
- `capabilities`：`generate`、`edit`、`mask`、`reference_images`、`native_transparency`、`seed`、`n` 的真实能力标记。
- `mask_semantics`：`white_edit`、`black_edit` 或 `transparent_edit`。

可选字段：`auth_header`、`auth_prefix`、不含秘密的固定 `headers`、`generation_defaults` 和 `edit_defaults`。

编辑传输字段：

- `edit_transport`：省略或设为 `multipart` 表示标准文件上传；平台用 JSON 接收 Data URI 时设为 `json_data_uri`。
- `edit_image_field`：输入图片数组的 JSON 点路径，例如 `extra_body.image`。
- `edit_size_from_input`：为 `true` 时，若任务没有指定尺寸，则从第一张输入图推导精确 `宽x高`。

若平台通过生成端点做 JSON 图生图，把 `endpoints.edit` 指向该端点，并在 `edit_defaults` 中保留平台要求的响应格式。只有平台明确支持遮罩输入和遮罩语义时，才能把 `capabilities.mask` 设为 `true`；支持普通图生图不等于支持严格局部编辑。发布或使用前应依据所选平台的当前官方文档核对端点、模型标识和能力字段。

## 选择顺序

1. 优先使用用户明确点名的平台。
2. 否则使用已启用、有相应能力且环境变量存在的 `default_provider`。
3. 否则使用唯一符合条件的平台。
4. 若仍有多个，询问用户选择。
5. 若没有可用平台，保存最终提示词并进入顾问模式。

不得把遮罩编辑静默降级为整图生成，也不得为了让请求成功而删掉关键能力要求。

## 响应与安全

接受 `data[].b64_json`、`data[].url` 和直接 `image/*` 响应。URL 结果可能过期，收到后立即下载。

异常和日志必须隐藏鉴权值；远程错误只保留简短、可操作的摘要。
