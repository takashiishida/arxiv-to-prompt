import logging
import os
import tarfile
import shutil
from typing import Optional, List
from dataclasses import dataclass, field
import re
from pathlib import Path
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_default_cache_dir() -> Path:
    """Get the default cache directory for downloaded files."""
    # Use standard OS-specific cache directory
    if os.name == 'nt':  # Windows
        base_dir = Path(os.environ.get('LOCALAPPDATA', '~'))
    else:  # Unix/Linux/MacOS
        base_dir = Path(os.environ.get('XDG_CACHE_HOME', '~/.cache'))
    
    cache_dir = base_dir.expanduser() / 'arxiv-to-prompt'
    return cache_dir


def download_arxiv_source(arxiv_id: str, cache_dir: Optional[str] = None, use_cache: bool = False) -> bool:
    """
    Download source files from arXiv.
    
    Args:
        arxiv_id: The arXiv ID of the paper
        cache_dir: Custom directory to store downloaded files
        use_cache: Whether to use cached files if they exist (default: False)
    
    Returns:
        bool: True if download successful, False if failed (including when source not available)
    """
    try:
        # First check if tex source is available
        if not check_source_available(arxiv_id):
            logging.warning(f"TeX source files not available for {arxiv_id}")
            return False
        
        # Use provided cache_dir or default
        base_dir = Path(cache_dir) if cache_dir else get_default_cache_dir()
        
        # Always use latest version by not specifying version in URL
        url = f'https://arxiv.org/e-print/{arxiv_id}'
        
        # Set up directory
        directory = base_dir / arxiv_id
        if use_cache and directory.exists():
            logging.info(f"Directory {directory} already exists, using cached version.")
            return True
        
        # Clean up existing directory if not using cache
        if directory.exists():
            shutil.rmtree(directory)
        
        # Create temporary directory for tar.gz file
        temp_dir = base_dir / 'temp'
        temp_dir.mkdir(parents=True, exist_ok=True)
        tar_path = temp_dir / f'{arxiv_id}.tar.gz'
        
        # Download the file
        logging.info(f"Downloading source from {url}")
        headers = {
            'User-Agent': 'Mozilla/5.0'
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Save and extract
        with open(tar_path, 'wb') as file:
            file.write(response.content)
        
        directory.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tar_path) as tar:
            tar.extractall(path=directory)
        
        # Clean up temporary files
        tar_path.unlink()
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
            
        logging.info(f"Source files downloaded and extracted to {directory}/")
        return True
        
    except Exception as e:
        logging.error(f"Error downloading/extracting source: {e}")
        if directory.exists():
            shutil.rmtree(directory)  # Clean up failed download
        return False

def find_main_tex(directory: str) -> Optional[str]:
    """
    Find the main .tex file containing documentclass.
    Searches recursively through subdirectories.
    First checks for common naming conventions (main.tex, paper.tex, index.tex).
    If none found, returns the path of the longest .tex file containing documentclass,
    since shorter files are typically conference templates or supplementary documents
    rather than the main manuscript.
    """
    common_names = ['main.tex', 'paper.tex', 'index.tex']
    main_tex_file = None
    max_line_count = 0

    # Walk through directory and subdirectories
    for root, dirs, files in os.walk(directory):
        rel_root = os.path.relpath(root, directory)

        # First pass: check for common naming conventions
        for file_name in files:
            if file_name in common_names:
                file_path = os.path.join(root, file_name)
                try:
                    with open(file_path, 'r', encoding='utf-8') as file:
                        lines = file.readlines()
                        if any('\\documentclass' in line for line in lines):
                            if rel_root == '.':
                                return file_name
                            return os.path.join(rel_root, file_name)
                except Exception as e:
                    logging.warning(f"Could not read file {file_path}: {e}")

    # Second pass: find the longest .tex file containing documentclass
    for root, dirs, files in os.walk(directory):
        rel_root = os.path.relpath(root, directory)

        for file_name in files:
            if file_name.endswith('.tex'):
                file_path = os.path.join(root, file_name)
                try:
                    with open(file_path, 'r', encoding='utf-8') as file:
                        lines = file.readlines()
                        if any('\\documentclass' in line for line in lines):
                            line_count = len(lines)
                            if line_count > max_line_count:
                                if rel_root == '.':
                                    main_tex_file = file_name
                                else:
                                    main_tex_file = os.path.join(rel_root, file_name)
                                max_line_count = line_count
                except Exception as e:
                    logging.warning(f"Could not read file {file_path}: {e}")

    return main_tex_file

def remove_comments_from_lines(text: str) -> str:
    """Remove LaTeX comments while preserving newlines."""
    # Remove \iffalse...\fi blocks (commonly used to comment out large sections)
    text = re.sub(r'\\iffalse\b.*?\\fi\b', '', text, flags=re.DOTALL)
    lines = text.split('\n')
    result = []
    for line in lines:
        # Skip pure comment lines
        if line.lstrip().startswith('%'):
            continue
        # Handle inline comments
        in_command = False
        cleaned_line = []
        for i, char in enumerate(line):
            if char == '\\':
                in_command = True
                cleaned_line.append(char)
            elif in_command:
                in_command = False
                cleaned_line.append(char)
            elif char == '%' and not in_command:
                break
            else:
                cleaned_line.append(char)
        result.append(''.join(cleaned_line).rstrip())
    return '\n'.join(result)

def remove_appendix(text: str) -> str:
    """Remove appendix section and everything after it."""
    # Find the position of \appendix command
    appendix_match = re.search(r'\\appendix\b', text)
    if appendix_match:
        return text[:appendix_match.start()].rstrip()
    return text


def list_sections(text: str) -> list:
    """Extract all section names from LaTeX content."""
    pattern = r'\\section\*?\{([^}]+)\}'
    return re.findall(pattern, text)


@dataclass
class SectionNode:
    """Represents a section/subsection/subsubsection in the LaTeX document tree."""
    level: int  # 0=section, 1=subsection, 2=subsubsection
    name: str
    start_pos: int
    end_pos: int = -1  # -1 means end of document
    children: List['SectionNode'] = field(default_factory=list)
    parent: Optional['SectionNode'] = None


def parse_section_tree(text: str) -> List[SectionNode]:
    """
    Build a hierarchical tree from LaTeX section commands.

    Returns a list of top-level section nodes, each containing their subsections as children.
    """
    # Match section, subsection, and subsubsection commands
    pattern = r'\\(section|subsection|subsubsection)\*?\{([^}]+)\}'

    level_map = {'section': 0, 'subsection': 1, 'subsubsection': 2}

    # Find all section commands with their positions
    matches = list(re.finditer(pattern, text))

    if not matches:
        return []

    # Create nodes for all sections
    all_nodes = []
    for match in matches:
        level = level_map[match.group(1)]
        name = match.group(2)
        start_pos = match.start()
        all_nodes.append(SectionNode(level=level, name=name, start_pos=start_pos))

    # Calculate end positions (each section ends where the next same-or-higher level starts)
    for i, node in enumerate(all_nodes):
        # Find next section at same or higher (lower number) level
        for j in range(i + 1, len(all_nodes)):
            if all_nodes[j].level <= node.level:
                node.end_pos = all_nodes[j].start_pos
                break
        # If no next section found at same/higher level, end at document end
        if node.end_pos == -1:
            node.end_pos = len(text)

    # Build tree structure
    root_nodes: List[SectionNode] = []
    section_stack: List[SectionNode] = []

    for node in all_nodes:
        # Pop from stack until we find a parent at a higher level
        while section_stack and section_stack[-1].level >= node.level:
            section_stack.pop()

        if section_stack:
            # This node is a child of the top of the stack
            node.parent = section_stack[-1]
            section_stack[-1].children.append(node)
        else:
            # This is a root node
            root_nodes.append(node)

        section_stack.append(node)

    return root_nodes


def format_section_tree(nodes: List[SectionNode], indent: int = 0) -> str:
    """
    Format section tree with indentation for display.

    Returns a string with each section name on its own line, indented by level.
    """
    lines = []
    for node in nodes:
        lines.append("  " * indent + node.name)
        if node.children:
            lines.append(format_section_tree(node.children, indent + 1))
    return "\n".join(lines)


def find_all_by_name(nodes: List[SectionNode], name: str, parent_path: str = "") -> List[str]:
    """
    Find all paths to sections with the given name.

    Returns a list of full paths (e.g., ["Introduction > Background", "Methods > Background"])
    """
    results = []
    for node in nodes:
        current_path = f"{parent_path} > {node.name}" if parent_path else node.name
        if node.name == name:
            results.append(current_path)
        if node.children:
            results.extend(find_all_by_name(node.children, name, current_path))
    return results


def find_section_by_path(nodes: List[SectionNode], path: str) -> Optional[SectionNode]:
    """
    Find a section by path notation (e.g., "Methods > Background").

    If path contains no " > ", searches for an exact name match at any level.
    If path contains " > ", follows the hierarchy.
    """
    parts = [p.strip() for p in path.split(" > ")]

    if len(parts) == 1:
        # Simple name lookup - find first match at any level
        def find_first(nodes: List[SectionNode], name: str) -> Optional[SectionNode]:
            for node in nodes:
                if node.name == name:
                    return node
                if node.children:
                    result = find_first(node.children, name)
                    if result:
                        return result
            return None
        return find_first(nodes, parts[0])

    # Path notation - follow the hierarchy
    current_nodes = nodes
    current_node = None

    for part in parts:
        found = None
        for node in current_nodes:
            if node.name == part:
                found = node
                break
        if not found:
            return None
        current_node = found
        current_nodes = found.children

    return current_node


def extract_section(text: str, section_path: str) -> Optional[str]:
    """
    Extract content of a specific section, subsection, or subsubsection.

    Args:
        text: The LaTeX content
        section_path: Section name or path (e.g., "Methods" or "Methods > Background")

    Returns:
        The section content including any subsections, or None if not found.
    """
    tree = parse_section_tree(text)
    node = find_section_by_path(tree, section_path)
    if not node:
        return None

    return text[node.start_pos:node.end_pos].rstrip()


def flatten_tex(directory: str, main_file: str) -> str:
    """Combine all tex files into one, resolving inputs."""
    def process_file(file_path: str, processed_files: set) -> str:
        if file_path in processed_files:
            return ""
        processed_files.add(file_path)
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Process \input and \include commands that are not commented out
            def replace_input(match):
                # Check if the match is preceded by a comment character
                line_start = content.rfind('\n', 0, match.start()) + 1
                line_prefix = content[line_start:match.start()]
                
                # If there's a % character in the line prefix that's not escaped,
                # this command is commented out, so return the original text
                comment_pos = -1
                i = 0
                while i < len(line_prefix):
                    if line_prefix[i] == '%':
                        # Check if the % is escaped with a backslash
                        if i > 0 and line_prefix[i-1] == '\\':
                            # Count backslashes before %
                            backslash_count = 0
                            j = i - 1
                            while j >= 0 and line_prefix[j] == '\\':
                                backslash_count += 1
                                j -= 1
                            # If odd number of backslashes, % is escaped
                            if backslash_count % 2 == 1:
                                i += 1
                                continue
                        comment_pos = i
                        break
                    i += 1
                
                if comment_pos != -1:
                    return match.group(0)  # Return the original text without processing
                
                # Process the command normally
                input_file = match.group(1)
                # Only add .tex extension if the file has no extension at all
                if not os.path.splitext(input_file)[1]:
                    input_file += '.tex'
                input_path = os.path.join(directory, input_file)
                return process_file(input_path, processed_files)
            
            content = re.sub(r'\\(?:input|include){([^}]+)}', replace_input, content)
            return content
            
        except Exception as e:
            logging.warning(f"Error processing file {file_path}: {e}")
            return ""

    main_file_path = os.path.join(directory, main_file)
    return process_file(main_file_path, set())

def process_latex_source(arxiv_id: Optional[str] = None, keep_comments: bool = True, 
                        cache_dir: Optional[str] = None,
                        use_cache: bool = False, remove_appendix_section: bool = False,
                        local_folder: Optional[str] = None) -> Optional[str]:
    """
    Process LaTeX source files from arXiv or a local folder and return the combined content.
    
    Args:
        arxiv_id: The arXiv ID of the paper (required if local_folder is not provided)
        keep_comments: Whether to keep LaTeX comments in the output
        cache_dir: Custom directory to store downloaded files (only used for arXiv)
        use_cache: Whether to use cached files if they exist (default: False, only used for arXiv)
        remove_appendix_section: Whether to remove the appendix section and everything after it
        local_folder: Path to a local folder containing TeX files (alternative to arxiv_id)
    
    Returns:
        The processed LaTeX content or None if processing fails
    """
    # Determine the directory to process
    if local_folder:
        directory = Path(local_folder).expanduser().resolve()
        
        # Validate the folder exists
        if not directory.exists():
            logging.error(f"Local folder does not exist: {directory}")
            return None
        
        if not directory.is_dir():
            logging.error(f"Path is not a directory: {directory}")
            return None
        
        logging.info(f"Processing local folder: {directory}")
    elif arxiv_id:
        base_dir = Path(cache_dir) if cache_dir else get_default_cache_dir()
        
        # Download the latest version
        if not download_arxiv_source(arxiv_id, cache_dir, use_cache):
            return None
        
        directory = base_dir / arxiv_id
    else:
        logging.error("Either arxiv_id or local_folder must be provided")
        return None

    main_file = find_main_tex(str(directory))
    if not main_file:
        logging.error("Main .tex file not found.")
        return None

    # Get the content
    content = flatten_tex(str(directory), main_file)
    
    # Process comments if requested
    if not keep_comments:
        content = remove_comments_from_lines(content)
    
    # Remove appendix if requested
    if remove_appendix_section:
        content = remove_appendix(content)
    
    return content

def check_source_available(arxiv_id: str) -> bool:
    """Check if source files are available by checking the format page."""
    url = f'https://arxiv.org/format/{arxiv_id}'
    headers = {
        'User-Agent': 'Mozilla/5.0'
    }
    
    # Create a session with retry capability
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(max_retries=3)
    session.mount('https://', adapter)
    
    try:
        # Use separate timeouts for connect and read operations
        response = session.get(url, headers=headers, timeout=(5, 30))  # (connect timeout, read timeout)
        response.raise_for_status()
        return 'Download source' in response.text
    except requests.exceptions.RequestException as e:
        logging.error(f"Error checking source availability: {e}")
        return False
    finally:
        session.close() 