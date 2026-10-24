"""Start local PostgreSQL, run pytest suite, then stop PostgreSQL cleanly."""
import os
import subprocess
import sys
import time

import psycopg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PG_DIR = os.path.join(ROOT, ".pg")
BIN_DIR = os.path.join(PG_DIR, "pgsql", "bin")
DATA_DIR = os.path.join(PG_DIR, "data")
LOG_FILE = os.path.join(PG_DIR, "pg.log")
PG_CTL = os.path.join(BIN_DIR, "pg_ctl.exe")
PORT = 5433

# Start the PostgreSQL server
print("Starting local PostgreSQL on 127.0.0.1:5433...")
subprocess.run([PG_CTL, "-D", DATA_DIR, "-l", LOG_FILE, "start"], check=True)

# Read credentials from .test_env
env_file = os.path.join(ROOT, ".test_env")
test_env = {}
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                test_env[k] = v

mig_url = test_env.get("TEST_MIGRATOR_URL", "")
app_url = test_env.get("TEST_DATABASE_URL", "")

if "sslmode" not in mig_url:
    mig_url += "?sslmode=disable"
if "sslmode" not in app_url:
    app_url += "?sslmode=disable"

# Verify connection
connected = False
for _ in range(20):
    try:
        with psycopg.connect(mig_url, connect_timeout=1) as c:
            connected = True
            break
    except Exception:
        time.sleep(0.5)

if not connected:
    print("Could not connect to PostgreSQL server.")
    subprocess.run([PG_CTL, "-D", DATA_DIR, "stop"])
    sys.exit(1)

print("Connected to PostgreSQL successfully.")
os.environ["TEST_DATABASE_URL"] = app_url
os.environ["TEST_MIGRATOR_URL"] = mig_url

# Run pytest with passed args
pytest_args = [sys.executable, "-m", "pytest"] + (sys.argv[1:] if len(sys.argv) > 1 else ["-v"])
print(f"Running pytest: {' '.join(pytest_args)}")
exit_code = 1
try:
    res = subprocess.run(pytest_args, cwd=ROOT, env=os.environ)
    exit_code = res.returncode
finally:
    print("Shutting down local PostgreSQL...")
    subprocess.run([PG_CTL, "-D", DATA_DIR, "stop"])

sys.exit(exit_code)
