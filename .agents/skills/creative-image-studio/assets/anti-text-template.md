# AI 底图反文字模板

每次生成海报、封面或任何需要后期排字的底图时，把以下约束原样附加到提示词末尾。项目的 `project.json` 记录 `anti_text_retry_count`；若出现伪字，最多重试 3 次，仍失败则换平台或把问题区域裁切为独立素材。

```text
This is a raw photograph. The sky must be a clean smooth gradient with natural clouds. Do not include any text, calligraphy, characters, marks, symbols, letters, numbers, signs, or signage anywhere in the image.
```

非人物主题额外附加：

```text
No people, no humans, no silhouettes, no shadows of people.
```

中文含义：画面必须是无文字、无字母、无数字、无标记、无招牌的纯视觉底图；非人物主题还不得出现人物、剪影或人影。英文约束保留是为了兼容 Agnes 等模型的提示词理解。
