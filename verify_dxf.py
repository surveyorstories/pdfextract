import ezdxf
import sys

def verify_dxf(path):
    try:
        doc = ezdxf.readfile(path)
        msp = doc.modelspace()
        
        print(f"DXF Version: {doc.dxfversion}")
        print(f"Entities in modelspace: {len(msp)}")
        
        lines = msp.query("LINE")
        polylines = msp.query("LWPOLYLINE")
        beziers = msp.query("SPLINE") # Bezier curves are stored as splines in ezdxf usually, or we used add_bezier_curve which creates splines?
        # Actually add_bezier_curve creates a SPLINE entity.
        
        print(f"Lines: {len(lines)}")
        print(f"Polylines: {len(polylines)}")
        print(f"Splines: {len(beziers)}")
        
        if len(msp) > 0:
            print("Verification SUCCESS: Entities found.")
        else:
            print("Verification FAILED: No entities found.")
            sys.exit(1)
            
    except IOError:
        print(f"Not a DXF file or file not found: {path}")
        sys.exit(1)
    except ezdxf.DXFStructureError:
        print(f"Invalid or corrupted DXF file: {path}")
        sys.exit(1)

if __name__ == "__main__":
    filename = "sample.dxf"
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    verify_dxf(filename)
