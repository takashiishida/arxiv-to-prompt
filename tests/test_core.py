import os
from pathlib import Path
import pytest
from arxiv_to_prompt.core import (
    process_latex_source,
    download_arxiv_source,
    get_default_cache_dir,
    find_main_tex,
    remove_comments_from_lines,
    check_source_available,
    flatten_tex,
    remove_appendix,
)
from arxiv_to_prompt.cli import extract_arxiv_id

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
