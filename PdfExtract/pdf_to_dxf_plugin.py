# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication
import os

from .pdf_to_dxf_provider import PdfToDxfProvider
from .pdftodxf_dialog import PdfToVectorDialog

class PdfToDxfPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dlg = None
        self.toolbar = None

    def initGui(self):
        self.provider = PdfToDxfProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)
        
        # Create Action
        icon_path = os.path.join(self.plugin_dir, 'images', 'icon.png')
        self.action = QAction(QIcon(icon_path), "PDF Extract", self.iface.mainWindow())
        self.action.setObjectName("PdfToDxfConverterAction")
        self.action.setToolTip("Convert PDF to DXF/Shapefile/GeoJSON")
        self.action.triggered.connect(self.run)
        
        # Create dedicated Toolbar
        self.toolbar = self.iface.addToolBar("PDF Extract")
        self.toolbar.setObjectName("Pdf Extract Toolbar")
        self.toolbar.addAction(self.action)
        
        # Add to Menu
        self.iface.addPluginToMenu("Pdf Extract", self.action)
        
        # Check dependencies on startup
        from . import dependencies
        dependencies.install_deps(self.iface)

    def unload(self):
        if self.provider:
            try:
                QgsApplication.processingRegistry().removeProvider(self.provider)
            except RuntimeError:
                pass
            self.provider = None
            
        if self.action:
            self.iface.removePluginMenu("Pdf Extract", self.action)
            if self.toolbar:
                self.toolbar.removeAction(self.action)
                del self.toolbar
                self.toolbar = None
            
            try:
                self.action.deleteLater()
            except RuntimeError:
                pass
            self.action = None

    def run(self):
        if not self.dlg:
            self.dlg = PdfToVectorDialog()
        
        self.dlg.show()
        if hasattr(self.dlg, 'exec'):
            result = self.dlg.exec()
        else:
            result = self.dlg.exec_()

