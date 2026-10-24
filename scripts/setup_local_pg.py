"""Set up a portable, isolated PostgreSQL test cluster for TrustVault on Windows."""
import os
import secrets
import shutil
import subprocess
import sys
import time

import psycopg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PG_DIR = os.path.join(ROOT, ".pg")
BIN_DIR = os.path.join(PG_DIR, "pgsql", "bin")
DATA_DIR = os.path.join(PG_DIR, "data")
LOG_FILE = os.path.join(PG_DIR, "pg.log")
INITDB = os.path.join(BIN_DIR, "initdb.exe")
PG_CTL = os.path.join(BIN_DIR, "pg_ctl.exe")
PORT = 5433

POSTGRES_PW = secrets.token_urlsafe(16) + "Pg1!"
MIGRATOR_PW = secrets.token_urlsafe(16) + "Mig1!"
APP_USER_PW = secrets.token_urlsafe(16) + "App1!"


def clean_and_init():
    # Stop existing instance if running
    if os.path.exists(DATA_DIR):
        print("Stopping any running instance on data dir...")
        subprocess.run([PG_CTL, "-D", DATA_DIR, "-m", "immediate", "stop"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        shutil.rmtree(DATA_DIR, ignore_errors=True)

    pwfile = os.path.join(PG_DIR, "pw.tmp")
    with open(pwfile, "w") as f:
        f.write(POSTGRES_PW)

    cmd = [
        INITDB,
        "-D", DATA_DIR,
        "-U", "postgres",
        "-A", "scram-sha-256",
        f"--pwfile={pwfile}",
        "-E", "UTF8",
    ]
    print("Running initdb with SCRAM-SHA-256...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if os.path.exists(pwfile):
        os.remove(pwfile)

    if res.returncode != 0:
        print("initdb failed:", res.stderr)
        sys.exit(1)

    # Configure postgresql.conf for loopback and isolated port
    conf_path = os.path.join(DATA_DIR, "postgresql.conf")
    with open(conf_path, "a") as f:
        f.write(f"\nlisten_addresses = '127.0.0.1'\nport = {PORT}\n")

    # Configure pg_hba.conf for strict SCRAM-SHA-256 on loopback
    hba_path = os.path.join(DATA_DIR, "pg_hba.conf")
    with open(hba_path, "w") as f:
        f.write("# Local test cluster strictly on loopback\n")
        f.write("host    all    all    127.0.0.1/32    scram-sha-256\n")
        f.write("host    all    all    ::1/128         scram-sha-256\n")
    print("Cluster initialized and hardened to 127.0.0.1 only.")


def start_server():
    print(f"Starting PostgreSQL on 127.0.0.1:{PORT}...")
    subprocess.Popen([PG_CTL, "-D", DATA_DIR, "-l", LOG_FILE, "start"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    pg_url = f"postgresql://postgres:{POSTGRES_PW}@127.0.0.1:{PORT}/postgres"
    connected = False
    last_err = ""
    for attempt in range(25):
        time.sleep(0.5)
        try:
            with psycopg.connect(pg_url, connect_timeout=1) as conn:
                connected = True
                break
        except Exception as e:
            last_err = str(e)
            continue

    if not connected:
        print(f"Error: PostgreSQL did not become ready. Last error: {last_err}")
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE) as f:
                print("Log output:", f.read())
        sys.exit(1)

    print("PostgreSQL is ready and accepting connections.")


def setup_database():
    pg_url = f"postgresql://postgres:{POSTGRES_PW}@127.0.0.1:{PORT}/postgres"
    print("Configuring migrator, app_user roles and trustvault_test database...")
    with psycopg.connect(pg_url, autocommit=True) as c:
        c.execute(f"CREATE ROLE migrator WITH LOGIN SUPERUSER PASSWORD '{MIGRATOR_PW}'")
        c.execute(f"CREATE ROLE app_user WITH LOGIN PASSWORD '{APP_USER_PW}'")
        c.execute("CREATE DATABASE trustvault_test OWNER migrator")

    # Connect as migrator to trustvault_test and apply schema.sql
    mig_url = f"postgresql://migrator:{MIGRATOR_PW}@127.0.0.1:{PORT}/trustvault_test"
    print("Applying db/schema.sql as migrator...")
    schema_path = os.path.join(ROOT, "db", "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with psycopg.connect(mig_url, autocommit=True) as c:
        c.execute(schema_sql)
    print("db/schema.sql applied successfully.")

    # Save connection URLs to .test_env (gitignored)
    env_file = os.path.join(ROOT, ".test_env")
    app_url = f"postgresql://app_user:{APP_USER_PW}@127.0.0.1:{PORT}/trustvault_test"
    with open(env_file, "w") as f:
        f.write(f"TEST_DATABASE_URL={app_url}\n")
        f.write(f"TEST_MIGRATOR_URL={mig_url}\n")

    print("\n--- Local Test Database Ready ---")
    print("Database: trustvault_test")
    print(f"Port: {PORT} (loopback only: 127.0.0.1)")
    print(f"Config saved to: {env_file}")


if __name__ == "__main__":
    clean_and_init()
    start_server()
    setup_database()
