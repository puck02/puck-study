import csv
import hashlib
import io
import json
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

DEFAULT_DB_PATH = os.environ.get('STUDYFLOW_DB_PATH', '/home/admin/workspace/puck-study/data/studyflow.db')


class EventCreate(BaseModel):
    raw_text: str = Field(..., min_length=1)
    source: str = 'manual'
    category: str = 'study'
    subject: str = '未分类'
    summary: Optional[str] = None
    duration_minutes: int = 0
    difficulty: str = 'unknown'
    tags: List[str] = Field(default_factory=list)
    source_hash: Optional[str] = None
    confidence: float = 0.8
    ignored_reason: Optional[str] = None


class ReviewItemCreate(BaseModel):
    question: str
    answer: str = ''
    event_id: Optional[int] = None
    status: str = 'active'
    next_review_at: Optional[str] = None


class QQIngest(BaseModel):
    text: str
    sender: str = 'unknown'


class PlanGenerate(BaseModel):
    mode: str = 'standard'


class TaskPatch(BaseModel):
    status: str


class MistakeCreate(BaseModel):
    subject: str = '未分类'
    raw_text: str
    question: str = ''
    wrong_answer: str = ''
    correct_answer: str = ''
    mistake_reason: str = ''
    knowledge_point: str = ''
    status: str = 'candidate'
    event_id: Optional[int] = None


class MistakePromote(BaseModel):
    status: str = 'full_card'


class LedgerRecordCreate(BaseModel):
    raw_text: str = Field(..., min_length=1)
    source: str = 'manual'
    direction: str = 'expense'
    category: str = '其他'
    amount: float = 0
    summary: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    source_hash: Optional[str] = None
    note: str = ''


def connect(db_path: str) -> sqlite3.Connection:
    dirname = os.path.dirname(db_path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def columns(conn: sqlite3.Connection, table: str) -> set:
    return {row['name'] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}


def add_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    name = definition.split()[0]
    if name not in columns(conn, table):
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {definition}')


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute('''CREATE TABLE IF NOT EXISTS study_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, source TEXT NOT NULL,
        raw_text TEXT NOT NULL, category TEXT NOT NULL, subject TEXT NOT NULL, summary TEXT NOT NULL,
        duration_minutes INTEGER NOT NULL DEFAULT 0, difficulty TEXT NOT NULL DEFAULT 'unknown',
        tags TEXT NOT NULL DEFAULT '[]')''')
    add_column(conn, 'study_events', 'source_hash TEXT')
    add_column(conn, 'study_events', 'confidence REAL DEFAULT 0.8')
    add_column(conn, 'study_events', 'ignored_reason TEXT')

    conn.execute('''CREATE TABLE IF NOT EXISTS review_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, event_id INTEGER,
        question TEXT NOT NULL, answer TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
        next_review_at TEXT, FOREIGN KEY(event_id) REFERENCES study_events(id))''')

    conn.execute('''CREATE TABLE IF NOT EXISTS study_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, mode TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, note TEXT NOT NULL DEFAULT '')''')
    conn.execute('''CREATE TABLE IF NOT EXISTS study_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER NOT NULL, subject TEXT NOT NULL,
        title TEXT NOT NULL, target_minutes INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
        priority INTEGER NOT NULL DEFAULT 2, source TEXT NOT NULL DEFAULT 'studyflow', created_at TEXT NOT NULL,
        completed_at TEXT, external_id TEXT, FOREIGN KEY(plan_id) REFERENCES study_plans(id))''')

    conn.execute('''CREATE TABLE IF NOT EXISTS mistake_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, subject TEXT NOT NULL,
        raw_text TEXT NOT NULL, question TEXT NOT NULL DEFAULT '', wrong_answer TEXT NOT NULL DEFAULT '',
        correct_answer TEXT NOT NULL DEFAULT '', mistake_reason TEXT NOT NULL DEFAULT '',
        knowledge_point TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'candidate',
        review_count INTEGER NOT NULL DEFAULT 0, next_review_at TEXT, event_id INTEGER)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS mistake_patterns (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, subject TEXT NOT NULL,
        title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', evidence_count INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'active')''')
    conn.execute('''CREATE TABLE IF NOT EXISTS weekly_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT, week_start TEXT NOT NULL, week_end TEXT NOT NULL,
        total_minutes INTEGER NOT NULL DEFAULT 0, subject_breakdown TEXT NOT NULL DEFAULT '{}',
        completion_rate REAL NOT NULL DEFAULT 0, summary TEXT NOT NULL DEFAULT '', blockers TEXT NOT NULL DEFAULT '[]',
        next_week_strategy TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS ledger_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, source TEXT NOT NULL,
        raw_text TEXT NOT NULL, direction TEXT NOT NULL, category TEXT NOT NULL,
        amount REAL NOT NULL DEFAULT 0, summary TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '[]',
        source_hash TEXT, note TEXT NOT NULL DEFAULT '')''')
    conn.commit()


def row_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return dict(row)


def row_to_event(row: sqlite3.Row) -> Dict[str, Any]:
    item = dict(row)
    item['tags'] = json.loads(item.get('tags') or '[]')
    return item


def row_to_ledger_record(row: sqlite3.Row) -> Dict[str, Any]:
    item = dict(row)
    item['tags'] = json.loads(item.get('tags') or '[]')
    return item


def rows_to_tasks(rows):
    return [dict(r) for r in rows]


def infer_subject(text: str) -> str:
    if '数学' in text:
        return '数学'
    if '英语' in text or '单词' in text or re.search(r'[a-zA-Z]{3,}', text):
        return '英语'
    if '政治' in text:
        return '政治'
    if any(w in text for w in ['专业课', '408', '11408', '数据结构', '组成原理', '计组', '操作系统', '计网', '计算机网络', '算法']):
        return '专业课'
    return '未分类'


def infer_minutes(text: str) -> int:
    m = re.search(r'(\d+)\s*(分钟|min)', text, re.I)
    if m:
        return int(m.group(1))
    h = re.search(r'(\d+(?:\.\d+)?)\s*(小时|h)', text, re.I)
    return int(float(h.group(1)) * 60) if h else 0


def looks_like_study(text: str) -> bool:
    return any(w in text for w in ['学习', '考研', '11408', '408', '刷题', '背', '复盘', '错题', '数学', '英语', '政治', '专业课', '算法', '单词', '数据结构', '组成原理', '计组', '操作系统', '计网', '计算机网络'])


def infer_category(text: str) -> str:
    if '错' in text or '错题' in text:
        return 'mistake'
    if '复盘' in text or '回顾' in text:
        return 'review'
    if '计划' in text or '明天' in text:
        return 'plan'
    return 'study'


def source_hash(sender: str, text: str) -> str:
    norm = re.sub(r'\s+', '', text.strip())
    return hashlib.sha256(f'{sender}:{norm}'.encode('utf-8')).hexdigest()[:24]


def plan_templates(mode: str):
    templates = {
        'minimal': [('英语', '英语单词保底', 15, 1), ('数学', '数学错题保底', 15, 1)],
        'standard': [('数学', '数学刷题', 40, 1), ('英语', '英语单词', 25, 2), ('复盘', '错题复盘', 15, 2)],
        'extra': [('数学', '数学专题训练', 60, 1), ('英语', '英语阅读', 40, 2), ('专业课', '408 专业课专题训练', 45, 3)],
    }
    return templates.get(mode, templates['standard'])


def heat_level(minutes: int) -> int:
    if minutes <= 0:
        return 0
    if minutes <= 30:
        return 1
    if minutes <= 90:
        return 2
    if minutes <= 180:
        return 3
    return 4


def looks_like_ledger(text: str) -> bool:
    has_amount = bool(re.search(r'\d+(?:\.\d+)?\s*(元|块|rmb)?', text, re.I))
    has_keyword = any(
        key in text for key in ['记账', '花', '花了', '用了', '支出', '收入', '到账', '买', '支付', '付款', '消费', '工资', '报销']
    )
    return has_amount and has_keyword


def infer_ledger_direction(text: str) -> str:
    income_keywords = ['收入', '到账', '工资', '报销', '退款', '收了', '赚了', '入账', '转给我']
    return 'income' if any(word in text for word in income_keywords) else 'expense'


def infer_ledger_amount(text: str) -> float:
    match = re.search(r'(\d+(?:\.\d+)?)\s*(元|块|rmb)', text, re.I)
    if not match:
        match = re.search(r'(\d+(?:\.\d+)?)', text)
    return round(float(match.group(1)), 2) if match else 0.0


def infer_ledger_category(text: str, direction: str) -> str:
    category_map = [
        ('餐饮', ['饭', '早餐', '午饭', '晚饭', '夜宵', '奶茶', '咖啡', '外卖', '拉面', '吃']),
        ('交通', ['地铁', '公交', '打车', '滴滴', '高铁', '火车', '车费']),
        ('购物', ['买', '淘宝', '京东', '拼多多', '耳机', '衣服', '裤子', '鞋']),
        ('住房', ['房租', '租房', '水电', '物业']),
        ('娱乐', ['电影', '游戏', '桌游', 'KTV', '演出']),
        ('医疗', ['医院', '药', '挂号', '体检']),
        ('学习', ['书', '课程', '打印', '资料', '题库', '报名']),
        ('社交', ['红包', '请客', '聚餐', '礼物']),
    ]
    if direction == 'income':
        income_map = [
            ('工资', ['工资', '发薪', '薪资']),
            ('兼职', ['兼职', '外快']),
            ('报销', ['报销']),
            ('退款', ['退款', '退回']),
            ('转账', ['转给我', '收款', '转账']),
        ]
        for category, keywords in income_map:
            if any(word in text for word in keywords):
                return category
        return '其他收入'
    for category, keywords in category_map:
        if any(word in text for word in keywords):
            return category
    return '其他'


def clean_ledger_summary(text: str) -> str:
    cleaned = re.sub(r'[，,。；;！!？?]', ' ', text)
    cleaned = re.sub(r'\d+(?:\.\d+)?\s*(元|块|rmb)?', '', cleaned, flags=re.I)
    cleaned = re.sub(r'(记账|花了|花费|支出|收入|到账|付款|支付|消费)', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned[:80] if cleaned else text[:80]


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, n: int) -> date:
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return date(y, m, 1)


def parse_month(value: str) -> date:
    return datetime.strptime(value, '%Y-%m').date().replace(day=1)


def parse_date_value(value: str) -> date:
    return datetime.strptime(value, '%Y-%m-%d').date()


def canonical_subject(subject_name: str) -> str:
    return '408' if subject_name == '专业课' else subject_name


def build_pretty_weekly_markdown(start: date, end: date, total: int, by: Dict[str, int], event_count: int) -> str:
    hours = round(total / 60, 1)
    lines = [
        f"## StudyFlow 周报 · {start.isoformat()} ~ {end.isoformat()}",
        '',
        f'✨ **本周总学习：{total} 分钟（约 {hours} 小时）**',
        f'📌 **记录条数：{event_count} 条**',
        '',
        '### 科目分布',
    ]
    if by:
        for subject_name in ['数学', '英语', '专业课', '政治']:
            minutes = by.get(subject_name, 0)
            label = canonical_subject(subject_name)
            bar = '█' * max(1, min(20, round(minutes / max(total, 1) * 20))) if minutes else '░'
            pct = round(minutes / total * 100, 1) if total else 0
            lines.append(f'- **{label}**：{minutes} min · {pct}% `{bar}`')
    else:
        lines.append('- 本周暂无学习记录，先从保底计划重新开始。')
    lines += [
        '',
        '### 下周策略',
        '1. 优先保证数学/408 的连续性。',
        '2. 英语保持每日轻量输入，不追求一次性补偿。',
        '3. 政治采用碎片时间推进，周末统一复盘。',
    ]
    return '\n'.join(lines)


def create_app(db_path: str = DEFAULT_DB_PATH) -> FastAPI:
    conn = connect(db_path)
    init_db(conn)
    app = FastAPI(title='StudyFlow', version='0.7.0')

    def create_event_record(payload: EventCreate) -> Dict[str, Any]:
        now = datetime.now().isoformat(timespec='seconds')
        summary = payload.summary or payload.raw_text[:120]
        cur = conn.execute(
            '''INSERT INTO study_events
            (created_at, source, raw_text, category, subject, summary, duration_minutes, difficulty, tags, source_hash, confidence, ignored_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                now,
                payload.source,
                payload.raw_text,
                payload.category,
                payload.subject,
                summary,
                payload.duration_minutes,
                payload.difficulty,
                json.dumps(payload.tags, ensure_ascii=False),
                payload.source_hash,
                payload.confidence,
                payload.ignored_reason,
            ),
        )
        conn.commit()
        return row_to_event(conn.execute('SELECT * FROM study_events WHERE id=?', (cur.lastrowid,)).fetchone())

    def create_review_record(payload: ReviewItemCreate) -> Dict[str, Any]:
        now = datetime.now().isoformat(timespec='seconds')
        cur = conn.execute(
            '''INSERT INTO review_items (created_at,event_id,question,answer,status,next_review_at)
            VALUES (?, ?, ?, ?, ?, ?)''',
            (now, payload.event_id, payload.question, payload.answer, payload.status, payload.next_review_at),
        )
        conn.commit()
        return row_dict(conn.execute('SELECT * FROM review_items WHERE id=?', (cur.lastrowid,)).fetchone())

    def create_ledger_record(payload: LedgerRecordCreate) -> Dict[str, Any]:
        now = datetime.now().isoformat(timespec='seconds')
        summary = payload.summary or payload.raw_text[:120]
        cur = conn.execute(
            '''INSERT INTO ledger_records
            (created_at, source, raw_text, direction, category, amount, summary, tags, source_hash, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                now,
                payload.source,
                payload.raw_text,
                payload.direction,
                payload.category,
                payload.amount,
                summary,
                json.dumps(payload.tags, ensure_ascii=False),
                payload.source_hash,
                payload.note,
            ),
        )
        conn.commit()
        return row_to_ledger_record(conn.execute('SELECT * FROM ledger_records WHERE id=?', (cur.lastrowid,)).fetchone())

    @app.get('/api/health')
    def health():
        return {'ok': True, 'service': 'studyflow'}

    @app.post('/api/events')
    def create_event(payload: EventCreate):
        return create_event_record(payload)

    @app.get('/api/events')
    def list_events(limit: int = 50):
        rows = conn.execute('SELECT * FROM study_events ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return {'items': [row_to_event(r) for r in rows]}

    @app.get('/api/summary/today')
    def today_summary():
        prefix = date.today().isoformat()
        rows = conn.execute('SELECT subject,duration_minutes FROM study_events WHERE created_at LIKE ?', (prefix + '%',)).fetchall()
        by = {}
        total = 0
        for r in rows:
            minutes = int(r['duration_minutes'] or 0)
            subject = r['subject'] or '未分类'
            total += minutes
            by[subject] = by.get(subject, 0) + minutes
        return {'date': prefix, 'event_count': len(rows), 'total_minutes': total, 'by_subject': by}

    @app.post('/api/review-items')
    def create_review_item(payload: ReviewItemCreate):
        return create_review_record(payload)

    @app.get('/api/review-items')
    def list_review_items(status: Optional[str] = None, limit: int = 50):
        if status:
            rows = conn.execute('SELECT * FROM review_items WHERE status=? ORDER BY id DESC LIMIT ?', (status, limit)).fetchall()
        else:
            rows = conn.execute('SELECT * FROM review_items ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return {'items': [row_dict(r) for r in rows]}

    @app.post('/api/ingest/qq')
    def ingest_qq(payload: QQIngest):
        text = payload.text.strip()
        hashed = source_hash(payload.sender, text)
        if not text or not looks_like_study(text):
            return {'ignored': True, 'ignored_reason': 'not_study', 'created_event': None, 'created_review_item': None}
        existing = conn.execute('SELECT * FROM study_events WHERE source_hash=? LIMIT 1', (hashed,)).fetchone()
        if existing:
            return {'ignored': True, 'ignored_reason': 'duplicate', 'created_event': row_to_event(existing), 'created_review_item': None}
        category = infer_category(text)
        subject = infer_subject(text)
        minutes = infer_minutes(text)
        event = create_event_record(
            EventCreate(
                raw_text=text,
                source='qq',
                category=category,
                subject=subject,
                summary=text[:80],
                duration_minutes=minutes,
                tags=[subject] if subject != '未分类' else [],
                source_hash=hashed,
                confidence=0.85,
            )
        )
        review = None
        if category == 'mistake':
            review = create_review_record(ReviewItemCreate(event_id=event['id'], question=text, status='active'))
        return {'ignored': False, 'ignored_reason': None, 'created_event': event, 'created_review_item': review}

    @app.post('/api/plans/today/generate')
    def generate_today_plan(payload: PlanGenerate):
        today = date.today().isoformat()
        now = datetime.now().isoformat(timespec='seconds')
        conn.execute('UPDATE study_plans SET status="archived" WHERE date=? AND status="active"', (today,))
        cur = conn.execute(
            'INSERT INTO study_plans (date,mode,status,created_at,note) VALUES (?, ?, "active", ?, ?)',
            (today, payload.mode, now, 'auto-generated'),
        )
        plan_id = cur.lastrowid
        for subject, title, minutes, priority in plan_templates(payload.mode):
            ext = f'studyflow:{today}:{payload.mode}:{title}'
            conn.execute(
                '''INSERT INTO study_tasks (plan_id,subject,title,target_minutes,status,priority,source,created_at,external_id)
                VALUES (?, ?, ?, ?, 'pending', ?, 'studyflow', ?, ?)''',
                (plan_id, subject, title, minutes, priority, now, ext),
            )
        conn.commit()
        return get_today_plan()

    @app.get('/api/plans/today')
    def get_today_plan():
        today = date.today().isoformat()
        plan = conn.execute('SELECT * FROM study_plans WHERE date=? AND status="active" ORDER BY id DESC LIMIT 1', (today,)).fetchone()
        if not plan:
            return {'plan': None, 'tasks': []}
        tasks = conn.execute('SELECT * FROM study_tasks WHERE plan_id=? ORDER BY priority,id', (plan['id'],)).fetchall()
        data = dict(plan)
        data['tasks'] = rows_to_tasks(tasks)
        return data

    @app.patch('/api/tasks/{task_id}')
    def patch_task(task_id: int, payload: TaskPatch):
        completed = datetime.now().isoformat(timespec='seconds') if payload.status == 'done' else None
        conn.execute('UPDATE study_tasks SET status=?, completed_at=? WHERE id=?', (payload.status, completed, task_id))
        conn.commit()
        return row_dict(conn.execute('SELECT * FROM study_tasks WHERE id=?', (task_id,)).fetchone())

    @app.post('/api/plans/today/downgrade')
    def downgrade():
        return generate_today_plan(PlanGenerate(mode='minimal'))

    @app.post('/api/plans/today/upgrade')
    def upgrade():
        return generate_today_plan(PlanGenerate(mode='extra'))

    @app.post('/api/integrations/puck-todo/sync')
    def puck_sync():
        plan = get_today_plan()
        return {'ok': True, 'synced': len(plan.get('tasks', [])), 'mode': plan.get('mode')}

    @app.post('/api/mistakes')
    def create_mistake(payload: MistakeCreate):
        now = datetime.now().isoformat(timespec='seconds')
        cur = conn.execute(
            '''INSERT INTO mistake_cards (created_at,subject,raw_text,question,wrong_answer,correct_answer,mistake_reason,knowledge_point,status,event_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                now,
                payload.subject,
                payload.raw_text,
                payload.question,
                payload.wrong_answer,
                payload.correct_answer,
                payload.mistake_reason,
                payload.knowledge_point,
                payload.status,
                payload.event_id,
            ),
        )
        conn.commit()
        return row_dict(conn.execute('SELECT * FROM mistake_cards WHERE id=?', (cur.lastrowid,)).fetchone())

    @app.get('/api/mistakes/candidates')
    def mistake_candidates():
        rows = conn.execute('SELECT * FROM mistake_cards WHERE status="candidate" ORDER BY id DESC').fetchall()
        return {'items': [row_dict(r) for r in rows]}

    @app.post('/api/mistakes/{mid}/promote')
    def promote_mistake(mid: int, payload: MistakePromote):
        conn.execute('UPDATE mistake_cards SET status=? WHERE id=?', (payload.status, mid))
        conn.commit()
        return row_dict(conn.execute('SELECT * FROM mistake_cards WHERE id=?', (mid,)).fetchone())

    @app.post('/api/mistakes/{mid}/discard')
    def discard_mistake(mid: int):
        return promote_mistake(mid, MistakePromote(status='discarded'))

    @app.post('/api/mistakes/{mid}/reviewed')
    def reviewed_mistake(mid: int):
        next_at = (date.today() + timedelta(days=1)).isoformat()
        conn.execute('UPDATE mistake_cards SET review_count=review_count+1,status="reviewing",next_review_at=? WHERE id=?', (next_at, mid))
        conn.commit()
        return row_dict(conn.execute('SELECT * FROM mistake_cards WHERE id=?', (mid,)).fetchone())

    @app.get('/api/mistake-patterns')
    def patterns():
        rows = conn.execute('SELECT * FROM mistake_patterns ORDER BY evidence_count DESC,id DESC').fetchall()
        return {'items': [row_dict(r) for r in rows]}

    @app.post('/api/mistake-patterns/consolidate')
    def consolidate():
        rows = conn.execute(
            'SELECT subject,knowledge_point,mistake_reason,COUNT(*) c FROM mistake_cards WHERE status != "discarded" GROUP BY subject,knowledge_point,mistake_reason'
        ).fetchall()
        conn.execute('DELETE FROM mistake_patterns')
        now = datetime.now().isoformat(timespec='seconds')
        for row in rows:
            title = row['knowledge_point'] or row['mistake_reason'] or f"{row['subject']}错因模式"
            conn.execute(
                'INSERT INTO mistake_patterns (created_at,subject,title,description,evidence_count,status) VALUES (?, ?, ?, ?, ?, "active")',
                (now, row['subject'], title, row['mistake_reason'] or '', row['c']),
            )
        conn.commit()
        return patterns()

    @app.get('/api/stats/heatmap')
    def heatmap(days: Optional[int] = None, subject: str = 'all', mode: str = 'recent_months', start_month: Optional[str] = None, end_month: Optional[str] = None):
        today = date.today()
        if start_month and end_month:
            start = parse_month(start_month)
            end_exclusive = add_months(parse_month(end_month), 1)
            mode_used = 'month_range'
        elif mode == 'year':
            start = add_months(month_start(today), -11)
            end_exclusive = add_months(month_start(today), 1)
            mode_used = 'year'
        elif days is not None:
            end = today
            start = end - timedelta(days=days - 1)
            end_exclusive = end + timedelta(days=1)
            mode_used = 'days'
        else:
            start = add_months(month_start(today), -4)
            end_exclusive = add_months(month_start(today), 1)
            mode_used = 'recent_months'
        out = []
        cursor = start
        while cursor < end_exclusive:
            prefix = cursor.isoformat()
            if subject == 'all':
                rows = conn.execute('SELECT subject,duration_minutes FROM study_events WHERE created_at LIKE ?', (prefix + '%',)).fetchall()
            else:
                db_subject = '专业课' if subject in ('408', '专业课') else subject
                rows = conn.execute('SELECT subject,duration_minutes FROM study_events WHERE created_at LIKE ? AND subject=?', (prefix + '%', db_subject)).fetchall()
            subjects = {}
            total = 0
            for row in rows:
                minutes = int(row['duration_minutes'] or 0)
                total += minutes
                label = canonical_subject(row['subject'])
                subjects[label] = subjects.get(label, 0) + minutes
            out.append({'date': prefix, 'total_minutes': total, 'event_count': len(rows), 'level': heat_level(total), 'subjects': subjects})
            cursor += timedelta(days=1)
        months = []
        for ym in sorted({item['date'][:7] for item in out}):
            month_days = [item for item in out if item['date'].startswith(ym)]
            total = sum(item['total_minutes'] for item in month_days)
            active = sum(1 for item in month_days if item['total_minutes'] > 0)
            months.append({'month': ym, 'total_minutes': total, 'active_days': active, 'avg_minutes_per_day': round(total / len(month_days), 1) if month_days else 0})
        return {
            'range': {
                'mode': mode_used,
                'months': 5 if mode_used == 'recent_months' else len(months),
                'start_month': start.strftime('%Y-%m'),
                'end_month': (end_exclusive - timedelta(days=1)).strftime('%Y-%m'),
            },
            'days': out,
            'months': months,
            'legend': [
                {'level': 0, 'label': '0 min'},
                {'level': 1, 'label': '1-30 min'},
                {'level': 2, 'label': '30-90 min'},
                {'level': 3, 'label': '90-180 min'},
                {'level': 4, 'label': '180+ min'},
            ],
        }

    @app.get('/api/stats/today-subjects')
    def today_subjects():
        prefix = date.today().isoformat()
        rows = conn.execute('SELECT subject,duration_minutes FROM study_events WHERE created_at LIKE ?', (prefix + '%',)).fetchall()
        order = [('数学', '数学'), ('英语', '英语'), ('专业课', '408'), ('政治', '政治')]
        totals = {db: 0 for db, _ in order}
        for row in rows:
            if row['subject'] in totals:
                totals[row['subject']] += int(row['duration_minutes'] or 0)
        total = sum(totals.values())
        items = [{'subject': label, 'minutes': totals[db], 'percent': round(totals[db] / total * 100, 1) if total else 0} for db, label in order]
        return {'date': prefix, 'total_minutes': total, 'items': items}

    @app.get('/api/stats/trends')
    def trends(range: str = 'week'):
        hm = heatmap(days=7 if range == 'week' else 30)
        streak = 0
        for item in reversed(hm['days']):
            if item['total_minutes'] > 0:
                streak += 1
            else:
                break
        return {'range': range, 'current_streak': streak, 'days': hm['days']}

    @app.post('/api/reports/weekly/generate')
    def weekly_report():
        today = date.today()
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        rows = conn.execute(
            'SELECT subject,duration_minutes FROM study_events WHERE created_at>=? AND created_at<?',
            (start.isoformat(), (end + timedelta(days=1)).isoformat()),
        ).fetchall()
        by = {}
        total = 0
        for row in rows:
            minutes = int(row['duration_minutes'] or 0)
            total += minutes
            by[row['subject']] = by.get(row['subject'], 0) + minutes
        summary = f'本周学习 {round(total / 60, 1)} 小时，共 {len(rows)} 条记录。'
        markdown = build_pretty_weekly_markdown(start, end, total, by, len(rows))
        cur = conn.execute(
            '''INSERT INTO weekly_reports (week_start,week_end,total_minutes,subject_breakdown,completion_rate,summary,blockers,next_week_strategy,created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (start.isoformat(), end.isoformat(), total, json.dumps(by, ensure_ascii=False), 0, summary, '[]', '保持保底计划，优先复盘错题。', datetime.now().isoformat(timespec='seconds')),
        )
        conn.commit()
        row = row_dict(conn.execute('SELECT * FROM weekly_reports WHERE id=?', (cur.lastrowid,)).fetchone())
        row['subject_breakdown'] = json.loads(row['subject_breakdown'])
        row['markdown'] = markdown
        return row

    @app.get('/api/reports/weekly/latest')
    def latest_report():
        row = conn.execute('SELECT * FROM weekly_reports ORDER BY id DESC LIMIT 1').fetchone()
        if not row:
            return {'report': None}
        data = row_dict(row)
        data['subject_breakdown'] = json.loads(data['subject_breakdown'])
        return data

    @app.post('/api/ledger/records')
    def create_ledger(payload: LedgerRecordCreate):
        return create_ledger_record(payload)

    @app.get('/api/ledger/records')
    def list_ledger_records(limit: int = 50, direction: str = 'all'):
        if direction == 'all':
            rows = conn.execute('SELECT * FROM ledger_records ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        else:
            rows = conn.execute('SELECT * FROM ledger_records WHERE direction=? ORDER BY id DESC LIMIT ?', (direction, limit)).fetchall()
        return {'items': [row_to_ledger_record(row) for row in rows]}

    @app.post('/api/ledger/ingest/qq')
    def ingest_ledger_qq(payload: QQIngest):
        text = payload.text.strip()
        hashed = source_hash(payload.sender, f'ledger:{text}')
        if not text or not looks_like_ledger(text):
            return {'ignored': True, 'ignored_reason': 'not_ledger', 'created_record': None}
        existing = conn.execute('SELECT * FROM ledger_records WHERE source_hash=? LIMIT 1', (hashed,)).fetchone()
        if existing:
            return {'ignored': True, 'ignored_reason': 'duplicate', 'created_record': row_to_ledger_record(existing)}
        direction = infer_ledger_direction(text)
        amount = infer_ledger_amount(text)
        category = infer_ledger_category(text, direction)
        summary = clean_ledger_summary(text)
        record = create_ledger_record(
            LedgerRecordCreate(
                raw_text=text,
                source='qq',
                direction=direction,
                category=category,
                amount=amount,
                summary=summary,
                tags=[category],
                source_hash=hashed,
            )
        )
        return {'ignored': False, 'ignored_reason': None, 'created_record': record}

    @app.get('/api/ledger/summary/today')
    def ledger_today_summary():
        prefix = date.today().isoformat()
        rows = conn.execute('SELECT direction,amount FROM ledger_records WHERE created_at LIKE ?', (prefix + '%',)).fetchall()
        expense_total = 0.0
        income_total = 0.0
        expense_count = 0
        income_count = 0
        for row in rows:
            amount = float(row['amount'] or 0)
            if row['direction'] == 'income':
                income_total += amount
                income_count += 1
            else:
                expense_total += amount
                expense_count += 1
        return {
            'date': prefix,
            'expense_total': round(expense_total, 2),
            'income_total': round(income_total, 2),
            'net_total': round(income_total - expense_total, 2),
            'expense_count': expense_count,
            'income_count': income_count,
        }

    def ledger_range_summary(start_prefix: str, end_prefix: str) -> Dict[str, Any]:
        rows = conn.execute(
            'SELECT direction, category, amount FROM ledger_records WHERE created_at>=? AND created_at<?',
            (start_prefix, end_prefix),
        ).fetchall()
        expense_total = 0.0
        income_total = 0.0
        expense_count = 0
        income_count = 0
        expense_by_category: Dict[str, float] = {}
        for row in rows:
            amount = float(row['amount'] or 0)
            if row['direction'] == 'income':
                income_total += amount
                income_count += 1
            else:
                expense_total += amount
                expense_count += 1
                category = row['category'] or '其他'
                expense_by_category[category] = expense_by_category.get(category, 0.0) + amount
        top_expense_category = None
        if expense_by_category:
            top_expense_category = sorted(expense_by_category.items(), key=lambda item: (-item[1], item[0]))[0][0]
        return {
            'expense_total': round(expense_total, 2),
            'income_total': round(income_total, 2),
            'net_total': round(income_total - expense_total, 2),
            'expense_count': expense_count,
            'income_count': income_count,
            'top_expense_category': top_expense_category,
        }

    def resolve_ledger_range(range_key: str = 'today', start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, str]:
        today = date.today()
        if range_key == 'custom':
            if not start or not end:
                raise ValueError('custom range requires start and end')
            start_date = parse_date_value(start)
            end_date = parse_date_value(end)
            if end_date < start_date:
                raise ValueError('end must be on or after start')
            end_exclusive = end_date + timedelta(days=1)
            label = f'{start_date.isoformat()} ~ {end_date.isoformat()}'
        elif range_key == '7d':
            start_date = today - timedelta(days=6)
            end_exclusive = today + timedelta(days=1)
            label = '近 7 天'
        elif range_key == 'month':
            start_date = month_start(today)
            end_exclusive = today + timedelta(days=1)
            label = '本月'
        elif range_key == 'year':
            start_date = date(today.year, 1, 1)
            end_exclusive = today + timedelta(days=1)
            label = '今年'
        else:
            start_date = today
            end_exclusive = today + timedelta(days=1)
            range_key = 'today'
            label = '今日'
        return {
            'range': range_key,
            'label': label,
            'start': start_date.isoformat(),
            'end': (end_exclusive - timedelta(days=1)).isoformat(),
            'end_exclusive': end_exclusive.isoformat(),
        }

    @app.get('/api/ledger/summary/range')
    def ledger_summary_range(range: str = 'today', start: Optional[str] = None, end: Optional[str] = None):
        try:
            info = resolve_ledger_range(range, start, end)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        summary = ledger_range_summary(info['start'], info['end_exclusive'])
        summary.update({
            'range': info['range'],
            'label': info['label'],
            'start': info['start'],
            'end': info['end'],
        })
        return summary

    @app.get('/api/ledger/summary/month')
    def ledger_month_summary(month: Optional[str] = None):
        target = parse_month(month) if month else month_start(date.today())
        next_month = add_months(target, 1)
        summary = ledger_range_summary(target.isoformat(), next_month.isoformat())
        summary['month'] = target.strftime('%Y-%m')
        return summary

    @app.get('/api/ledger/stats/monthly-categories')
    def ledger_monthly_categories(direction: str = 'expense', month: Optional[str] = None):
        target = parse_month(month) if month else month_start(date.today())
        next_month = add_months(target, 1)
        rows = conn.execute(
            'SELECT category, SUM(amount) total FROM ledger_records WHERE direction=? AND created_at>=? AND created_at<? GROUP BY category ORDER BY total DESC, category ASC',
            (direction, target.isoformat(), next_month.isoformat()),
        ).fetchall()
        total_amount = round(sum(float(row['total'] or 0) for row in rows), 2)
        items = []
        for row in rows:
            amount = round(float(row['total'] or 0), 2)
            items.append({
                'category': row['category'],
                'amount': amount,
                'percent': round(amount / total_amount * 100, 1) if total_amount else 0,
            })
        return {'month': target.strftime('%Y-%m'), 'direction': direction, 'total_amount': total_amount, 'items': items}

    @app.get('/api/ledger/stats/monthly-overview')
    def ledger_monthly_overview(months: int = 6):
        count = max(1, min(months, 24))
        current = month_start(date.today())
        start = add_months(current, -(count - 1))
        out = []
        cursor = start
        while cursor <= current:
            next_month = add_months(cursor, 1)
            summary = ledger_range_summary(cursor.isoformat(), next_month.isoformat())
            out.append({'month': cursor.strftime('%Y-%m'), **summary})
            cursor = next_month
        return {'months': out}

    @app.get('/api/ledger/stats/category-breakdown')
    def ledger_category_breakdown(direction: str = 'expense', range: str = 'today', start: Optional[str] = None, end: Optional[str] = None):
        resolved = resolve_ledger_range(range, start, end)
        rows = conn.execute(
            'SELECT category, SUM(amount) total FROM ledger_records WHERE direction=? AND created_at>=? AND created_at<? GROUP BY category ORDER BY total DESC, category ASC',
            (direction, resolved['start'], resolved['end_exclusive']),
        ).fetchall()
        total_amount = round(sum(float(row['total'] or 0) for row in rows), 2)
        items = []
        for row in rows:
            amount = round(float(row['total'] or 0), 2)
            items.append({
                'category': row['category'],
                'amount': amount,
                'percent': round(amount / total_amount * 100, 1) if total_amount else 0,
            })
        return {
            'direction': direction,
            'range': resolved['range'],
            'label': resolved['label'],
            'start': resolved['start'],
            'end': resolved['end'],
            'total_amount': total_amount,
            'items': items,
        }

    @app.get('/api/ledger/stats/daily')
    def ledger_daily(days: int = 14):
        end = date.today()
        start = end - timedelta(days=max(days - 1, 0))
        cursor = start
        out = []
        while cursor <= end:
            prefix = cursor.isoformat()
            rows = conn.execute('SELECT direction,amount FROM ledger_records WHERE created_at LIKE ?', (prefix + '%',)).fetchall()
            expense_total = 0.0
            income_total = 0.0
            for row in rows:
                amount = float(row['amount'] or 0)
                if row['direction'] == 'income':
                    income_total += amount
                else:
                    expense_total += amount
            out.append({
                'date': prefix,
                'expense_total': round(expense_total, 2),
                'income_total': round(income_total, 2),
                'net_total': round(income_total - expense_total, 2),
            })
            cursor += timedelta(days=1)
        return {'days': out}

    @app.get('/api/export/events.json')
    def export_json():
        return list_events(limit=10000)

    @app.get('/api/export/events.csv')
    def export_csv():
        rows = list_events(limit=10000)['items']
        buf = io.StringIO()
        fields = ['id', 'created_at', 'source', 'raw_text', 'category', 'subject', 'summary', 'duration_minutes', 'difficulty']
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, '') for key in fields})
        return Response(buf.getvalue(), media_type='text/csv')

    @app.get('/api/export/report.md')
    def export_md():
        summary = today_summary()
        return PlainTextResponse(f"# StudyFlow Report\n\n今日记录：{summary['event_count']} 条\n今日时长：{summary['total_minutes']} 分钟\n")

    frontend_dir = '/home/admin/workspace/puck-study/frontend'
    if os.path.isdir(frontend_dir):
        app.mount('/static', StaticFiles(directory=frontend_dir), name='static')

        @app.get('/')
        def index():
            return FileResponse(os.path.join(frontend_dir, 'index.html'))

        @app.get('/app.js')
        def app_js():
            return FileResponse(os.path.join(frontend_dir, 'app.js'))

        @app.get('/ledger')
        def ledger_clean():
            return FileResponse(os.path.join(frontend_dir, 'ledger.html'))

        @app.get('/ledger.html')
        def ledger_html():
            return FileResponse(os.path.join(frontend_dir, 'ledger.html'))

        @app.get('/ledger.js')
        def ledger_js():
            return FileResponse(os.path.join(frontend_dir, 'ledger.js'))

        @app.get('/style.css')
        def style_css():
            return FileResponse(os.path.join(frontend_dir, 'style.css'))

    return app


app = create_app()
