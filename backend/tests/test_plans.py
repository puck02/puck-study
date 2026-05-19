import os
import tempfile
from fastapi.testclient import TestClient
from studyflow.app import create_app


def client():
    tmp=tempfile.NamedTemporaryFile(delete=False); tmp.close()
    return TestClient(create_app(db_path=tmp.name)), tmp.name


def test_generate_today_plan_and_mark_task_done():
    c,p=client()
    try:
        res=c.post('/api/plans/today/generate', json={'mode':'standard'})
        assert res.status_code==200
        plan=res.json()
        assert plan['mode']=='standard'
        assert len(plan['tasks'])>=2
        task_id=plan['tasks'][0]['id']
        done=c.patch(f'/api/tasks/{task_id}', json={'status':'done'}).json()
        assert done['status']=='done'
        today=c.get('/api/plans/today').json()
        assert any(t['id']==task_id and t['status']=='done' for t in today['tasks'])
    finally:
        os.unlink(p)


def test_downgrade_and_upgrade_today_plan():
    c,p=client()
    try:
        c.post('/api/plans/today/generate', json={'mode':'standard'})
        assert c.post('/api/plans/today/downgrade').json()['mode']=='minimal'
        assert c.post('/api/plans/today/upgrade').json()['mode']=='extra'
    finally:
        os.unlink(p)
