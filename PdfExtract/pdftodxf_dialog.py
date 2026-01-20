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
    QFrame, QScrollArea, QDoubleSpinBox
)
from qgis.PyQt.QtCore import Qt, QTimer, QVariant, QRect, QPoint
from qgis.PyQt.QtGui import QPixmap, QImage, QPainter, QPen, QColor
from qgis.core import (
    QgsTask, QgsApplication, QgsProject,
    QgsVectorLayer, QgsVectorFileWriter, QgsFields, QgsField,
    QgsFeature, QgsGeometry, QgsWkbTypes, QgsCoordinateReferenceSystem,
    QgsPointXY, Qgis, QgsLayerTreeGroup
)
from qgis.utils import iface
import os
import traceback

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


def clip_line_to_rect(x1, y1, x2, y2, rect):
    """
    Clip a line segment to a rectangle using Cohen-Sutherland algorithm.
    Returns (clipped_x1, clipped_y1, clipped_x2, clipped_y2) or None if line is completely outside.
    """
    # Define region codes
    INSIDE = 0  # 0000
    LEFT = 1    # 0001
    RIGHT = 2   # 0010
    BOTTOM = 4  # 0100
    TOP = 8     # 1000

    def compute_code(x, y):
        code = INSIDE
        if x < rect.x0:
            code |= LEFT
        elif x > rect.x1:
            code |= RIGHT
        if y < rect.y0:
            code |= BOTTOM
        elif y > rect.y1:
            code |= TOP
        return code

    code1 = compute_code(x1, y1)
    code2 = compute_code(x2, y2)

    while True:
        # Both endpoints inside - accept
        if code1 == 0 and code2 == 0:
            return (x1, y1, x2, y2)

        # Both endpoints share an outside region - reject
        if code1 & code2:
            return None

        # Line needs clipping
        # Pick an endpoint that is outside
        code_out = code1 if code1 != 0 else code2

        # Find intersection point
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

        # Replace the outside point with the intersection
        if code_out == code1:
            x1, y1 = x, y
            code1 = compute_code(x1, y1)
        else:
            x2, y2 = x, y
            code2 = compute_code(x2, y2)


def convert_pdf_page_to_dxf_direct(page, output_dxf_path, crop_rect=None, min_size=0.0, skip_curves=False):
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
            # Check if path intersects with crop region (not full containment)
            if crop_rect:
                path_rect = path.get("rect")
                if path_rect:
                    # Check if path intersects the crop region
                    if not (path_rect.x0 <= crop_rect.x1 and path_rect.x1 >= crop_rect.x0 and
                            path_rect.y0 <= crop_rect.y1 and path_rect.y1 >= crop_rect.y0):
                        continue  # Skip paths that don't intersect crop region

                try:
                    cmd = item[0]
                    if isinstance(cmd, bytes):
                        cmd = cmd.decode("utf-8", "ignore")

                    # Check size for filtering logic
                    # Calculate bounding box of the item if possible or approximate size
                    # For simple lines/curves we can check length or bounds
                    pass_size_check = True
                    if min_size > 0:
                        # item structure depends on cmd
                        # l, c, re/rect
                        bbox_w = 0
                        bbox_h = 0
                        if str(cmd).lower() == "l":
                            p1, p2 = item[1], item[2]
                            bbox_w = abs(p1[0] - p2[0])
                            bbox_h = abs(p1[1] - p2[1])
                        elif str(cmd).lower() == "c":
                            # bezier control points
                            xs = [pt[0] for pt in item[1:] if pt]
                            ys = [pt[1] for pt in item[1:] if pt]
                            if xs and ys:
                                bbox_w = max(xs) - min(xs)
                                bbox_h = max(ys) - min(ys)
                        elif str(cmd).lower() in ("re", "rect"):
                            rect = item[1]
                            bbox_w = rect.width
                            bbox_h = rect.height

                        if max(bbox_w, bbox_h) < min_size:
                            pass_size_check = False

                    if not pass_size_check:
                        continue

                    # LINE
                    if str(cmd).lower() == "l":
                        p1 = item[1]
                        p2 = item[2]

                        # Clip line to crop region if needed
                        if crop_rect:
                            clipped = clip_line_to_rect(
                                p1[0], p1[1], p2[0], p2[1], crop_rect)
                            if clipped is None:
                                continue  # Line is completely outside crop region

                            x1, y1, x2, y2 = clipped
                            msp.add_line(
                                (x1, page_height - y1),
                                (x2, page_height - y2),
                                dxfattribs={'layer': 'PDF_GEOMETRY'}
                            )
                        else:
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
                        # For curves, check if all points are within crop region
                        all_inside = True
                        for pt in item[1:]:
                            if crop_rect:
                                if not (crop_rect.x0 <= pt[0] <= crop_rect.x1 and
                                        crop_rect.y0 <= pt[1] <= crop_rect.y1):
                                    all_inside = False
                                    break

                        if not all_inside and crop_rect:
                            continue  # Skip curves that extend outside crop region

                        for pt in item[1:]:
                            control_points.append((pt[0], page_height - pt[1]))
                        if len(control_points) >= 2:
                            msp.add_spline(control_points, degree=3, dxfattribs={
                                           'layer': 'PDF_GEOMETRY'})

                    # RECTANGLE
                    elif str(cmd).lower() in ("re", "rect"):
                        rect = item[1]

                        if crop_rect:
                            # For rectangles, check if fully contained within crop
                            if not (rect.x0 >= crop_rect.x0 and rect.x1 <= crop_rect.x1 and
                                    rect.y0 >= crop_rect.y0 and rect.y1 <= crop_rect.y1):
                                continue  # Skip rectangles not fully within crop

                        x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1

                        points = [
                            (x0, page_height - y0),
                            (x1, page_height - y0),
                            (x1, page_height - y1),
                            (x0, page_height - y1),
                            (x0, page_height - y0)
                        ]
                        msp.add_lwpolyline(points, dxfattribs={
                                           'layer': 'PDF_GEOMETRY'})

                except Exception:
                    continue

        # 2. Extract Text
        try:
            if crop_rect:
                # Use clip parameter to extract only text in crop region
                text_dict = page.get_text("dict", clip=crop_rect)
            else:
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
# CROP PREVIEW DIALOG
# =========================================================
class CropPreviewDialog(QDialog):
    """Dialog for selecting a crop region on a PDF page preview."""

    def __init__(self, pdf_path, existing_crop_rect=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Crop Region")
        self.setMinimumSize(800, 600)

        self.pdf_path = pdf_path
        self.crop_rect = existing_crop_rect  # Will be a fitz.Rect in PDF coordinates
        self.page_rect = None  # Full page rect

        # Selection state
        self.selecting = False
        self.start_point = None
        self.current_point = None

        # Display scaling and zoom
        self.base_scale_factor = 1.0  # Base scale from PDF to rendered image
        self.zoom_level = 1.0  # Current zoom multiplier (1.0 = 100%)
        self.offset_x = 0
        self.offset_y = 0

        # Store the original rendered pixmap
        self.original_pixmap = None
        self.base_pixmap = None  # Zoomed version

        # Page navigation
        self.current_page = 0  # 0-indexed
        self.total_pages = 0

        self._build_ui()
        self._load_pdf_preview()

    def _build_ui(self):
        layout = QVBoxLayout()

        # Scroll area for the image (no instruction label to prevent scroll)
        scroll = QScrollArea()
        # Fixed size to avoid coordinate issues
        scroll.setWidgetResizable(False)

        # Image label (will draw the PDF and selection)
        self.image_label = QLabel()
        self.image_label.setMouseTracking(True)
        self.image_label.setScaledContents(False)

        # Set crosshair cursor
        try:
            # Qt6
            self.image_label.setCursor(Qt.CursorShape.CrossCursor)
        except AttributeError:
            # Qt5
            self.image_label.setCursor(Qt.CrossCursor)

        self.image_label.mousePressEvent = self._on_mouse_press
        self.image_label.mouseMoveEvent = self._on_mouse_move
        self.image_label.mouseReleaseEvent = self._on_mouse_release
        scroll.setWidget(self.image_label)

        layout.addWidget(scroll)

        # Page navigation controls
        page_row = QHBoxLayout()
        page_row.addWidget(QLabel("Page:"))

        self.btn_prev_page = QPushButton("◀")
        self.btn_prev_page.setMaximumWidth(40)
        self.btn_prev_page.setToolTip("Previous Page")
        self.btn_prev_page.clicked.connect(self._prev_page)

        self.lbl_page = QLabel("1 / 1")
        try:
            self.lbl_page.setAlignment(Qt.AlignCenter)
        except AttributeError:
            self.lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_page.setMinimumWidth(80)

        self.btn_next_page = QPushButton("▶")
        self.btn_next_page.setMaximumWidth(40)
        self.btn_next_page.setToolTip("Next Page")
        self.btn_next_page.clicked.connect(self._next_page)

        page_row.addWidget(self.btn_prev_page)
        page_row.addWidget(self.lbl_page)
        page_row.addWidget(self.btn_next_page)
        page_row.addSpacing(20)

        # Zoom controls
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel("Zoom:"))

        btn_zoom_out = QPushButton("-")
        btn_zoom_out.setMaximumWidth(40)
        btn_zoom_out.setToolTip("Zoom Out")
        btn_zoom_out.clicked.connect(self._zoom_out)

        self.lbl_zoom = QLabel("100%")
        try:
            self.lbl_zoom.setAlignment(Qt.AlignCenter)
        except AttributeError:
            self.lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_zoom.setMinimumWidth(60)

        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setMaximumWidth(40)
        btn_zoom_in.setToolTip("Zoom In")
        btn_zoom_in.clicked.connect(self._zoom_in)

        btn_zoom_fit = QPushButton("Fit")
        btn_zoom_fit.setMaximumWidth(60)
        btn_zoom_fit.setToolTip("Fit to Window")
        btn_zoom_fit.clicked.connect(self._zoom_fit)

        zoom_row.addWidget(btn_zoom_out)
        zoom_row.addWidget(self.lbl_zoom)
        zoom_row.addWidget(btn_zoom_in)
        zoom_row.addWidget(btn_zoom_fit)
        zoom_row.addStretch()

        # Combine page and zoom controls in one row
        controls_row = QHBoxLayout()
        controls_row.addLayout(page_row)
        controls_row.addLayout(zoom_row)

        layout.addLayout(controls_row)

        # Buttons
        btn_row = QHBoxLayout()
        btn_clear = QPushButton("Clear Selection")
        btn_clear.clicked.connect(self._clear_selection)
        btn_ok = QPushButton("OK")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)

        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)

        layout.addLayout(btn_row)
        self.setLayout(layout)

    def _load_pdf_preview(self, page_num=None):
        """Load specified page of PDF as an image, scaled to fit window."""
        if fitz is None:
            QMessageBox.warning(self, "Error", "PyMuPDF not available")
            self.reject()
            return

        try:
            doc = fitz.open(self.pdf_path)
            if len(doc) == 0:
                QMessageBox.warning(self, "Error", "PDF has no pages")
                self.reject()
                return

            # Track total pages
            self.total_pages = len(doc)

            # Use specified page or current_page
            if page_num is not None:
                self.current_page = max(0, min(page_num, self.total_pages - 1))

            # Update page label and button states
            if hasattr(self, 'lbl_page'):
                self.lbl_page.setText(
                    f"{self.current_page + 1} / {self.total_pages}")
            if hasattr(self, 'btn_prev_page'):
                self.btn_prev_page.setEnabled(self.current_page > 0)
            if hasattr(self, 'btn_next_page'):
                self.btn_next_page.setEnabled(
                    self.current_page < self.total_pages - 1)

            page = doc[self.current_page]
            self.page_rect = page.rect

            # Calculate scale to fit within dialog (accounting for UI elements)
            # Target size: dialog minus padding and buttons (~700x500 usable area)
            # Target size: dialog minus padding, zoom controls (~40px), and buttons (~50px)

            target_width = 700
            target_height = 450

            # Calculate aspect-preserving scale
            scale_w = target_width / self.page_rect.width
            scale_h = target_height / self.page_rect.height
            scale = min(scale_w, scale_h)

            # Render at 2x resolution for better quality (high-DPI rendering)
            # This creates a sharper image that we'll scale down smoothly
            render_scale = scale * 2.0
            mat = fitz.Matrix(render_scale, render_scale)
            pix = page.get_pixmap(matrix=mat, alpha=False)

            # Convert to QImage with Qt5/Qt6 compatibility
            try:
                # Qt5
                img_format = QImage.Format_RGB888 if pix.n == 3 else QImage.Format_RGBA8888
            except AttributeError:
                # Qt6
                img_format = QImage.Format.Format_RGB888 if pix.n == 3 else QImage.Format.Format_RGBA8888

            qimg = QImage(pix.samples, pix.width,
                          pix.height, pix.stride, img_format)

            # Create high-res pixmap and scale down smoothly for display
            high_res_pixmap = QPixmap.fromImage(qimg)

            # Scale down to target size with smooth transformation
            display_width = int(self.page_rect.width * scale)
            display_height = int(self.page_rect.height * scale)

            try:
                # Qt5
                self.original_pixmap = high_res_pixmap.scaled(
                    display_width, display_height,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
            except AttributeError:
                # Qt6
                self.original_pixmap = high_res_pixmap.scaled(
                    display_width, display_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )

            self.base_pixmap = self.original_pixmap.copy()

            # Calculate scale factor (display pixels per PDF point)
            # This is the scale we calculated, not from the high-res render
            self.base_scale_factor = scale

            # Store page and doc reference for re-rendering at different zooms
            self.fitz_page = page
            self.fitz_doc = doc
            self.base_scale = scale

            # Initialize the display properly (without any selection overlay)
            self.image_label.setPixmap(self.base_pixmap)
            self.image_label.resize(self.base_pixmap.size())

        except Exception as e:
            QMessageBox.warning(
                self, "Error", f"Failed to load PDF preview: {e}")
            self.reject()

    def closeEvent(self, event):
        """Clean up fitz document when dialog closes."""
        if hasattr(self, 'fitz_doc') and self.fitz_doc:
            try:
                self.fitz_doc.close()
            except:
                pass
        super().closeEvent(event)

    def showEvent(self, event):
        """Initialize display when dialog is shown, preserving existing crop selection."""
        super().showEvent(event)
        # Don't clear crop_rect - preserve it if it exists
        # Clear interactive selection state
        self.start_point = None
        self.current_point = None
        self.selecting = False
        # Reset zoom to default
        self.zoom_level = 1.0

        # If there's an existing crop_rect, convert it to screen coordinates and display
        if self.crop_rect and self.base_pixmap:
            # Convert PDF coordinates to screen coordinates
            x1 = self.crop_rect.x0 * self.base_scale_factor
            y1 = self.crop_rect.y0 * self.base_scale_factor
            x2 = self.crop_rect.x1 * self.base_scale_factor
            y2 = self.crop_rect.y1 * self.base_scale_factor

            # Set the points for display
            self.start_point = QPoint(int(x1), int(y1))
            self.current_point = QPoint(int(x2), int(y2))

            self._update_display()
        elif self.base_pixmap:
            # No existing crop, just refresh display
            self._update_display()

    def _widget_to_pixmap_coords(self, widget_pos):
        """Convert widget coordinates to pixmap coordinates."""
        if not self.base_pixmap:
            return None

        # Since we're using setWidgetResizable(False), the widget size equals pixmap size
        # Just clamp to bounds
        pixmap_x = max(0, min(widget_pos.x(), self.base_pixmap.width()))
        pixmap_y = max(0, min(widget_pos.y(), self.base_pixmap.height()))

        return QPoint(int(pixmap_x), int(pixmap_y))

    def _on_mouse_press(self, event):
        """Start selection."""
        try:
            # Qt6
            pos = event.position().toPoint()
        except AttributeError:
            # Qt5
            pos = event.pos()

        # Convert to pixmap coordinates
        pixmap_pos = self._widget_to_pixmap_coords(pos)
        if pixmap_pos is None:
            return

        self.selecting = True
        self.start_point = pixmap_pos
        self.current_point = pixmap_pos

    def _on_mouse_move(self, event):
        """Update selection."""
        if not self.selecting:
            return

        try:
            # Qt6
            pos = event.position().toPoint()
        except AttributeError:
            # Qt5
            pos = event.pos()

        # Convert to pixmap coordinates
        pixmap_pos = self._widget_to_pixmap_coords(pos)
        if pixmap_pos is None:
            return

        self.current_point = pixmap_pos
        self._update_display()

    def _on_mouse_release(self, event):
        """Finish selection."""
        if not self.selecting:
            return

        try:
            # Qt6
            pos = event.position().toPoint()
        except AttributeError:
            # Qt5
            pos = event.pos()

        # Convert to pixmap coordinates
        pixmap_pos = self._widget_to_pixmap_coords(pos)
        if pixmap_pos is None:
            return

        self.current_point = pixmap_pos
        self.selecting = False
        self._finalize_selection()
        self._update_display()

    def _finalize_selection(self):
        """Convert screen coordinates to PDF coordinates."""
        if self.start_point is None or self.current_point is None:
            return

        # Get screen rectangle
        x1 = min(self.start_point.x(), self.current_point.x())
        y1 = min(self.start_point.y(), self.current_point.y())
        x2 = max(self.start_point.x(), self.current_point.x())
        y2 = max(self.start_point.y(), self.current_point.y())

        # Convert to PDF coordinates (account for zoom)
        # The display scale is base_scale_factor * zoom_level
        display_scale = self.base_scale_factor * self.zoom_level
        pdf_x1 = x1 / display_scale
        pdf_y1 = y1 / display_scale
        pdf_x2 = x2 / display_scale
        pdf_y2 = y2 / display_scale

        # Create fitz.Rect
        if fitz:
            self.crop_rect = fitz.Rect(pdf_x1, pdf_y1, pdf_x2, pdf_y2)

    def _prev_page(self):
        """Navigate to previous page."""
        if self.current_page > 0:
            self._load_pdf_preview(self.current_page - 1)
            # Clear selection when changing pages
            self._clear_selection()

    def _next_page(self):
        """Navigate to next page."""
        if self.current_page < self.total_pages - 1:
            self._load_pdf_preview(self.current_page + 1)
            # Clear selection when changing pages
            self._clear_selection()

    def _zoom_in(self):
        """Zoom in by 25%."""
        self.zoom_level = min(self.zoom_level * 1.25, 5.0)  # Max 500%
        self._apply_zoom()

    def _zoom_out(self):
        """Zoom out by 25%."""
        self.zoom_level = max(self.zoom_level / 1.25, 0.25)  # Min 25%
        self._apply_zoom()

    def _zoom_fit(self):
        """Reset zoom to fit window."""
        self.zoom_level = 1.0
        self._apply_zoom()

    def _apply_zoom(self):
        """Apply current zoom level to the displayed image."""
        if not self.original_pixmap:
            return

        # Scale the original pixmap
        new_width = int(self.original_pixmap.width() * self.zoom_level)
        new_height = int(self.original_pixmap.height() * self.zoom_level)

        try:
            # Qt5
            self.base_pixmap = self.original_pixmap.scaled(
                new_width, new_height,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
        except AttributeError:
            # Qt6
            self.base_pixmap = self.original_pixmap.scaled(
                new_width, new_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

        # Update zoom label
        self.lbl_zoom.setText(f"{int(self.zoom_level * 100)}%")

        # Clear selection when zooming
        self.start_point = None
        self.current_point = None
        self.selecting = False

        # Update display
        self.image_label.setPixmap(self.base_pixmap)
        self.image_label.resize(self.base_pixmap.size())

    def _clear_selection(self):
        """Clear the current selection."""
        self.start_point = None
        self.current_point = None
        self.crop_rect = None
        self.selecting = False
        self._update_display()

    def _update_display(self):
        """Redraw the image with selection overlay."""
        if self.base_pixmap is None:
            return

        # Create a copy of the base pixmap
        display_pixmap = QPixmap(self.base_pixmap)

        # Draw selection rectangle if active
        if self.start_point and self.current_point:
            painter = QPainter(display_pixmap)

            # Draw semi-transparent overlay
            painter.setPen(QPen(QColor(0, 120, 212), 2))
            painter.setBrush(QColor(0, 120, 212, 30))

            x1 = min(self.start_point.x(), self.current_point.x())
            y1 = min(self.start_point.y(), self.current_point.y())
            width = abs(self.current_point.x() - self.start_point.x())
            height = abs(self.current_point.y() - self.start_point.y())

            painter.drawRect(x1, y1, width, height)
            painter.end()

        self.image_label.setPixmap(display_pixmap)

    def get_crop_rect(self):
        """Return the selected crop rectangle in PDF coordinates (fitz.Rect)."""
        return self.crop_rect


# =========================================================
# BACKGROUND TASK
# =========================================================
class PdfToVectorTask(QgsTask):
    def __init__(self, pdf_paths, out_dir, out_fmt, crs, canvas_extent,
                 page_from, page_to, include_geom, include_text,
                 load_outputs, crop_rect=None, dialog_ref=None,
                 min_size=0.0, skip_curves=False):

        super().__init__("PDF → Vector Conversion", QgsTask.CanCancel)
        self.pdf_paths = pdf_paths if isinstance(
            pdf_paths, list) else [pdf_paths]
        self.out_dir = out_dir
        self.out_fmt = out_fmt
        self.crs = crs
        self.canvas_extent = canvas_extent
        self.page_from = page_from
        self.page_to = page_to
        self.include_geom = include_geom
        self.include_text = include_text
        self.load_outputs = load_outputs
        self.crop_rect = crop_rect  # fitz.Rect or None
        self.dialog_ref = dialog_ref
        self.min_size = min_size
        self.skip_curves = skip_curves

        self.generated = []
        self.error = None

    def run(self):
        """Runs in background thread processing multiple files."""
        try:
            total_progress_steps = 0
            files_to_process = []

            # 1. Pre-calculate total work for progress bar
            for pdf_path in self.pdf_paths:
                if self.isCanceled():
                    return False
                try:
                    doc = fitz.open(pdf_path)
                    page_count = len(doc)
                    files_to_process.append((pdf_path, doc, page_count))

                    start = max(1, self.page_from)
                    end = min(page_count, self.page_to)
                    cnt = max(0, end - start + 1)
                    total_progress_steps += cnt
                except:
                    continue

            if total_progress_steps == 0:
                total_progress_steps = 1

            processed_steps = 0
            os.makedirs(self.out_dir, exist_ok=True)

            # 2. Process each file
            for pdf_path, doc, total_pages in files_to_process:
                base = os.path.splitext(os.path.basename(pdf_path))[0]

                start = max(1, self.page_from)
                end = min(total_pages, self.page_to)

                for i in range(start - 1, end):
                    if self.isCanceled():
                        doc.close()
                        return False

                    page_num = i + 1
                    page = doc[i]

                    # Determine extensions and driver
                    if self.out_fmt == "shp":
                        geom_ext, text_ext = ".shp", ".shp"
                        driver = "ESRI Shapefile"
                    elif self.out_fmt == "geojson":
                        geom_ext, text_ext = ".geojson", ".geojson"
                        driver = "GeoJSON"
                    else:
                        geom_ext, text_ext = ".geojson", ".geojson"
                        driver = "GeoJSON"

                    # Output paths
                    geom_path = os.path.join(
                        self.out_dir, f"{base}_p{page_num}_geom{geom_ext}")
                    text_path = os.path.join(
                        self.out_dir, f"{base}_p{page_num}_text{text_ext}")

                    # DXF Export
                    if self.out_fmt == "dxf":
                        dxf_out = os.path.join(
                            self.out_dir, f"{base}_p{page_num}.dxf")
                        ok, msg = convert_pdf_page_to_dxf_direct(
                            page, dxf_out, self.crop_rect,
                            min_size=self.min_size, skip_curves=self.skip_curves)
                        if ok:
                            self.generated.append(
                                (dxf_out, f"{base} Page {page_num}", "dxf"))
                        else:
                            QgsApplication.logMessage(
                                f"ezdxf fail for {base} p{page}: {msg}", "PDF2Vector", Qgis.Warning)
                            if self.include_geom:
                                self._write_geometry(page, geom_path, driver)
                                self.generated.append(
                                    (geom_path, f"{base} Page {page_num} Geometry", "geom"))

                            if self.include_text:
                                self._write_text(page, text_path, driver)
                                self.generated.append(
                                    (text_path, f"{base} Page {page_num} Text", "text"))
                    # SHP/GeoJSON Export
                    else:
                        if self.include_geom:
                            self._write_geometry(page, geom_path, driver)
                            self.generated.append(
                                (geom_path, f"{base} Page {page_num} Geometry", "geom"))
                        if self.include_text:
                            self._write_text(page, text_path, driver)
                            self.generated.append(
                                (text_path, f"{base} Page {page_num} Text", "text"))

                    # Update progress
                    processed_steps += 1
                    percent = int(
                        (processed_steps / total_progress_steps) * 100)
                    self.setProgress(percent)

                doc.close()

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
            # Check if drawing intersects with crop region (not full containment)
            if self.crop_rect:
                d_rect = d.get("rect")
                if d_rect:
                    # Check if drawing intersects the crop region
                    if not (d_rect.x0 <= self.crop_rect.x1 and d_rect.x1 >= self.crop_rect.x0 and
                            d_rect.y0 <= self.crop_rect.y1 and d_rect.y1 >= self.crop_rect.y0):
                        continue  # Skip drawings that don't intersect crop region

            for item in d.get("items", []):
                try:
                    cmd = item[0]
                    if isinstance(cmd, bytes):
                        cmd = cmd.decode("utf-8", "ignore")

                    # Check size for filtering logic
                    pass_size_check = True
                    if self.min_size > 0:
                        bbox_w = 0.0
                        bbox_h = 0.0
                        if str(cmd).lower() == "l":
                            p1, p2 = item[1], item[2]
                            bbox_w = abs(p1[0] - p2[0])
                            bbox_h = abs(p1[1] - p2[1])
                        elif str(cmd).lower() == "c":
                            xs = [pt[0] for pt in item[1:] if pt]
                            ys = [pt[1] for pt in item[1:] if pt]
                            if xs and ys:
                                bbox_w = max(xs) - min(xs)
                                bbox_h = max(ys) - min(ys)
                        elif str(cmd).lower() in ("re", "rect"):
                            rect = item[1]
                            bbox_w = rect.width
                            bbox_h = rect.height

                        if max(bbox_w, bbox_h) < self.min_size:
                            pass_size_check = False

                    if not pass_size_check:
                        continue

                    feat = QgsFeature(fields)
                    feat.setAttribute("id", fid)

                    # LINE
                    if str(cmd).lower() == "l":
                        p1 = item[1]
                        p2 = item[2]

                        # Apply clipping if crop region is set
                        if self.crop_rect:
                            clipped = clip_line_to_rect(
                                p1[0], p1[1], p2[0], p2[1], self.crop_rect)
                            if clipped is None:
                                continue  # Line is completely outside crop region

                            x1, y1, x2, y2 = clipped
                            x1, y1 = x1 + ox, page_h - y1 + oy
                            x2, y2 = x2 + ox, page_h - y2 + oy
                        else:
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
                        if self.skip_curves:
                            continue

                        # For curves, check if all points are within crop region
                        all_inside = True
                        if self.crop_rect:
                            for cpt in item[1:]:
                                if not (self.crop_rect.x0 <= cpt[0] <= self.crop_rect.x1 and
                                        self.crop_rect.y0 <= cpt[1] <= self.crop_rect.y1):
                                    all_inside = False
                                    break

                        if not all_inside and self.crop_rect:
                            continue  # Skip curves that extend outside crop region

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

                        if self.crop_rect:
                            # For rectangles, check if fully contained within crop
                            if not (rect.x0 >= self.crop_rect.x0 and rect.x1 <= self.crop_rect.x1 and
                                    rect.y0 >= self.crop_rect.y0 and rect.y1 <= self.crop_rect.y1):
                                continue  # Skip rectangles not fully within crop

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
            if self.crop_rect:
                # Use clip parameter to extract only text in crop region
                info = page.get_text("dict", clip=self.crop_rect)
            else:
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
                        feat.setGeometry(
                            QgsGeometry.fromPointXY(QgsPointXY(x, y)))
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

        # Create a group if multiple files or multiple output layers
        group = None
        if len(self.generated) > 1 and self.load_outputs:
            if len(self.pdf_paths) == 1:
                base_name = os.path.splitext(
                    os.path.basename(self.pdf_paths[0]))[0]
                group_name = f"PDF_{base_name}"
            else:
                group_name = "PDF_Batch_Import"

            root = prj.layerTreeRoot()
            group = root.insertGroup(0, group_name)

        for path, name, typ in self.generated:
            if not os.path.exists(path):
                continue
            if not self.load_outputs:
                continue

            lyr = QgsVectorLayer(path, name, "ogr")
            if lyr.isValid():
                # Add without showing in legend yet
                prj.addMapLayer(lyr, False)

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
    def __init__(self, iface):
        super().__init__(iface.mainWindow())
        # Force it as a top-level window that stays on top of QGIS
        self.setWindowTitle("PDF → Vector Converter")
        self.setMinimumWidth(450)
        self.task = None
        self.task_timer = QTimer()
        self.task_timer.setInterval(300)
        self.task_timer.timeout.connect(self._update_progress_safe)
        self.crop_rect = None  # Stores the crop region (fitz.Rect or None)

        self._build_ui()

    def showEvent(self, event):
        """Reset dialog state when shown to ensure clean start."""
        super().showEvent(event)
        # Reset crop settings
        self.crop_rect = None
        if hasattr(self, 'lbl_crop_status'):
            self.lbl_crop_status.setText("Crop: Full Page")
        # Reset progress
        if hasattr(self, 'progress'):
            self.progress.setValue(0)
        if hasattr(self, 'lbl_prog'):
            self.lbl_prog.setText("Ready")

    def closeEvent(self, event):
        """Clean up when dialog is closed."""
        # Stop any running tasks
        if self.task:
            try:
                self.task.cancel()
            except:
                pass
            self.task = None

        # Stop the progress timer
        if self.task_timer:
            self.task_timer.stop()

        # Accept the close event
        super().closeEvent(event)

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
            background-color: #0078d4;
            color: white;

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
        self.pdf_edit.setPlaceholderText("Select PDF file(s)...")
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
        self.format_combo.addItems(
            ["Shapefile (.shp)", "GeoJSON (.geojson)", "DXF (.dxf)"])
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

        # Crop region controls
        crop_row = QHBoxLayout()
        btn_crop = QPushButton("Set Crop Region...")
        btn_crop.clicked.connect(self._set_crop_region)
        btn_clear_crop = QPushButton("Clear Crop")
        btn_clear_crop.clicked.connect(self._clear_crop_region)
        btn_clear_crop.setMaximumWidth(100)
        self.lbl_crop_status = QLabel("Crop: Full Page")
        self.lbl_crop_status.setStyleSheet("color: #666666; font-size: 11px;")
        crop_row.addWidget(btn_crop)
        crop_row.addWidget(btn_clear_crop)
        crop_row.addWidget(self.lbl_crop_status)
        crop_row.addStretch()
        grp_options_layout.addLayout(crop_row)

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

        self.spin_from = QSpinBox()
        self.spin_from.setMinimum(1)
        self.spin_from.setMinimumWidth(80)
        self.spin_to = QSpinBox()
        self.spin_to.setMinimum(1)
        self.spin_to.setMinimumWidth(80)
        self.spin_from.setEnabled(False)
        self.spin_to.setEnabled(False)

        frm.addRow(self.chk_range_all)
        hr = QHBoxLayout()
        hr.setSpacing(10)
        hr.addWidget(QLabel("From:"))
        hr.addWidget(self.spin_from)
        hr.addWidget(QLabel("To:"))
        hr.addWidget(self.spin_to)
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

        # Filters
        grp_filters = QGroupBox("Filter Geometries")
        grp_filters_layout = QVBoxLayout()
        grp_filters_layout.setSpacing(6)

        self.chk_skip_curves = QCheckBox(
            "Skip Curved Geometries (Bezier/Splines)")
        grp_filters_layout.addWidget(self.chk_skip_curves)

        row_size = QHBoxLayout()
        row_size.addWidget(QLabel("Minimum Size (points):"))
        self.spin_min_size = QDoubleSpinBox()
        self.spin_min_size.setMinimum(0.0)
        self.spin_min_size.setMaximum(99999.0)
        self.spin_min_size.setDecimals(1)
        self.spin_min_size.setSingleStep(1.0)
        self.spin_min_size.setValue(0.0)
        self.spin_min_size.setToolTip(
            "Skip geometries where max side is smaller than this value")
        row_size.addWidget(self.spin_min_size)
        row_size.addStretch()

        grp_filters_layout.addLayout(row_size)
        grp_filters.setLayout(grp_filters_layout)
        layout_adv.addWidget(grp_filters)

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
        # Use instance-based dialog to ensure multiple selection works reliably across bindings
        dlg = QFileDialog(self, "Select PDF(s)")
        try:
            # Qt5
            mode = QFileDialog.ExistingFiles
        except AttributeError:
            # Qt6
            mode = QFileDialog.FileMode.ExistingFiles
        dlg.setFileMode(mode)
        dlg.setNameFilter("PDF (*.pdf)")

        exec_func = dlg.exec if hasattr(dlg, 'exec') else dlg.exec_

        # Qt5/Qt6 compatible Accepted constant
        try:
            accepted = QDialog.Accepted
        except AttributeError:
            accepted = QDialog.DialogCode.Accepted

        if exec_func() == accepted:
            files = dlg.selectedFiles()

            if files:
                # Store old PDF to detect changes
                old_pdf = self.pdf_edit.text().strip()

                # Join with semicolon for display
                joined_paths = "; ".join(files)
                self.pdf_edit.setText(joined_paths)

                # Reset crop if PDF changed
                if old_pdf != joined_paths:
                    self.crop_rect = None
                    if hasattr(self, 'lbl_crop_status'):
                        self.lbl_crop_status.setText("Crop: Full Page")

                # Use the first file to set page counts
                try:
                    if len(files) > 0:
                        doc = fitz.open(files[0])
                        n = len(doc)
                        self.spin_from.setMaximum(n)
                        self.spin_to.setMaximum(n)
                        self.spin_to.setValue(n)
                        doc.close()
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

    def _set_crop_region(self):
        """Open crop region selection dialog."""
        pdf_input = self.pdf_edit.text().strip()
        if not pdf_input:
            QMessageBox.warning(
                self, "Error", "Please select a PDF file first")
            return

        # Get the first PDF file
        pdf_files = [f.strip() for f in pdf_input.split(";") if f.strip()]
        if not pdf_files:
            QMessageBox.warning(self, "Error", "No PDF files selected")
            return

        first_pdf = pdf_files[0]
        if not os.path.exists(first_pdf):
            QMessageBox.warning(
                self, "Error", f"PDF file not found: {first_pdf}")
            return

        # Open crop preview dialog
        dlg = CropPreviewDialog(first_pdf, self.crop_rect, self)

        # Qt5/Qt6 compatible exec
        exec_func = dlg.exec if hasattr(dlg, 'exec') else dlg.exec_

        # Qt5/Qt6 compatible Accepted constant
        try:
            accepted = QDialog.Accepted
        except AttributeError:
            accepted = QDialog.DialogCode.Accepted

        if exec_func() == accepted:
            self.crop_rect = dlg.get_crop_rect()
            if self.crop_rect:
                # Update status label
                self.lbl_crop_status.setText(
                    f"Crop: ({self.crop_rect.x0:.1f}, {self.crop_rect.y0:.1f}) - "
                    f"({self.crop_rect.x1:.1f}, {self.crop_rect.y1:.1f})"
                )
            else:
                self.crop_rect = None
                self.lbl_crop_status.setText("Crop: Full Page")

    def _clear_crop_region(self):
        """Clear the crop region selection."""
        self.crop_rect = None
        self.lbl_crop_status.setText("Crop: Full Page")

    # ----------------------------------------------------
    # START TASK
    # ----------------------------------------------------
    def start(self):
        pdf_input = self.pdf_edit.text().strip()
        out = self.out_edit.text().strip()

        # Split by semicolon to get all files
        pdf_files = [f.strip() for f in pdf_input.split(";") if f.strip()]

        if not pdf_files:
            QMessageBox.warning(self, "Error", "No PDF files selected")
            return

        for pdf in pdf_files:
            if not os.path.exists(pdf):
                QMessageBox.warning(self, "Error", f"Invalid PDF path: {pdf}")
                return

        if not out:
            QMessageBox.warning(self, "Error", "Select output folder")
            return

        # Check first file for page count
        try:
            doc = fitz.open(pdf_files[0])
            first_pages = len(doc)
            doc.close()
        except Exception as e:
            QMessageBox.warning(self, "Error opening PDF", str(e))
            return

        if self.chk_range_all.isChecked():
            p_from, p_to = 1, 9999999
        else:
            p_from = self.spin_from.value()
            p_to = self.spin_to.value()

            # Use stricter check only if single file
            if len(pdf_files) == 1:
                if p_to > first_pages:
                    QMessageBox.warning(
                        self, "Error", "Page range exceeds PDF page count")
                    return

            if p_from < 1 or p_to < p_from:
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
            pdf_files, out, out_fmt, crs, cext,
            page_from=p_from, page_to=p_to,
            include_geom=self.chk_geom.isChecked(),
            include_text=self.chk_text.isChecked(),
            load_outputs=self.chk_load.isChecked(),
            crop_rect=self.crop_rect,
            dialog_ref=self,
            min_size=self.spin_min_size.value(),
            skip_curves=self.chk_skip_curves.isChecked()
        )
        QgsApplication.taskManager().addTask(self.task)

        self.progress.setValue(0)
        self.lbl_prog.setText("0%")
        self.task_timer.start()

    def _cancel(self):
        """Cancel the running task."""
        if self.task:
            self.task.cancel()
        self.lbl_prog.setText("Cancelling...")

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
