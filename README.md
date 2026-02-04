<div align="center">
<img src="logo.png#gh-light-mode-only" alt="" width="475"><img src="logo.png#gh-dark-mode-only" alt="" width="475">

[![PyPI version](https://badge.fury.io/py/arxiv-to-prompt.svg)](https://pypi.org/project/arxiv-to-prompt/)
[![Tests](https://github.com/takashiishida/arxiv-to-prompt/actions/workflows/tests.yml/badge.svg)](https://github.com/takashiishida/arxiv-to-prompt/actions)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Changelog](https://img.shields.io/github/v/release/takashiishida/arxiv-to-prompt?label=changelog)](https://github.com/takashiishida/arxiv-to-prompt/releases)
[![Downloads](https://static.pepy.tech/badge/arxiv-to-prompt)](https://pepy.tech/project/arxiv-to-prompt)
</div>

A command-line tool to transform arXiv papers into a single LaTeX source that can be used as a prompt for asking LLMs questions about the paper. It downloads the source files, automatically finds the main tex file containing `\documentclass`, and flattens multiple files into a single coherent source by resolving `\input` and `\include` commands. The tool also provides options to remove LaTeX comments and appendix sections from the output (which can be useful to shorten the prompt).

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

# Display LaTeX source without appendix sections
arxiv-to-prompt 2303.08774 --no-appendix

# Combine options (no comments and no appendix)
arxiv-to-prompt 2303.08774 --no-comments --no-appendix

# Process a local folder containing TeX files (instead of downloading from arXiv)
arxiv-to-prompt --local-folder /path/to/tex/files

# List all sections (with subsections indented)
arxiv-to-prompt 2307.09288 --list-sections
# Introduction
# Pretraining
#   Pretraining Data
#   Training Details
#     Training Hardware \& Carbon Footprint
#   ...

# Extract specific sections
arxiv-to-prompt 2307.09288 --section "Introduction" --section "Pretraining"

# Ambiguous names show a helpful error
arxiv-to-prompt 2307.09288 --section "Human Evaluation"
# Warning: 'Human Evaluation' is ambiguous. Found at:
#   - Fine-tuning > RLHF Results > Human Evaluation
#   - Appendix > Additional Details for Fine-tuning > Human Evaluation
# Use path notation to disambiguate.

# Use path notation when the same name appears multiple times
arxiv-to-prompt 2307.09288 --section "Fine-tuning > RLHF Results > Human Evaluation"

# Copy to clipboard
arxiv-to-prompt 2303.08774 | pbcopy

# Combine with the `llm` library from https://github.com/simonw/llm to chat about the paper
arxiv-to-prompt 1706.03762 | llm -s "explain this paper"
```

You can use either the arXiv ID (e.g., `2303.08774`) or the full URL (e.g., `https://arxiv.org/abs/2303.08774`). It will automatically download the latest version of the paper, so you don't need to specify the version.

### Python API

You can also use arxiv-to-prompt in your Python code:

```python
from arxiv_to_prompt import process_latex_source

# Get LaTeX source with comments
latex_source = process_latex_source("2303.08774")

# Get LaTeX source without comments
latex_source = process_latex_source("2303.08774", keep_comments=False)

# Get LaTeX source without appendix sections
latex_source = process_latex_source("2303.08774", remove_appendix_section=True)

# Combine options (no comments and no appendix)
latex_source = process_latex_source("2303.08774", keep_comments=False, remove_appendix_section=True)

# Process LaTeX sources from a local folder (instead of downloading from arXiv)
latex_source = process_latex_source(local_folder="/path/to/tex/files")
```

### Projects Using arxiv-to-prompt

Here are some projects and use cases that leverage arxiv-to-prompt:

- [arxiv-latex-mcp](https://github.com/takashiishida/arxiv-latex-mcp): MCP server that fetch and process arXiv LaTeX sources for precise interpretation of mathematical expressions in papers.
- [arxiv-tex-ui](https://github.com/takashiishida/arxiv-tex-ui): chat with an LLM about an arxiv paper by using the latex source.
- [paper2slides](https://github.com/takashiishida/paper2slides): transform an arXiv paper into slides.
- [ArXivToPrompt](https://apps.apple.com/jp/app/arxivtoprompt/id6751013390): iOS app that allows users to easily extract LaTeX source from arXiv papers on their iPhone and copy it to the clipboard for use with LLM apps. 

If you're using arxiv-to-prompt in your project, please submit a pull request to add it to this list!
