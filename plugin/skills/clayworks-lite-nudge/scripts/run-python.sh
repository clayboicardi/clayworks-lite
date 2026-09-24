#!/usr/bin/env bash
# =============================================================================
# run-python.sh: portable Python launcher for Clayworks LITE hooks
# =============================================================================
# Usage: bash run-python.sh <script.py> [args...]
#
# I know Claude Code runs hook commands under bash on macOS/Linux and under Git
# Bash on Windows, and I see the Python executable name differ by platform:
# `python3` on macOS and most Linux distros, often only `python` or the `py`
# launcher on Windows. With a bare `python3 script.py` hook, I'd fail on those
# Windows machines and show a hook error on every prompt.
#
# I try, in order: python3, python, py -3. I need each candidate to actually run
# Python 3.10+ (I've seen the Windows Store "python3" alias sit on PATH and only
# print an install hint), so I probe it before handing off.
#
# If no usable Python exists, I exit 0 with no output. I made Nudge optional,
# and I won't let a missing interpreter turn every prompt into a hook error.
# I report the missing Python from `install.sh --verify` / `install.ps1 -Verify`.
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
