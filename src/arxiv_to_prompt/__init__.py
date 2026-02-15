"""
arxiv-to-prompt: A tool to download and process LaTeX source from arXiv papers or local folders.

This package provides functionality to:
- Download source files from any arXiv paper using its ID
- Process LaTeX source files from a local folder
- Smart concatenation of multiple LaTeX files into a single coherent source
- Option to remove LaTeX comments

Example:
    >>> from arxiv_to_prompt import process_latex_source
    >>> # From arXiv
    >>> latex_source = process_latex_source("2303.08774")
    >>> # From local folder
    >>> latex_source = process_latex_source(local_folder="/path/to/tex/files")
"""

from .core import process_latex_source, download_arxiv_source, get_default_cache_dir, list_sections, extract_section, extract_figure_paths

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
    "list_sections",
    "extract_section",
    "extract_figure_paths",
    "__version__",
]
