const numericColumns = ['value_1', 'value_2', 'value_3', 'value_4'];
const shortlistKey = 'nba-tracker-shortlist';
const displayTimeZone = 'America/Chicago';
const colors = ['#6ee7f5', '#ffad66', '#92e6b5', '#ff8f91', '#c5a8ff', '#f6e58d'];

const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[char]));
const number = value => {
  if (value === '' || value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};
const fmt = value => {
  const parsed = number(value);
  if (parsed === null) return value || '—';
  return Math.abs(parsed) < 1 && parsed !== 0 ? parsed.toFixed(3) : parsed.toLocaleString(undefined, {maximumFractionDigits: 2});
};
const fmtScore = value => number(value) === null ? '—' : fmt(value);

function parseCSV(text) {
  const rows = [];
  let row = [], cell = '', quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i], next = text[i + 1];
    if (char === '"' && quoted && next === '"') { cell += '"'; i += 1; }
    else if (char === '"') quoted = !quoted;
    else if (char === ',' && !quoted) { row.push(cell); cell = ''; }
    else if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && next === '\n') i += 1;
      row.push(cell); cell = '';
      if (row.some(value => value !== '')) rows.push(row);
      row = [];
    } else cell += char;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  const headers = rows.shift() || [];
  return rows.map(values => Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ''])));
}

async function loadData() {
  async function load(path) {
    const primary = await fetch(`data/${path}`, {cache: 'no-store'});
    if (primary.ok) return primary;
    return fetch(`../data/${path}`, {cache: 'no-store'});
  }
  const [statusResponse, historyResponse] = await Promise.all([load('status.json'), load('history.csv')]);
  if (!statusResponse.ok || !historyResponse.ok) throw new Error('The data files could not be loaded. Run the pipeline once, then reload this page.');
  return {status: await statusResponse.json(), history: parseCSV(await historyResponse.text())};
}

function days(history) { return [...new Set(history.map(row => row.date).filter(Boolean))].sort(); }
function latestDay(history) { return days(history).at(-1) || ''; }
function previousDay(history, day) { return days(history).filter(value => value < day).at(-1) || ''; }
function key(row) { return `${row.source}:${row.item_id}`; }
function rowsFor(history, day) { return history.filter(row => row.date === day); }
function numericMove(oldRow, newRow) {
  if (!oldRow || !newRow) return Infinity;
  const scores = numericColumns.map(column => {
    const oldValue = number(oldRow[column]), newValue = number(newRow[column]);
    return oldValue !== null && newValue !== null && oldValue !== newValue ? Math.abs(newValue - oldValue) / Math.max(Math.abs(oldValue), 1) : 0;
  });
  return Math.max(...scores, 0);
}
function calculateMoves(previous, current, limit = 10) {
  const oldMap = Object.fromEntries(previous.map(row => [key(row), row]));
  const newMap = Object.fromEntries(current.map(row => [key(row), row]));
  return [...new Set([...Object.keys(oldMap), ...Object.keys(newMap)])].map(itemKey => {
    const oldRow = oldMap[itemKey], newRow = newMap[itemKey], score = numericMove(oldRow, newRow);
    return {key: itemKey, old: oldRow, new: newRow, score, kind: !oldRow ? 'new' : !newRow ? 'gone' : 'changed'};
  }).filter(move => move.score !== 0).sort((a, b) => b.score - a.score || a.key.localeCompare(b.key)).slice(0, limit);
}
function changeFor(row, previous) {
  const old = previous.find(candidate => key(candidate) === key(row));
  const score = numericMove(old, row);
  if (!old) return {label: 'NEW', className: 'new'};
  if (score === 0) return {label: '—', className: ''};
  const primaryOld = number(old.value_1), primaryNew = number(row.value_1);
  const direction = primaryOld !== null && primaryNew !== null && primaryNew >= primaryOld ? '↑' : '↓';
  return {label: `${direction} ${Math.round(score * 100)}%`, className: direction === '↑' ? 'up' : 'down'};
}
function metricLabels(row) {
  if (row.category === 'standings') return [['Wins', 'value_1'], ['Losses', 'value_2'], ['Win %', 'value_3'], ['Games behind', 'value_4']];
  if (row.category === 'game') return [['Home points', 'value_1'], ['Away points', 'value_2'], ['Margin', 'value_3'], ['Attendance', 'value_4']];
  return [['Metric 1', 'value_1'], ['Metric 2', 'value_2'], ['Metric 3', 'value_3'], ['Metric 4', 'value_4']];
}
function metricValue(row, column) {
  const value = number(row[column]);
  if (value === null) return '—';
  if (row.category === 'standings' && column === 'value_3') return `${(value * 100).toFixed(1)}%`;
  return fmt(value);
}
function metricMarkup(row) {
  return `<div class="metrics-cell">${metricLabels(row).filter(([, column]) => row[column] !== '').map(([label, column]) => `<span class="metric-chip"><b>${label}</b>${metricValue(row, column)}</span>`).join('')}</div>`;
}
function statusText(value) { return value ? '<span class="ok">OK</span>' : '<span class="bad">FAILED</span>'; }
function formatDateTime(value) {
  if (!value) return 'Not run yet';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat('en-US', {year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: displayTimeZone, timeZoneName: 'short'}).format(parsed);
}
function formatLocalDate(value) {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone: displayTimeZone}).format(parsed);
}
function showError(error) { const box = $('app-error'); if (box) { box.textContent = error.message || String(error); box.hidden = false; } }

function renderToday({status, history}) {
  const day = latestDay(history), current = rowsFor(history, day), previous = rowsFor(history, previousDay(history, day));
  $('last-run').textContent = formatDateTime(status.run_time);
  $('latest-day').textContent = `UTC archive: ${day || '—'} · Central date: ${formatLocalDate(status.run_time)}`;
  $('summary-cards').innerHTML = [
    ['Items today', status.items ?? current.length, `${status.new_today ?? 0} new · ${status.gone_today ?? 0} gone`],
    ['History days', status.days_with_success ?? days(history).length, 'days with at least one raw file'],
    ['Feeds healthy', `${(status.sources || []).filter(source => source.ok).length}/${(status.sources || []).length}`, 'source results this run'],
    ['Latest games', current.filter(row => row.category === 'game').length, 'scoreboard rows in the archive']
  ].map(([label, value, detail]) => `<div class="stat-card"><div class="label">${label}</div><div class="number">${escapeHTML(value)}</div><div class="detail">${detail}</div></div>`).join('');
  $('source-meta').textContent = `${status.sources?.length || 0} registered sources`;
  $('source-cards').innerHTML = (status.sources || []).map(source => `<article class="source-card"><div><h3>${escapeHTML(source.name.replaceAll('_', ' '))}</h3><p>${source.count} converted rows for ${day || 'the latest day'}</p></div><span class="source-state ${source.ok ? 'ok' : 'bad'}">${source.ok ? '● ok' : '● failed'}</span></article>`).join('');
  const latestRows = [...current].sort((a, b) => (a.category || '').localeCompare(b.category || '') || a.item.localeCompare(b.item)).slice(0, 60);
  $('latest-table').querySelector('tbody').innerHTML = latestRows.length ? latestRows.map(row => {
    const move = changeFor(row, previous);
    return `<tr><td>${escapeHTML(row.item)}</td><td class="muted">${escapeHTML(row.source.replaceAll('_', ' '))}</td><td>${metricMarkup(row)}</td><td><span class="movement ${move.className}">${move.label}</span></td></tr>`;
  }).join('') : '<tr><td colspan="4" class="muted">No rows have been collected yet.</td></tr>';
  const moves = calculateMoves(previous, current);
  $('moves-list').innerHTML = moves.length ? moves.map(move => {
    const row = move.new || move.old;
    return `<div class="move-row"><strong>${escapeHTML(row.item)}</strong><span class="move-kind">${move.kind}</span><span class="move-detail">${escapeHTML(move.old ? numericSummary(move.old) : '—')} → ${escapeHTML(move.new ? numericSummary(move.new) : '—')}</span></div>`;
  }).join('') : '<div class="notice">No numeric values moved relative to the previous collected day.</div>';
}
function numericSummary(row) { return metricLabels(row).filter(([, column]) => row[column] !== '').map(([label, column]) => `${label} ${metricValue(row, column)}`).join(' · '); }

function shortlist() { try { return new Set(JSON.parse(localStorage.getItem(shortlistKey) || '[]')); } catch (_) { return new Set(); } }
function saveShortlist(set) { localStorage.setItem(shortlistKey, JSON.stringify([...set])); }
function renderBrowse({status, history}) {
  const day = latestDay(history), current = rowsFor(history, day);
  $('browse-title').textContent = day ? `Collected ${day}` : 'No collection yet';
  const sourceFilter = $('source-filter'), categoryFilter = $('category-filter');
  [...new Set(current.map(row => row.source))].sort().forEach(source => sourceFilter.insertAdjacentHTML('beforeend', `<option value="${escapeHTML(source)}">${escapeHTML(source.replaceAll('_', ' '))}</option>`));
  [...new Set(current.map(row => row.category).filter(Boolean))].sort().forEach(category => categoryFilter.insertAdjacentHTML('beforeend', `<option value="${escapeHTML(category)}">${escapeHTML(category)}</option>`));
  const draw = () => {
    const term = $('search-input').value.trim().toLowerCase(), source = sourceFilter.value, category = categoryFilter.value, sort = $('sort-column').value, direction = $('sort-direction').value, onlyShortlist = $('shortlist-only').checked, saved = shortlist();
    let filtered = current.filter(row => (!term || row.item.toLowerCase().includes(term)) && (!source || row.source === source) && (!category || row.category === category) && (!onlyShortlist || saved.has(key(row))));
    filtered.sort((a, b) => {
      if (sort) return ((number(a[sort]) ?? -Infinity) - (number(b[sort]) ?? -Infinity)) * (direction === 'asc' ? 1 : -1);
      return a.item.localeCompare(b.item);
    });
    $('browse-count').textContent = `${filtered.length} of ${current.length} items`;
    $('browse-table').querySelector('tbody').innerHTML = filtered.length ? filtered.map(row => `<tr><td><button class="star ${saved.has(key(row)) ? 'saved' : ''}" data-key="${escapeHTML(key(row))}" aria-label="${saved.has(key(row)) ? 'Remove from shortlist' : 'Add to shortlist'}">${saved.has(key(row)) ? '★' : '☆'}</button></td><td>${escapeHTML(row.item)}</td><td class="muted">${escapeHTML(row.source.replaceAll('_', ' '))}</td><td class="muted">${escapeHTML(row.category)}</td><td>${metricMarkup(row)}</td><td class="muted">${escapeHTML(row.game_status)}</td></tr>`).join('') : '<tr><td colspan="6" class="muted">No items match these filters.</td></tr>';
    $('browse-table').querySelectorAll('.star').forEach(button => button.addEventListener('click', () => { const next = shortlist(); next.has(button.dataset.key) ? next.delete(button.dataset.key) : next.add(button.dataset.key); saveShortlist(next); draw(); }));
  };
  ['search-input', 'source-filter', 'category-filter', 'sort-column', 'sort-direction', 'shortlist-only'].forEach(id => $(id).addEventListener('input', draw));
  draw();
}

function chartSVG(series, options = {}) {
  const width = 720, height = options.height || 230, pad = {left: 42, right: 18, top: 18, bottom: 30};
  const allValues = series.flatMap(item => item.values.map(value => value).filter(value => value !== null));
  if (!allValues.length) return '<div class="chart-empty">Not enough numeric observations for this chart yet.</div>';
  const min = Math.min(...allValues), max = Math.max(...allValues), span = max - min || 1, count = Math.max(...series.map(item => item.values.length), 1);
  const x = index => pad.left + index * ((width - pad.left - pad.right) / Math.max(count - 1, 1));
  const y = value => height - pad.bottom - ((value - min) / span) * (height - pad.top - pad.bottom);
  const lines = series.map((item, itemIndex) => {
    const points = item.values.map((value, index) => value === null ? null : `${x(index)},${y(value)}`).filter(Boolean).join(' ');
    const dots = item.values.map((value, index) => value === null ? '' : `<circle cx="${x(index)}" cy="${y(value)}" r="3" fill="${colors[itemIndex % colors.length]}"/>`).join('');
    return `<polyline points="${points}" fill="none" stroke="${colors[itemIndex % colors.length]}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>${dots}`;
  }).join('');
  const labels = (options.labels || []).map((label, index) => index % Math.ceil((options.labels || []).length / 6 || 1) === 0 ? `<text x="${x(index)}" y="${height - 8}" fill="#91a3bb" font-size="10" text-anchor="middle">${label.slice(5)}</text>` : '').join('');
  const legend = series.map((item, index) => `<text x="${pad.left + index * 125}" y="12" fill="${colors[index % colors.length]}" font-size="10">${escapeHTML(item.name).slice(0, 18)}</text>`).join('');
  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Trend chart"><line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${height-pad.bottom}" stroke="#2a405c"/><line x1="${pad.left}" y1="${height-pad.bottom}" x2="${width-pad.right}" y2="${height-pad.bottom}" stroke="#2a405c"/><text x="8" y="${pad.top+4}" fill="#91a3bb" font-size="10">${fmt(max)}</text><text x="8" y="${height-pad.bottom}" fill="#91a3bb" font-size="10">${fmt(min)}</text>${legend}${lines}${labels}</svg>`;
}
function barSVG(labels, values, color = '#6ee7f5') {
  const width = 520, height = 160, max = Math.max(...values, 1), barWidth = Math.max(8, (width - 30) / Math.max(values.length, 1) - 8);
  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Bar chart">${values.map((value, index) => { const x = 15 + index * ((width - 30) / values.length), h = (value / max) * 110; return `<rect x="${x}" y="${130-h}" width="${barWidth}" height="${h}" rx="3" fill="${color}" opacity=".9"/><text x="${x+barWidth/2}" y="${124-h}" fill="#edf4ff" font-size="10" text-anchor="middle">${fmt(value)}</text><text x="${x+barWidth/2}" y="148" fill="#91a3bb" font-size="9" text-anchor="middle">${escapeHTML(labels[index]).slice(0, 10)}</text>`; }).join('')}</svg>`;
}
function renderTrends({history}) {
  const dateList = days(history), latest = dateList.at(-1) || '';
  $('trend-days').textContent = `${dateList.length} collected day${dateList.length === 1 ? '' : 's'}`;
  const current = rowsFor(history, latest), teams = current.filter(row => row.category === 'standings').sort((a,b) => (number(b.value_1)||0)-(number(a.value_1)||0));
  const picker = $('trend-items');
  teams.slice(0, 8).forEach(team => picker.insertAdjacentHTML('beforeend', `<option value="${escapeHTML(key(team))}" selected>${escapeHTML(team.item)}</option>`));
  const drawCustom = () => {
    const selected = [...picker.selectedOptions].map(option => option.value), column = $('trend-column').value;
    const series = selected.map(itemKey => { const row = teams.find(team => key(team) === itemKey) || current.find(row => key(row) === itemKey); return row ? {name: row.item, values: dateList.map(day => number(history.find(candidate => candidate.date === day && key(candidate) === itemKey)?.[column]))} : null; }).filter(Boolean);
    $('trend-chart').innerHTML = chartSVG(series, {labels: dateList});
  };
  picker.addEventListener('change', drawCustom); $('trend-column').addEventListener('change', drawCustom); drawCustom();
  const standingsByDay = dateList.map(day => rowsFor(history, day).filter(row => row.category === 'standings'));
  const spread = standingsByDay.map(rows => { const values = rows.map(row => number(row.value_1)).filter(value => value !== null); return values.length ? Math.max(...values) - Math.min(...values) : null; });
  const avgPct = standingsByDay.map(rows => { const values = rows.map(row => number(row.value_3)).filter(value => value !== null); return values.length ? values.reduce((a,b) => a+b, 0) / values.length : null; });
  const maxMargin = dateList.map(day => { const values = rowsFor(history, day).filter(row => row.category === 'game').map(row => Math.abs(number(row.value_3))).filter(value => value !== null); return values.length ? Math.max(...values) : null; });
  const currentWins = teams.slice(0, 5).map(team => number(team.value_1) || 0);
  const cards = [
    {title: `${teams[0]?.item || 'The league'} leads the latest standings`, text: `The top team has ${fmt(teams[0]?.value_1)} wins and ${fmt(teams[0]?.value_2)} losses. This is the latest-day standings row, not a projection.`, chart: barSVG(teams.slice(0, 5).map(team => team.team_abbreviation || team.item), currentWins), method: 'Computed from the latest-day standings rows, sorted by wins.'},
    {title: `The standings spread is ${fmt(spread.at(-1))} wins`, text: `The gap between the most and least wins currently represented in the standings is ${fmt(spread.at(-1))}.`, chart: chartSVG([{name: 'win spread', values: spread}], {labels: dateList}), method: 'For each date, the most wins minus the fewest wins across teams.'},
    {title: `The largest latest game margin is ${fmt(maxMargin.at(-1))} points`, text: `The biggest absolute home-margin value in the latest scoreboard snapshot is ${fmt(maxMargin.at(-1))} points.`, chart: chartSVG([{name: 'max margin', values: maxMargin}], {labels: dateList}), method: 'For each date, take the largest absolute margin among games.'},
    {title: `Average win percentage is ${avgPct.at(-1) === null ? 'not available' : (avgPct.at(-1) * 100).toFixed(1) + '%'}`, text: `Across teams represented in the latest standings snapshot, the mean win percentage is ${avgPct.at(-1) === null ? 'not available yet' : (avgPct.at(-1) * 100).toFixed(1) + '%'}.`, chart: chartSVG([{name: 'average win %', values: avgPct}], {labels: dateList}), method: 'For each date, average the teams’ win percentages.'}
  ];
  $('findings').innerHTML = cards.map(card => `<article class="finding-card"><p class="eyebrow">FINDING</p><h3>${escapeHTML(card.title)}</h3><p>${escapeHTML(card.text)} <span class="muted">${escapeHTML(card.method)}</span></p>${card.chart}</article>`).join('');
}

async function start() {
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
  try {
    const data = await loadData();
    const page = document.body.dataset.page;
    if (page === 'today') renderToday(data);
    if (page === 'browse') renderBrowse(data);
    if (page === 'trends') renderTrends(data);
  } catch (error) { showError(error); }
}
start();
