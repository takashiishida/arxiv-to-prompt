# Changelog

## 0.11.0 (2026-02-22)
- Add `--expand-macros` flag to expand `\newcommand` and related macro definitions inline. Supports `\newcommand`, `\renewcommand`, `\providecommand` (and starred variants), `\DeclareMathOperator` (and starred), and basic `\def`. Handles macros with arguments and nested expansion. [#3](https://github.com/takashiishida/arxiv-to-prompt/issues/3) [#24](https://github.com/takashiishida/arxiv-to-prompt/pull/24)

## 0.10.0 (2026-02-15)
- Add `--figure-paths` flag to output resolved image file paths instead of LaTeX text. Respects `--no-comments` and `--no-appendix` filters. [#22](https://github.com/takashiishida/arxiv-to-prompt/pull/22)
- Add `--abstract` flag to output only the abstract text. Comments are automatically stripped to avoid extracting commented-out abstracts. [#23](https://github.com/takashiishida/arxiv-to-prompt/pull/23)
- Add validation to prevent incompatible flag combinations (e.g. `--abstract` + `--figure-paths`, `--figure-paths` + `--section`)

## 0.9.0 (2026-02-12)
- Fix `\input` failing on paths containing dots (e.g. `\input{sections/3.5_dataset}`). [#20](https://github.com/takashiishida/arxiv-to-prompt/issues/20)

## 0.8.0 (2026-02-12)
- Use cached papers by default instead of re-downloading. Add `--force-download` to override. [#17](https://github.com/takashiishida/arxiv-to-prompt/issues/17)
- Add `-c`/`--copy` flag to copy output to clipboard using `pyperclip`. [#15](https://github.com/takashiishida/arxiv-to-prompt/issues/15)

## 0.7.0 (2026-02-11)
- Make arXiv source cache parallel-safe with file locking (`filelock`). [#16](https://github.com/takashiishida/arxiv-to-prompt/pull/16)
  - Concurrent downloads of the same paper no longer race or corrupt the cache
  - Atomic cache publish with rollback on failure
  - Safe tar extraction blocks path traversal, symlinks, and hardlinks
  - New `--lock-timeout` option (default 120s) to control lock wait time
  - Incomplete/corrupt cache directories are detected and rebuilt automatically

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