#!/usr/bin/env python3
"""Stable launcher for the linked Hermes skill."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from apk_lab.cli import main
raise SystemExit(main())
