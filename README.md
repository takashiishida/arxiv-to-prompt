# arxiv-to-prompt

[![PyPI version](https://badge.fury.io/py/arxiv-to-prompt.svg?update=20250202)](https://pypi.org/project/arxiv-to-prompt/)
[![Tests](https://github.com/takashiishida/arxiv-to-prompt/actions/workflows/tests.yml/badge.svg)](https://github.com/takashiishida/arxiv-to-prompt/actions)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Changelog](https://img.shields.io/github/v/release/takashiishida/arxiv-to-prompt?label=changelog)](https://github.com/takashiishida/arxiv-to-prompt/releases)

A command-line tool to transform arXiv papers into a single LaTeX source that can be used as a prompt for asking LLMs questions about the paper. It downloads the source files, automatically finds the main tex file containing `\documentclass`, and flattens multiple files into a single coherent source by resolving `\input` and `\include` commands. The tool also provides an option to remove LaTeX comments from the output (which can be useful to shorten the prompt).

### Installation

```bash
pip install arxiv-to-prompt
```

### Usage

Basic usage:
```bash
# Display LaTeX source with comments
arxiv-to-prompt 2303.08774

# Display LaTeX source without comments
arxiv-to-prompt 2303.08774 --no-comments

# Copy to clipboard
arxiv-to-prompt 2303.08774 | pbcopy

# Combine with the `llm` library from https://github.com/simonw/llm to chat about the paper
arxiv-to-prompt 1706.03762 | llm -s "explain this paper"
```

The arXiv ID can be found in the paper's URL. For example, for `https://arxiv.org/abs/2303.08774`, the ID is `2303.08774`. It will automatically download the latest version of the paper, so you don't need to specify the version.

### Python API

You can also use arxiv-to-prompt in your Python code:

```python
from arxiv_to_prompt import process_latex_source

# Get LaTeX source with comments
latex_source = process_latex_source("2303.08774")

# Get LaTeX source without comments
latex_source = process_latex_source("2303.08774", keep_comments=False)
```

### References

- Inspired by [files-to-prompt](https://github.com/simonw/files-to-prompt).
- Reused some code from [paper2slides](https://github.com/takashiishida/paper2slides).
