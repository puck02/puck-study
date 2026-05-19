# StudyFlow v0.1 Architecture

## Product idea

StudyFlow 是一个“QQ 自然输入 + 网站可视化”的低摩擦学习系统。
用户不需要维护表格；助手从自然语言中提取学习事件、计划、错题和复盘。

## Data model

### study_events
- id
- created_at
- source: qq/manual/api
- raw_text
- category: study/mistake/review/plan/reflection
- subject
- summary
- duration_minutes
- difficulty: easy/medium/hard/unknown
- tags JSON

### review_items
- id
- created_at
- event_id
- question
- answer
- status: active/reviewed/archived
- next_review_at

## API

- GET /api/health
- POST /api/events
- GET /api/events
- GET /api/summary/today
- POST /api/review-items
- GET /api/review-items

## Frontend

- Dashboard cards: 今日概览、最近记录、复习队列、计划入口
- Theme mode: auto/light/dark
- Theme preference stored in localStorage
