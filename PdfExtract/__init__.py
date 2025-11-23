# -*- coding: utf-8 -*-

def classFactory(iface):
    from .pdf_to_dxf_plugin import PdfToDxfPlugin
    return PdfToDxfPlugin(iface)
