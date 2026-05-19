import os
import tempfile

from fastapi.testclient import TestClient

from studyflow.app import create_app


def make_client():
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    app = create_app(db_path=tmp.name)
    return TestClient(app), tmp.name


def test_health_reports_ok_and_service_name():
    client, path = make_client()
    try:
        res = client.get('/api/health')
        assert res.status_code == 200
        body = res.json()
        assert body['ok'] is True
        assert body['service'] == 'studyflow'
    finally:
        os.unlink(path)


def test_create_event_persists_and_lists_back():
    client, path = make_client()
    try:
        payload = {
            'raw_text': '今天背了考研英语单词 40 分钟，错了 abandon 的用法',
            'source': 'qq',
            'category': 'study',
            'subject': '考研英语',
            'summary': '背单词 40 分钟，记录 abandon 用法错误',
            'duration_minutes': 40,
            'difficulty': 'medium',
            'tags': ['英语', '单词']
        }
        created = client.post('/api/events', json=payload)
        assert created.status_code == 200
        event = created.json()
        assert event['id'] == 1
        assert event['raw_text'] == payload['raw_text']
        assert event['source'] == 'qq'
        assert event['tags'] == ['英语', '单词']

        listed = client.get('/api/events')
        assert listed.status_code == 200
        items = listed.json()['items']
        assert len(items) == 1
        assert items[0]['summary'] == payload['summary']
    finally:
        os.unlink(path)


def test_today_summary_aggregates_minutes_and_count():
    client, path = make_client()
    try:
        client.post('/api/events', json={
            'raw_text': '数学刷题 30 分钟',
            'category': 'study',
            'subject': '数学',
            'duration_minutes': 30
        })
        client.post('/api/events', json={
            'raw_text': '英语复盘 20 分钟',
            'category': 'review',
            'subject': '英语',
            'duration_minutes': 20
        })
        res = client.get('/api/summary/today')
        assert res.status_code == 200
        body = res.json()
        assert body['event_count'] == 2
        assert body['total_minutes'] == 50
        assert body['by_subject']['数学'] == 30
        assert body['by_subject']['英语'] == 20
    finally:
        os.unlink(path)
