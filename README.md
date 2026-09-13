# Content Production Skills

This repository contains six anonymized Codex skills for content-production workflows. The repository copy is intentionally separated from the original working files so that organization names, personal names, caches, private delivery archives, contact details, licensed fonts, and identifiable portrait examples are not published accidentally.

## Included skills

- `create-senior-video-scripts`: plan, write, verify, and package senior-friendly video narration projects.
- `create-travel-video-cover`: render a consistent series of 3:4 travel-video covers from verified no-text backgrounds.
- `video-copy-splitter`: produce voice-cloning text, semantic subtitle text, and structured storyboard data from narration.
- `creative-image-studio`: use a configured OpenAI-compatible image endpoint and editable SVG workflow.
- `artifact-template-v4`: render the fixed 1080x2568 V4 travel-poster layout.
- `create-public-course-poster`: render a fixed public-course poster after the user supplies licensed fonts and authorized imagery.

## Install

Clone the repository, then either run Codex from the repository or copy the desired folder from `.agents/skills/` into your personal skills directory. Install only the skills and external tools you intend to use.

## Runtime requirements

- Python 3.10 or newer.
- Pillow for image-rendering skills.
- A spreadsheet-capable tool for the XLSX deliverables requested by `video-copy-splitter` and `create-senior-video-scripts`.
- A document-capable tool for DOCX deliverables requested by `create-senior-video-scripts`.
- Edge or Chrome for SVG rendering in `creative-image-studio`.
- User-supplied, properly licensed fonts and images where a skill explicitly requires them.

Install Pillow when needed:

```powershell
python -m pip install Pillow
```

## Privacy and licensing

This repository does not bundle the paid WenYue XinQingNianTi font, organization or personal names, phone numbers, delivery archives, or identifiable portrait examples. Do not add private or restricted material unless you have explicit redistribution and publicity rights. Noto CJK fonts may be obtained separately under their own SIL Open Font License terms.

No open-source license has been selected for this repository yet. Keep the GitHub repository private until the owner chooses a license and confirms that the remaining templates, examples, and source images may be published.

## Validation

Run the bundled Codex skill validator against each folder before publishing. Script tests are included where the original skill had meaningful automated coverage.
