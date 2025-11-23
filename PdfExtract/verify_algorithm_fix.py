
import sys
import unittest
from unittest.mock import MagicMock, patch
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

class TestAlgorithm(unittest.TestCase):
    def setUp(self):
        # Mock QGIS modules
        sys.modules['qgis'] = MagicMock()
        sys.modules['qgis.PyQt'] = MagicMock()
        sys.modules['qgis.PyQt.QtCore'] = MagicMock()
        sys.modules['qgis.PyQt.QtWidgets'] = MagicMock()
        sys.modules['qgis.core'] = MagicMock()
        sys.modules['qgis.utils'] = MagicMock()
        
        # Mock fitz and ezdxf to avoid missing deps error during import if they are not installed in this env
        sys.modules['fitz'] = MagicMock()
        sys.modules['fitz'].open = MagicMock()
        sys.modules['ezdxf'] = MagicMock()

        # Define a base class for QgsProcessingAlgorithm to avoid MagicMock inheritance issues
        class MockQgsProcessingAlgorithm:
            def __init__(self):
                pass
            def tr(self, string):
                return string
            def addParameter(self, param):
                pass
            def createInstance(self):
                return self.__class__()
            def name(self):
                return 'mock_algo'
            def displayName(self):
                return 'Mock Algo'
            def group(self):
                return ''
            def groupId(self):
                return ''
            def shortHelpString(self):
                return ''
            def initAlgorithm(self, config=None):
                pass
            def prepareAlgorithm(self, parameters, context, feedback):
                return True
            def processAlgorithm(self, parameters, context, feedback):
                return {}
            def parameterAsFile(self, parameters, name, context):
                return ''
            def parameterAsString(self, parameters, name, context):
                return ''
            def parameterAsBool(self, parameters, name, context):
                return True
            def parameterAsEnum(self, parameters, name, context):
                return 0

        sys.modules['qgis.core'].QgsProcessingAlgorithm = MockQgsProcessingAlgorithm

        # Configure translate to return the input string
        def side_effect(context, string):
            return string
        sys.modules['qgis.PyQt.QtCore'].QCoreApplication.translate.side_effect = side_effect

    def test_algorithm_structure(self):
        if 'pdf_to_dxf_algorithm' in sys.modules:
            del sys.modules['pdf_to_dxf_algorithm']
        import pdf_to_dxf_algorithm
        
        algo = pdf_to_dxf_algorithm.PdfToDxfAlgorithm()
        
        # Check if initAlgorithm defines 3 options for OUTPUT_FORMAT
        config = MagicMock()
        algo.addParameter = MagicMock()
        algo.initAlgorithm(config)
        
        self.assertTrue(hasattr(algo, 'convert_pdf_page_to_dxf_direct'), "Algorithm should have convert_pdf_page_to_dxf_direct method")
        
        # Check shortHelpString mentions DXF
        help_str = algo.shortHelpString()
        self.assertIn("DXF", help_str, "Help string should mention DXF")
        
        print(f"MISSING_DEPS in algorithm: {pdf_to_dxf_algorithm.MISSING_DEPS}")

    def test_dependencies_missing(self):
        # Force missing dependencies
        sys.modules['fitz'] = None
        sys.modules['ezdxf'] = None
        
        if 'dependencies' in sys.modules:
            del sys.modules['dependencies']
            
        import dependencies
        missing = dependencies.check_missing()
        print(f"Missing deps (forced missing): {missing}")
        self.assertIn('pymupdf', missing)
        # ezdxf requirement string might vary, but it should be there
        self.assertTrue(any('ezdxf' in m for m in missing))

if __name__ == '__main__':
    unittest.main()
