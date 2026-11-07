#!/bin/sh
set -e
ruff check .
python3 -m pytest -q
