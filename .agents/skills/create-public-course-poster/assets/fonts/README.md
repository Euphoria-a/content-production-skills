# Fonts are not bundled

This public-ready package does not redistribute the paid WenYue XinQingNianTi font or local font files.

For exact template fidelity, place authorized copies in this directory using these names:

- `文悦新青年体简体W8.otf`
- `NotoSerifCJKsc-Regular.otf`
- `NotoSerifCJKsc-Bold.otf`
- `NotoSansCJKsc-Regular.otf`
- `NotoSansCJKsc-Bold.otf`

Alternatively, set `PUBLIC_COURSE_FONT_YOUTH`, `PUBLIC_COURSE_FONT_SERIF`, `PUBLIC_COURSE_FONT_SERIF_BOLD`, `PUBLIC_COURSE_FONT_SANS`, and `PUBLIC_COURSE_FONT_SANS_BOLD` to authorized font files. The renderer can use common system fonts for the four Noto roles, but it deliberately refuses to substitute the distinctive youth title font silently.
