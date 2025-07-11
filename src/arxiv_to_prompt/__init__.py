"""
arxiv-to-prompt: A tool to download and process LaTeX source from arXiv papers.

This package provides functionality to:
- Download source files from any arXiv paper using its ID
- Smart concatenation of multiple LaTeX files into a single coherent source
- Option to remove LaTeX comments

Example:
    >>> from arxiv_to_prompt import process_latex_source
    >>> latex_source = process_latex_source("2303.08774")
"""

from .core import process_latex_source, download_arxiv_source, get_default_cache_dir

# Import version from package metadata
try:
    from importlib.metadata import version

    __version__ = version("arxiv-to-prompt")
except ImportError:
    # Python < 3.8 fallback
    from importlib_metadata import version

    __version__ = version("arxiv-to-prompt")

__all__ = [
    "process_latex_source",
    "download_arxiv_source",
    "get_default_cache_dir",
    "__version__",
]
