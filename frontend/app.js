const API = window.location.origin;
const $ = s => document.querySelector(s);
const subjectPie = $('#subjectPie');
const emptyStateText = $('#emptyStateText');
const planList = $('#planList');
const countdownDays = $('#countdownDays');
const summaryText = $('#todaySummaryText');
const rangeButtons = [...document.querySelectorAll('[data-heat-mode]')];
const PLAN_STATE_KEY = 'studyflow-plan-manual-state-v1';
const DEFAULT_PLAN_EXAMPLE = [
  { title: '外刊一篇', completed: false },
  { title: '李林讲尖高数第一章', completed: true }
];
const REFERENCE_QUOTE = {
  text: '不要温和地走进那个良夜',
  source: '狄兰·托马斯《不要温和地走进那个良夜》'
};
const REFERENCE_COUNTDOWN_DAYS = 211;
const REFERENCE_SUMMARY_LINES = [
  '合计: 4h40min',
  '数学: 2h',
  '403: 1h',
  '英语: 30min',
  '政治: 10min'
];

let activeRange = 'today';

function resolveTheme(choice) {
  return choice === 'light' || choice === 'dark'
    ? choice
    : (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
}

function applyTheme(choice = 'auto') {
  document.documentElement.dataset.theme = choice;
  document.documentElement.dataset.resolvedTheme = resolveTheme(choice);
}

function renderReferenceQuote() {
  $('#dailyQuote').textContent = REFERENCE_QUOTE.text;
  $('#dailyQuoteSource').textContent = `—— ${REFERENCE_QUOTE.source}`;
}

function escapeHtml(v) {
  return String(v ?? '').replace(/[&<>"']/g, ch => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'": '&#039;' }[ch]));
}

async function api(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  });
  if (!res.ok) throw new Error(`${path} ${res.status}`);
  return res.json();
}

function renderReferenceCountdown() {
  countdownDays.textContent = String(REFERENCE_COUNTDOWN_DAYS);
}

function renderReferenceSummary() {
  summaryText.innerHTML = REFERENCE_SUMMARY_LINES.map(line => `<p>${escapeHtml(line)}</p>`).join('');
}

function renderReferencePie() {
  subjectPie.style.background = 'rgba(220, 205, 205, 0.42)';
  subjectPie.innerHTML = '';
  emptyStateText.textContent = '';
  emptyStateText.classList.remove('has-data');
}

function readPlanState() {
  try {
    const raw = localStorage.getItem(PLAN_STATE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function writePlanState(items) {
  localStorage.setItem(PLAN_STATE_KEY, JSON.stringify(items));
}

function normalizeReferenceTasks() {
  const saved = readPlanState();
  const savedMap = new Map(saved.map(item => [item.title, !!item.completed]));
  return DEFAULT_PLAN_EXAMPLE.map(item => ({
    title: item.title,
    completed: savedMap.has(item.title) ? savedMap.get(item.title) : item.completed
  }));
}

function renderPlan() {
  const items = normalizeReferenceTasks();
  writePlanState(items);

  const tasks = items.map((task, index) => {
    const done = !!task.completed;
    return `
      <article class="figma-task-item ${done ? 'is-done' : ''}" data-plan-title="${escapeHtml(task.title)}">
        <button class="figma-task-bullet ${done ? 'done' : ''}" type="button" data-plan-toggle="${index}" aria-pressed="${done ? 'true' : 'false'}" aria-label="${done ? '取消完成' : '标记完成'}：${escapeHtml(task.title)}">
          <span class="figma-task-bullet-ring"></span>
          <span class="figma-task-bullet-check">✓</span>
        </button>
        <div class="figma-task-text ${done ? 'done' : ''}">${escapeHtml(task.title)}</div>
      </article>
    `;
  }).join('');

  planList.className = 'task-list figma-task-list';
  planList.innerHTML = tasks;
}

function togglePlanItem(index) {
  const items = normalizeReferenceTasks();
  if (!items[index]) return;
  items[index].completed = !items[index].completed;
  writePlanState(items);
  renderPlan();
}

async function hydrateReferenceFromBackend() {
  await Promise.allSettled([
    api('/api/plans/today'),
    api('/api/stats/today-subjects')
  ]);
}

rangeButtons.forEach(button => {
  button.addEventListener('click', () => {
    activeRange = button.dataset.heatMode;
    rangeButtons.forEach(btn => btn.classList.toggle('active', btn === button));
  });
});

planList.addEventListener('click', event => {
  const button = event.target.closest('[data-plan-toggle]');
  if (!button) return;
  togglePlanItem(Number(button.dataset.planToggle));
});

matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  if ((localStorage.getItem('studyflow-theme') || 'auto') === 'auto') applyTheme('auto');
});

applyTheme(localStorage.getItem('studyflow-theme') || 'auto');
renderReferenceQuote();
renderReferenceCountdown();
renderReferenceSummary();
renderReferencePie();
renderPlan();
hydrateReferenceFromBackend().catch(() => {});
