"""
Settings shared by every test.

Qt runs offscreen unless QT_QPA_PLATFORM already names a platform. Without
this, every GUI test opens a real window on the developer's screen - well over
a hundred of them, some maximised, each taking focus - and a test run fights
the person at the keyboard for the mouse. Set here, at import time, so it is in
place before pytest-qt creates the QApplication, and inherited by any process a
test starts. To watch a test on screen, set QT_QPA_PLATFORM=windows (or xcb)
before running pytest.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
