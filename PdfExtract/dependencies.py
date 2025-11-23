# -*- coding: utf-8 -*-
import sys
import subprocess
import os
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import Qgis, QgsMessageLog

# Qt Enum Compatibility
if hasattr(QMessageBox, "Yes"):
    QMessageBox_Yes = QMessageBox.Yes
    QMessageBox_No = QMessageBox.No
else:
    QMessageBox_Yes = QMessageBox.StandardButton.Yes
    QMessageBox_No = QMessageBox.StandardButton.No

def get_ezdxf_requirement():
    """
    Determines the appropriate ezdxf version based on the numpy version.
    QGIS 3.26 bundles older numpy which conflicts with newer ezdxf.
    Newer QGIS versions can use newer ezdxf.
    """
    try:
        import numpy
        from packaging import version
        
        # ezdxf 1.1+ requires numpy >= 1.21 for typing
        if version.parse(numpy.__version__) < version.parse("1.21.0"):
            return "ezdxf<1.1"
        else:
            return "ezdxf" # Install latest compatible
    except ImportError:
        # If numpy is missing (unlikely in QGIS), fallback to safe version
        return "ezdxf<1.1"
    except Exception:
        return "ezdxf<1.1"

def check_missing():
    missing = []
    try:
        import fitz
        # Verify it's the correct fitz (PyMuPDF) and not another package named fitz
        if not hasattr(fitz, 'open'):
             missing.append('pymupdf')
    except ImportError:
        missing.append('pymupdf')
    
    try:
        import ezdxf
    except ImportError:
        missing.append(get_ezdxf_requirement())
    except AttributeError:
        # Catch the numpy.typing error if it happens during import
        missing.append(get_ezdxf_requirement())
    except Exception:
        missing.append(get_ezdxf_requirement())
    
    return missing

def install_deps(iface):
    missing = check_missing()
    if not missing:
        return True

    # Ask user for permission
    reply = QMessageBox.question(
        iface.mainWindow(),
        'Missing Dependencies',
        f"The PDF to DXF plugin requires the following libraries:\n{', '.join(missing)}\n\n"
        "Do you want to install them automatically?",
        QMessageBox_Yes | QMessageBox_No,
        QMessageBox_Yes
    )

    if reply == QMessageBox_No:
        return False

    # Locate python executable
    python_exe = None
    if sys.platform == 'win32':
        candidates = [
            os.path.join(sys.exec_prefix, 'python.exe'),
            os.path.join(sys.exec_prefix, 'bin', 'python.exe'),
            os.path.join(os.path.dirname(sys.executable), 'python-qgis-ltr.exe'),
            sys.executable
        ]
        
        for c in candidates:
            if os.path.exists(c) and 'python' in os.path.basename(c).lower():
                python_exe = c
                break
    
    if not python_exe:
        if 'python' in os.path.basename(sys.executable).lower():
            python_exe = sys.executable
        else:
            python_exe = os.path.join(sys.exec_prefix, 'python.exe')

    QgsMessageLog.logMessage(f"PDF2DXF: Using python: {python_exe}", "PDF2DXF", Qgis.Info)

    try:
        # Run pip install
        cmd = [python_exe, '-m', 'pip', 'install'] + missing
        
        iface.messageBar().pushMessage("PDF2DXF", "Installing dependencies... Please wait.", level=Qgis.Info)
        QgsMessageLog.logMessage(f"PDF2DXF: Running {cmd}", "PDF2DXF", Qgis.Info)
        
        subprocess.check_call(cmd)
        
        QMessageBox.information(
            iface.mainWindow(),
            "Success",
            "Dependencies installed successfully.\nPlease restart QGIS to apply changes."
        )
        return True
        
    except subprocess.CalledProcessError as e:
        QMessageBox.critical(
            iface.mainWindow(),
            "Installation Failed",
            f"Failed to install dependencies.\nError code: {e.returncode}\n\n"
            "Please try installing manually using OSGeo4W Shell."
        )
        return False
    except Exception as e:
        QMessageBox.critical(
            iface.mainWindow(),
            "Error",
            f"An unexpected error occurred:\n{str(e)}"
        )
        return False
