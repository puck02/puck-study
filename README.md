# StudyFlow

QQ 无感化在职考研 / AI 学习助手 + Web 可视化驾驶舱。

## v0.1 目标

- QQ/手动 API 写入自然语言学习记录
- 后端 SQLite 持久化
- Web Dashboard 展示今日学习、计划、错题/复盘队列
- 主题支持 auto / light / dark，默认跟随系统偏好，用户可手动覆盖

## 后续路线

稳定版路线图见：[`docs/roadmap-v0.2-v0.6.md`](docs/roadmap-v0.2-v0.6.md)

核心方向：QQ 无感记录 → 自适应每日计划 + Puck Todo 同步 → 错题模式合并 → GitHub-style 热力图 + 周报趋势分析 → 稳定部署/备份/导出。

## 技术栈

- Backend: FastAPI + SQLite
- Frontend: 静态 HTML/CSS/JS（轻量、低内存）
- Deploy: uvicorn + 静态页面
