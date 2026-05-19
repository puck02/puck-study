import os
import tempfile
from fastapi.testclient import TestClient
from studyflow.app import create_app


def client():
    tmp=tempfile.NamedTemporaryFile(delete=False); tmp.close()
    return TestClient(create_app(db_path=tmp.name)), tmp.name


def test_duplicate_qq_message_is_ignored_with_reason_and_hash():
    c,p=client()
    try:
        payload={'text':'今天数学刷题40分钟，错在导数单调性','sender':'aton_puck'}
        first=c.post('/api/ingest/qq', json=payload).json()
        second=c.post('/api/ingest/qq', json=payload).json()
        assert first['ignored'] is False
        assert first['created_event']['source_hash']
        assert second['ignored'] is True
        assert second['ignored_reason']=='duplicate'
        assert c.get('/api/events').json()['items'][0]['source_hash']==first['created_event']['source_hash']
    finally:
        os.unlink(p)
