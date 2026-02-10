import argparse
import re
from .core import (
    process_latex_source,
    get_default_cache_dir,
    list_sections,
    extract_section,
    parse_section_tree,
    format_section_tree,
    find_all_by_name,
)


def extract_arxiv_id(input_str: str) -> str:
    """Extract arxiv ID from URL or return input as-is if already an ID."""
    if "arxiv.org" in input_str:
        match = re.search(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?', input_str)
        if match:
            return match.group(1)
    return input_str

def main():
    default_cache = str(get_default_cache_dir())
    
    parser = argparse.ArgumentParser(
        description="Download and display LaTeX source from arXiv papers or process local TeX files."
    )
    parser.add_argument(
        "arxiv_id",
        nargs="?",
        default=None,
        help="The arXiv ID (e.g. 2303.08774) or URL (e.g. https://arxiv.org/abs/2303.08774). Not needed if --local-folder is provided."
    )
    parser.add_argument(
        "--no-comments",
        action="store_true",
        help="Remove LaTeX comments from the output"
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        help=f"Custom directory to store downloaded files (default: {default_cache})",
        default=None
    )
    parser.add_argument(
        "--no-appendix",
        action="store_true",
        help="Remove the appendix section and everything after it"
    )
    parser.add_argument(
        "--local-folder",
        type=str,
        help="Path to a local folder containing TeX files (alternative to arxiv_id)",
        default=None
    )
    parser.add_argument(
        "--list-sections",
        action="store_true",
        help="List all section names in the document"
    )
    parser.add_argument(
        "--section",
        type=str,
        action="append",
        help="Extract only the specified section(s). Can be used multiple times."
    )
    parser.add_argument(
        "--lock-timeout",
        type=float,
        default=120.0,
        help="Seconds to wait for the per-paper cache lock when another process is downloading",
    )

    args = parser.parse_args()
    
    # Validate that either arxiv_id or local_folder is provided
    if not args.arxiv_id and not args.local_folder:
        parser.error("Either provide an arXiv ID or use --local-folder to specify a local folder")
    
    if args.arxiv_id and args.local_folder:
        parser.error("Cannot specify both arXiv ID and --local-folder")

    arxiv_id = extract_arxiv_id(args.arxiv_id) if args.arxiv_id else None

    content = process_latex_source(
        arxiv_id=arxiv_id,
        keep_comments=not args.no_comments,
        cache_dir=args.cache_dir,
        remove_appendix_section=args.no_appendix,
        local_folder=args.local_folder,
        lock_timeout_seconds=args.lock_timeout,
    )
    if not content:
        return

    if args.list_sections:
        tree = parse_section_tree(content)
        print(format_section_tree(tree))
    elif args.section:
        import sys
        tree = parse_section_tree(content)
        extracted = []
        for section_path in args.section:
            # Check for ambiguity only if not using path notation
            if " > " not in section_path:
                matching_paths = find_all_by_name(tree, section_path)
                if len(matching_paths) > 1:
                    print(f"Warning: '{section_path}' is ambiguous. Found at:", file=sys.stderr)
                    for path in matching_paths:
                        print(f"  - {path}", file=sys.stderr)
                    print("Use path notation to disambiguate.", file=sys.stderr)
                    continue

            section_content = extract_section(content, section_path)
            if section_content:
                extracted.append(section_content)
            else:
                print(f"Warning: Section '{section_path}' not found", file=sys.stderr)
        if extracted:
            print("\n\n".join(extracted))
    else:
        print(content)

if __name__ == "__main__":
    main()
