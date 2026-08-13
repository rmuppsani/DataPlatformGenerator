const $ = (id) => document.getElementById(id);
const money = (value) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value || 0);
const number = (value) => new Intl.NumberFormat('en-IN').format(value || 0);

function showToast(message) {
  const toast = $('toast');
  toast.textContent = message;
  toast.classList.add('show');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove('show'), 3200);
}

function renderActivity(events) {
  const list = $('activity-list');
  if (!events || !events.length) {
    list.innerHTML = '<div class="empty">No activity yet.</div>';
    return;
  }
  list.innerHTML = events.map((item) => {
    const status = item.status || 'completed';
    const time = new Date(item.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return `<div class="activity-item"><span class="activity-dot ${status}"></span><div><b>${item.message}</b><small>${time} · ${status.toUpperCase()}</small>${item.detail ? `<p>${item.detail}</p>` : ''}</div></div>`;
  }).join('');
}

function render(data) {
  $('total-sales').textContent = money(data.metrics.total_sales);
  $('clean-records').textContent = number(data.metrics.clean_records);
  $('products').textContent = number(data.metrics.products);
  $('check-count').textContent = '4 checks';
  Object.entries(data.layers).forEach(([layer, details]) => {
    const status = $(layer + '-status');
    status.textContent = details.status.toUpperCase();
    status.className = `layer-status ${details.status}`;
    $(layer + '-meta').textContent = `${details.files} file${details.files === 1 ? '' : 's'} · ${number(details.records)} records`;
  });
  const body = $('summary-body');
  body.innerHTML = data.summary.length ? data.summary.map((row) => `<tr><td>${row.Product_Name || 'Unknown'}</td><td>${number(Number(row.Total_Quantity))}</td><td class="right">${money(Number(row.Total_Sales))}</td></tr>`).join('') : '<tr><td colspan="3" class="empty">Run the pipeline to populate Gold output.</td></tr>';
  renderActivity(data.events);
  $('last-sync').textContent = `Updated ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
}

async function refresh() {
  try {
    const response = await fetch('/api/status');
    if (!response.ok) throw new Error('Status unavailable');
    render(await response.json());
  } catch (error) {
    showToast('Could not connect to dashboard server.');
  }
}

async function runPipeline() {
  const button = $('run-btn');
  const file = $('source-file').files[0];
  const form = new FormData();
  if (file) form.append('source', file);
  button.disabled = true;
  button.innerHTML = '<span class="play">◌</span> Running…';
  $('run-note').textContent = 'Processing Bronze → Silver → Gold…';
  try {
    const response = await fetch('/api/run', { method: 'POST', body: form });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Pipeline failed');
    render(payload);
    showToast('Pipeline completed successfully.');
    $('run-note').textContent = 'Latest run completed and outputs were refreshed.';
  } catch (error) {
    showToast(error.message);
    $('run-note').textContent = 'Run failed. Check the activity log.';
    await refresh();
  } finally {
    button.disabled = false;
    button.innerHTML = '<span class="play">▶</span> Run pipeline';
  }
}

$('source-file').addEventListener('change', (event) => {
  const file = event.target.files[0];
  $('file-label').textContent = file ? file.name : 'Choose a source file';
});
$('run-btn').addEventListener('click', runPipeline);
$('refresh-btn').addEventListener('click', refresh);
refresh();
