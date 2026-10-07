import os

# Lets Qt run without a display (CI, containers, SSH sessions). Set before pytest-qt
# creates the QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
