import os
import tempfile
from fastapi.testclient import TestClient
from studyflow.app import create_app


def client():
    tmp=tempfile.NamedTemporaryFile(delete=False); tmp.close()
    return TestClient(create_app(db_path=tmp.name)), tmp.name


def test_mistake_triage_review_and_pattern_consolidation():
    c,p=client()
    try:
        created=c.post('/api/mistakes', json={
            'subject':'数学','raw_text':'极限换元又错了','knowledge_point':'极限换元','mistake_reason':'换元条件不熟'
        }).json()
        mid=created['id']
        assert created['status']=='candidate'
        promoted=c.post(f'/api/mistakes/{mid}/promote', json={'status':'full_card'}).json()
        assert promoted['status']=='full_card'
        reviewed=c.post(f'/api/mistakes/{mid}/reviewed').json()
        assert reviewed['review_count']==1
        pattern=c.post('/api/mistake-patterns/consolidate').json()['items'][0]
        assert pattern['subject']=='数学'
        assert pattern['evidence_count']>=1
    finally:
        os.unlink(p)
