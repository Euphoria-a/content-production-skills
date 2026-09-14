# Publication checklist

## Completed

- Six unique, anonymized skills collected under `.agents/skills/`.
- Archive duplicates and stale working copies excluded.
- Folder names match each skill `name`.
- Python bytecode and cache directories excluded.
- Personal Windows profile paths and original `D:` workspace paths removed.
- Real phone numbers and the original travel-company example removed.
- Paid WenYue font binaries excluded.
- Identifiable portrait posters and personal biography examples excluded.
- External image-provider example reduced to a disabled generic template.
- All six skills pass the Codex `quick_validate.py` structural check.
- Repository validator checks skill names, UI metadata, resource links, UTF-8, JSON, Python syntax, cache files and common sensitive patterns.
- Six automated suites contain 84 passing tests.
- `video-copy-splitter`: 53 transaction, encoding and text-integrity tests.
- `creative-image-studio`: 13 provider, secret-redaction, mask and SVG tests.
- Four previously untested skills now include 18 contract, analysis and rendering tests.
- Image-rendering entry points load successfully.
- `artifact-template-v4` renders a sanitized 1080x2568 reference and preview.
- GitHub Actions validates the repository on Python 3.11 and 3.12 for every push and pull request.

## Public-release maintenance

- Choose an open-source or proprietary license before granting reuse rights.
- Confirm permission to publish the generalized workflow rules, templates, examples, and source-image requirements.
- Keep user-supplied fonts, portraits, contact details, credentials, and customer source files outside the repository.
- Recheck third-party provider endpoints and model identifiers against current official documentation before enabling them.
- Repeat the secret/path scan and test suite before each public release.

The repository may remain public for portfolio viewing while reuse and redistribution remain unlicensed.
