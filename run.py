#!/usr/bin/env python3
"""Launch Slate PDF Editor from a source checkout:  python run.py [file.pdf ...]"""

# Verify required runtime tools BEFORE importing the heavy app modules. If something
# essential is missing, the user gets a clear error (with download links) and we exit.
from slate.preflight import run_or_exit
run_or_exit()

from slate.app import main

if __name__ == "__main__":
    main()
