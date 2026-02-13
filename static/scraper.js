let currentJobId = null;
let eventSource = null;

document.addEventListener('DOMContentLoaded', () => {
    loadRetailers();
    document.getElementById('selectAll').addEventListener('click', () => toggleAll(true));
    document.getElementById('deselectAll').addEventListener('click', () => toggleAll(false));
});

async function loadRetailers() {
    try {
        const res = await fetch('/api/retailers');
        const data = await res.json();
        const grid = document.getElementById('retailerGrid');
        grid.innerHTML = '';

        data.retailers.forEach(name => {
            const item = document.createElement('div');
            item.className = 'retailer-item checked';

            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.checked = true;
            cb.id = `cb-${name.replace(/[^a-zA-Z0-9]/g, '')}`;
            cb.value = name;
            cb.addEventListener('change', () => {
                item.classList.toggle('checked', cb.checked);
            });

            const label = document.createElement('label');
            label.textContent = name;
            label.htmlFor = cb.id;

            item.addEventListener('click', (e) => {
                if (e.target !== cb) {
                    cb.checked = !cb.checked;
                    cb.dispatchEvent(new Event('change'));
                }
            });

            item.appendChild(cb);
            item.appendChild(label);
            grid.appendChild(item);
        });
    } catch (e) {
        console.error('Failed to load retailers:', e);
    }
}

function toggleAll(checked) {
    document.querySelectorAll('.retailer-item input[type="checkbox"]').forEach(cb => {
        cb.checked = checked;
        cb.closest('.retailer-item').classList.toggle('checked', checked);
    });
}

function getSelectedRetailers() {
    return Array.from(
        document.querySelectorAll('.retailer-item input[type="checkbox"]:checked')
    ).map(cb => cb.value);
}

async function startScraping() {
    const keyword = document.getElementById('keyword').value.trim();
    const retailers = getSelectedRetailers();

    if (!keyword) { alert('Please enter a keyword.'); return; }
    if (retailers.length === 0) { alert('Please select at least one retailer.'); return; }

    const btn = document.getElementById('startBtn');
    btn.disabled = true;
    btn.textContent = 'Scraping...';

    // Show progress section
    const progressSection = document.getElementById('progressSection');
    progressSection.classList.add('active');
    document.getElementById('logContainer').innerHTML = '';
    document.getElementById('progressBar').style.width = '0%';
    document.getElementById('progressPct').textContent = '0%';
    document.getElementById('downloadSection').classList.remove('active');

    try {
        const res = await fetch('/api/product-scrape', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keyword, retailers }),
        });
        const data = await res.json();

        if (data.error) {
            addLog(data.error, 'fail');
            btn.disabled = false;
            btn.textContent = 'Start Scraping';
            return;
        }

        currentJobId = data.job_id;
        connectSSE(data.job_id);
    } catch (e) {
        addLog('Failed to start scraping: ' + e.message, 'fail');
        btn.disabled = false;
        btn.textContent = 'Start Scraping';
    }
}

function connectSSE(jobId) {
    if (eventSource) eventSource.close();

    eventSource = new EventSource(`/api/progress/${jobId}`);

    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);

        switch (data.type) {
            case 'log':
                let cls = 'info';
                if (data.message.includes('[OK]')) cls = 'ok';
                else if (data.message.includes('[FAIL]') || data.message.includes('Error')) cls = 'fail';
                else if (data.message.startsWith('DONE')) cls = 'ok';
                addLog(data.message, cls);
                break;

            case 'progress':
                const pct = data.percent;
                document.getElementById('progressBar').style.width = pct + '%';
                document.getElementById('progressPct').textContent = pct + '%';
                break;

            case 'completed':
                eventSource.close();
                document.getElementById('progressBar').style.width = '100%';
                document.getElementById('progressPct').textContent = '100%';

                const btn = document.getElementById('startBtn');
                btn.disabled = false;
                btn.textContent = 'Start Scraping';

                if (data.has_file || (data.summary && data.summary.total > 0)) {
                    const dl = document.getElementById('downloadSection');
                    dl.classList.add('active');
                    document.getElementById('downloadBtn').href = `/api/download/${jobId}?format=csv`;
                    document.getElementById('downloadSummary').textContent =
                        `${data.summary.total} products scraped`;
                }
                break;

            case 'error':
                eventSource.close();
                addLog('Error: ' + data.message, 'fail');
                const errBtn = document.getElementById('startBtn');
                errBtn.disabled = false;
                errBtn.textContent = 'Start Scraping';
                break;
        }
    };

    eventSource.onerror = () => {
        eventSource.close();
    };
}

function addLog(message, cls = '') {
    const container = document.getElementById('logContainer');
    const entry = document.createElement('div');
    entry.className = 'log-entry' + (cls ? ' ' + cls : '');
    entry.textContent = message;
    container.appendChild(entry);
    container.scrollTop = container.scrollHeight;
}
