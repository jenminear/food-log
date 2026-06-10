#!/usr/bin/env python3
"""
setup.py — Food Log one-time setup script
==========================================
Run this once after cloning / downloading the project:

    python setup.py

What it does:
  1. Creates a Python virtual environment (.venv)
  2. Installs all dependencies from requirements.txt
  3. Initialises the SQLite database
  4. Creates a .env template (if one doesn't already exist)
  5. Prints next steps
"""

import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent


def run(cmd: list[str], **kwargs) -> None:
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        print(f"\n[error] Command failed: {' '.join(cmd)}")
        sys.exit(1)


def main() -> None:
    print("\n🍽  Food Log — Setup\n" + "─" * 40)

    # 1. Virtual environment
    venv = BASE / ".venv"
    if not venv.exists():
        print("\n[1/4] Creating virtual environment...")
        run([sys.executable, "-m", "venv", str(venv)])
    else:
        print("\n[1/4] Virtual environment already exists — skipping.")

    pip = str(venv / ("Scripts/pip" if sys.platform == "win32" else "bin/pip"))

    # 2. Install dependencies
    print("\n[2/4] Installing dependencies...")
    run([pip, "install", "-r", str(BASE / "requirements.txt"), "-q"])

    # 3. Initialise database
    print("\n[3/4] Initialising database...")
    python = str(venv / ("Scripts/python" if sys.platform == "win32" else "bin/python"))
    run([python, str(BASE / "init_db.py")])

    # 4. .env template
    env_file = BASE / ".env"
    if not env_file.exists():
        print("\n[4/4] Creating .env template...")
        env_file.write_text(
            "# Food Log configuration\n"
            "\n"
            "# USDA FoodData Central API key\n"
            "# Get a free key at: https://fdc.nal.usda.gov/api-guide.html\n"
            "# Without a key, the app uses the DEMO_KEY (1000 requests/day).\n"
            "USDA_API_KEY=\n"
            "\n"
            "# Optional API key to protect your Food Log API.\n"
            "# Leave blank for local personal use.\n"
            "# When set, all requests must include: X-Api-Key: <your-key>\n"
            "FOOD_LOG_API_KEY=\n"
        )
        print("  Created .env — add your USDA_API_KEY to enable nutrition lookup.")
    else:
        print("\n[4/4] .env already exists — skipping.")

    # 5. Run tests
    print("\n[bonus] Running test suites to verify everything is working...")
    run([python, str(BASE / "test_db.py")])
    run([python, str(BASE / "test_nutrition_lookup.py")])
    run([python, str(BASE / "test_app.py")])
    run([python, str(BASE / "test_api.py")])

    # Done
    if sys.platform == "win32":
        activate = r".venv\Scripts\activate"
        start    = "uvicorn main:app --reload"
    else:
        activate = "source .venv/bin/activate"
        start    = "uvicorn main:app --reload"

    print(f"""
{'─' * 40}
✅  Setup complete!

To start the API:
    {activate}
    {start}

Then open:
    http://localhost:8000/docs   ← Interactive API docs (Swagger UI)
    http://localhost:8000/health ← Health check

To run tests:
    python test_db.py
    python test_nutrition_lookup.py
    python test_app.py
    python test_api.py
{'─' * 40}
""")


if __name__ == "__main__":
    main()
