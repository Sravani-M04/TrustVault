"""Scan tracked project files for accidentally hardcoded secrets."""
import os
import re

PATTERNS = {
    "AWS Access Key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "AWS Secret Key": re.compile(r"(?i)aws_secret_access_key\s*=\s*['\"][^\'\"]+['\"]"),
    "PostgreSQL Connection URI with Password": re.compile(r"postgresql://[^:]+:[^@]+@"),
    "Hardcoded API Key / Secret Token": re.compile(r"(?i)(secret_key|api_key)\s*=\s*['\"][a-zA-Z0-9_\-\.]{24,}['\"]"),
}

IGNORE_DIRS = {".git", ".pg", "venv", "__pycache__", ".pytest_cache"}
IGNORE_FILES = {".test_env"}

findings = []
for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
    for file in files:
        if file in IGNORE_FILES or file.endswith((".pyc", ".zip", ".exe")):
            continue
        filepath = os.path.normpath(os.path.join(root, file))
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                for secret_type, regex in PATTERNS.items():
                    if regex.search(content):
                        # Note: we report ONLY the filepath and secret type, NEVER the value
                        findings.append((filepath, secret_type))
        except Exception:
            pass

if not findings:
    print("SECRET SCAN CLEAN: No hardcoded secrets detected in source files.")
else:
    print("FINDINGS:")
    for path, stype in sorted(set(findings)):
        print(f"  - {path}: {stype}")
