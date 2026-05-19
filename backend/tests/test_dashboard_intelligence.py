import os
import tempfile
from datetime import date
from fastapi.testclient import TestClient

from studyflow.app import create_app


def client():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    app = create_app(path)
    return TestClient(app), path


def post_event(c, raw_text, subject, minutes):
    return c.post('/api/events', json={
        'raw_text': raw_text,
        'source': 'test',
        'category': 'study',
        'subject': subject,
        'summary': raw_text,
        'duration_minutes': minutes,
    })


def test_heatmap_default_is_recent_five_months_and_supports_year_expand():
    c, _ = client()
    default = c.get('/api/stats/heatmap').json()
    assert default['range']['mode'] == 'recent_months'
    assert default['range']['months'] == 5
    assert 140 <= len(default['days']) <= 155
    assert len(default['months']) <= 5

    year = c.get('/api/stats/heatmap?mode=year').json()
    assert year['range']['mode'] == 'year'
    assert len(year['days']) in (365, 366)
    assert len(year['months']) == 12


def test_heatmap_supports_month_range_and_month_stats():
    c, _ = client()
    today = date.today()
    month = today.strftime('%Y-%m')
    post_event(c, '数学学习60分钟', '数学', 60)
    post_event(c, '英语学习30分钟', '英语', 30)

    data = c.get(f'/api/stats/heatmap?start_month={month}&end_month={month}').json()
    assert data['range']['start_month'] == month
    assert data['range']['end_month'] == month
    assert data['months'][0]['month'] == month
    assert data['months'][0]['total_minutes'] == 90
    assert data['months'][0]['active_days'] == 1
    assert data['months'][0]['avg_minutes_per_day'] > 0


def test_today_subject_distribution_is_limited_to_11408_subjects():
    c, _ = client()
    post_event(c, '数学学习60分钟', '数学', 60)
    post_event(c, '英语学习30分钟', '英语', 30)
    post_event(c, '408学习45分钟', '专业课', 45)
    post_event(c, '政治学习15分钟', '政治', 15)
    data = c.get('/api/stats/today-subjects').json()
    assert data['total_minutes'] == 150
    labels = [i['subject'] for i in data['items']]
    assert labels == ['数学', '英语', '408', '政治']
    assert sum(i['minutes'] for i in data['items']) == 150
    assert all('percent' in i for i in data['items'])


def test_weekly_report_has_pretty_markdown_for_sunday_delivery():
    c, _ = client()
    post_event(c, '数学学习60分钟', '数学', 60)
    post_event(c, '408学习45分钟', '专业课', 45)
    report = c.post('/api/reports/weekly/generate').json()
    assert 'markdown' in report
    md = report['markdown']
    assert '## StudyFlow 周报' in md
    assert '本周总学习' in md
    assert '科目分布' in md
    assert '下周策略' in md
    assert '408' in md
