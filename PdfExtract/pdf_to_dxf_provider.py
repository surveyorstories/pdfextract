# -*- coding: utf-8 -*-

from qgis.core import QgsProcessingProvider
from .pdf_to_dxf_algorithm import PdfToDxfAlgorithm
from qgis.PyQt.QtGui import QIcon
import inspect
import os
class PdfToDxfProvider(QgsProcessingProvider):

    def loadAlgorithms(self):
        self.addAlgorithm(PdfToDxfAlgorithm())

    def id(self):
        return 'pdftodxf'

    def name(self):
        return 'Pdf Extract'

    def icon(self):
        """
        Should return a QIcon which is used for your provider inside
        the Processing toolbox.
        """

        cmd_folder = os.path.split(inspect.getfile(inspect.currentframe()))[0]
        icon = QIcon(os.path.join(os.path.join(cmd_folder, 'images/icon.png')))
        return icon

    def longName(self):
        return self.name()
