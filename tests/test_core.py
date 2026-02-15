import os
import io
import tarfile
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from filelock import FileLock
from arxiv_to_prompt.core import (
    process_latex_source,
    download_arxiv_source,
    get_default_cache_dir,
    find_main_tex,
    remove_comments_from_lines,
    check_source_available,
    flatten_tex,
    remove_appendix,
    list_sections,
    extract_section,
    extract_figure_paths,
    SectionNode,
    parse_section_tree,
    format_section_tree,
    find_all_by_name,
    find_section_by_path,
    _CACHE_COMPLETE_MARKER,
    _get_lock_path,
    _is_valid_cache_dir,
)
from arxiv_to_prompt.cli import extract_arxiv_id, main


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        return None


def _make_tar_bytes(files: dict) -> bytes:
    """Build a gzipped tar archive in memory."""
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
        for filename, content in files.items():
            encoded = content.encode("utf-8")
            info = tarfile.TarInfo(name=filename)
            info.size = len(encoded)
            tar.addfile(info, io.BytesIO(encoded))
    return tar_buffer.getvalue()


def _make_tar_with_link(link_name: str, link_target: str, hard_link: bool = False) -> bytes:
    """Build a gzipped tar archive containing a single symlink or hardlink member."""
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo(name=link_name)
        info.type = tarfile.LNKTYPE if hard_link else tarfile.SYMTYPE
        info.linkname = link_target
        tar.addfile(info)
    return tar_buffer.getvalue()


# Test fixtures
@pytest.fixture
def sample_arxiv_id():
    """arXiv ID for testing. Use a paper known to have source files."""
    return "2305.18290"  # DPO paper - known to have source files

@pytest.fixture(autouse=True)
def temp_cache_dir(tmp_path):
    """Automatically use a temporary directory for all tests."""
    cache_dir = tmp_path / "arxiv-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir

# Test core functions
def test_get_default_cache_dir():
    cache_dir = get_default_cache_dir()
    assert isinstance(cache_dir, Path)
    if os.name == 'nt':  # Windows
        assert 'AppData/Local' in str(cache_dir)
    else:  # Unix/Linux/MacOS
        assert '.cache' in str(cache_dir)


def test_source_availability():
    """Test checking source availability for different papers."""
    # Paper known to have source files
    assert check_source_available("2305.18290")  # DPO paper
    # Paper known to not have source files
    assert not check_source_available("2412.14370")  # Patent paper
    # Invalid arxiv ID
    assert not check_source_available("invalid-id")


def test_download_arxiv_source(sample_arxiv_id, temp_cache_dir):
    """Test downloading source files."""
    # Test fresh download
    assert download_arxiv_source(sample_arxiv_id, str(temp_cache_dir))
    
    # Check if files were downloaded
    directory = temp_cache_dir / sample_arxiv_id
    assert directory.exists(), "Download directory not found"
    assert any(f.endswith('.tex') for f in os.listdir(directory)), "No .tex files found"

    # Test cache behavior - should redownload by default
    first_mtime = os.path.getmtime(directory)
    assert download_arxiv_source(sample_arxiv_id, str(temp_cache_dir))
    second_mtime = os.path.getmtime(directory)
    assert second_mtime > first_mtime, "File should have been redownloaded"

    # Test with use_cache=True
    assert download_arxiv_source(sample_arxiv_id, str(temp_cache_dir), use_cache=True)
    third_mtime = os.path.getmtime(directory)
    assert third_mtime == second_mtime, "File should have been cached"


def test_process_latex_source(sample_arxiv_id, temp_cache_dir):
    """Test processing LaTeX source with and without comments."""
    # Test with comments
    result = process_latex_source(
        sample_arxiv_id,
        keep_comments=True,
        cache_dir=str(temp_cache_dir)
    )
    assert result is not None
    assert "\\documentclass" in result
    
    # Test without comments
    result = process_latex_source(
        sample_arxiv_id,
        keep_comments=False,
        cache_dir=str(temp_cache_dir)
    )
    assert result is not None
    assert "\\documentclass" in result
    
    # Check comment removal
    lines = result.split('\n')
    for line in lines:
        if '%' in line:
            # Allow \% escaped percent signs
            index = line.find('%')
            if index > 0 and line[index - 1] == '\\':
                continue
            assert False, f"Found unexpected comment in line: {line}"


def test_remove_comments_from_lines():
    """Test comment removal functionality."""
    test_cases = [
        ("No comments", "No comments"),
        ("Line with % comment", "Line with"),
        ("% Full comment line", ""),
        ("Command \\% not comment", "Command \\% not comment"),
        ("Multiple % comments % here", "Multiple"),
        ("Line with both \\% and % real comment", "Line with both \\% and"),
    ]

    for input_text, expected in test_cases:
        assert remove_comments_from_lines(input_text).rstrip() == expected


def test_remove_iffalse_blocks():
    """Test removal of \\iffalse...\\fi blocks."""
    # Single line
    assert remove_comments_from_lines("before \\iffalse hidden \\fi after") == "before  after"

    # Multi-line block
    input_text = "before\n\\iffalse\nhidden\ncontent\n\\fi\nafter"
    result = remove_comments_from_lines(input_text)
    assert "hidden" not in result
    assert "before" in result
    assert "after" in result

    # Multiple blocks
    input_text = "a \\iffalse x \\fi b \\iffalse y \\fi c"
    result = remove_comments_from_lines(input_text)
    assert result == "a  b  c"


def test_find_main_tex(temp_cache_dir):
    """Test finding the main tex file."""
    # Create test files
    tex_dir = temp_cache_dir / "test_tex"
    tex_dir.mkdir(parents=True)
    
    # Create a main file with \documentclass
    main_file = tex_dir / "main.tex"
    main_file.write_text("\\documentclass{article}")
    
    # Create another .tex file without \documentclass
    other_file = tex_dir / "other.tex"
    other_file.write_text("Some content")
    
    # Test finding main file
    found_main = find_main_tex(str(tex_dir))
    assert found_main == "main.tex"


def test_find_main_tex_in_subdirectory(temp_cache_dir):
    """Test finding main tex file in a subdirectory."""
    # Create test directory with subdirectory
    tex_dir = temp_cache_dir / "test_tex_subdir"
    tex_dir.mkdir(parents=True)
    subdir = tex_dir / "paper"
    subdir.mkdir()

    # Create main.tex in subdirectory
    main_file = subdir / "main.tex"
    main_file.write_text("\\documentclass{article}\n\\begin{document}\nHello\n\\end{document}")

    # Test finding main file in subdirectory
    found_main = find_main_tex(str(tex_dir))
    assert found_main == os.path.join("paper", "main.tex")


def test_commented_input_commands(temp_cache_dir):
    """Test that commented-out \\include and \\input commands are ignored."""
    # Create test directory and files
    tex_dir = temp_cache_dir / "test_commented_input"
    tex_dir.mkdir(parents=True)
    
    # Create a main file with both regular and commented-out input commands
    main_file = tex_dir / "main.tex"
    main_content = """\\documentclass{article}
\\begin{document}
% This is a comment with \\input{commented_file1}
Regular text
\\input{existing_file}
More text
% Another comment with \\include{commented_file2}
Text with escaped \\% and then % \\input{commented_file3}
% \\input{nonexistent_file}
\\end{document}
"""
    main_file.write_text(main_content)
    
    # Create the file that should be included
    existing_file = tex_dir / "existing_file.tex"
    existing_content = "This is content from the existing file."
    existing_file.write_text(existing_content)
    
    # Run the flatten_tex function
    result = flatten_tex(str(tex_dir), "main.tex")
    
    # Check that the existing file was included
    assert "This is content from the existing file." in result
    
    # Check that the commented-out input commands are still present but not processed
    assert "% This is a comment with \\input{commented_file1}" in result
    assert "% Another comment with \\include{commented_file2}" in result
    assert "Text with escaped \\% and then % \\input{commented_file3}" in result
    assert "% \\input{nonexistent_file}" in result
    
    # The commented files should not have been looked for
    # (if they were, there would be error logs, but we can't easily test for that)
    # So we'll check that the original text is preserved
    assert "\\input{commented_file1}" in result
    assert "\\include{commented_file2}" in result
    assert "\\input{commented_file3}" in result
    assert "\\input{nonexistent_file}" in result


def test_remove_appendix():
    """Test appendix removal functionality."""
    test_cases = [
        # Basic appendix removal
        (
            "Main content\n\n\\appendix\nAppendix content",
            "Main content"
        ),
        # No appendix to remove
        (
            "Main content only",
            "Main content only"
        ),
        # Appendix with sections
        (
            "Introduction\n\\section{Method}\nContent\n\\appendix\n\\section{Additional Info}\nMore stuff",
            "Introduction\n\\section{Method}\nContent"
        ),
        # Multiple appendix commands (should remove from first one)
        (
            "Content\n\\appendix\nFirst appendix\n\\appendix\nSecond appendix",
            "Content"
        ),
        # Appendix at the beginning
        (
            "\\appendix\nAll appendix content",
            ""
        ),
    ]
    
    for input_text, expected in test_cases:
        result = remove_appendix(input_text)
        assert result == expected, f"Failed for input: {input_text}"


def test_process_latex_with_appendix_removal(sample_arxiv_id, temp_cache_dir):
    """Test processing LaTeX source with appendix removal."""
    # Test with appendix removal
    result = process_latex_source(
        sample_arxiv_id,
        keep_comments=True,
        cache_dir=str(temp_cache_dir),
        remove_appendix_section=True
    )
    assert result is not None
    assert "\\documentclass" in result
    
    # Check that appendix was removed (if it existed)
    assert "\\appendix" not in result


def test_input_file_extensions(temp_cache_dir):
    """Test that input files with existing extensions are not modified."""
    # Create test directory and files
    tex_dir = temp_cache_dir / "test_extensions"
    tex_dir.mkdir(parents=True)
    
    # Create main file with various input commands
    main_file = tex_dir / "main.tex"
    main_content = """\\documentclass{article}
\\begin{document}
\\input{chapter1}
\\input{main.bbl}
\\input{mystyle.sty}
\\input{config.cls}
\\input{already.tex}
\\end{document}
"""
    main_file.write_text(main_content)
    
    # Create the files that should be included
    files_to_create = [
        ("chapter1.tex", "Chapter 1 content"),
        ("main.bbl", "Bibliography content"),
        ("mystyle.sty", "Style content"),
        ("config.cls", "Class content"),
        ("already.tex", "Already tex content"),
    ]
    
    for filename, content in files_to_create:
        file_path = tex_dir / filename
        file_path.write_text(content)
    
    # Run the flatten_tex function
    result = flatten_tex(str(tex_dir), "main.tex")
    
    # Check that all files were included correctly
    assert "Chapter 1 content" in result
    assert "Bibliography content" in result
    assert "Style content" in result
    assert "Class content" in result
    assert "Already tex content" in result


def test_input_file_with_dots_in_path(temp_cache_dir):
    """Test that \\input paths with dots (e.g. 3.5_dataset) resolve correctly."""
    tex_dir = temp_cache_dir / "test_dots"
    tex_dir.mkdir(parents=True)
    (tex_dir / "sections").mkdir()

    main_file = tex_dir / "main.tex"
    main_file.write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\input{sections/3.5_dataset}\n"
        "\\end{document}\n"
    )

    (tex_dir / "sections" / "3.5_dataset.tex").write_text("Dataset section content")

    result = flatten_tex(str(tex_dir), "main.tex")
    assert "Dataset section content" in result


def test_extract_arxiv_id():
    """Test extracting arxiv ID from URLs and plain IDs."""
    # Plain IDs should be returned as-is
    assert extract_arxiv_id("2505.18102") == "2505.18102"
    assert extract_arxiv_id("2401.12345") == "2401.12345"

    # Extract from abs URLs
    assert extract_arxiv_id("https://arxiv.org/abs/2505.18102") == "2505.18102"
    assert extract_arxiv_id("http://arxiv.org/abs/2505.18102") == "2505.18102"

    # Extract from pdf URLs
    assert extract_arxiv_id("https://arxiv.org/pdf/2505.18102") == "2505.18102"
    assert extract_arxiv_id("https://arxiv.org/pdf/2505.18102.pdf") == "2505.18102"

    # Strip version suffixes
    assert extract_arxiv_id("https://arxiv.org/abs/2505.18102v1") == "2505.18102"
    assert extract_arxiv_id("https://arxiv.org/abs/2505.18102v2") == "2505.18102"
    assert extract_arxiv_id("https://arxiv.org/pdf/2505.18102v3.pdf") == "2505.18102"

    # Non-arxiv input returned as-is
    assert extract_arxiv_id("invalid") == "invalid"
    assert extract_arxiv_id("https://example.com/2505.18102") == "https://example.com/2505.18102"


def test_list_sections():
    """Test listing section names."""
    text = r"""
\section{Introduction}
Some intro text.
\section{Methods}
Some methods text.
\subsection{Data}
Data description.
\section*{Acknowledgments}
Thanks.
"""
    sections = list_sections(text)
    assert sections == ["Introduction", "Methods", "Acknowledgments"]


def test_extract_section():
    """Test extracting a specific section."""
    text = r"""
\section{Introduction}
Intro content here.
\section{Methods}
Methods content here.
\subsection{Data Collection}
Data info.
\section{Results}
Results here.
"""
    # Extract Methods section (should include subsection)
    methods = extract_section(text, "Methods")
    assert methods is not None
    assert "Methods content here." in methods
    assert "Data Collection" in methods
    assert "Data info." in methods
    assert "Results here." not in methods

    # Extract non-existent section
    assert extract_section(text, "Discussion") is None

    # Extract last section
    results = extract_section(text, "Results")
    assert results is not None
    assert "Results here." in results


def test_parse_section_tree():
    """Test parsing LaTeX into a hierarchical section tree."""
    text = r"""
\section{Introduction}
Intro text.
\subsection{Background}
Background text.
\subsection{Motivation}
Motivation text.
\section{Methods}
Methods text.
\subsection{Background}
Methods background.
\subsubsection{Details}
Details text.
\subsection{Data Collection}
Data text.
\section{Results}
Results text.
"""
    tree = parse_section_tree(text)

    # Should have 3 top-level sections
    assert len(tree) == 3
    assert tree[0].name == "Introduction"
    assert tree[1].name == "Methods"
    assert tree[2].name == "Results"

    # Introduction should have 2 subsections
    assert len(tree[0].children) == 2
    assert tree[0].children[0].name == "Background"
    assert tree[0].children[1].name == "Motivation"

    # Methods should have 2 subsections
    assert len(tree[1].children) == 2
    assert tree[1].children[0].name == "Background"
    assert tree[1].children[1].name == "Data Collection"

    # Methods > Background should have 1 subsubsection
    assert len(tree[1].children[0].children) == 1
    assert tree[1].children[0].children[0].name == "Details"

    # Results should have no subsections
    assert len(tree[2].children) == 0


def test_parse_section_tree_levels():
    """Test that section levels are correctly assigned."""
    text = r"""
\section{Sec}
\subsection{Subsec}
\subsubsection{Subsubsec}
"""
    tree = parse_section_tree(text)

    assert tree[0].level == 0
    assert tree[0].children[0].level == 1
    assert tree[0].children[0].children[0].level == 2


def test_format_section_tree():
    """Test formatting section tree with indentation."""
    text = r"""
\section{Introduction}
\subsection{Background}
\section{Methods}
\subsection{Data}
\subsubsection{Collection}
"""
    tree = parse_section_tree(text)
    output = format_section_tree(tree)

    lines = output.split('\n')
    assert lines[0] == "Introduction"
    assert lines[1] == "  Background"
    assert lines[2] == "Methods"
    assert lines[3] == "  Data"
    assert lines[4] == "    Collection"


def test_find_all_by_name():
    """Test finding all paths to sections with a given name."""
    text = r"""
\section{Introduction}
\subsection{Background}
\section{Methods}
\subsection{Background}
\section{Results}
"""
    tree = parse_section_tree(text)

    # Background appears twice under different parents
    paths = find_all_by_name(tree, "Background")
    assert len(paths) == 2
    assert "Introduction > Background" in paths
    assert "Methods > Background" in paths

    # Unique name
    paths = find_all_by_name(tree, "Results")
    assert paths == ["Results"]

    # Non-existent name
    paths = find_all_by_name(tree, "Discussion")
    assert paths == []


def test_find_section_by_path_simple():
    """Test finding section by simple name."""
    text = r"""
\section{Introduction}
\section{Methods}
\subsection{Data}
"""
    tree = parse_section_tree(text)

    # Find by simple name
    node = find_section_by_path(tree, "Introduction")
    assert node is not None
    assert node.name == "Introduction"

    # Find subsection by simple name
    node = find_section_by_path(tree, "Data")
    assert node is not None
    assert node.name == "Data"


def test_find_section_by_path_notation():
    """Test finding section by path notation."""
    text = r"""
\section{Introduction}
\subsection{Background}
\section{Methods}
\subsection{Background}
"""
    tree = parse_section_tree(text)

    # Find by path notation
    node = find_section_by_path(tree, "Introduction > Background")
    assert node is not None
    assert node.name == "Background"
    assert node.parent.name == "Introduction"

    node = find_section_by_path(tree, "Methods > Background")
    assert node is not None
    assert node.name == "Background"
    assert node.parent.name == "Methods"


def test_find_section_by_path_not_found():
    """Test that non-existent paths return None."""
    text = r"""
\section{Introduction}
\subsection{Background}
"""
    tree = parse_section_tree(text)

    assert find_section_by_path(tree, "NonExistent") is None
    assert find_section_by_path(tree, "Introduction > NonExistent") is None
    assert find_section_by_path(tree, "NonExistent > Background") is None


def test_extract_section_with_path():
    """Test extracting section using path notation."""
    text = r"""
\section{Introduction}
Intro text.
\subsection{Background}
Intro background.
\section{Methods}
Methods text.
\subsection{Background}
Methods background.
\section{Results}
Results text.
"""
    # Extract using path notation
    content = extract_section(text, "Introduction > Background")
    assert content is not None
    assert "Intro background." in content
    assert "Methods background." not in content

    content = extract_section(text, "Methods > Background")
    assert content is not None
    assert "Methods background." in content
    assert "Intro background." not in content


def test_extract_subsection_boundaries():
    """Test that subsection extraction stops at correct boundary."""
    text = r"""
\section{Methods}
Methods intro.
\subsection{First}
First content.
\subsection{Second}
Second content.
\section{Results}
Results content.
"""
    # Extract first subsection - should stop at second subsection
    content = extract_section(text, "First")
    assert content is not None
    assert "First content." in content
    assert "Second content." not in content

    # Extract second subsection - should stop at Results section
    content = extract_section(text, "Second")
    assert content is not None
    assert "Second content." in content
    assert "Results content." not in content


def test_extract_section_includes_subsections():
    """Test that extracting a section includes all its subsections."""
    text = r"""
\section{Methods}
Methods intro.
\subsection{Data}
Data info.
\subsubsection{Collection}
Collection details.
\subsection{Analysis}
Analysis info.
\section{Results}
Results content.
"""
    content = extract_section(text, "Methods")
    assert content is not None
    assert "Methods intro." in content
    assert "Data info." in content
    assert "Collection details." in content
    assert "Analysis info." in content
    assert "Results content." not in content


def test_section_tree_with_starred_sections():
    """Test that starred sections are correctly parsed."""
    text = r"""
\section*{Introduction}
Intro.
\subsection*{Background}
Background.
\section{Methods}
Methods.
"""
    tree = parse_section_tree(text)

    assert len(tree) == 2
    assert tree[0].name == "Introduction"
    assert tree[0].children[0].name == "Background"
    assert tree[1].name == "Methods"


def test_cli_force_download_flag(temp_cache_dir, monkeypatch, capsys):
    """Test that --force-download passes use_cache=False to process_latex_source."""
    captured_kwargs = {}

    def mock_process(**kwargs):
        captured_kwargs.update(kwargs)
        return "\\documentclass{article}\n\\begin{document}Hello\\end{document}"

    monkeypatch.setattr("arxiv_to_prompt.cli.process_latex_source", mock_process)

    # Default behavior: use_cache should be True
    monkeypatch.setattr("sys.argv", ["arxiv-to-prompt", "2303.08774", "--cache-dir", str(temp_cache_dir)])
    main()
    assert captured_kwargs["use_cache"] is True

    # With --force-download: use_cache should be False
    captured_kwargs.clear()
    monkeypatch.setattr("sys.argv", ["arxiv-to-prompt", "2303.08774", "--cache-dir", str(temp_cache_dir), "--force-download"])
    main()
    assert captured_kwargs["use_cache"] is False


def test_cli_copy_flag(temp_cache_dir, monkeypatch, capsys):
    """Test that --copy copies output to clipboard instead of printing."""
    mock_content = "\\documentclass{article}\n\\begin{document}Hello\\end{document}"

    def mock_process(**kwargs):
        return mock_content

    monkeypatch.setattr("arxiv_to_prompt.cli.process_latex_source", mock_process)

    copied_text = {}

    def mock_pyperclip_copy(text):
        copied_text["value"] = text

    import pyperclip
    monkeypatch.setattr(pyperclip, "copy", mock_pyperclip_copy)

    # With --copy: should copy to clipboard, not print to stdout
    monkeypatch.setattr("sys.argv", ["arxiv-to-prompt", "2303.08774", "--cache-dir", str(temp_cache_dir), "--copy"])
    main()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Copied to clipboard." in captured.err
    assert copied_text["value"] == mock_content

    # With -c shorthand: same behavior
    copied_text.clear()
    monkeypatch.setattr("sys.argv", ["arxiv-to-prompt", "2303.08774", "--cache-dir", str(temp_cache_dir), "-c"])
    main()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert copied_text["value"] == mock_content

    # Without --copy: should print to stdout
    monkeypatch.setattr("sys.argv", ["arxiv-to-prompt", "2303.08774", "--cache-dir", str(temp_cache_dir)])
    main()
    captured = capsys.readouterr()
    assert mock_content in captured.out


def test_use_cache_skips_network_when_cache_is_valid(temp_cache_dir, monkeypatch):
    """When cache is already valid, use_cache=True should avoid network calls."""
    arxiv_id = "9999.00001"
    cache_dir = temp_cache_dir / arxiv_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "main.tex").write_text("\\documentclass{article}")
    (cache_dir / _CACHE_COMPLETE_MARKER).write_text("ok\n")

    def _should_not_be_called(*args, **kwargs):
        raise AssertionError("Network path should not be called for valid cache")

    monkeypatch.setattr("arxiv_to_prompt.core.check_source_available", _should_not_be_called)
    monkeypatch.setattr("arxiv_to_prompt.core.requests.get", _should_not_be_called)

    assert download_arxiv_source(arxiv_id, str(temp_cache_dir), use_cache=True)


def test_use_cache_repairs_incomplete_cache(temp_cache_dir, monkeypatch):
    """Incomplete cache directories should be rebuilt when use_cache=True."""
    arxiv_id = "9999.00002"
    cache_dir = temp_cache_dir / arxiv_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "partial.txt").write_text("incomplete")

    tar_bytes = _make_tar_bytes({"paper/main.tex": "\\documentclass{article}"})
    monkeypatch.setattr("arxiv_to_prompt.core.check_source_available", lambda _id: True)
    monkeypatch.setattr("arxiv_to_prompt.core.requests.get", lambda *a, **k: _FakeResponse(tar_bytes))

    assert download_arxiv_source(arxiv_id, str(temp_cache_dir), use_cache=True)
    assert _is_valid_cache_dir(cache_dir)


def test_download_parallel_same_id_no_race_crash(temp_cache_dir, monkeypatch):
    """Concurrent downloads of the same ID should not fail due to races."""
    arxiv_id = "9999.00003"
    tar_bytes = _make_tar_bytes({"main.tex": "\\documentclass{article}"})

    monkeypatch.setattr("arxiv_to_prompt.core.check_source_available", lambda _id: True)
    monkeypatch.setattr("arxiv_to_prompt.core.requests.get", lambda *a, **k: _FakeResponse(tar_bytes))

    def _run_once(_):
        return download_arxiv_source(
            arxiv_id,
            str(temp_cache_dir),
            use_cache=False,
            lock_timeout_seconds=10.0,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(_run_once, range(16)))

    assert all(results)
    assert _is_valid_cache_dir(temp_cache_dir / arxiv_id)


def test_download_lock_timeout_returns_false(temp_cache_dir, monkeypatch):
    """Caller should get False when lock wait times out."""
    arxiv_id = "9999.00004"
    lock_path = _get_lock_path(temp_cache_dir, arxiv_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("arxiv_to_prompt.core.check_source_available", lambda _id: True)
    monkeypatch.setattr(
        "arxiv_to_prompt.core.requests.get",
        lambda *a, **k: _FakeResponse(_make_tar_bytes({"main.tex": "\\documentclass{article}"})),
    )

    with FileLock(str(lock_path), timeout=1):
        assert not download_arxiv_source(
            arxiv_id,
            str(temp_cache_dir),
            use_cache=False,
            lock_timeout_seconds=0.01,
        )


def test_download_rejects_unsafe_tar_paths(temp_cache_dir, monkeypatch):
    """Path traversal entries in tar archives should be rejected."""
    arxiv_id = "9999.00005"
    tar_bytes = _make_tar_bytes({"../escape.tex": "bad"})

    monkeypatch.setattr("arxiv_to_prompt.core.check_source_available", lambda _id: True)
    monkeypatch.setattr("arxiv_to_prompt.core.requests.get", lambda *a, **k: _FakeResponse(tar_bytes))

    assert not download_arxiv_source(arxiv_id, str(temp_cache_dir), use_cache=False)
    assert not (temp_cache_dir / arxiv_id).exists()


def test_download_rejects_symlink_tar_entries(temp_cache_dir, monkeypatch):
    """Symlink entries in tar archives should be rejected."""
    arxiv_id = "9999.00006"
    tar_bytes = _make_tar_with_link("sym.tex", "../escape.tex", hard_link=False)

    monkeypatch.setattr("arxiv_to_prompt.core.check_source_available", lambda _id: True)
    monkeypatch.setattr("arxiv_to_prompt.core.requests.get", lambda *a, **k: _FakeResponse(tar_bytes))

    assert not download_arxiv_source(arxiv_id, str(temp_cache_dir), use_cache=False)
    assert not (temp_cache_dir / arxiv_id).exists()


def test_download_rejects_hardlink_tar_entries(temp_cache_dir, monkeypatch):
    """Hardlink entries in tar archives should be rejected."""
    arxiv_id = "9999.00007"
    tar_bytes = _make_tar_with_link("hard.tex", "target.tex", hard_link=True)

    monkeypatch.setattr("arxiv_to_prompt.core.check_source_available", lambda _id: True)
    monkeypatch.setattr("arxiv_to_prompt.core.requests.get", lambda *a, **k: _FakeResponse(tar_bytes))

    assert not download_arxiv_source(arxiv_id, str(temp_cache_dir), use_cache=False)
    assert not (temp_cache_dir / arxiv_id).exists()


def test_old_marker_is_not_accepted_without_legacy_support(temp_cache_dir, monkeypatch):
    """Old cache marker '.complete' should be treated as invalid."""
    arxiv_id = "9999.00008"
    cache_dir = temp_cache_dir / arxiv_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "main.tex").write_text("\\documentclass{article}")
    (cache_dir / ".complete").write_text("ok\n")

    assert not _is_valid_cache_dir(cache_dir)

    tar_bytes = _make_tar_bytes({"fresh.tex": "\\documentclass{article}"})
    monkeypatch.setattr("arxiv_to_prompt.core.check_source_available", lambda _id: True)
    monkeypatch.setattr("arxiv_to_prompt.core.requests.get", lambda *a, **k: _FakeResponse(tar_bytes))

    assert download_arxiv_source(arxiv_id, str(temp_cache_dir), use_cache=True)
    assert (cache_dir / _CACHE_COMPLETE_MARKER).exists()
    assert not (cache_dir / ".complete").exists()


def test_download_rolls_back_if_publish_swap_fails(temp_cache_dir, monkeypatch):
    """If publish swap fails, old cache should be restored."""
    arxiv_id = "9999.00009"
    cache_dir = temp_cache_dir / arxiv_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "old.tex").write_text("\\documentclass{article}\nold")
    (cache_dir / _CACHE_COMPLETE_MARKER).write_text("ok\n")

    tar_bytes = _make_tar_bytes({"new.tex": "\\documentclass{article}\nnew"})
    monkeypatch.setattr("arxiv_to_prompt.core.check_source_available", lambda _id: True)
    monkeypatch.setattr("arxiv_to_prompt.core.requests.get", lambda *a, **k: _FakeResponse(tar_bytes))

    original_replace = os.replace
    replace_calls = {"count": 0}

    def _flaky_replace(src, dst):
        replace_calls["count"] += 1
        if replace_calls["count"] == 2:
            raise OSError("simulated publish failure")
        return original_replace(src, dst)

    monkeypatch.setattr("arxiv_to_prompt.core.os.replace", _flaky_replace)

    assert not download_arxiv_source(arxiv_id, str(temp_cache_dir), use_cache=False)
    assert (cache_dir / "old.tex").exists()
    assert not (cache_dir / "new.tex").exists()
    assert _is_valid_cache_dir(cache_dir)
    assert not list(temp_cache_dir.glob(f"{arxiv_id}.old.*"))


def test_publish_succeeds_even_if_old_backup_cleanup_fails(temp_cache_dir, monkeypatch, caplog):
    """Backup cleanup failure should warn but still succeed."""
    arxiv_id = "9999.00010"
    cache_dir = temp_cache_dir / arxiv_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "old.tex").write_text("\\documentclass{article}\nold")
    (cache_dir / _CACHE_COMPLETE_MARKER).write_text("ok\n")

    tar_bytes = _make_tar_bytes({"new.tex": "\\documentclass{article}\nnew"})
    monkeypatch.setattr("arxiv_to_prompt.core.check_source_available", lambda _id: True)
    monkeypatch.setattr("arxiv_to_prompt.core.requests.get", lambda *a, **k: _FakeResponse(tar_bytes))

    original_rmtree = shutil.rmtree

    def _flaky_rmtree(path, *args, **kwargs):
        path_obj = Path(path)
        if path_obj.name.startswith(f"{arxiv_id}.old."):
            raise PermissionError("simulated busy backup directory")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr("arxiv_to_prompt.core.shutil.rmtree", _flaky_rmtree)

    with caplog.at_level("WARNING"):
        assert download_arxiv_source(arxiv_id, str(temp_cache_dir), use_cache=False)

    assert (cache_dir / "new.tex").exists()
    assert list(temp_cache_dir.glob(f"{arxiv_id}.old.*"))
    assert "Failed to remove directory" in caplog.text


# ── Figure path extraction tests ──────────────────────────────────────


def test_extract_figure_paths_basic(temp_cache_dir):
    """Test basic extraction with explicit file extensions."""
    tex_dir = temp_cache_dir / "test_figures"
    tex_dir.mkdir(parents=True)
    (tex_dir / "fig1.png").write_bytes(b"fake png")
    (tex_dir / "fig2.pdf").write_bytes(b"fake pdf")

    text = r"""
\begin{figure}
\includegraphics{fig1.png}
\end{figure}
\begin{figure}
\includegraphics{fig2.pdf}
\end{figure}
"""
    paths = extract_figure_paths(text, str(tex_dir))
    assert len(paths) == 2
    assert paths[0].endswith("fig1.png")
    assert paths[1].endswith("fig2.pdf")
    # All paths should be absolute
    for p in paths:
        assert os.path.isabs(p)


def test_extract_figure_paths_extension_resolution(temp_cache_dir):
    """Test that omitted extensions are resolved in priority order."""
    tex_dir = temp_cache_dir / "test_ext"
    tex_dir.mkdir(parents=True)
    (tex_dir / "plot.png").write_bytes(b"fake png")

    text = r"\includegraphics{plot}"
    paths = extract_figure_paths(text, str(tex_dir))
    assert len(paths) == 1
    assert paths[0].endswith("plot.png")


def test_extract_figure_paths_extension_priority(temp_cache_dir):
    """Test that .pdf is preferred over .png when both exist (pdf comes first)."""
    tex_dir = temp_cache_dir / "test_priority"
    tex_dir.mkdir(parents=True)
    (tex_dir / "chart.pdf").write_bytes(b"fake pdf")
    (tex_dir / "chart.png").write_bytes(b"fake png")

    text = r"\includegraphics{chart}"
    paths = extract_figure_paths(text, str(tex_dir))
    assert len(paths) == 1
    assert paths[0].endswith("chart.pdf")


def test_extract_figure_paths_with_graphicspath(temp_cache_dir):
    """Test that \\graphicspath directories are searched."""
    tex_dir = temp_cache_dir / "test_gpath"
    tex_dir.mkdir(parents=True)
    images_dir = tex_dir / "images"
    images_dir.mkdir()
    (images_dir / "diagram.pdf").write_bytes(b"fake pdf")

    text = r"""
\graphicspath{{images/}}
\includegraphics{diagram}
"""
    paths = extract_figure_paths(text, str(tex_dir))
    assert len(paths) == 1
    assert "images" in paths[0]
    assert paths[0].endswith("diagram.pdf")


def test_extract_figure_paths_with_options(temp_cache_dir):
    """Test that \\includegraphics with optional arguments is handled."""
    tex_dir = temp_cache_dir / "test_opts"
    tex_dir.mkdir(parents=True)
    (tex_dir / "fig.png").write_bytes(b"fake")

    text = r"""
\includegraphics[width=0.5\textwidth]{fig.png}
\includegraphics[scale=2,angle=90]{fig.png}
\includegraphics {fig.png}
"""
    paths = extract_figure_paths(text, str(tex_dir))
    # All three reference the same file, so deduplication should yield 1
    assert len(paths) == 1
    assert paths[0].endswith("fig.png")


def test_extract_figure_paths_deduplication(temp_cache_dir):
    """Test that duplicate references yield a single path."""
    tex_dir = temp_cache_dir / "test_dedup"
    tex_dir.mkdir(parents=True)
    (tex_dir / "same.png").write_bytes(b"fake")

    text = r"""
\includegraphics{same.png}
\includegraphics{same.png}
\includegraphics{same.png}
"""
    paths = extract_figure_paths(text, str(tex_dir))
    assert len(paths) == 1


def test_extract_figure_paths_nonexistent_files(temp_cache_dir):
    """Test that non-existent files are silently skipped."""
    tex_dir = temp_cache_dir / "test_missing"
    tex_dir.mkdir(parents=True)

    text = r"\includegraphics{does_not_exist.png}"
    paths = extract_figure_paths(text, str(tex_dir))
    assert paths == []


def test_extract_figure_paths_skips_urls(temp_cache_dir):
    """Test that URL references are skipped."""
    tex_dir = temp_cache_dir / "test_urls"
    tex_dir.mkdir(parents=True)

    text = r"\includegraphics{https://example.com/fig.png}"
    paths = extract_figure_paths(text, str(tex_dir))
    assert paths == []


def test_extract_figure_paths_subdirectory(temp_cache_dir):
    """Test resolution of images in subdirectories."""
    tex_dir = temp_cache_dir / "test_subdir"
    tex_dir.mkdir(parents=True)
    figs_dir = tex_dir / "figures"
    figs_dir.mkdir()
    (figs_dir / "deep.jpg").write_bytes(b"fake")

    text = r"\includegraphics{figures/deep.jpg}"
    paths = extract_figure_paths(text, str(tex_dir))
    assert len(paths) == 1
    assert paths[0].endswith("deep.jpg")


def test_extract_figure_paths_comment_filtering(temp_cache_dir):
    """Test that figures in comments are excluded after comment removal."""
    tex_dir = temp_cache_dir / "test_comment_filter"
    tex_dir.mkdir(parents=True)
    (tex_dir / "visible.png").write_bytes(b"fake")
    (tex_dir / "hidden.png").write_bytes(b"fake")

    text = r"""
\includegraphics{visible.png}
% \includegraphics{hidden.png}
"""
    # First remove comments, then extract (as process_latex_source does)
    filtered = remove_comments_from_lines(text)
    paths = extract_figure_paths(filtered, str(tex_dir))
    assert len(paths) == 1
    assert paths[0].endswith("visible.png")


def test_extract_figure_paths_appendix_filtering(temp_cache_dir):
    """Test that figures in appendix are excluded after appendix removal."""
    tex_dir = temp_cache_dir / "test_appendix_filter"
    tex_dir.mkdir(parents=True)
    (tex_dir / "main_fig.png").write_bytes(b"fake")
    (tex_dir / "appendix_fig.png").write_bytes(b"fake")

    text = r"""
\includegraphics{main_fig.png}
\appendix
\includegraphics{appendix_fig.png}
"""
    filtered = remove_appendix(text)
    paths = extract_figure_paths(filtered, str(tex_dir))
    assert len(paths) == 1
    assert paths[0].endswith("main_fig.png")


def test_process_latex_source_figure_paths_only(temp_cache_dir):
    """Test process_latex_source with figure_paths_only=True."""
    tex_dir = temp_cache_dir / "test_process_figs"
    tex_dir.mkdir(parents=True)
    (tex_dir / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\includegraphics{plot.png}\n"
        "\\end{document}\n"
    )
    (tex_dir / "plot.png").write_bytes(b"fake png")

    result = process_latex_source(
        local_folder=str(tex_dir),
        figure_paths_only=True,
    )
    assert result is not None
    lines = result.strip().split("\n")
    assert len(lines) == 1
    assert lines[0].endswith("plot.png")
    # Should NOT contain LaTeX
    assert "\\documentclass" not in result


def test_process_latex_source_figure_paths_respects_filters(temp_cache_dir):
    """Test that figure_paths_only respects --no-comments and --no-appendix."""
    tex_dir = temp_cache_dir / "test_process_filter"
    tex_dir.mkdir(parents=True)
    (tex_dir / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\includegraphics{body.png}\n"
        "% \\includegraphics{commented.png}\n"
        "\\appendix\n"
        "\\includegraphics{appendix.png}\n"
        "\\end{document}\n"
    )
    (tex_dir / "body.png").write_bytes(b"fake")
    (tex_dir / "commented.png").write_bytes(b"fake")
    (tex_dir / "appendix.png").write_bytes(b"fake")

    result = process_latex_source(
        local_folder=str(tex_dir),
        figure_paths_only=True,
        keep_comments=False,
        remove_appendix_section=True,
    )
    assert result is not None
    lines = result.strip().split("\n")
    assert len(lines) == 1
    assert lines[0].endswith("body.png")


def test_process_latex_source_figure_paths_no_images(temp_cache_dir):
    """Test that figure_paths_only returns None when no images are found."""
    tex_dir = temp_cache_dir / "test_no_figs"
    tex_dir.mkdir(parents=True)
    (tex_dir / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\nHello\n\\end{document}\n"
    )

    result = process_latex_source(
        local_folder=str(tex_dir),
        figure_paths_only=True,
    )
    assert result is None


def test_cli_figure_paths_flag(temp_cache_dir, monkeypatch, capsys):
    """Test that --figure-paths passes figure_paths_only=True to process_latex_source."""
    captured_kwargs = {}

    def mock_process(**kwargs):
        captured_kwargs.update(kwargs)
        return "/tmp/fig1.png\n/tmp/fig2.pdf"

    monkeypatch.setattr("arxiv_to_prompt.cli.process_latex_source", mock_process)

    monkeypatch.setattr("sys.argv", [
        "arxiv-to-prompt", "2303.08774",
        "--cache-dir", str(temp_cache_dir),
        "--figure-paths",
    ])
    main()
    assert captured_kwargs["figure_paths_only"] is True

    # Without flag: should be False
    captured_kwargs.clear()
    monkeypatch.setattr("sys.argv", [
        "arxiv-to-prompt", "2303.08774",
        "--cache-dir", str(temp_cache_dir),
    ])
    main()
    assert captured_kwargs["figure_paths_only"] is False
