"""Stop the portable PostgreSQL test cluster."""
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PG_DIR = os.path.join(ROOT, ".pg")
DATA_DIR = os.path.join(PG_DIR, "data")
PG_CTL = os.path.join(PG_DIR, "pgsql", "bin", "pg_ctl.exe")

if os.path.exists(DATA_DIR):
    res = subprocess.run([PG_CTL, "-D", DATA_DIR, "-m", "fast", "stop"], capture_output=True, text=True)
    print("PostgreSQL stopped:", res.stdout or res.stderr)
else:
    print("No data directory found; server not running.")
