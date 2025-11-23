# PDF to DXF Converter

This repository contains tools to convert PDF files to DXF format, usable as a QGIS plugin or a standalone Python tool.

## Contents

- **[QGIS Plugin](PDFtoDXF/)**: A plugin for QGIS to convert PDFs directly within the interface.
    - [Documentation](QGIS_PLUGIN_DOCS.md)
- **Standalone Tool**: A Python script to convert PDFs from the command line.
    - [Documentation](STANDALONE_DOCS.md)

## Quick Start

### QGIS Plugin
1.  Zip the `PDFtoDXF` folder.
2.  Install via QGIS Plugin Manager ("Install from Zip").
3.  Or copy `PDFtoDXF` to your QGIS plugins folder.

### Web App (Streamlit)
```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

### Standalone CLI
```bash
pip install pymupdf "ezdxf<1.1"
python src/converter.py input.pdf output.dxf
```
