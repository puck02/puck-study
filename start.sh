#!/usr/bin/env bash
set -euo pipefail
cd /home/admin/workspace/puck-study
export PYTHONPATH=/home/admin/workspace/puck-study/backend
export STUDYFLOW_DB_PATH=/home/admin/workspace/puck-study/data/studyflow.db
exec python3 -m uvicorn studyflow.app:app --host 0.0.0.0 --port 5188
