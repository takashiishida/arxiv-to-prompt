# Changelog

## 0.6.0 (2026-02-04)
- Add `\subsection` and `\subsubsection` support to `--list-sections` and `--section`. [#13](https://github.com/takashiishida/arxiv-to-prompt/issues/13)
  - `--list-sections` now shows indented hierarchy
  - `--section` supports path notation (e.g., `--section "Methods > Background"`) for disambiguation
  - Ambiguous section names show helpful error with available paths

## 0.5.1 (2026-01-30)
- Search subdirectories for main.tex file. [#9](https://github.com/takashiishida/arxiv-to-prompt/issues/9)

## 0.5.0 (2026-01-30)
- Add `--list-sections` and `--section` options to extract specific sections. [#12](https://github.com/takashiishida/arxiv-to-prompt/issues/12)

## 0.4.1 (2026-01-30)
- `--no-comments` now also removes `\iffalse...\fi` blocks. [#10](https://github.com/takashiishida/arxiv-to-prompt/issues/10)

## 0.4.0 (2026-01-30)
- Accept arXiv URLs in addition to IDs. [#8](https://github.com/takashiishida/arxiv-to-prompt/issues/8)

## 0.3.0 (2025-12-24)
- Added `--local-folder` option to process LaTeX sources from a local directory.

## 0.2.2 (2025-06-29)
- Added `__version__` support. [#7](https://github.com/takashiishida/arxiv-to-prompt/issues/7)

## 0.2.1 (2025-06-29)
- Fixed incorrect file extension handling for \input commands with non-.tex files. [#6](https://github.com/takashiishida/arxiv-to-prompt/issues/6)

## 0.2.0 (2025-06-29)
- Added new feature to remove appendix section. Shorter prompts can be helpful to reduce token count. [#5](https://github.com/takashiishida/arxiv-to-prompt/issues/5)

## 0.1.1 (2025-03-07)
- Fixed an issue where commented-out \include and \input commands were still being processed. [#1](https://github.com/takashiishida/arxiv-to-prompt/issues/1)
- Add an example of combining with the [llm](https://github.com/simonw/llm) library in the README.

## 0.1.0 (2025-02-02)
- Initial release.