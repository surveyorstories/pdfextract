# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFile,
                       QgsProcessingParameterFileDestination,
                       QgsProcessingException,
                       QgsMessageLog,
                       Qgis)
import sys
import os

# Add the directory containing this script to sys.path
# This allows you to place 'ezdxf' and 'pymupdf' (fitz) folders directly next to this script
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)



# Check dependencies at module level but don't fail yet
MISSING_DEPS = []
try:
    import fitz
except ImportError:
    MISSING_DEPS.append('pymupdf')

try:
    import ezdxf
except ImportError:
    MISSING_DEPS.append('ezdxf')

class PdfToDxfAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return PdfToDxfAlgorithm()

    def name(self):
        return 'pdftodxf'

    def displayName(self):
        return self.tr('PDF to DXF Converter')

    def group(self):
        return self.tr('CAD Tools')

    def groupId(self):
        return 'cadtools'

    def shortHelpString(self):
        return self.tr("Converts a PDF file to a DXF file using PyMuPDF and ezdxf.\n\n"
                       "IMPORTANT: You must install 'pymupdf' and 'ezdxf' in your QGIS Python environment.\n"
                       "Run 'pip install pymupdf ezdxf' in the OSGeo4W Shell.")

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT,
                self.tr('Input PDF'),
                behavior=QgsProcessingParameterFile.File,
                fileFilter='PDF Files (*.pdf)'
            )
        )

        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT,
                self.tr('Output DXF'),
                fileFilter='DXF Files (*.dxf)'
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        # Check dependencies first
        if MISSING_DEPS:
            raise QgsProcessingException(
                self.tr(f"Missing dependencies: {', '.join(MISSING_DEPS)}.\n"
                        "Please install them in your QGIS Python environment (e.g., 'pip install pymupdf ezdxf').")
            )

        source_path = self.parameterAsFile(parameters, self.INPUT, context)
        output_path = self.parameterAsString(parameters, self.OUTPUT, context)

        if not source_path:
            raise QgsProcessingException(self.tr('Invalid input PDF.'))
        
        if not output_path:
             raise QgsProcessingException(self.tr('Invalid output path.'))

        feedback.pushInfo(f"Converting {source_path} to {output_path}...")

        try:
            # Import here to ensure we use the loaded modules
            import fitz
            import ezdxf
            
            # Define converter here or use a helper function to avoid global scope issues if deps are missing
            self.convert_pdf_to_dxf(source_path, output_path, fitz, ezdxf)
            
            feedback.pushInfo("Conversion successful.")
        except Exception as e:
            QgsMessageLog.logMessage(f"PDF2DXF Error: {str(e)}", "PDF2DXF", Qgis.Critical)
            raise QgsProcessingException(self.tr(f"Conversion failed: {e}"))

        return {self.OUTPUT: output_path}

    def convert_pdf_to_dxf(self, pdf_path, dxf_path, fitz, ezdxf):
        """
        Standalone conversion logic to avoid dependency on global class definition
        which might fail if deps are missing.
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
            
        doc = fitz.open(pdf_path)
        dxf = ezdxf.new()
        msp = dxf.modelspace()
        
        x_offset = 0
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            paths = page.get_drawings()
            page_height = page.rect.height
            
            for path in paths:
                for item in path["items"]:
                    cmd = item[0]
                    if cmd == "l":
                        p1 = item[1]
                        p2 = item[2]
                        msp.add_line(
                            self._transform_point(p1, x_offset, page_height),
                            self._transform_point(p2, x_offset, page_height)
                        )
                    elif cmd == "c":
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
                        msp.add_spline(control_points, degree=3)
                    elif cmd == "re":
                        rect = item[1]
                        p1 = (rect.x0, rect.y0)
                        p2 = (rect.x1, rect.y0)
                        p3 = (rect.x1, rect.y1)
                        p4 = (rect.x0, rect.y1)
                        points = [p1, p2, p3, p4, p1]
                        dxf_points = [self._transform_point(p, x_offset, page_height) for p in points]
                        msp.add_lwpolyline(dxf_points)
            
            x_offset += page.rect.width + 50
            
        dxf.saveas(dxf_path)

    def _transform_point(self, point, x_offset, page_height):
        x, y = point[0], point[1]
        new_y = page_height - y
        return (x + x_offset, new_y)
