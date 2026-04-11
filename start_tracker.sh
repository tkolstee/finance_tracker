#!/bin/bash
# Finance Tracker Launcher
# Run this script to start the Finance Tracker app, then open http://localhost:5757

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "  Starting Finance Tracker..."
echo "  Open your browser to: http://localhost:5757"
echo "  Press Ctrl+C to stop."
echo ""

python3 finance_tracker.py
