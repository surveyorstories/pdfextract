# ========================================================================
# PDF → Vector Converter (Tabbed UI, Progress Bar, Page Range, Safe Tasks)
# ========================================================================
# Author: Surveyor Stories
# Features:
#   ✓ Tabbed UI (Input / Advanced)
#   ✓ Progress bar inside dialog (updates safely)
#   ✓ Page range: All pages or From–To
#   ✓ Extract: Geometry only, Text only, or Both
#   ✓ Output: Shapefile, GeoJSON, DXF
#   ✓ Option: Load output layers into QGIS project
#   ✓ Groups multiple files in layer panel
#   ✓ Qt5 and Qt6 compatible
# ========================================================================

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QComboBox, QMessageBox, QTabWidget,
    QWidget, QCheckBox, QSpinBox, QGroupBox, QFormLayout, QProgressBar,
    QFrame
)
from qgis.PyQt.QtCore import Qt, QTimer, QVariant
from qgis.core import (
    QgsTask, QgsApplication, QgsProject,
    QgsVectorLayer, QgsVectorFileWriter, QgsFields, QgsField,
    QgsFeature, QgsGeometry, QgsWkbTypes, QgsCoordinateReferenceSystem,
    QgsPointXY, Qgis, QgsLayerTreeGroup
)
from qgis.utils import iface
import os, traceback

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

try:
    import ezdxf
except Exception:
    ezdxf = None

# =========================================================
# DXF EXPORT HELPER (using ezdxf)
# =========================================================
def convert_pdf_page_to_dxf_direct(page, output_dxf_path):
    """Convert PDF page directly to DXF using ezdxf (better quality)."""
    if ezdxf is None:
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
                        control_points = []
                        for pt in item[1:]:
                            control_points.append((pt[0], page_height - pt[1]))
                        if len(control_points) >= 2:
                            msp.add_spline(control_points, degree=3, dxfattribs={'layer': 'PDF_GEOMETRY'})
                    
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
                        msp.add_lwpolyline(points, dxfattribs={'layer': 'PDF_GEOMETRY'})
                
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



# =========================================================
# BACKGROUND TASK
# =========================================================
class PdfToVectorTask(QgsTask):
    def __init__(self, pdf_path, out_dir, out_fmt, crs, canvas_extent,
                 page_from, page_to, include_geom, include_text,
                 load_outputs, dialog_ref=None):

        super().__init__("PDF → Vector Conversion", QgsTask.CanCancel)
        self.pdf_path = pdf_path
        self.out_dir = out_dir
        self.out_fmt = out_fmt
        self.crs = crs
        self.canvas_extent = canvas_extent
        self.page_from = page_from
        self.page_to = page_to
        self.include_geom = include_geom
        self.include_text = include_text
        self.load_outputs = load_outputs
        self.dialog_ref = dialog_ref

        self.generated = []
        self.error = None

    def run(self):
        """Runs in background thread."""
        try:
            doc = fitz.open(self.pdf_path)
            total_pages = len(doc)

            start = max(1, self.page_from)
            end = min(total_pages, self.page_to)

            base = os.path.splitext(os.path.basename(self.pdf_path))[0]
            os.makedirs(self.out_dir, exist_ok=True)

            # Choose driver for geometry/text
            for index, i in enumerate(range(start - 1, end)):
                if self.isCanceled():
                    return False

                page_num = i + 1
                page = doc[i]

                # driver for intermediate files (DXF uses geojson intermediate)
                if self.out_fmt == "shp":
                    geom_ext, text_ext = ".shp", ".shp"
                    driver = "ESRI Shapefile"
                elif self.out_fmt == "geojson":
                    geom_ext, text_ext = ".geojson", ".geojson"
                    driver = "GeoJSON"
                else:
                    geom_ext, text_ext = ".geojson", ".geojson"
                    driver = "GeoJSON"

                geom_path = os.path.join(self.out_dir, f"{base}_p{page_num}_geom{geom_ext}")
                text_path = os.path.join(self.out_dir, f"{base}_p{page_num}_text{text_ext}")

                # DXF export - use direct ezdxf method if available
                if self.out_fmt == "dxf":
                    dxf_out = os.path.join(self.out_dir, f"{base}_p{page_num}.dxf")
                    
                    # Try ezdxf direct conversion (better quality)
                    ok, msg = convert_pdf_page_to_dxf_direct(page, dxf_out)
                    
                    if ok:
                        self.generated.append((dxf_out, f"{base} Page {page_num}", "dxf"))
                    else:
                        QgsApplication.logMessage(f"ezdxf conversion failed: {msg}, using fallback", "PDF2Vector", Qgis.Warning)
                        # Fallback: write intermediate files
                        if self.include_geom:
                            self._write_geometry(page, geom_path, driver)
                            self.generated.append((geom_path, f"{base} Page {page_num} Geometry", "geom"))
                        if self.include_text:
                            self._write_text(page, text_path, driver)
                            self.generated.append((text_path, f"{base} Page {page_num} Text", "text"))
                else:
                    # Write layers for shp/geojson
                    if self.include_geom:
                        self._write_geometry(page, geom_path, driver)
                        self.generated.append((geom_path, f"{base} Page {page_num} Geometry", "geom"))
                    if self.include_text:
                        self._write_text(page, text_path, driver)
                        self.generated.append((text_path, f"{base} Page {page_num} Text", "text"))

                # update progress
                percent = int(((index + 1) / (end - start + 1)) * 100)
                self.setProgress(percent)

            return True

        except Exception as e:
            self.error = e
            traceback.print_exc()
            return False


    # -----------------------------------------------
    # GEOMETRY WRITER
    # -----------------------------------------------
    def _write_geometry(self, page, out_path, driver):
        fields = QgsFields()
        fields.append(QgsField("id", QVariant.Int))
        fields.append(QgsField("type", QVariant.String))

        page_w = float(page.rect.width)
        page_h = float(page.rect.height)

        ox, oy = 0.0, 0.0
        if self.canvas_extent and not self.canvas_extent.isEmpty():
            ox = self.canvas_extent.center().x() - page_w / 2
            oy = self.canvas_extent.center().y() - page_h / 2

        # create writer compatible with different QGIS versions
        try:
            writer = QgsVectorFileWriter(
                out_path, "UTF-8", fields,
                QgsWkbTypes.LineString, self.crs, driver)
        except:
            writer = QgsVectorFileWriter(out_path, fields,
                                         QgsWkbTypes.LineString,
                                         self.crs, driver)

        drawings = page.get_drawings() or []
        fid = 0
        for d in drawings:
            for item in d.get("items", []):
                try:
                    cmd = item[0]
                    if isinstance(cmd, bytes):
                        cmd = cmd.decode("utf-8", "ignore")

                    feat = QgsFeature(fields)
                    feat.setAttribute("id", fid)

                    # LINE
                    if str(cmd).lower() == "l":
                        p1 = item[1]; p2 = item[2]
                        x1, y1 = p1[0] + ox, page_h - p1[1] + oy
                        x2, y2 = p2[0] + ox, page_h - p2[1] + oy
                        geom = QgsGeometry.fromPolylineXY([
                            QgsPointXY(x1, y1),
                            QgsPointXY(x2, y2)
                        ])
                        feat.setGeometry(geom)
                        feat.setAttribute("type", "line")
                        writer.addFeature(feat)
                        fid += 1

                    # CURVE (write polyline through control points)
                    elif str(cmd).lower() == "c":
                        pts = []
                        for cpt in item[1:]:
                            px = cpt[0] + ox
                            py = page_h - cpt[1] + oy
                            pts.append(QgsPointXY(px, py))
                        if len(pts) >= 2:
                            geom = QgsGeometry.fromPolylineXY(pts)
                            feat.setGeometry(geom)
                            feat.setAttribute("type", "curve")
                            writer.addFeature(feat)
                            fid += 1

                    # RECTANGLE
                    elif str(cmd).lower() in ("re", "rect"):
                        rect = item[1]
                        x0, y0 = rect.x0, rect.y0
                        x1, y1 = rect.x1, rect.y1
                        pts = [
                            QgsPointXY(x0 + ox, page_h - y0 + oy),
                            QgsPointXY(x1 + ox, page_h - y0 + oy),
                            QgsPointXY(x1 + ox, page_h - y1 + oy),
                            QgsPointXY(x0 + ox, page_h - y1 + oy),
                            QgsPointXY(x0 + ox, page_h - y0 + oy)
                        ]
                        geom = QgsGeometry.fromPolylineXY(pts)
                        feat.setGeometry(geom)
                        feat.setAttribute("type", "rect")
                        writer.addFeature(feat)
                        fid += 1

                except Exception:
                    continue

        del writer


    # -----------------------------------------------
    # TEXT WRITER
    # -----------------------------------------------
    def _write_text(self, page, out_path, driver):
        fields = QgsFields()
        fields.append(QgsField("id", QVariant.Int))
        fields.append(QgsField("text", QVariant.String))
        fields.append(QgsField("size", QVariant.Double))
        fields.append(QgsField("font", QVariant.String))

        page_h = float(page.rect.height)

        try:
            writer = QgsVectorFileWriter(
                out_path, "UTF-8", fields,
                QgsWkbTypes.Point, self.crs, driver)
        except:
            writer = QgsVectorFileWriter(out_path, fields,
                                         QgsWkbTypes.Point,
                                         self.crs, driver)

        ox = oy = 0.0
        page_w = float(page.rect.width)
        if self.canvas_extent and not self.canvas_extent.isEmpty():
            ox = self.canvas_extent.center().x() - page_w / 2
            oy = self.canvas_extent.center().y() - page_h / 2

        try:
            info = page.get_text("dict")
        except Exception:
            info = {}

        fid = 0
        for block in info.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    try:
                        txt = span.get("text", "").strip()
                        if not txt:
                            continue
                        oxg, oyg = span.get("origin", (None, None))
                        if oxg is None:
                            continue
                        x = oxg + ox
                        y = page_h - oyg + oy
                        feat = QgsFeature(fields)
                        feat.setAttribute("id", fid)
                        feat.setAttribute("text", txt)
                        feat.setAttribute("size", float(span.get("size", 0.0)))
                        feat.setAttribute("font", span.get("font", "Unknown"))
                        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
                        writer.addFeature(feat)
                        fid += 1
                    except Exception:
                        continue

        del writer


    # -----------------------------------------------
    # TASK FINISHED (MAIN THREAD)
    # -----------------------------------------------
    def finished(self, result):
        """Called in MAIN thread."""
        if self.error:
            iface.messageBar().pushCritical("PDF→Vector", str(self.error))
            if self.dialog_ref:
                self.dialog_ref.on_task_finished(False, str(self.error))
            return

        loaded = 0
        prj = QgsProject.instance()
        
        # Create a group if multiple files
        group = None
        if len(self.generated) > 1 and self.load_outputs:
            base_name = os.path.splitext(os.path.basename(self.pdf_path))[0]
            group_name = f"PDF_{base_name}"
            
            root = prj.layerTreeRoot()
            group = root.insertGroup(0, group_name)

        for path, name, typ in self.generated:
            if not os.path.exists(path): 
                continue
            if not self.load_outputs: 
                continue

            lyr = QgsVectorLayer(path, name, "ogr")
            if lyr.isValid():
                prj.addMapLayer(lyr, False)  # Add without showing in legend yet
                
                if group:
                    group.addLayer(lyr)
                else:
                    # If only one layer, add normally
                    prj.layerTreeRoot().addLayer(lyr)
                
                loaded += 1

        iface.messageBar().pushSuccess("PDF→Vector",
            f"Conversion completed. {loaded} layers loaded.")

        if self.dialog_ref:
            self.dialog_ref.on_task_finished(True, f"{loaded} layers loaded.")



# =========================================================
# TABBED UI DIALOG
# =========================================================
class PdfToVectorDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF → Vector Converter")
        self.setMinimumWidth(450)

        self.task = None
        self.task_timer = QTimer()
        self.task_timer.setInterval(300)
        self.task_timer.timeout.connect(self._update_progress_safe)

        self._build_ui()

    # ----------------------------------------------------
    # UI CREATION
    # ----------------------------------------------------
    def _build_ui(self):
        main = QVBoxLayout()
        main.setSpacing(12)
        main.setContentsMargins(12, 12, 12, 12)
        
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #c0c0c0;
                border-radius: 4px;
             
            }
            QTabBar::tab {
                padding: 8px 20px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
           
                border-bottom: 2px solid #0078d4;
            }
        """)

        # --------------------------
        # Input Tab
        # --------------------------
        tab_input = QWidget()
        layout_in = QVBoxLayout()
        layout_in.setSpacing(10)
        layout_in.setContentsMargins(12, 12, 12, 12)

        # Input & Output section
        grp_io = QGroupBox("Input / Output")
        grp_io_layout = QVBoxLayout()
        grp_io_layout.setSpacing(8)
        
        grp_io_layout.addWidget(QLabel("PDF File:"))
        row_pdf = QHBoxLayout()
        self.pdf_edit = QLineEdit()
        self.pdf_edit.setPlaceholderText("Select a PDF file...")
        btn_pdf = QPushButton("Browse...")
        btn_pdf.setMinimumWidth(100)
        btn_pdf.clicked.connect(self._pick_pdf)
        row_pdf.addWidget(self.pdf_edit)
        row_pdf.addWidget(btn_pdf)
        grp_io_layout.addLayout(row_pdf)

        grp_io_layout.addSpacing(4)
        grp_io_layout.addWidget(QLabel("Output Folder:"))
        row_out = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("Select output folder...")
        btn_out = QPushButton("Browse...")
        btn_out.setMinimumWidth(100)
        btn_out.clicked.connect(self._pick_out)
        row_out.addWidget(self.out_edit)
        row_out.addWidget(btn_out)
        grp_io_layout.addLayout(row_out)

        grp_io_layout.addSpacing(4)
        grp_io_layout.addWidget(QLabel("Output Format:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["Shapefile (.shp)", "GeoJSON (.geojson)", "DXF (.dxf)"])
        grp_io_layout.addWidget(self.format_combo)
        
        grp_io.setLayout(grp_io_layout)
        layout_in.addWidget(grp_io)

        # Options section
        grp_options = QGroupBox("Options")
        grp_options_layout = QVBoxLayout()
        grp_options_layout.setSpacing(6)
        
        self.chk_load = QCheckBox("Load results into QGIS project")
        self.chk_load.setChecked(True)
        grp_options_layout.addWidget(self.chk_load)
        
        grp_options.setLayout(grp_options_layout)
        layout_in.addWidget(grp_options)

        layout_in.addStretch()
        tab_input.setLayout(layout_in)
        tabs.addTab(tab_input, "Input")

        # --------------------------
        # Advanced Tab
        # --------------------------
        tab_adv = QWidget()
        layout_adv = QVBoxLayout()
        layout_adv.setSpacing(10)
        layout_adv.setContentsMargins(12, 12, 12, 12)

        # Page range
        grp_range = QGroupBox("Page Range")
        frm = QFormLayout()
        frm.setSpacing(8)

        self.chk_range_all = QCheckBox("Process all pages")
        self.chk_range_all.setChecked(True)
        self.chk_range_all.stateChanged.connect(self._toggle_range)

        self.spin_from = QSpinBox(); self.spin_from.setMinimum(1)
        self.spin_from.setMinimumWidth(80)
        self.spin_to = QSpinBox(); self.spin_to.setMinimum(1)
        self.spin_to.setMinimumWidth(80)
        self.spin_from.setEnabled(False); self.spin_to.setEnabled(False)

        frm.addRow(self.chk_range_all)
        hr = QHBoxLayout()
        hr.setSpacing(10)
        hr.addWidget(QLabel("From:")); hr.addWidget(self.spin_from)
        hr.addWidget(QLabel("To:"));   hr.addWidget(self.spin_to)
        hr.addStretch()
        frm.addRow(hr)
        grp_range.setLayout(frm)
        layout_adv.addWidget(grp_range)

        # include
        grp_inc = QGroupBox("Extract Content")
        grp_inc_layout = QVBoxLayout()
        grp_inc_layout.setSpacing(6)
        self.chk_geom = QCheckBox("Geometry (lines, curves, rectangles)")
        self.chk_geom.setChecked(True)
        self.chk_text = QCheckBox("Text (labels and annotations)")
        self.chk_text.setChecked(True)
        grp_inc_layout.addWidget(self.chk_geom)
        grp_inc_layout.addWidget(self.chk_text)
        grp_inc.setLayout(grp_inc_layout)
        layout_adv.addWidget(grp_inc)

        layout_adv.addStretch()
        tab_adv.setLayout(layout_adv)
        tabs.addTab(tab_adv, "Advanced")

        main.addWidget(tabs)

        # --------------------------
        # Progress & Buttons
        pb_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: #e0e0e0;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: #0078d4;
                border-radius: 2px;
            }
        """)
        
        self.lbl_prog = QLabel("Ready")
        self.lbl_prog.setStyleSheet("color: #666666; font-size: 11px;")
        
        pb_row.addWidget(self.progress)
        pb_row.addWidget(self.lbl_prog)
        main.addLayout(pb_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_convert = QPushButton("Convert")
        self.btn_convert.setMinimumWidth(100)
        self.btn_convert.setMinimumHeight(32)
        self.btn_convert.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        self.btn_convert.clicked.connect(self.start)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setMinimumWidth(100)
        self.btn_cancel.setMinimumHeight(32)
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_cancel.setEnabled(False)
        
        self.btn_close = QPushButton("Close")
        self.btn_close.setMinimumWidth(100)
        self.btn_close.setMinimumHeight(32)
        self.btn_close.clicked.connect(self.close)
        
        btn_row.addWidget(self.btn_convert)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_close)
        main.addLayout(btn_row)

        self.setLayout(main)

    # ----------------------------------------------------
    # UI callbacks
    # ----------------------------------------------------
    def _pick_pdf(self):
        # Qt5/Qt6 compatible file dialog
        result = QFileDialog.getOpenFileName(self, "Select PDF", "", "PDF (*.pdf)")
        # In Qt5 it returns (filename, filter), in Qt6 same
        f = result[0] if isinstance(result, tuple) else result
        if f:
            self.pdf_edit.setText(f)
            try:
                doc = fitz.open(f)
                n = len(doc)
                self.spin_from.setMaximum(n)
                self.spin_to.setMaximum(n)
                self.spin_to.setValue(n)
            except:
                pass

    def _pick_out(self):
        # Qt5/Qt6 compatible directory dialog
        d = QFileDialog.getExistingDirectory(self, "Select output folder")
        if d:
            self.out_edit.setText(d)

    def _toggle_range(self, state):
        # Qt5/Qt6 compatible: check if state is checked
        try:
            # Qt6
            allp = (state == Qt.CheckState.Checked)
        except AttributeError:
            # Qt5
            allp = (state == Qt.Checked)
        self.spin_from.setEnabled(not allp)
        self.spin_to.setEnabled(not allp)

    # ----------------------------------------------------
    # START TASK
    # ----------------------------------------------------
    def start(self):
        pdf = self.pdf_edit.text().strip()
        out = self.out_edit.text().strip()
        if not os.path.exists(pdf):
            QMessageBox.warning(self, "Error", "Invalid PDF")
            return
        if not out:
            QMessageBox.warning(self, "Error", "Select output folder")
            return

        try:
            doc = fitz.open(pdf)
            pages = len(doc)
        except Exception as e:
            QMessageBox.warning(self, "Error opening PDF", str(e))
            return

        if self.chk_range_all.isChecked():
            p_from, p_to = 1, pages
        else:
            p_from = self.spin_from.value()
            p_to = self.spin_to.value()
            if p_from < 1 or p_to < p_from or p_to > pages:
                QMessageBox.warning(self, "Error", "Invalid page range")
                return

        if not (self.chk_geom.isChecked() or self.chk_text.isChecked()):
            QMessageBox.warning(self, "Error", "Select geometry or text.")
            return

        fmt_i = self.format_combo.currentIndex()
        out_fmt = "shp" if fmt_i == 0 else ("geojson" if fmt_i == 1 else "dxf")

        # disable UI
        self.btn_convert.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_close.setEnabled(False)

        prj = QgsProject.instance()
        crs = prj.crs() if prj.crs().isValid() else QgsCoordinateReferenceSystem("EPSG:4326")

        try:
            cext = iface.mapCanvas().extent()
        except:
            cext = None

        self.task = PdfToVectorTask(
            pdf, out, out_fmt, crs, cext,
            page_from=p_from, page_to=p_to,
            include_geom=self.chk_geom.isChecked(),
            include_text=self.chk_text.isChecked(),
            load_outputs=self.chk_load.isChecked(),
            dialog_ref=self
        )
        QgsApplication.taskManager().addTask(self.task)

        self.progress.setValue(0)
        self.lbl_prog.setText("0%")
        self.task_timer.start()

    # ----------------------------------------------------
    # CANCEL TASK
    # ----------------------------------------------------
    def _cancel(self):
        if self.task:
            self.task.cancel()
            self.lbl_prog.setText("Cancelling...")

    # ----------------------------------------------------
    # SAFE PROGRESS UPDATE (patched)
    # ----------------------------------------------------
    
    def _update_progress_safe(self):
        """Safely update progress without touching deleted QObject."""
        if self.task is None:
            self.task_timer.stop()
            return

        # Safe status poll
        try:
            status = self.task.status()
        except RuntimeError:
            # Task is already deleted
            self.task = None
            self.task_timer.stop()
            return

        # If task finished or terminated, stop timer
        # Qt5/Qt6 compatible task status check
        try:
            # Qt6 style
            if status in (QgsTask.TaskStatus.Complete, QgsTask.TaskStatus.Terminated):
                self.task_timer.stop()
                return
        except AttributeError:
            # Qt5 style
            if status in (QgsTask.Complete, QgsTask.Terminated):
                self.task_timer.stop()
                return

        # Safe reading of progress
        try:
            prog = int(self.task.progress())
            self.progress.setValue(prog)
            self.lbl_prog.setText(f"{prog}%")
        except RuntimeError:
            self.task = None
            self.task_timer.stop()
            return

    # ----------------------------------------------------
    # TASK FINISHED (called by thread in main thread)
    # ----------------------------------------------------
    def on_task_finished(self, success, message=""):
        self.task_timer.stop()
        self.task = None

        if success:
            self.progress.setValue(100)
            self.lbl_prog.setText("Done")
        else:
            self.progress.setValue(0)
            self.lbl_prog.setText("Failed")

        # re-enable UI
        self.btn_convert.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_close.setEnabled(True)

        if success:
            QMessageBox.information(self, "Done", message)
            # Reset progress after user acknowledges
            self.progress.setValue(0)
            self.lbl_prog.setText("Ready")
        else:
            QMessageBox.critical(self, "Error", message)



# =========================================================
# SHOW DIALOG
# =========================================================
# dlg = PdfToVectorDialog()
# dlg.show()