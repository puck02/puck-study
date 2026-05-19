import os
import tempfile
from fastapi.testclient import TestClient
from studyflow.app import create_app


def client():
    tmp=tempfile.NamedTemporaryFile(delete=False); tmp.close()
    return TestClient(create_app(db_path=tmp.name)), tmp.name


def test_heatmap_weekly_report_and_exports():
    c,p=client()
    try:
        c.post('/api/events', json={'raw_text':'数学30分钟','subject':'数学','duration_minutes':30})
        c.post('/api/events', json={'raw_text':'英语45分钟','subject':'英语','duration_minutes':45})
        heat=c.get('/api/stats/heatmap?days=7&subject=all').json()
        assert len(heat['days'])==7
        assert heat['days'][-1]['total_minutes']==75
        assert heat['days'][-1]['level']==2
        report=c.post('/api/reports/weekly/generate').json()
        assert report['total_minutes']==75
        assert report['subject_breakdown']['数学']==30
        assert c.get('/api/export/events.json').json()['items']
        csv=c.get('/api/export/events.csv')
        assert csv.status_code==200 and 'raw_text' in csv.text
        md=c.get('/api/export/report.md')
        assert md.status_code==200 and 'StudyFlow' in md.text
    finally:
        os.unlink(p)
