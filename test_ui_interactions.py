"""
NEXUS V3.4 — Automated UI Interaction & Navigation Test Suite Runner
"""
import subprocess
import os
import sys

def test_ui_interactions():
    res = subprocess.run(['node', 'test_ui_interactions.js'], capture_output=True, text=True)
    print(res.stdout)
    if res.stderr:
        print(res.stderr, file=sys.stderr)
    assert res.returncode == 0, f"UI tests failed with exit code {res.returncode}"
    assert "ALL 10 UI INTERACTION & NAVIGATION TEST SUITES PASSED (100%)" in res.stdout

if __name__ == '__main__':
    test_ui_interactions()
    print("test_ui_interactions.py: SUCCESS")
