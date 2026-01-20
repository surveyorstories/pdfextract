# -*- coding: utf-8 -*-
# Author: Surveyor Stories
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFile,
                       QgsProcessingParameterFileDestination,
                       QgsProcessingParameterBoolean,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterEnum,
                       QgsProcessingException,
                       QgsProcessingContext,
                       QgsMessageLog,
                       QgsVectorLayer,
                       QgsVectorFileWriter,
                       QgsFeature,
                       QgsGeometry,
                       QgsPointXY,
                       QgsField,
                       QgsFields,
                       QgsCoordinateReferenceSystem,
                       QgsProject,
                       QgsWkbTypes,
                       Qgis)
from qgis.utils import iface
from qgis.PyQt.QtCore import QVariant
import sys
import os

# dependency list handled by caller/plugin initializer
MISSING_DEPS = []
try:
    import fitz
    if not hasattr(fitz, 'open'):
        MISSING_DEPS.append('pymupdf')
except ImportError:
    MISSING_DEPS.append('pymupdf')

try:
    import ezdxf
except ImportError:
    MISSING_DEPS.append('ezdxf')
except Exception:
    MISSING_DEPS.append('ezdxf')


class PdfToDxfAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'
    OUTPUT_FORMAT = 'OUTPUT_FORMAT'
    OUTPUT_FORMAT = 'OUTPUT_FORMAT'
    LOAD_OUTPUT = 'LOAD_OUTPUT'
    MIN_SIZE = 'MIN_SIZE'
    SKIP_CURVES = 'SKIP_CURVES'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return PdfToDxfAlgorithm()

    def name(self):
        return 'pdfextract_algo'

    def displayName(self):
        return self.tr('PDF Extract')

    def group(self):
        return ''

    def groupId(self):
        return ''

    def shortHelpString(self):
        return self.tr(
            "Converts a PDF file to editable vector format (Shapefile, GeoJSON, or DXF) using PyMuPDF and ezdxf.\n"
            "Required dependencies: pymupdf, ezdxf\n\n"
            "The plugin will attempt to install these automatically on first run.\n"
            "If that fails, you can install them manually via OSGeo4W Shell:\n"
            "pip install pymupdf ezdxf\n\n"
            "Creates separate layers for geometry and text that are natively editable in QGIS.\n"
            "Output uses the current project CRS."
        )

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
            QgsProcessingParameterEnum(
                self.OUTPUT_FORMAT,
                self.tr('Output Format'),
                options=['Shapefile', 'GeoJSON', 'DXF'],
                defaultValue=0
            )
        )

        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT,
                self.tr('Output Base Name'),
                fileFilter='Shapefile (*.shp);;GeoJSON (*.geojson);;DXF (*.dxf)'
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.LOAD_OUTPUT,
                self.tr('Load output into project'),
                defaultValue=True
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.SKIP_CURVES,
                self.tr('Skip Curved Geometries'),
                defaultValue=False
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_SIZE,
                self.tr('Minimum Size (points)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.0,
                minValue=0.0
            )
        )

    def prepareAlgorithm(self, parameters, context, feedback):
        """
        Prepare the algorithm for execution.
        This runs on the main thread, so it's safe to access iface here.
        """
        self.canvas_extent = None
        # iface is imported from qgis.utils
        if iface:
            try:
                self.canvas_extent = iface.mapCanvas().extent()
                feedback.pushInfo(
                    f"Captured canvas extent: {self.canvas_extent.toString()}")
            except Exception:
                # It's possible iface is not available or canvas is not ready
                pass
        return True

    def processAlgorithm(self, parameters, context, feedback):
        if MISSING_DEPS:
            raise QgsProcessingException(
                self.tr(f"Missing dependencies: {', '.join(MISSING_DEPS)}.\n\n"
                        "The plugin attempts to install these automatically.\n"
                        "If that failed, please install manually using OSGeo4W Shell:\n"
                        "pip install pymupdf ezdxf\n"
                        "Then restart QGIS.")
            )

        source_path = self.parameterAsFile(parameters, self.INPUT, context)
        output_path = self.parameterAsString(parameters, self.OUTPUT, context)
        load_output = self.parameterAsBool(
            parameters, self.LOAD_OUTPUT, context)
        output_format = self.parameterAsEnum(
            parameters, self.OUTPUT_FORMAT, context)
        min_size = self.parameterAsDouble(parameters, self.MIN_SIZE, context)
        skip_curves = self.parameterAsBool(
            parameters, self.SKIP_CURVES, context)

        if not source_path:
            raise QgsProcessingException(self.tr('Invalid input PDF.'))

        if not output_path:
            raise QgsProcessingException(self.tr('Invalid output path.'))

        # Ensure output has correct extension
        base_path = os.path.splitext(output_path)[0]
        if output_format == 0:  # Shapefile
            output_path = base_path + \
                '.shp' if not output_path.lower().endswith('.shp') else output_path
        elif output_format == 1:  # GeoJSON
            output_path = base_path + \
                '.geojson' if not output_path.lower().endswith('.geojson') else output_path
        else:  # DXF
            output_path = base_path + \
                '.dxf' if not output_path.lower().endswith('.dxf') else output_path

        # Create parent directory if needed
        out_dir = os.path.dirname(output_path)
        if out_dir and not os.path.exists(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
                feedback.pushInfo(f"Created output directory: {out_dir}")
            except Exception as e:
                raise QgsProcessingException(
                    self.tr(f"Failed to create output directory {out_dir}: {e}"))

        # Get project CRS
        project = context.project()
        if not project:
            project = QgsProject.instance()

        project_crs = project.crs()
        if not project_crs.isValid():
            project_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            feedback.pushWarning("No valid project CRS found, using EPSG:4326")

        # Get current canvas extent (captured in prepareAlgorithm)
        canvas_extent = getattr(self, 'canvas_extent', None)
        if canvas_extent:
            feedback.pushInfo(
                f"Using canvas extent: {canvas_extent.toString()}")
        else:
            feedback.pushInfo("No canvas extent available.")

        feedback.pushInfo(f"Converting {source_path} to vector format...")
        feedback.pushInfo(
            f"Using CRS: {project_crs.authid()} - {project_crs.description()}")

        try:
            import fitz
            if not hasattr(fitz, 'open'):
                raise ImportError(
                    "Incorrect 'fitz' package installed. Please install 'pymupdf'.")

            generated_files = self.convert_pdf_to_vector(
                source_path,
                output_path,
                fitz,
                project_crs,
                output_format,
                output_format,
                feedback,
                canvas_extent,
                min_size,
                skip_curves
            )

            if load_output and generated_files:
                for file_path, layer_name in generated_files:
                    if not os.path.exists(file_path):
                        feedback.pushWarning(
                            f"Expected output not found: {file_path}")
                        continue

                    # Use context to load layer safely on completion
                    details = QgsProcessingContext.LayerDetails(
                        layer_name, context.project(), self.OUTPUT)
                    context.addLayerToLoadOnCompletion(file_path, details)
                    feedback.pushInfo(
                        f"Scheduled layer for loading: {layer_name}")

            feedback.pushInfo(
                f"Successfully converted. Generated {len(generated_files)} layer(s).")
        except Exception as e:
            QgsMessageLog.logMessage(
                f"PDF2Vector Error: {str(e)}", "PDF2Vector", Qgis.Critical)
            raise QgsProcessingException(self.tr(f"Conversion failed: {e}"))

        return {self.OUTPUT: output_path}

    def convert_pdf_to_vector(self, pdf_path, output_path, fitz, crs, output_format, feedback, canvas_extent=None, min_size=0.0, skip_curves=False):
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        doc = fitz.open(pdf_path)
        generated_files = []

        # Determine output extension and driver
        if output_format == 0:  # Shapefile
            ext = '.shp'
            driver = 'ESRI Shapefile'
        elif output_format == 1:  # GeoJSON
            ext = '.geojson'
            driver = 'GeoJSON'
        else:  # DXF
            ext = '.dxf'
            driver = 'DXF'

        # Multi-page -> separate files per page
        base, _ = os.path.splitext(output_path)

        # If DXF, we can use direct conversion
        if output_format == 2:  # DXF
            if len(doc) > 1:
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    dxf_path = f"{base}_page_{page_num + 1}{ext}"
                    ok, msg = self.convert_pdf_page_to_dxf_direct(
                        page, dxf_path, min_size=min_size, skip_curves=skip_curves)
                    if ok:
                        generated_files.append(
                            (dxf_path, f"Page {page_num + 1} - DXF"))
                    else:
                        feedback.pushWarning(
                            f"DXF conversion failed for page {page_num + 1}: {msg}")
            else:
                dxf_path = f"{base}{ext}"
                if len(doc) > 0:
                    ok, msg = self.convert_pdf_page_to_dxf_direct(
                        doc[0], dxf_path, min_size=min_size, skip_curves=skip_curves)
                    if ok:
                        generated_files.append((dxf_path, "PDF DXF"))
                    else:
                        feedback.pushWarning(f"DXF conversion failed: {msg}")
                else:
                    feedback.pushWarning("PDF document contains no pages.")

            return generated_files

        # For Shapefile/GeoJSON
        if len(doc) > 1:
            for page_num in range(len(doc)):
                page = doc[page_num]
                geom_path = f"{base}_page_{page_num + 1}_geometry{ext}"
                text_path = f"{base}_page_{page_num + 1}_text{ext}"

                self._create_geometry_layer(
                    page, geom_path, crs, driver, feedback, canvas_extent, min_size, skip_curves)
                self._create_text_layer(
                    page, text_path, crs, driver, feedback, canvas_extent)

                generated_files.append(
                    (geom_path, f"Page {page_num + 1} - Geometry"))
                generated_files.append(
                    (text_path, f"Page {page_num + 1} - Text"))
        else:
            # Single page or empty doc
            geom_path = f"{base}_geometry{ext}"
            text_path = f"{base}_text{ext}"
            if len(doc) > 0:
                self._create_geometry_layer(
                    doc[0], geom_path, crs, driver, feedback, canvas_extent, min_size, skip_curves)
                self._create_text_layer(
                    doc[0], text_path, crs, driver, feedback, canvas_extent)
            else:
                feedback.pushWarning("PDF document contains no pages.")
            generated_files.append((geom_path, "PDF Geometry"))
            generated_files.append((text_path, "PDF Text"))

        return generated_files

    def convert_pdf_page_to_dxf_direct(self, page, output_dxf_path, min_size=0.0, skip_curves=False):
        """Convert PDF page directly to DXF using ezdxf (better quality)."""
        try:
            import ezdxf
        except ImportError:
            return False, "ezdxf not installed"

        try:
            dxf = ezdxf.new()
            # Create layers
            dxf.layers.new(name='PDF_GEOMETRY', dxfattribs={'color': 7})
            dxf.layers.new(name='PDF_TEXT', dxfattribs={'color': 1})

            msp = dxf.modelspace()
            page_height = page.rect.height

            # 1. Extract Drawings
            paths = page.get_drawings()

            for path in paths:
                for item in path.get("items", []):
                    try:
                        cmd = item[0]
                        if isinstance(cmd, bytes):
                            cmd = cmd.decode("utf-8", "ignore")

                        # Size Filter
                        pass_size = True
                        if min_size > 0:
                            w, h = 0, 0
                            if str(cmd).lower() == "l":
                                p1, p2 = item[1], item[2]
                                w = abs(p1[0] - p2[0])
                                h = abs(p1[1] - p2[1])
                            elif str(cmd).lower() == "c":
                                xs = [pt[0] for pt in item[1:] if pt]
                                ys = [pt[1] for pt in item[1:] if pt]
                                if xs and ys:
                                    w = max(xs) - min(xs)
                                    h = max(ys) - min(ys)
                            elif str(cmd).lower() in ("re", "rect"):
                                rect = item[1]
                                w, h = rect.width, rect.height

                            if max(w, h) < min_size:
                                pass_size = False

                        if not pass_size:
                            continue

                        # LINE
                        if str(cmd).lower() == "l":
                            p1 = item[1]
                            p2 = item[2]
                            msp.add_line(
                                (p1[0], page_height - p1[1]),
                                (p2[0], page_height - p2[1]),
                                dxfattribs={'layer': 'PDF_GEOMETRY'}
                            )

                        # CURVE
                        elif str(cmd).lower() == "c":
                            if skip_curves:
                                continue

                            control_points = []
                            for pt in item[1:]:
                                control_points.append(
                                    (pt[0], page_height - pt[1]))
                            if len(control_points) >= 2:
                                msp.add_spline(control_points, degree=3, dxfattribs={
                                               'layer': 'PDF_GEOMETRY'})

                        # RECTANGLE
                        elif str(cmd).lower() in ("re", "rect"):
                            rect = item[1]
                            points = [
                                (rect.x0, page_height - rect.y0),
                                (rect.x1, page_height - rect.y0),
                                (rect.x1, page_height - rect.y1),
                                (rect.x0, page_height - rect.y1),
                                (rect.x0, page_height - rect.y0)
                            ]
                            msp.add_lwpolyline(points, dxfattribs={
                                               'layer': 'PDF_GEOMETRY'})

                    except Exception:
                        continue

            # 2. Extract Text
            try:
                text_dict = page.get_text("dict")
            except Exception:
                text_dict = {}

            for block in text_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        try:
                            text = span.get("text", "").strip()
                            if not text:
                                continue

                            size = span.get("size", 10)
                            origin = span.get("origin", (0, 0))
                            insert_point = (origin[0], page_height - origin[1])

                            msp.add_mtext(
                                text,
                                dxfattribs={
                                    'char_height': size,
                                    'insert': insert_point,
                                    'attachment_point': 7,  # BottomLeft
                                    'layer': 'PDF_TEXT'
                                }
                            )
                        except Exception:
                            continue

            dxf.saveas(output_dxf_path)
            return True, None

        except Exception as e:
            return False, str(e)

    def _create_geometry_layer(self, page, output_path, crs, driver, feedback, canvas_extent=None, min_size=0.0, skip_curves=False):
        """Create a vector layer for PDF geometry (lines, curves, rectangles)"""
        # Minimal, shapefile-friendly field names
        fields = QgsFields()
        fields.append(QgsField("id", QVariant.Int))
        # shorter name for shapefile compatibility
        fields.append(QgsField("gtype", QVariant.String))

        page_width = getattr(page, "rect", None).width if getattr(
            page, "rect", None) else None
        page_height = getattr(page, "rect", None).height if getattr(
            page, "rect", None) else None

        if page_width is None or page_height is None:
            raise QgsProcessingException(
                "Unable to determine page dimensions from PyMuPDF page object.")

        feedback.pushInfo(
            f"Page dimensions: {page_width} x {page_height} points")

        # Calculate offset to center PDF in canvas extent (if available)
        if canvas_extent and not canvas_extent.isEmpty():
            canvas_center_x = canvas_extent.center().x()
            canvas_center_y = canvas_extent.center().y()
            offset_x = canvas_center_x - (page_width / 2.0)
            offset_y = canvas_center_y - (page_height / 2.0)
            feedback.pushInfo(
                f"Canvas center: ({canvas_center_x:.2f}, {canvas_center_y:.2f})")
            feedback.pushInfo(
                f"PDF will be placed at offset: ({offset_x:.2f}, {offset_y:.2f})")
        else:
            offset_x = 0.0
            offset_y = 0.0
            feedback.pushInfo("No canvas extent, placing PDF at origin (0, 0)")

        # Ensure parent dir exists
        parent = os.path.dirname(output_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

        # Create writer
        try:
            writer = QgsVectorFileWriter(
                output_path,
                "UTF-8",
                fields,
                QgsWkbTypes.LineString,
                crs,
                driver
            )
        except TypeError:
            # In case of QGIS API differences, try alternate signature
            try:
                writer = QgsVectorFileWriter(
                    output_path, fields, QgsWkbTypes.LineString, crs, driver)
            except Exception as e:
                raise Exception(f"Error creating geometry layer writer: {e}")

        # If writer reports error, raise
        try:
            err = writer.hasError() if hasattr(writer, 'hasError') else None
            if err is not None and err != QgsVectorFileWriter.NoError:
                msg = writer.errorMessage() if hasattr(
                    writer, 'errorMessage') else "Unknown writer error"
                raise Exception(f"Error creating geometry layer: {msg}")
        except Exception:
            # proceed — some QGIS versions don't expose hasError in same way
            pass

        paths = []
        try:
            # fitz page.get_drawings() sometimes returns None or empty
            paths = page.get_drawings() or []
        except Exception as e:
            feedback.pushWarning(f"Could not extract drawings from page: {e}")
            paths = []

        feature_id = 0
        for path in paths:
            # path is usually a dict with key "items"
            items = path.get("items", []) if isinstance(path, dict) else []
            for item in items:
                if not item:
                    continue
                cmd = item[0]
                # safe decode for bytes
                if isinstance(cmd, bytes):
                    try:
                        cmd = cmd.decode('utf-8', errors='ignore')
                    except Exception:
                        cmd = str(cmd)
                else:
                    cmd = str(cmd)

                # Size Filter
                pass_size = True
                if min_size > 0:
                    w, h = 0, 0
                    if str(cmd).lower() == "l":
                        p1, p2 = item[1], item[2]
                        w = abs(p1[0] - p2[0])
                        h = abs(p1[1] - p2[1])
                    elif str(cmd).lower() == "c":
                        xs = [pt[0] for pt in item[1:] if pt]
                        ys = [pt[1] for pt in item[1:] if pt]
                        if xs and ys:
                            w = max(xs) - min(xs)
                            h = max(ys) - min(ys)
                    elif str(cmd).lower() in ("re", "rect"):
                        rect = item[1]
                        w, h = rect.width, rect.height

                    if max(w, h) < min_size:
                        pass_size = False

                if not pass_size:
                    continue

                try:
                    feature = QgsFeature(fields)
                    feature.setAttribute("id", feature_id)

                    if cmd == 'l' or cmd.lower() == 'l':  # line
                        # item[1], item[2] are points
                        p1 = item[1]
                        p2 = item[2]
                        pt1 = self._simple_transform(
                            p1, page_height, offset_x, offset_y)
                        pt2 = self._simple_transform(
                            p2, page_height, offset_x, offset_y)
                        geom = QgsGeometry.fromPolylineXY(
                            [QgsPointXY(pt1[0], pt1[1]), QgsPointXY(pt2[0], pt2[1])])
                        feature.setGeometry(geom)
                        feature.setAttribute("gtype", "line")
                        writer.addFeature(feature)
                        feature_id += 1

                    elif cmd == 'c' or cmd.lower() == 'c':  # curve (bezier segment)
                        if skip_curves:
                            continue

                        # safe-get points; some versions provide 4 points
                        pts = []
                        for pi in item[1:]:
                            if pi is None:
                                continue
                            # pi might be tuple(x,y)
                            if isinstance(pi, (list, tuple)) and len(pi) >= 2:
                                pts.append(self._simple_transform(
                                    pi, page_height, offset_x, offset_y))
                                if len(pts) >= 4:
                                    break
                        if len(pts) >= 2:
                            qgs_pts = [QgsPointXY(p[0], p[1]) for p in pts]
                            geom = QgsGeometry.fromPolylineXY(qgs_pts)
                            feature.setGeometry(geom)
                            feature.setAttribute("gtype", "curve")
                            writer.addFeature(feature)
                            feature_id += 1

                    elif cmd == 're' or cmd.lower() == 're' or cmd == 'rect':
                        # rectangle data may be in item[1] as a Rect objects or tuple
                        rect = item[1]
                        try:
                            # rect might have attributes x0, y0, x1, y1
                            x0, y0 = rect.x0, rect.y0
                            x1, y1 = rect.x1, rect.y1
                        except Exception:
                            # maybe it's a tuple (x0, y0, x1, y1)
                            try:
                                x0, y0, x1, y1 = rect
                            except Exception:
                                continue
                        pts = [(x0, y0), (x1, y0), (x1, y1),
                               (x0, y1), (x0, y0)]
                        qgs_points = [QgsPointXY(
                            *self._simple_transform(p, page_height, offset_x, offset_y)) for p in pts]
                        geom = QgsGeometry.fromPolylineXY(qgs_points)
                        feature.setGeometry(geom)
                        feature.setAttribute("gtype", "rectangle")
                        writer.addFeature(feature)
                        feature_id += 1

                    else:
                        # unhandled command; attempt to extract any point-like data and write as short polyline
                        pts = []
                        for part in item[1:]:
                            if isinstance(part, (list, tuple)) and len(part) >= 2:
                                pts.append(self._simple_transform(
                                    part, page_height, offset_x, offset_y))
                        if pts:
                            qgs_pts = [QgsPointXY(p[0], p[1]) for p in pts]
                            geom = QgsGeometry.fromPolylineXY(qgs_pts)
                            feature.setGeometry(geom)
                            feature.setAttribute("gtype", f"cmd_{cmd}")
                            writer.addFeature(feature)
                            feature_id += 1
                except Exception as e:
                    feedback.pushWarning(
                        f"Skipping drawing item due to error: {e}")
                    continue

        # finalize writer
        try:
            del writer
        except Exception:
            pass

        feedback.pushInfo(f"Created geometry layer with {feature_id} features")

        # Report final extent
        final_x_min = offset_x
        final_y_min = offset_y
        final_x_max = offset_x + page_width
        final_y_max = offset_y + page_height
        feedback.pushInfo(
            f"Layer extent: ({final_x_min:.2f}, {final_y_min:.2f}) to ({final_x_max:.2f}, {final_y_max:.2f})")

    def _create_text_layer(self, page, output_path, crs, driver, feedback, canvas_extent=None):
        """Create a vector layer for PDF text"""
        fields = QgsFields()
        fields.append(QgsField("id", QVariant.Int))
        fields.append(QgsField("txt", QVariant.String))
        fields.append(QgsField("fsize", QVariant.Double))
        fields.append(QgsField("fname", QVariant.String))

        page_width = getattr(page, "rect", None).width if getattr(
            page, "rect", None) else None
        page_height = getattr(page, "rect", None).height if getattr(
            page, "rect", None) else None

        if page_width is None or page_height is None:
            raise QgsProcessingException(
                "Unable to determine page dimensions from PyMuPDF page object.")

        if canvas_extent and not canvas_extent.isEmpty():
            canvas_center_x = canvas_extent.center().x()
            canvas_center_y = canvas_extent.center().y()
            offset_x = canvas_center_x - (page_width / 2.0)
            offset_y = canvas_center_y - (page_height / 2.0)
        else:
            offset_x = 0.0
            offset_y = 0.0

        parent = os.path.dirname(output_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

        try:
            writer = QgsVectorFileWriter(
                output_path,
                "UTF-8",
                fields,
                QgsWkbTypes.Point,
                crs,
                driver
            )
        except TypeError:
            try:
                writer = QgsVectorFileWriter(
                    output_path, fields, QgsWkbTypes.Point, crs, driver)
            except Exception as e:
                raise Exception(f"Error creating text layer writer: {e}")

        try:
            text_dict = page.get_text("dict") or {}
        except Exception as e:
            feedback.pushWarning(f"Could not extract text from page: {e}")
            text_dict = {}

        text_count = 0
        for block in text_dict.get("blocks", []):
            if block.get("type", None) != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "")
                    if not text or not text.strip():
                        continue
                    size = span.get("size", 0.0)
                    origin = span.get("origin", None)
                    font = span.get("font", "Unknown")

                    if not origin or len(origin) < 2:
                        # sometimes origin not present; try bbox
                        bbox = span.get("bbox", None)
                        if bbox and len(bbox) >= 2:
                            origin = (bbox[0], bbox[1])
                        else:
                            continue

                    transformed_pt = self._simple_transform(
                        origin, page_height, offset_x, offset_y)

                    try:
                        feature = QgsFeature(fields)
                        feature.setAttribute("id", text_count)
                        feature.setAttribute("txt", text)
                        feature.setAttribute("fsize", float(size))
                        feature.setAttribute("fname", font)
                        geom = QgsGeometry.fromPointXY(QgsPointXY(
                            transformed_pt[0], transformed_pt[1]))
                        feature.setGeometry(geom)
                        writer.addFeature(feature)
                        text_count += 1
                    except Exception as e:
                        feedback.pushWarning(
                            f"Skipping text span due to error: {e}")
                        continue

        try:
            del writer
        except Exception:
            pass

        feedback.pushInfo(f"Created text layer with {text_count} features")

    def _simple_transform(self, point, page_height, offset_x, offset_y):
        """
        Simple transformation: flip Y axis and add offset.
        PDF: (0,0) at top-left, Y increases downward
        Output: (0,0) at bottom-left, Y increases upward, then offset to canvas center
        """
        # point expected as (x, y)
        try:
            x = float(point[0])
            y = float(point[1])
        except Exception:
            # fallback: if point is object with x,y
            try:
                x = float(point.x)
                y = float(point.y)
            except Exception:
                x, y = 0.0, 0.0
        new_y = page_height - y
        final_x = x + offset_x
        final_y = new_y + offset_y
        return (final_x, final_y)
