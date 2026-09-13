# 固定模板字段

## 固定文字

- `location_scope=china`：`区域文化 · 网络公益课`
- `location_scope=world`：`世界文化 · 网络公益课`
- `分享嘉宾｜{嘉宾姓名}`
- `核心内容`
- `课程时间｜{日期与时间}`
- `课程地点｜{课程地点}`

不得在 JSON 中加入 `brand`、`brand_text`、`font`、`colors`、`layout` 或 `title_color` 字段。

## JSON 结构

```json
{
  "location_scope": "world",
  "title_lines": ["示例城市", "文化行走"],
  "subtitle": "从城市空间读懂地方记忆",
  "guest_name": "示例嘉宾",
  "guest_identity": "请填写材料明确支持的身份",
  "guest_intro": [
    "请填写材料明确支持的履历",
    "不得补写或夸大嘉宾经历"
  ],
  "core_points": [
    "城市空间观察",
    "地方文化线索"
  ],
  "event_time": "示例日期 示例时间",
  "course_location": "示例会议地点",
  "panel_theme": "dark_teal",
  "portrait_face_box": [360, 210, 520, 390],
  "background_sources": [
    {
      "source": "用户提供文件或许可清楚的网页地址",
      "element": "示例地点背景",
      "license": "用户授权或明确许可说明",
      "usage": "主背景远景",
      "contains_person": false
    }
  ]
}
```

## 数据规则

| 字段 | 规则 |
| --- | --- |
| `location_scope` | 只能是 `china` 或 `world`；不明确时先询问用户。 |
| `title_lines` | 输入一至两段；脚本优先合并成单行，合并后宽度≤864px时强制单行，否则使用固定双行。 |
| `subtitle` | 单行；使用新青年体 42px；建议不超过 22 个汉字。 |
| `guest_name` | 只写姓名，最多 6 个汉字。 |
| `guest_identity` | 固定一行；多个身份使用 ` · `。 |
| `guest_intro` | 一至两行，每项必须单行显示；与身份合计形成两至三行正文。 |
| `core_points` | 两至三项，每项必须单行显示。 |
| `event_time` | 只进入课程时间行。 |
| `course_location` | 只进入课程地点行，不得由背景地点推断。 |
| `panel_theme` | 可省略，默认 `dark_teal`；只有用户明确要求浅色卡片时可用 `light_sand`，不接受任意颜色值。 |
| `portrait_face_box` | 放大测量人物层中可见脸部的 `[左, 上, 右, 下]`；脚本据此强制检查中心与高度。 |
| `background_sources` | 至少一项；每项必须有 `source`、`element`、`license`、`usage`、布尔值 `contains_person`。至少一项最终背景素材必须不含人物。 |

## 核心内容拆分

1. 先按换行以及 `，,。；;！？!?` 拆分语义片段。
2. 删除片段首尾空格和最终标点。
3. 将过短且不能独立表达含义的片段与相邻片段合并。
4. 超过三段时，在不新增事实的前提下提炼为三段。
5. 只有一段时，只能在明确语义边界拆为两段；不明确时询问用户。
6. 最终保留两至三项，不添加圆点、编号、短横线和句末标点。

脚本只负责标点拆分和数量校验，不负责事实性总结；总结由执行 Skill 的智能体在读取完整材料后完成。

## 必须询问的情况

- 地点无法可靠归入中国或中国以外。
- 嘉宾照片、姓名、时间、课程地点或背景地点缺失。
- 材料不能支持嘉宾履历或课程核心内容。
- 核心内容不能可靠提炼为两至三条。
