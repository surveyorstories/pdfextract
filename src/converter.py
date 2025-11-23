import fitz  # PyMuPDF
import ezdxf
from ezdxf.math import Vec3
import os

class PDF2DXFConverter:
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self.doc = None
        self.dxf = None
        self.msp = None
        self.verbose = True

    def load_pdf(self):
        """Loads the PDF file."""
        if not os.path.exists(self.pdf_path):
            raise FileNotFoundError(f"PDF file not found: {self.pdf_path}")
        self.doc = fitz.open(self.pdf_path)

    def _setup_dxf(self):
        """Initializes the DXF document with necessary layers."""
        self.dxf = ezdxf.new()
        self.msp = self.dxf.modelspace()
        
        # Create layers
        self.dxf.layers.new(name='PDF_GEOMETRY', dxfattribs={'color': 7}) # White/Black
        self.dxf.layers.new(name='PDF_TEXT', dxfattribs={'color': 1}) # Red

    def convert(self, output_path, pages=None):
        """
        Converts PDF pages to DXF.
        :param output_path: Path to save the DXF file.
        :param pages: List of page numbers to convert (0-indexed). If None, converts all.
        """
        if not self.doc:
            self.load_pdf()
        
        if pages is None:
            pages = range(len(self.doc))

        # Check if we need to split into multiple files
        if len(pages) > 1:
            base, ext = os.path.splitext(output_path)
            for i, page_num in enumerate(pages):
                if page_num >= len(self.doc):
                    print(f"Warning: Page {page_num} out of range.")
                    continue
                
                # Create a new DXF for each page
                self._setup_dxf()
                page = self.doc[page_num]
                self._convert_page(page, 0) # No offset needed for separate files
                
                # Construct new filename
                # Use page_num + 1 for 1-based indexing in filename
                page_output_path = f"{base}_page_{page_num + 1}{ext}"
                self.dxf.saveas(page_output_path)
                if self.verbose:
                    print(f"Saved page {page_num + 1} to {page_output_path}")
        else:
            # Single page case (or user selected just one page)
            self._setup_dxf()
            if pages:
                page_num = pages[0]
                if page_num < len(self.doc):
                    self._convert_page(self.doc[page_num], 0)
            self.dxf.saveas(output_path)
            if self.verbose:
                print(f"DXF saved to {output_path}")

    def _convert_page(self, page, x_offset):
        """Extracts vector graphics and text from a single page and adds to DXF."""
        page_height = page.rect.height

        # 1. Extract Drawings (Vectors)
        paths = page.get_drawings()
        for path in paths:
            for item in path["items"]:
                cmd = item[0]
                if cmd == "l":  # Line
                    p1 = item[1]
                    p2 = item[2]
                    self.msp.add_line(
                        self._transform_point(p1, x_offset, page_height),
                        self._transform_point(p2, x_offset, page_height),
                        dxfattribs={'layer': 'PDF_GEOMETRY'}
                    )
                elif cmd == "c":  # Cubic Bezier
                    p1 = item[1]
                    p2 = item[2]
                    p3 = item[3]
                    p4 = item[4]
                    control_points = [
                        self._transform_point(p1, x_offset, page_height),
                        self._transform_point(p2, x_offset, page_height),
                        self._transform_point(p3, x_offset, page_height),
                        self._transform_point(p4, x_offset, page_height)
                    ]
                    self.msp.add_spline(control_points, degree=3, dxfattribs={'layer': 'PDF_GEOMETRY'})
                elif cmd == "re": # Rectangle
                    rect = item[1]
                    p1 = (rect.x0, rect.y0)
                    p2 = (rect.x1, rect.y0)
                    p3 = (rect.x1, rect.y1)
                    p4 = (rect.x0, rect.y1)
                    
                    points = [p1, p2, p3, p4, p1] # Closed loop
                    dxf_points = [self._transform_point(p, x_offset, page_height) for p in points]
                    self.msp.add_lwpolyline(dxf_points, dxfattribs={'layer': 'PDF_GEOMETRY'})

        # 2. Extract Text
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if block["type"] == 0: # Text block
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"]
                        if not text.strip():
                            continue
                        
                        # Font size and origin
                        size = span["size"]
                        origin = span["origin"] # (x, y)
                        
                        # Transform origin
                        insert_point = self._transform_point(origin, x_offset, page_height)
                        
                        # Add MTEXT
                        self.msp.add_mtext(
                            text,
                            dxfattribs={
                                'char_height': size,
                                'insert': insert_point,
                                'attachment_point': 7, # BottomLeft
                                'layer': 'PDF_TEXT'
                            }
                        )

    def _transform_point(self, point, x_offset, page_height):
        """
        Transforms a PDF point (x, y) to DXF coordinates.
        Flips Y axis.
        """
        # point might be a fitz.Point or tuple
        x, y = point[0], point[1]
        
        # Flip Y: new_y = page_height - old_y
        new_y = page_height - y
        
        return (x + x_offset, new_y)
