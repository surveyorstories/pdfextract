import fitz

def create_sample_pdf(path):
    doc = fitz.open()
    page = doc.new_page()
    
    # Draw a rectangle
    page.draw_rect(fitz.Rect(100, 100, 300, 200), color=(0, 0, 1), width=2)
    
    # Draw a line
    page.draw_line(fitz.Point(50, 50), fitz.Point(400, 400), color=(1, 0, 0), width=1)
    
    # Draw a circle (bezier approximation in PDF usually)
    page.draw_circle(fitz.Point(200, 400), 50, color=(0, 1, 0), width=2)
    
    # Draw a bezier curve
    p1 = fitz.Point(300, 100)
    p2 = fitz.Point(350, 50)
    p3 = fitz.Point(400, 150)
    p4 = fitz.Point(450, 100)
    page.draw_bezier(p1, p2, p3, p4, color=(0, 0, 0), width=2)

    doc.save(path)
    print(f"Sample PDF created at {path}")

if __name__ == "__main__":
    create_sample_pdf("sample.pdf")
