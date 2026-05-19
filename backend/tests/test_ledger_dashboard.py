import os
import tempfile
from datetime import date

from fastapi.testclient import TestClient

from studyflow.app import create_app


def make_client():
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    app = create_app(db_path=tmp.name)
    return TestClient(app), tmp.name


def test_ingest_qq_expense_creates_ledger_record_and_extracts_fields():
    client, path = make_client()
    try:
        res = client.post('/api/ledger/ingest/qq', json={
            'text': '今天午饭兰州拉面 18 元，记账',
            'sender': 'aton_puck'
        })
        assert res.status_code == 200
        body = res.json()
        assert body['ignored'] is False
        record = body['created_record']
        assert record['direction'] == 'expense'
        assert record['amount'] == 18
        assert record['category'] == '餐饮'
        assert '兰州拉面' in record['summary']

        listed = client.get('/api/ledger/records').json()['items']
        assert len(listed) == 1
        assert listed[0]['amount'] == 18
    finally:
        os.unlink(path)


def test_ingest_qq_expense_without_explicit_jizhang_still_creates_ledger_record():
    client, path = make_client()
    try:
        res = client.post('/api/ledger/ingest/qq', json={
            'text': '昨天买零食花了34.6元',
            'sender': 'aton_puck'
        })
        assert res.status_code == 200
        body = res.json()
        assert body['ignored'] is False
        record = body['created_record']
        assert record['direction'] == 'expense'
        assert record['amount'] == 34.6
        assert record['category'] in ['餐饮', '购物', '其他']
        assert '零食' in record['summary']

        listed = client.get('/api/ledger/records').json()['items']
        assert len(listed) == 1
        assert listed[0]['amount'] == 34.6
    finally:
        os.unlink(path)


def test_ingest_qq_income_creates_income_record():
    client, path = make_client()
    try:
        res = client.post('/api/ledger/ingest/qq', json={
            'text': '今天工资到账 3500 元，记账',
            'sender': 'aton_puck'
        })
        assert res.status_code == 200
        record = res.json()['created_record']
        assert record['direction'] == 'income'
        assert record['amount'] == 3500
        assert record['category'] == '工资'
    finally:
        os.unlink(path)


def test_ingest_qq_ledger_deduplicates_same_message():
    client, path = make_client()
    try:
        payload = {'text': '奶茶 16 元，记账', 'sender': 'aton_puck'}
        first = client.post('/api/ledger/ingest/qq', json=payload)
        second = client.post('/api/ledger/ingest/qq', json=payload)
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()['ignored'] is True
        assert second.json()['ignored_reason'] == 'duplicate'
        listed = client.get('/api/ledger/records').json()['items']
        assert len(listed) == 1
    finally:
        os.unlink(path)


def test_ledger_dashboard_summary_and_breakdowns():
    client, path = make_client()
    try:
        client.post('/api/ledger/records', json={
            'raw_text': '午饭 20 元',
            'source': 'qq',
            'direction': 'expense',
            'category': '餐饮',
            'amount': 20,
            'summary': '午饭'
        })
        client.post('/api/ledger/records', json={
            'raw_text': '地铁 4 元',
            'source': 'qq',
            'direction': 'expense',
            'category': '交通',
            'amount': 4,
            'summary': '地铁'
        })
        client.post('/api/ledger/records', json={
            'raw_text': '兼职收入 100 元',
            'source': 'qq',
            'direction': 'income',
            'category': '兼职',
            'amount': 100,
            'summary': '兼职'
        })

        summary = client.get('/api/ledger/summary/today')
        assert summary.status_code == 200
        body = summary.json()
        assert body['date'] == date.today().isoformat()
        assert body['expense_total'] == 24
        assert body['income_total'] == 100
        assert body['net_total'] == 76
        assert body['expense_count'] == 2
        assert body['income_count'] == 1

        pie = client.get('/api/ledger/stats/category-breakdown?direction=expense&range=today')
        assert pie.status_code == 200
        pie_body = pie.json()
        assert pie_body['range'] == 'today'
        assert pie_body['label'] == '今日'
        items = pie_body['items']
        assert items[0]['category'] == '餐饮'
        assert items[0]['amount'] == 20
        assert items[1]['category'] == '交通'
        assert items[1]['amount'] == 4

        trend = client.get('/api/ledger/stats/daily?days=7')
        assert trend.status_code == 200
        assert len(trend.json()['days']) == 7
        assert trend.json()['days'][-1]['expense_total'] == 24
    finally:
        os.unlink(path)


def test_ledger_category_breakdown_custom_range_only_counts_selected_dates():
    client, path = make_client()
    try:
        client.post('/api/ledger/records', json={
            'raw_text': '今天午饭 20 元',
            'source': 'qq',
            'direction': 'expense',
            'category': '餐饮',
            'amount': 20,
            'summary': '午饭'
        })
        client.post('/api/ledger/records', json={
            'raw_text': '今天地铁 6 元',
            'source': 'qq',
            'direction': 'expense',
            'category': '交通',
            'amount': 6,
            'summary': '地铁'
        })
        yesterday = date.today().replace(day=date.today().day - 1).isoformat()
        client.post('/api/ledger/records', json={
            'raw_text': '昨天零食 34.6 元',
            'source': 'qq',
            'direction': 'expense',
            'category': '餐饮',
            'amount': 34.6,
            'summary': '零食'
        })
        from studyflow.app import connect
        conn = connect(path)
        conn.execute("UPDATE ledger_records SET created_at=? WHERE summary='零食'", (f"{yesterday}T12:00:00",))
        conn.commit()

        custom = client.get(f'/api/ledger/stats/category-breakdown?direction=expense&range=custom&start={yesterday}&end={yesterday}')
        assert custom.status_code == 200
        body = custom.json()
        assert body['range'] == 'custom'
        assert body['total_amount'] == 34.6
        assert len(body['items']) == 1
        assert body['items'][0]['category'] == '餐饮'
        assert body['items'][0]['amount'] == 34.6
    finally:
        os.unlink(path)


def test_ledger_monthly_summary_and_monthly_categories():
    client, path = make_client()
    try:
        current_month = date.today().strftime('%Y-%m')
        client.post('/api/ledger/records', json={
            'raw_text': '午饭 20 元',
            'source': 'qq',
            'direction': 'expense',
            'category': '餐饮',
            'amount': 20,
            'summary': '午饭'
        })
        client.post('/api/ledger/records', json={
            'raw_text': '地铁 6 元',
            'source': 'qq',
            'direction': 'expense',
            'category': '交通',
            'amount': 6,
            'summary': '地铁'
        })
        client.post('/api/ledger/records', json={
            'raw_text': '工资 5000 元',
            'source': 'qq',
            'direction': 'income',
            'category': '工资',
            'amount': 5000,
            'summary': '工资'
        })

        summary = client.get('/api/ledger/summary/month').json()
        assert summary['month'] == current_month
        assert summary['expense_total'] == 26
        assert summary['income_total'] == 5000
        assert summary['net_total'] == 4974
        assert summary['top_expense_category'] == '餐饮'

        categories = client.get('/api/ledger/stats/monthly-categories?direction=expense').json()
        assert categories['month'] == current_month
        assert categories['items'][0]['category'] == '餐饮'
        assert categories['items'][0]['amount'] == 20
        assert categories['items'][1]['category'] == '交通'
        assert categories['items'][1]['amount'] == 6
    finally:
        os.unlink(path)


def test_ledger_monthly_trend_and_clean_route():
    client, path = make_client()
    try:
        trend = client.get('/api/ledger/stats/monthly-overview?months=6')
        assert trend.status_code == 200
        body = trend.json()
        assert len(body['months']) == 6
        assert 'month' in body['months'][-1]
        assert 'expense_total' in body['months'][-1]

        ledger_page = client.get('/ledger')
        assert ledger_page.status_code == 200
        assert 'MoneyFlow' in ledger_page.text
    finally:
        os.unlink(path)


def test_ledger_ingest_ignores_non_bookkeeping_chat():
    client, path = make_client()
    try:
        res = client.post('/api/ledger/ingest/qq', json={
            'text': '晚上想吃什么呀',
            'sender': 'aton_puck'
        })
        assert res.status_code == 200
        body = res.json()
        assert body['ignored'] is True
        assert body['ignored_reason'] == 'not_ledger'
        assert body['created_record'] is None
    finally:
        os.unlink(path)
