
import sys
import os

print("--- PDF Extract Dependency Debug ---")
print(f"Python Executable: {sys.executable}")
print(f"Python Version: {sys.version}")

try:
    import fitz
    print(f"fitz (PyMuPDF) imported: {fitz}")
    print(f"fitz.open exists: {hasattr(fitz, 'open')}")
    if hasattr(fitz, '__file__'):
        print(f"fitz location: {fitz.__file__}")
except ImportError as e:
    print(f"fitz import failed: {e}")

try:
    import ezdxf
    print(f"ezdxf imported: {ezdxf}")
    if hasattr(ezdxf, '__file__'):
        print(f"ezdxf location: {ezdxf.__file__}")
except ImportError as e:
    print(f"ezdxf import failed: {e}")
except Exception as e:
    print(f"ezdxf import error (other): {e}")

# Check what the plugin's dependencies module says
try:
    # Adjust path if needed to find the plugin
    # Assuming this script is run from the plugin directory or user adds it
    import dependencies
    print(f"dependencies module found: {dependencies}")
    missing = dependencies.check_missing()
    print(f"dependencies.check_missing() returned: {missing}")
except ImportError:
    print("Could not import 'dependencies' module. Make sure you are running this from the plugin directory or add it to sys.path.")
    # Try to find it relative to this script
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.append(current_dir)
    try:
        import dependencies
        print(f"dependencies module found (after path add): {dependencies}")
        missing = dependencies.check_missing()
        print(f"dependencies.check_missing() returned: {missing}")
    except ImportError as e:
        print(f"Still could not import dependencies: {e}")

print("------------------------------------")
