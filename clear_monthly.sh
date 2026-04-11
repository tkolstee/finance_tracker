#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${FINANCE_TRACKER_DATA_DIR:-$SCRIPT_DIR}"
DB_PATH="${FINANCE_TRACKER_DB_PATH:-$DATA_DIR/tracker.db}"

sqlite3 "$DB_PATH" "DELETE FROM transactions;"
