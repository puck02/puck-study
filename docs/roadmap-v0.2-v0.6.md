# StudyFlow Stable Roadmap v0.2-v0.6

> **Goal:** 将 StudyFlow 从 v0.1 最小闭环，稳定演进为「QQ 无感记录 + 自适应计划 + 错题模式合并 + GitHub-style 热力图 + 周报趋势分析」的长期学习驾驶舱。

## Current baseline: v0.1

已完成：

- FastAPI + SQLite 后端
- 静态 Dashboard 前端
- `POST /api/ingest/qq` 自然文本写入
- 学习事件 `study_events`
- 复盘项 `review_items`
- Dashboard 今日概览、最近记录、复盘队列
- 主题系统 `auto / light / dark`
- 后端测试 5 个通过
- 服务端口：`0.0.0.0:5188`

当前限制：

- QQ 还没有真正自动调用 StudyFlow，只是 API 已准备好
- 数据模型还偏 MVP，缺少 plan/task/mistake pattern/weekly report/heatmap 聚合
- 服务还不是 systemd 常驻
- 前端没有真实图表和热力图

---

# Design Principles

1. **先稳定数据，再美化图表**
   - 热力图、周报、趋势分析依赖稳定数据源。
   - 不要先画漂亮图，再反过来补数据。

2. **QQ 是输入入口，Web 是观察入口**
   - QQ：自然记录、低摩擦确认、轻提醒。
   - Web：看趋势、看计划、看复盘队列。

3. **避免学习垃圾堆**
   - 错题不是越多越好。
   - 要有 candidate / light_note / full_card / pattern / archived 等分流。

4. **适配在职考研节奏**
   - 每日计划要有：保底 / 标准 / 加餐。
   - 系统目标不是压榨，而是降低波动。

5. **每个版本都必须可验收**
   - API 测试
   - 页面加载
   - 交互点击/输入/切换
   - SQLite 持久化
   - 服务重启后数据仍在

---

# v0.2 — QQ 无感记录接入

## Goal

让用户在 QQ 里自然说学习内容时，StudyFlow 能自动记录；闲聊不污染数据库。

## Scope

### Backend

Modify:

- `backend/studyflow/app.py`
- `backend/tests/test_ingest.py`

Add/extend:

- duplicate detection
- confidence field
- ignored reason
- source message hash

Recommended schema migration:

```sql
ALTER TABLE study_events ADD COLUMN source_hash TEXT;
ALTER TABLE study_events ADD COLUMN confidence REAL DEFAULT 0.8;
ALTER TABLE study_events ADD COLUMN ignored_reason TEXT;
```

If SQLite migration is implemented manually, ensure `PRAGMA table_info(study_events)` is used so existing DBs are upgraded safely.

### Hermes script

Create:

- `/home/admin/.hermes/scripts/studyflow-ingest.py`

Responsibilities:

1. Accept natural text from CLI arg or stdin.
2. POST to `http://127.0.0.1:5188/api/ingest/qq`.
3. Print concise QQ-safe response:
   - recorded
   - ignored
   - duplicate
   - service unavailable

Example:

```bash
python3 /home/admin/.hermes/scripts/studyflow-ingest.py "今天数学刷题40分钟，错在导数单调性"
```

Expected output:

```text
已记录：数学 40 分钟，生成 1 条复盘项。
```

### Tests

Create:

- `backend/tests/test_dedup.py`
- optional script-level test if feasible

Test cases:

1. learning message is recorded
2. casual chat is ignored
3. duplicate message within short window is ignored
4. service response includes concise status
5. source_hash persists

### Verification

Commands:

```bash
cd /home/admin/workspace/puck-study
PYTHONPATH=backend python3 -m pytest -q backend/tests
curl -sS -X POST http://127.0.0.1:5188/api/ingest/qq \
  -H 'Content-Type: application/json' \
  -d '{"text":"今天数学刷题40分钟，错在导数单调性","sender":"aton_puck"}'
curl -sS http://127.0.0.1:5188/api/events
```

Acceptance criteria:

- QQ-style learning text appears in Dashboard
- casual chat ignored
- duplicate ignored
- no raw tracebacks in QQ-facing output

---

# v0.3 — 自适应每日计划 + Puck Todo 同步

## Goal

把 StudyFlow 从“记录系统”推进成“每日学习节奏系统”。

## Data model

Add tables:

```sql
CREATE TABLE IF NOT EXISTS study_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  mode TEXT NOT NULL, -- minimal / standard / extra
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS study_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  plan_id INTEGER NOT NULL,
  subject TEXT NOT NULL,
  title TEXT NOT NULL,
  target_minutes INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending', -- pending / done / skipped
  priority INTEGER NOT NULL DEFAULT 2,
  source TEXT NOT NULL DEFAULT 'studyflow',
  created_at TEXT NOT NULL,
  completed_at TEXT,
  FOREIGN KEY(plan_id) REFERENCES study_plans(id)
);
```

## API

Add:

- `POST /api/plans/today/generate`
- `GET /api/plans/today`
- `PATCH /api/tasks/{task_id}`
- `POST /api/plans/today/downgrade`
- `POST /api/plans/today/upgrade`
- `POST /api/integrations/puck-todo/sync`

## Plan modes

### 保底 minimal

低状态日：只保留不断链任务。

Example:

- 英语单词 15 min
- 数学错题 15 min

### 标准 standard

普通工作日。

Example:

- 数学刷题 40 min
- 英语单词 25 min
- 错题复盘 15 min

### 加餐 extra

状态好 / 周末。

Example:

- 数学专题 60 min
- 英语阅读 40 min
- 408 专业课专题训练 45 min

## Puck Todo sync

Puck Todo should remain the reminder/execution layer, not the learning database.

Sync strategy:

- StudyFlow owns learning plan data.
- Puck Todo receives actionable reminders.
- Sync only today active tasks.
- Avoid duplicate Todo items via deterministic external id.

## Frontend

Add section:

- 今日计划
- 保底 / 标准 / 加餐 switch
- task checkbox
- sync to Puck Todo button

## Tests

Create:

- `backend/tests/test_plans.py`
- `backend/tests/test_puck_todo_sync.py`

Acceptance criteria:

- generate today plan
- downgrade/upgrade plan
- mark task done
- sync does not duplicate
- Dashboard updates after task completion

---

# v0.4 — 错题队列 + 错因模式合并

## Goal

建立真正可复习、可收敛的错题系统，避免无限堆错题。

## Data model

Add tables:

```sql
CREATE TABLE IF NOT EXISTS mistake_cards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  subject TEXT NOT NULL,
  raw_text TEXT NOT NULL,
  question TEXT NOT NULL DEFAULT '',
  wrong_answer TEXT NOT NULL DEFAULT '',
  correct_answer TEXT NOT NULL DEFAULT '',
  mistake_reason TEXT NOT NULL DEFAULT '',
  knowledge_point TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'candidate',
  review_count INTEGER NOT NULL DEFAULT 0,
  next_review_at TEXT,
  event_id INTEGER
);

CREATE TABLE IF NOT EXISTS mistake_patterns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  subject TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  evidence_count INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'active'
);
```

## Status design

For `mistake_cards.status`:

- `candidate`: maybe useful, needs triage
- `light_note`: small issue, no full card needed
- `full_card`: worth reviewing seriously
- `reviewing`: in review queue
- `mastered`: already handled
- `archived`: no longer active
- `discarded`: noise / not worth keeping

## API

Add:

- `GET /api/mistakes/candidates`
- `POST /api/mistakes/{id}/promote`
- `POST /api/mistakes/{id}/discard`
- `POST /api/mistakes/{id}/reviewed`
- `GET /api/mistake-patterns`
- `POST /api/mistake-patterns/consolidate`

## Frontend

Add:

- 今日需复盘
- 候选错题收件箱
- 一键转 full card / light note / discard
- 错因模式卡片

## Pattern consolidation

Start rule-based:

- same subject
- overlapping knowledge_point or repeated keywords
- repeated mistake_reason

Later LLM-assisted consolidation can be added in v0.5+.

## Tests

Create:

- `backend/tests/test_mistakes.py`
- `backend/tests/test_mistake_patterns.py`

Acceptance criteria:

- mistake can be triaged
- review_count increments
- next_review_at updates
- similar mistakes can form one pattern
- Dashboard does not show scary huge backlog; shows today-focused queue

---

# v0.5 — 周报 + GitHub-style 热力图 + 趋势分析

## Goal

提供长期反馈感和趋势洞察，让用户一眼看到学习连续性、强度和偏科情况。

## Data model

Add table:

```sql
CREATE TABLE IF NOT EXISTS weekly_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  week_start TEXT NOT NULL,
  week_end TEXT NOT NULL,
  total_minutes INTEGER NOT NULL DEFAULT 0,
  subject_breakdown TEXT NOT NULL DEFAULT '{}',
  completion_rate REAL NOT NULL DEFAULT 0,
  summary TEXT NOT NULL DEFAULT '',
  blockers TEXT NOT NULL DEFAULT '[]',
  next_week_strategy TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
```

Heatmap can be computed from `study_events`, not necessarily stored at first.

## API

Add:

- `GET /api/stats/heatmap?days=180&subject=all`
- `GET /api/stats/trends?range=week`
- `POST /api/reports/weekly/generate`
- `GET /api/reports/weekly/latest`

## Heatmap contract

`GET /api/stats/heatmap` should return:

```json
{
  "days": [
    {
      "date": "2026-05-17",
      "total_minutes": 70,
      "event_count": 2,
      "level": 2,
      "subjects": {
        "数学": 45,
        "英语": 25
      }
    }
  ],
  "legend": [
    {"level": 0, "label": "0 min"},
    {"level": 1, "label": "1-30 min"},
    {"level": 2, "label": "30-90 min"},
    {"level": 3, "label": "90-180 min"},
    {"level": 4, "label": "180+ min"}
  ]
}
```

## Heatmap levels

- `0`: 0 min
- `1`: 1-30 min
- `2`: 30-90 min
- `3`: 90-180 min
- `4`: 180+ min

## Frontend

Add:

- GitHub-style contribution heatmap
- subject filter
- hover tooltip
- current streak
- longest streak
- last 7/30/180 day selector
- week trend line or simple bar chart

No heavy chart library required at first. CSS grid is enough.

## Weekly report

Generate from real data first, LLM later.

Report sections:

- total time
- subject breakdown
- completion rate
- recurring blockers
- mistake review status
- next week strategy

## Tests

Create:

- `backend/tests/test_heatmap.py`
- `backend/tests/test_weekly_reports.py`

Acceptance criteria:

- heatmap returns continuous date range including zero days
- levels match thresholds
- subject filter works
- weekly report aggregates correct totals
- Dashboard renders heatmap and tooltip data

---

# v0.6 — 稳定部署、备份、导出

## Goal

让 StudyFlow 成为长期可用服务，而不是临时后台进程。

## systemd user service

Create:

- `/home/admin/.config/systemd/user/studyflow.service`

Service content:

```ini
[Unit]
Description=StudyFlow personal learning dashboard
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/admin/workspace/puck-study
Environment=PYTHONPATH=/home/admin/workspace/puck-study/backend
Environment=STUDYFLOW_DB_PATH=/home/admin/workspace/puck-study/data/studyflow.db
ExecStart=/home/admin/.hermes/hermes-agent/venv/bin/python3 -m uvicorn studyflow.app:app --host 0.0.0.0 --port 5188
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

Commands:

```bash
systemctl --user daemon-reload
systemctl --user enable --now studyflow
systemctl --user status studyflow
```

## Healthcheck

Create:

- `/home/admin/.hermes/scripts/studyflow-healthcheck.py`

Checks:

- service active
- port 5188 listening
- `/api/health` returns ok
- SQLite file exists and is writable
- homepage returns StudyFlow

## Backup

Create:

- `/home/admin/.hermes/scripts/studyflow-backup.py`

Backup target:

- `/home/admin/backups/studyflow/YYYYMMDD-HHMMSS-studyflow.db`

Keep latest N backups, e.g. 30.

## Export

API:

- `GET /api/export/events.json`
- `GET /api/export/events.csv`
- `GET /api/export/report.md`

## Tests

Create:

- `backend/tests/test_export.py`

Acceptance criteria:

- service survives restart
- healthcheck returns concise OK
- backup file is created
- export contains study events and review items

---

# Recommended Implementation Order

## Sprint A: v0.2 foundation

1. Add safe DB migration helper.
2. Add `source_hash`, `confidence`, `ignored_reason` fields.
3. Add duplicate detection tests.
4. Implement duplicate detection.
5. Create `/home/admin/.hermes/scripts/studyflow-ingest.py`.
6. Verify CLI → API → SQLite → Dashboard.

## Sprint B: v0.3 planning

1. Add `study_plans` and `study_tasks` migrations.
2. Add plan generation API.
3. Add task completion API.
4. Add Dashboard today plan card.
5. Add Puck Todo sync endpoint/script.
6. Verify no duplicate Todo sync.

## Sprint C: v0.4 mistakes

1. Add `mistake_cards` and `mistake_patterns`.
2. Add candidate/full_card/light_note/discard workflow.
3. Add review scheduling.
4. Add Dashboard triage UI.
5. Add pattern consolidation.

## Sprint D: v0.5 analytics

1. Add heatmap API.
2. Add heatmap frontend CSS grid.
3. Add trend API.
4. Add weekly report generation.
5. Add weekly report UI.

## Sprint E: v0.6 ops

1. Add systemd service.
2. Add healthcheck script.
3. Add backup script.
4. Add export APIs.
5. Verify restart/recovery.

---

# Definition of Done for every sprint

Each sprint is not done until all are true:

- `PYTHONPATH=backend python3 -m pytest -q backend/tests` passes
- `python3 -m py_compile backend/studyflow/app.py` passes
- API manually verified with curl
- frontend page loads
- relevant interaction works
- data persists in SQLite
- no raw traceback in user-facing output
- README/docs updated

