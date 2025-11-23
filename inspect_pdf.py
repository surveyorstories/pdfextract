import fitz
import sys

def inspect_pdf(pdf_path):
    print(f"Inspecting {pdf_path}...")
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Error opening PDF: {e}")
        return

    for i, page in enumerate(doc):
        print(f"\n--- Page {i+1} ---")
        
        # Check Text
        text = page.get_text("dict")
        blocks = text.get("blocks", [])
        text_blocks = [b for b in blocks if b["type"] == 0]
        print(f"Text Blocks Found: {len(text_blocks)}")
        
        if len(text_blocks) > 0:
            print("First 5 text spans:")
            count = 0
            for b in text_blocks:
                for l in b["lines"]:
                    for s in l["spans"]:
                        print(f"  - '{s['text']}' (Font: {s['font']}, Size: {s['size']})")
                        count += 1
                        if count >= 5: break
                    if count >= 5: break
                if count >= 5: break
        
        # Check Drawings
        drawings = page.get_drawings()
        print(f"Drawing Paths Found: {len(drawings)}")
        
        # Check for hidden text or other modes
        raw_text = page.get_text()
        print(f"Raw Text Content (first 100 chars): {raw_text[:100]!r}")

if __name__ == "__main__":
    pdf_file = "sample2.pdf"
    if len(sys.argv) > 1:
        pdf_file = sys.argv[1]
    inspect_pdf(pdf_file)
