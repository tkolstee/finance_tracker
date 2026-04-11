import os
from finance_tracker import app, init_users, DATA_DIR
from auth import init_secret

os.makedirs(DATA_DIR, exist_ok=True)
init_secret(DATA_DIR)   # must come before any JWT operations
init_users(DATA_DIR)
