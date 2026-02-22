import logging
import os
import tarfile
import shutil
import tempfile
import hashlib
import uuid
from typing import Optional, List
from dataclasses import dataclass, field
import re
from pathlib import Path
import requests
from filelock import FileLock, Timeout

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

_CACHE_COMPLETE_MARKER = ".arxiv_cache_complete"

def get_default_cache_dir() -> Path:
    """Get the default cache directory for downloaded files."""
    # Use standard OS-specific cache directory
    if os.name == 'nt':  # Windows
        base_dir = Path(os.environ.get('LOCALAPPDATA', '~'))
    else:  # Unix/Linux/MacOS
        base_dir = Path(os.environ.get('XDG_CACHE_HOME', '~/.cache'))
    
    cache_dir = base_dir.expanduser() / 'arxiv-to-prompt'
    return cache_dir


def _cache_has_tex_files(directory: Path) -> bool:
    """Return True if the directory contains at least one .tex file recursively."""
    return any(directory.rglob("*.tex"))


def _is_valid_cache_dir(directory: Path) -> bool:
    """Return True if a cache directory looks complete and usable."""
    if not directory.exists() or not directory.is_dir():
        return False
    marker_path = directory / _CACHE_COMPLETE_MARKER
    return marker_path.is_file() and _cache_has_tex_files(directory)


def _safe_rmtree(path: Path) -> None:
    """Best-effort directory removal that never raises."""
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass
    except Exception as e:
        logging.warning(f"Failed to remove directory {path}: {e}")


def _get_lock_path(base_dir: Path, arxiv_id: str) -> Path:
    """Return lock path for a given arXiv ID."""
    lock_key = hashlib.sha256(arxiv_id.encode("utf-8")).hexdigest()
    return base_dir / ".locks" / f"{lock_key}.lock"


def _extract_tar_safely(tar_path: Path, extract_to: Path) -> None:
    """Extract tar file while blocking path traversal entries."""
    with tarfile.open(tar_path) as tar:
        for member in tar.getmembers():
            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError(f"Unsafe path in tar archive: {member.name}")
            if member.issym() or member.islnk():
                raise ValueError(f"Link entry in tar archive is not allowed: {member.name}")
        try:
            tar.extractall(path=extract_to, filter="data")
        except TypeError:
            # Python < 3.12 does not support extraction filters.
            tar.extractall(path=extract_to)


def download_arxiv_source(
    arxiv_id: str,
    cache_dir: Optional[str] = None,
    use_cache: bool = False,
    lock_timeout_seconds: float = 120.0,
    stale_cache_repair: bool = True,
) -> bool:
    """
    Download source files from arXiv.
    
    Args:
        arxiv_id: The arXiv ID of the paper
        cache_dir: Custom directory to store downloaded files
        use_cache: Whether to use cached files if they exist (default: False)
        lock_timeout_seconds: Max seconds to wait for the per-paper cache lock
        stale_cache_repair: Whether to remove and rebuild incomplete/corrupt cache dirs
    
    Returns:
        bool: True if download successful, False if failed (including when source not available)
    """
    # Use provided cache_dir or default
    base_dir = Path(cache_dir) if cache_dir else get_default_cache_dir()
    directory = base_dir / arxiv_id
    lock_path = _get_lock_path(base_dir, arxiv_id)
    staging_root = base_dir / ".staging"

    try:
        base_dir.mkdir(parents=True, exist_ok=True)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        staging_root.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logging.error(f"Failed to initialize cache directories in {base_dir}: {e}")
        return False

    try:
        with FileLock(str(lock_path), timeout=lock_timeout_seconds):
            if directory.exists():
                # Fast path for valid cache if requested.
                if use_cache and _is_valid_cache_dir(directory):
                    logging.info(f"Directory {directory} already exists, using cached version.")
                    return True

                if use_cache and not stale_cache_repair:
                    logging.error(f"Cached directory {directory} is incomplete and stale cache repair is disabled.")
                    return False

                if not _is_valid_cache_dir(directory):
                    logging.warning(f"Found incomplete cache at {directory}; rebuilding.")

            # Check availability only when we need to download.
            if not check_source_available(arxiv_id):
                logging.warning(f"TeX source files not available for {arxiv_id}")
                return False

            # Always use latest version by not specifying version in URL.
            url = f'https://arxiv.org/e-print/{arxiv_id}'
            logging.info(f"Downloading source from {url}")
            headers = {'User-Agent': 'Mozilla/5.0'}

            # Build in isolated staging and atomically publish to cache path.
            staging_dir = Path(tempfile.mkdtemp(prefix=f"{arxiv_id}.", dir=staging_root))
            extracted_dir = staging_dir / "extracted"
            tar_path = staging_dir / "source.tar"

            try:
                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                with open(tar_path, 'wb') as file:
                    file.write(response.content)

                extracted_dir.mkdir(parents=True, exist_ok=True)
                _extract_tar_safely(tar_path, extracted_dir)

                if not _cache_has_tex_files(extracted_dir):
                    raise ValueError("Downloaded archive does not contain any .tex files")

                (extracted_dir / _CACHE_COMPLETE_MARKER).write_text("ok\n", encoding="utf-8")

                backup_dir = None
                published = False
                try:
                    if directory.exists():
                        backup_dir = directory.parent / f"{directory.name}.old.{uuid.uuid4().hex}"
                        os.replace(str(directory), str(backup_dir))

                    os.replace(str(extracted_dir), str(directory))
                    published = True
                except Exception as publish_error:
                    rollback_error = None
                    rollback_succeeded = False
                    if backup_dir and backup_dir.exists() and not directory.exists():
                        try:
                            os.replace(str(backup_dir), str(directory))
                            rollback_succeeded = True
                        except Exception as rollback_exc:
                            rollback_error = rollback_exc

                    if rollback_error is not None:
                        raise RuntimeError(
                            f"Failed to publish new cache and rollback failed: {rollback_error}"
                        ) from publish_error
                    if rollback_succeeded:
                        raise RuntimeError("Failed to publish new cache; rolled back to previous cache.") from publish_error
                    raise RuntimeError("Failed to publish new cache.") from publish_error
                finally:
                    if published and backup_dir and backup_dir.exists():
                        _safe_rmtree(backup_dir)

                logging.info(f"Source files downloaded and extracted to {directory}/")
                return True
            finally:
                _safe_rmtree(staging_dir)

    except Timeout:
        logging.error(f"Timed out waiting for download lock for {arxiv_id} after {lock_timeout_seconds} seconds")
        return False
    except Exception as e:
        logging.error(f"Error downloading/extracting source: {e}")
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


def extract_abstract(text: str) -> Optional[str]:
    """Extract the abstract from LaTeX content.

    Args:
        text: Processed LaTeX content

    Returns:
        The abstract text, or None if no abstract found.
    """
    match = re.search(r'\\begin\{abstract\}(.*?)\\end\{abstract\}', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


@dataclass
class MacroDefinition:
    """Represents a parsed LaTeX macro definition."""
    name: str
    num_args: int
    optional_default: Optional[str]  # default value for optional first arg
    body: str
    is_math_operator: bool = False
    starred: bool = False


def _find_matching_brace(text: str, pos: int) -> int:
    """Find the position of the closing brace matching the opening brace at pos.

    Args:
        text: The text to search in
        pos: Position of the opening '{' character

    Returns:
        Position of the matching '}', or -1 if not found.
    """
    if pos >= len(text) or text[pos] != '{':
        return -1
    depth = 1
    i = pos + 1
    while i < len(text):
        if text[i] == '\\' and i + 1 < len(text) and text[i + 1] in ('{', '}'):
            i += 2  # skip escaped brace
            continue
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _find_matching_bracket(text: str, pos: int) -> int:
    """Find the position of the closing bracket matching the opening bracket at pos.

    Args:
        text: The text to search in
        pos: Position of the opening '[' character

    Returns:
        Position of the matching ']', or -1 if not found.
    """
    if pos >= len(text) or text[pos] != '[':
        return -1
    depth = 1
    i = pos + 1
    while i < len(text):
        if text[i] == '\\' and i + 1 < len(text) and text[i + 1] in ('[', ']'):
            i += 2
            continue
        if text[i] == '[':
            depth += 1
        elif text[i] == ']':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _parse_macro_definitions(text: str) -> tuple:
    """Parse all macro definitions from LaTeX text.

    Supports \\newcommand, \\renewcommand, \\providecommand (and starred variants),
    \\DeclareMathOperator (and starred), and basic \\def\\cmd{body}.

    Args:
        text: The LaTeX source text

    Returns:
        Tuple of (dict mapping macro name to MacroDefinition, cleaned text with definitions removed).
        For redefined macros, the last definition wins.
    """
    macros = {}
    regions_to_remove = []  # (start, end) spans to remove

    # Pattern for \newcommand, \renewcommand, \providecommand (with optional *)
    cmd_pattern = re.compile(
        r'\\(newcommand|renewcommand|providecommand)\*?\s*'
    )

    for match in cmd_pattern.finditer(text):
        start = match.start()
        pos = match.end()

        # Skip whitespace
        while pos < len(text) and text[pos] in ' \t':
            pos += 1

        # Extract command name: either {\\name} or \\name
        if pos < len(text) and text[pos] == '{':
            close = _find_matching_brace(text, pos)
            if close == -1:
                continue
            cmd_name = text[pos + 1:close].strip()
            pos = close + 1
        elif pos < len(text) and text[pos] == '\\':
            # \newcommand\foo{...} form
            name_match = re.match(r'\\([a-zA-Z@]+)', text[pos:])
            if not name_match:
                continue
            cmd_name = '\\' + name_match.group(1)
            pos += name_match.end()
        else:
            continue

        if not cmd_name.startswith('\\'):
            cmd_name = '\\' + cmd_name

        # Skip whitespace
        while pos < len(text) and text[pos] in ' \t':
            pos += 1

        # Optional [num_args]
        num_args = 0
        if pos < len(text) and text[pos] == '[':
            bracket_close = _find_matching_bracket(text, pos)
            if bracket_close == -1:
                continue
            try:
                num_args = int(text[pos + 1:bracket_close].strip())
            except ValueError:
                continue
            pos = bracket_close + 1

        # Skip whitespace
        while pos < len(text) and text[pos] in ' \t':
            pos += 1

        # Optional [default] for first argument
        optional_default = None
        if pos < len(text) and text[pos] == '[':
            bracket_close = _find_matching_bracket(text, pos)
            if bracket_close == -1:
                continue
            optional_default = text[pos + 1:bracket_close]
            pos = bracket_close + 1

        # Skip whitespace
        while pos < len(text) and text[pos] in ' \t':
            pos += 1

        # Body in braces
        if pos >= len(text) or text[pos] != '{':
            continue
        body_close = _find_matching_brace(text, pos)
        if body_close == -1:
            continue
        body = text[pos + 1:body_close]

        starred = '*' in match.group(0)
        macros[cmd_name] = MacroDefinition(
            name=cmd_name,
            num_args=num_args,
            optional_default=optional_default,
            body=body,
            starred=starred,
        )

        # Mark entire definition for removal (including trailing newline)
        end = body_close + 1
        if end < len(text) and text[end] == '\n':
            end += 1
        regions_to_remove.append((start, end))

    # Pattern for \DeclareMathOperator{\\name}{text} and \DeclareMathOperator*{\\name}{text}
    decl_pattern = re.compile(r'\\DeclareMathOperator(\*?)\s*')
    for match in decl_pattern.finditer(text):
        start = match.start()
        starred = match.group(1) == '*'
        pos = match.end()

        # Skip whitespace
        while pos < len(text) and text[pos] in ' \t':
            pos += 1

        # {\\name}
        if pos >= len(text) or text[pos] != '{':
            continue
        close = _find_matching_brace(text, pos)
        if close == -1:
            continue
        cmd_name = text[pos + 1:close].strip()
        if not cmd_name.startswith('\\'):
            cmd_name = '\\' + cmd_name
        pos = close + 1

        # Skip whitespace
        while pos < len(text) and text[pos] in ' \t':
            pos += 1

        # {text}
        if pos >= len(text) or text[pos] != '{':
            continue
        body_close = _find_matching_brace(text, pos)
        if body_close == -1:
            continue
        op_text = text[pos + 1:body_close]

        if starred:
            body = f'\\operatorname*{{{op_text}}}'
        else:
            body = f'\\operatorname{{{op_text}}}'

        macros[cmd_name] = MacroDefinition(
            name=cmd_name,
            num_args=0,
            optional_default=None,
            body=body,
            is_math_operator=True,
            starred=starred,
        )

        end = body_close + 1
        if end < len(text) and text[end] == '\n':
            end += 1
        regions_to_remove.append((start, end))

    # Pattern for basic \def\cmd{body} (zero-arg only)
    def_pattern = re.compile(r'\\def\s*(\\[a-zA-Z@]+)\s*')
    for match in def_pattern.finditer(text):
        start = match.start()
        cmd_name = match.group(1)
        pos = match.end()

        # Skip whitespace
        while pos < len(text) and text[pos] in ' \t':
            pos += 1

        if pos >= len(text) or text[pos] != '{':
            continue
        body_close = _find_matching_brace(text, pos)
        if body_close == -1:
            continue
        body = text[pos + 1:body_close]

        macros[cmd_name] = MacroDefinition(
            name=cmd_name,
            num_args=0,
            optional_default=None,
            body=body,
        )

        end = body_close + 1
        if end < len(text) and text[end] == '\n':
            end += 1
        regions_to_remove.append((start, end))

    # Remove definition regions from text (process in reverse to preserve positions)
    # Merge overlapping regions first
    regions_to_remove.sort()
    merged = []
    for s, e in regions_to_remove:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    cleaned = text
    for s, e in reversed(merged):
        cleaned = cleaned[:s] + cleaned[e:]

    return macros, cleaned


def _expand_single_macro(text: str, macro: MacroDefinition) -> str:
    """Expand all usages of a single macro in the text.

    Args:
        text: The LaTeX text
        macro: The macro definition to expand

    Returns:
        Text with all usages of this macro expanded.
    """
    name_escaped = re.escape(macro.name)

    if macro.num_args == 0:
        # Zero-arg macro: replace \cmd not followed by [a-zA-Z]
        pattern = re.compile(name_escaped + r'(?![a-zA-Z@])')
        # Use lambda to avoid backslash interpretation in replacement string
        text = pattern.sub(lambda m: macro.body, text)
        return text

    # Macro with arguments: find each usage and expand
    pattern = re.compile(name_escaped + r'(?![a-zA-Z@])')
    replacements = []  # (start, end, replacement_text)

    for match in pattern.finditer(text):
        usage_start = match.start()
        pos = match.end()

        # Skip whitespace between command and first arg
        while pos < len(text) and text[pos] in ' \t\n':
            pos += 1

        args = []
        has_optional = macro.optional_default is not None
        used_default = False

        if has_optional:
            # Check for optional first argument [...]
            if pos < len(text) and text[pos] == '[':
                bracket_close = _find_matching_bracket(text, pos)
                if bracket_close == -1:
                    continue
                args.append(text[pos + 1:bracket_close])
                pos = bracket_close + 1
            else:
                args.append(macro.optional_default)
                used_default = True

            # Parse remaining mandatory args
            remaining = macro.num_args - 1
        else:
            remaining = macro.num_args

        success = True
        for _ in range(remaining):
            # Skip whitespace
            while pos < len(text) and text[pos] in ' \t\n':
                pos += 1
            if pos >= len(text) or text[pos] != '{':
                success = False
                break
            brace_close = _find_matching_brace(text, pos)
            if brace_close == -1:
                success = False
                break
            args.append(text[pos + 1:brace_close])
            pos = brace_close + 1

        if not success or len(args) != macro.num_args:
            continue

        # Substitute #1..#9 in body
        result = macro.body
        for i, arg in enumerate(args, 1):
            result = result.replace(f'#{i}', arg)

        replacements.append((usage_start, pos, result))

    # Apply replacements in reverse order
    for start, end, replacement in reversed(replacements):
        text = text[:start] + replacement + text[end:]

    return text


def expand_macros(text: str) -> str:
    """Expand all custom LaTeX macro definitions inline and remove definition lines.

    Supports \\newcommand, \\renewcommand, \\providecommand (and starred variants),
    \\DeclareMathOperator (and starred), and basic \\def\\cmd{body}.

    Handles macros with zero arguments, positional arguments (#1..#9),
    and optional first arguments with defaults. Nested macro expansion
    is handled via multiple passes (up to 10 iterations).

    Args:
        text: The LaTeX source text

    Returns:
        Text with all macro usages expanded and definition lines removed.
    """
    macros, text = _parse_macro_definitions(text)

    if not macros:
        return text

    # Iteratively expand until stable (handles nested macros)
    for _ in range(10):
        previous = text
        for macro in macros.values():
            text = _expand_single_macro(text, macro)
        if text == previous:
            break

    return text


_IMAGE_EXTENSIONS = ['.pdf', '.png', '.jpg', '.jpeg', '.eps', '.svg']


def _resolve_image_path(reference: str, search_dirs: List[str]) -> Optional[str]:
    """Resolve an image reference to an absolute file path."""
    for search_dir in search_dirs:
        candidate = os.path.join(search_dir, reference)
        # Try exact path first
        if os.path.isfile(candidate):
            return str(Path(candidate).resolve())
        # If no extension, try common image extensions
        _, ext = os.path.splitext(reference)
        if not ext:
            for image_ext in _IMAGE_EXTENSIONS:
                candidate_with_ext = candidate + image_ext
                if os.path.isfile(candidate_with_ext):
                    return str(Path(candidate_with_ext).resolve())
    return None


def extract_figure_paths(text: str, source_dir: str) -> List[str]:
    """
    Extract and resolve \\includegraphics file paths from processed LaTeX content.

    Scans the text for \\includegraphics commands and resolves each reference
    to an absolute file path in the source directory. Respects \\graphicspath
    declarations. When a file reference omits its extension, common image
    extensions are tried in order.

    Args:
        text: Processed LaTeX content (after comment/appendix removal as desired)
        source_dir: Absolute path to the source directory for resolving relative paths

    Returns:
        List of resolved absolute file paths (only files that actually exist on disk).
        Paths appear in the order they are referenced in the text, with duplicates removed.
    """
    # Parse \graphicspath if present (use the last declaration, as LaTeX does)
    graphicspath_pattern = r'\\graphicspath\{((?:\{[^}]*\})+)\}'
    graphicspath_matches = list(re.finditer(graphicspath_pattern, text))
    search_dirs: List[str] = []
    if graphicspath_matches:
        last_match = graphicspath_matches[-1]
        dir_pattern = r'\{([^}]*)\}'
        for dir_match in re.finditer(dir_pattern, last_match.group(1)):
            gpath = os.path.join(source_dir, dir_match.group(1))
            if os.path.isdir(gpath):
                search_dirs.append(gpath)
    search_dirs.append(source_dir)

    # Find all \includegraphics references
    pattern = r'\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}'
    matches = re.findall(pattern, text)

    seen: set = set()
    resolved_paths: List[str] = []
    for ref in matches:
        ref = ref.strip()
        # Skip URL references
        if '://' in ref:
            continue
        resolved = _resolve_image_path(ref, search_dirs)
        if resolved and resolved not in seen:
            seen.add(resolved)
            resolved_paths.append(resolved)
    return resolved_paths


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
                # LaTeX's \input tries filename.tex first, then bare filename.
                # e.g. \input{ch1} -> ch1.tex, \input{ref.bbl} -> ref.bbl.tex (not found) -> ref.bbl
                # See https://latexref.xyz/_005cinput.html
                if not input_file.endswith('.tex'):
                    tex_path = os.path.join(directory, input_file + '.tex')
                    if os.path.isfile(tex_path):
                        input_path = tex_path
                    else:
                        input_path = os.path.join(directory, input_file)
                else:
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
                        local_folder: Optional[str] = None,
                        lock_timeout_seconds: float = 120.0,
                        figure_paths_only: bool = False,
                        abstract_only: bool = False,
                        expand_macros_flag: bool = False) -> Optional[str]:
    """
    Process LaTeX source files from arXiv or a local folder and return the combined content.

    Args:
        arxiv_id: The arXiv ID of the paper (required if local_folder is not provided)
        keep_comments: Whether to keep LaTeX comments in the output
        cache_dir: Custom directory to store downloaded files (only used for arXiv)
        use_cache: Whether to use cached files if they exist (default: False, only used for arXiv)
        remove_appendix_section: Whether to remove the appendix section and everything after it
        local_folder: Path to a local folder containing TeX files (alternative to arxiv_id)
        lock_timeout_seconds: Max seconds to wait for the per-paper cache lock
        figure_paths_only: Whether to return resolved figure file paths instead of LaTeX text
        abstract_only: Whether to return only the abstract text
        expand_macros_flag: Whether to expand \\newcommand and related macro definitions inline

    Returns:
        The processed LaTeX content or None if processing fails.
        When figure_paths_only is True, returns newline-joined absolute paths of image files
        referenced by \\includegraphics commands.
        When abstract_only is True, returns the abstract text.
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
        if not download_arxiv_source(
            arxiv_id,
            cache_dir,
            use_cache,
            lock_timeout_seconds=lock_timeout_seconds,
        ):
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
    
    # Process comments if requested, or always when extracting abstract
    if not keep_comments or abstract_only:
        content = remove_comments_from_lines(content)

    # Expand macros if requested
    if expand_macros_flag:
        content = expand_macros(content)

    # Remove appendix if requested
    if remove_appendix_section:
        content = remove_appendix(content)

    if figure_paths_only:
        paths = extract_figure_paths(content, str(directory))
        return "\n".join(paths) if paths else None

    if abstract_only:
        return extract_abstract(content)

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
