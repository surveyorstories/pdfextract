
from qgis.PyQt.QtWidgets import QMessageBox
try:
    print(f"QMessageBox.StandardButton.Yes: {QMessageBox.StandardButton.Yes}")
    print(f"QMessageBox.StandardButton.No: {QMessageBox.StandardButton.No}")
    print("Scoped Enums are available.")
except AttributeError:
    print("Scoped Enums are NOT available.")

try:
    print(f"QMessageBox.Yes: {QMessageBox.Yes}")
    print("Unscoped Enums are available.")
except AttributeError:
    print("Unscoped Enums are NOT available.")
