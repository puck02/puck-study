import os
import tempfile

from fastapi.testclient import TestClient

from studyflow.app import create_app


def make_client():
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    app = create_app(db_path=tmp.name)
    return TestClient(app), tmp.name


def test_ingest_qq_text_extracts_minutes_subject_and_review_item():
    client, path = make_client()
    try:
        res = client.post('/api/ingest/qq', json={
            'text': '今天考研数学刷题45分钟，错在极限换元，晚上要复盘',
            'sender': 'aton_puck'
        })
        assert res.status_code == 200
        body = res.json()
        assert body['created_event']['source'] == 'qq'
        assert body['created_event']['subject'] == '数学'
        assert body['created_event']['duration_minutes'] == 45
        assert body['created_event']['category'] == 'mistake'
        assert body['created_review_item']['status'] == 'active'
        assert '极限换元' in body['created_review_item']['question']

        summary = client.get('/api/summary/today').json()
        assert summary['event_count'] == 1
        assert summary['total_minutes'] == 45
    finally:
        os.unlink(path)


def test_ingest_qq_text_ignores_non_study_chat():
    client, path = make_client()
    try:
        res = client.post('/api/ingest/qq', json={
            'text': '今天晚饭吃啥啊',
            'sender': 'aton_puck'
        })
        assert res.status_code == 200
        body = res.json()
        assert body['created_event'] is None
        assert body['created_review_item'] is None
        assert body['ignored'] is True
    finally:
        os.unlink(path)
