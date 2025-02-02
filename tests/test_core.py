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
)

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

