# Standalone PDF to DXF Converter

## Quick Start

### 1. Install Dependencies
```bash
pip install pymupdf "ezdxf<1.1"
```

### 2. Usage

You can use the converter by creating a simple Python script.

**Create a file `convert.py`:**
```python
import sys
import os

# Add 'src' to path if needed
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from converter import PDF2DXFConverter

# Usage: python convert.py input.pdf output.dxf
if len(sys.argv) < 3:
    print("Usage: python convert.py <input_pdf> <output_dxf>")
    sys.exit(1)

input_pdf = sys.argv[1]
output_dxf = sys.argv[2]

converter = PDF2DXFConverter(input_pdf)
converter.convert(output_dxf)
print("Done!")
```

**Run it:**
```bash
python convert.py my_drawing.pdf output.dxf
```
