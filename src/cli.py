import argparse
import sys
import os

# Add current directory to path so we can import converter if running directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.converter import PDF2DXFConverter

def main():
    parser = argparse.ArgumentParser(description="Convert PDF to DXF.")
    parser.add_argument("input_pdf", help="Path to the input PDF file.")
    parser.add_argument("output_dxf", help="Path to the output DXF file.")
    parser.add_argument("--pages", help="Comma-separated list of page numbers to convert (0-indexed).", default=None)

    args = parser.parse_args()

    pages = None
    if args.pages:
        try:
            pages = [int(p.strip()) for p in args.pages.split(",")]
        except ValueError:
            print("Error: Pages must be integers.")
            sys.exit(1)

    try:
        converter = PDF2DXFConverter(args.input_pdf)
        converter.convert(args.output_dxf, pages=pages)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
