import argparse
from .core import process_latex_source, get_default_cache_dir

def main():
    default_cache = str(get_default_cache_dir())
    
    parser = argparse.ArgumentParser(
        description="Download and display LaTeX source from arXiv papers."
    )
    parser.add_argument(
        "arxiv_id",
        help="The arXiv ID of the paper (do not include the version, e.g. v1, v2)"
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
    
    args = parser.parse_args()
    
    content = process_latex_source(
        args.arxiv_id, 
        keep_comments=not args.no_comments,
        cache_dir=args.cache_dir
    )
    if content:
        print(content)

if __name__ == "__main__":
    main()