import argparse
from .core import process_latex_source, get_default_cache_dir

def main():
    default_cache = str(get_default_cache_dir())
    
    parser = argparse.ArgumentParser(
        description="Download and display LaTeX source from arXiv papers or process local TeX files."
    )
    parser.add_argument(
        "arxiv_id",
        nargs="?",
        default=None,
        help="The arXiv ID of the paper (do not include the version, e.g. v1, v2). Not needed if --local-folder is provided."
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
    
    args = parser.parse_args()
    
    # Validate that either arxiv_id or local_folder is provided
    if not args.arxiv_id and not args.local_folder:
        parser.error("Either provide an arXiv ID or use --local-folder to specify a local folder")
    
    if args.arxiv_id and args.local_folder:
        parser.error("Cannot specify both arXiv ID and --local-folder")
    
    content = process_latex_source(
        arxiv_id=args.arxiv_id,
        keep_comments=not args.no_comments,
        cache_dir=args.cache_dir,
        remove_appendix_section=args.no_appendix,
        local_folder=args.local_folder
    )
    if content:
        print(content)

if __name__ == "__main__":
    main()