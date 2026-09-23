#!/usr/bin/env bash
# =============================================================================
# run-python.sh: portable Python launcher for Clayworks LITE hooks
# =============================================================================
# Usage: bash run-python.sh <script.py> [args...]
#
# Hook commands run under bash on macOS/Linux and under Git Bash on Windows,
# and the Python executable name differs by platform: `python3` on macOS and
# most Linux distros, often only `python` or the `py` launcher on Windows. A
# bare `python3 script.py` hook fails on those Windows machines and shows a
# hook error on every prompt.
#
# I try, in order: python3, python, py -3. Each candidate must actually run
# Python 3.10+ (the Windows Store "python3" alias exists on PATH but only
# prints an install hint), so I probe it before handing off.
#
# If no usable Python exists, I exit 0 with no output. Nudge is optional; a
# missing interpreter shouldn't turn every prompt into a hook error.
# `install.sh --verify` / `install.ps1 -Verify` report the missing Python.
# =============================================================================

set -u

if [[ $# -lt 1 ]]; then
    echo "usage: run-python.sh <script.py> [args...]" >&2
    exit 0
fi

PROBE='import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'

for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 \
        && "$candidate" -c "$PROBE" >/dev/null 2>&1; then
        exec "$candidate" "$@"
    fi
done

if command -v py >/dev/null 2>&1 && py -3 -c "$PROBE" >/dev/null 2>&1; then
    exec py -3 "$@"
fi

exit 0
