import fitz  # PyMuPDF
import ezdxf
from ezdxf.math import Vec3
import os

def clip_line_to_rect(x1, y1, x2, y2, rect):
    INSIDE = 0
    LEFT = 1
    RIGHT = 2
    BOTTOM = 4
    TOP = 8

    def compute_code(x, y):
        code = INSIDE
        if x < rect.x0: code |= LEFT
        elif x > rect.x1: code |= RIGHT
        if y < rect.y0: code |= BOTTOM
        elif y > rect.y1: code |= TOP
        return code

    code1 = compute_code(x1, y1)
    code2 = compute_code(x2, y2)

    while True:
        if code1 == 0 and code2 == 0:
            return (x1, y1, x2, y2)
        if code1 & code2:
            return None

        code_out = code1 if code1 != 0 else code2
        if code_out & TOP:
            x = x1 + (x2 - x1) * (rect.y1 - y1) / (y2 - y1)
            y = rect.y1
        elif code_out & BOTTOM:
            x = x1 + (x2 - x1) * (rect.y0 - y1) / (y2 - y1)
            y = rect.y0
        elif code_out & RIGHT:
            y = y1 + (y2 - y1) * (rect.x1 - x1) / (x2 - x1)
            x = rect.x1
        elif code_out & LEFT:
            y = y1 + (y2 - y1) * (rect.x0 - x1) / (x2 - x1)
            x = rect.x0

        if code_out == code1:
            x1, y1 = x, y
            code1 = compute_code(x1, y1)
        else:
            x2, y2 = x, y
            code2 = compute_code(x2, y2)

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

    def convert(self, output_path, pages=None, crop_rect=None, min_size=0.0, skip_curves=False, include_geom=True, include_text=True):
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
                self._convert_page(page, 0, crop_rect, min_size, skip_curves, include_geom, include_text) # No offset needed for separate files
                
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
                        self._convert_page(self.doc[page_num], 0, crop_rect, min_size, skip_curves, include_geom, include_text)
            self.dxf.saveas(output_path)
            if self.verbose:
                print(f"DXF saved to {output_path}")

    def _convert_page(self, page, x_offset, crop_rect=None, min_size=0.0, skip_curves=False, include_geom=True, include_text=True):
        """Extracts vector graphics and text from a single page and adds to DXF."""
        page_height = page.rect.height
        
        if crop_rect and not isinstance(crop_rect, fitz.Rect):
            crop_rect = fitz.Rect(*crop_rect)

        # 1. Extract Drawings (Vectors)
        if include_geom:
            paths = page.get_drawings()
            for path in paths:
                if crop_rect:
                    path_rect = path.get("rect")
                    if path_rect:
                        if not (path_rect.x0 <= crop_rect.x1 and path_rect.x1 >= crop_rect.x0 and
                                path_rect.y0 <= crop_rect.y1 and path_rect.y1 >= crop_rect.y0):
                            continue
                
                for item in path["items"]:
                    cmd = item[0]
                    
                    pass_size_check = True
                    if min_size > 0:
                        bbox_w = bbox_h = 0.0
                        if cmd == "l":
                            bbox_w = abs(item[1][0] - item[2][0])
                            bbox_h = abs(item[1][1] - item[2][1])
                        elif cmd == "c":
                            xs = [pt[0] for pt in item[1:5]]
                            ys = [pt[1] for pt in item[1:5]]
                            bbox_w = max(xs) - min(xs)
                            bbox_h = max(ys) - min(ys)
                        elif cmd == "re":
                            rect = item[1]
                            bbox_w = rect.width
                            bbox_h = rect.height
                            
                        if max(bbox_w, bbox_h) < min_size:
                            pass_size_check = False
                            
                    if not pass_size_check:
                        continue

                    if cmd == "l":  # Line
                        p1 = item[1]
                        p2 = item[2]
                        if crop_rect:
                            clipped = clip_line_to_rect(p1[0], p1[1], p2[0], p2[1], crop_rect)
                            if clipped is None:
                                continue
                            p1, p2 = (clipped[0], clipped[1]), (clipped[2], clipped[3])
                        self.msp.add_line(
                            self._transform_point(p1, x_offset, page_height),
                            self._transform_point(p2, x_offset, page_height),
                            dxfattribs={'layer': 'PDF_GEOMETRY'}
                        )
                    elif cmd == "c":  # Cubic Bezier
                        if skip_curves:
                            continue
                        if crop_rect:
                            all_inside = True
                            for pt in item[1:5]:
                                if not (crop_rect.x0 <= pt[0] <= crop_rect.x1 and crop_rect.y0 <= pt[1] <= crop_rect.y1):
                                    all_inside = False
                                    break
                            if not all_inside:
                                continue
                                
                        p1, p2, p3, p4 = item[1], item[2], item[3], item[4]
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
                        
                        # Convert rectangle to 4 clippable lines so crossing borders are correctly cropped
                        lines = [(p1, p2), (p2, p3), (p3, p4), (p4, p1)]
                        for pt1, pt2 in lines:
                            if crop_rect:
                                clipped = clip_line_to_rect(pt1[0], pt1[1], pt2[0], pt2[1], crop_rect)
                                if clipped is None:
                                    continue
                                c_p1 = (clipped[0], clipped[1])
                                c_p2 = (clipped[2], clipped[3])
                            else:
                                c_p1, c_p2 = pt1, pt2
                                
                            self.msp.add_line(
                                self._transform_point(c_p1, x_offset, page_height),
                                self._transform_point(c_p2, x_offset, page_height),
                                dxfattribs={'layer': 'PDF_GEOMETRY'}
                            )

        # 2. Extract Text
        if include_text:
            text_dict = page.get_text("dict", clip=crop_rect) if crop_rect else page.get_text("dict")
            for block in text_dict.get("blocks", []):
                if block.get("type", -1) == 0: # Text block
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            text = span.get("text", "")
                            if not text.strip():
                                continue
                            
                            # Font size and origin
                            size = span.get("size", 10)
                            origin = span.get("origin", (0, 0)) # (x, y)
                            
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
