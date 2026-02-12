// ─── State ────────────────────────────────────────────────────────────────

let currentJobId = null;
let eventSource = null;

// ─── Category Presets ────────────────────────────────────────────────────

const CATEGORY_EMOJIS = {
    'restaurant': '🍽️',
    'things-to-do': '🎯',
    'spa': '💆',
    'hotel': '🏨',
    'guest-house': '🏠',
    'nightlife': '🌙',
    'coworking': '💻',
    'gym': '💪',
    'shopping': '🛍️',
    'health': '🏥',
};

const DEFAULT_CATEGORIES = [
    'restaurant', 'things-to-do', 'spa', 'hotel', 'guest-house'
];

// ─── Init ─────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    loadPresets();
    setupEventListeners();
});

async function loadPresets() {
    try {
        const resp = await fetch('/api/presets');
        const data = await resp.json();
        renderCategories(data.presets, data.defaults);
    } catch (e) {
        // Fallback: render from known names
        const presets = {};
        Object.keys(CATEGORY_EMOJIS).forEach(k => {
            presets[k] = { category: k.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) };
        });
        renderCategories(presets, DEFAULT_CATEGORIES);
    }
}

function renderCategories(presets, defaults) {
    const grid = document.getElementById('categoriesGrid');
    grid.innerHTML = '';

    Object.keys(presets).forEach(key => {
        const preset = presets[key];
        const label = preset.category || key.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        const emoji = CATEGORY_EMOJIS[key] || '📍';
        const checked = defaults.includes(key) ? 'checked' : '';

        const chip = document.createElement('div');
        chip.className = 'category-chip';
        chip.innerHTML = `
            <input type="checkbox" id="cat-${key}" name="categories" value="${key}" ${checked}>
            <label for="cat-${key}">
                <span class="category-emoji">${emoji}</span>
                ${label}
            </label>
        `;
        grid.appendChild(chip);
    });
}

// ─── Event Listeners ─────────────────────────────────────────────────────

function setupEventListeners() {
    // Form submit
    document.getElementById('scrapeForm').addEventListener('submit', handleSubmit);

    // API key toggle
    document.getElementById('toggleApiKey').addEventListener('click', () => {
        const input = document.getElementById('apiKey');
        input.type = input.type === 'password' ? 'text' : 'password';
    });

    // Radius slider
    const radiusSlider = document.getElementById('radius');
    const radiusValue = document.getElementById('radiusValue');
    radiusSlider.addEventListener('input', () => {
        const val = parseInt(radiusSlider.value);
        if (val >= 1000) {
            radiusValue.textContent = (val / 1000).toFixed(val % 1000 === 0 ? 0 : 1) + ' km';
        } else {
            radiusValue.textContent = val + 'm';
        }
    });

    // New scrape button
    document.getElementById('newScrapeBtn').addEventListener('click', resetToForm);
    document.getElementById('errorRetryBtn').addEventListener('click', resetToForm);
}

// ─── Form Submission ─────────────────────────────────────────────────────

async function handleSubmit(e) {
    e.preventDefault();

    const apiKey = document.getElementById('apiKey').value.trim();
    const location = document.getElementById('location').value.trim();
    const radius = parseInt(document.getElementById('radius').value);
    const customQueries = document.getElementById('customQueries').value.trim();

    // Get selected categories
    const checkboxes = document.querySelectorAll('input[name="categories"]:checked');
    const categories = Array.from(checkboxes).map(cb => cb.value);

    // Validate
    if (!apiKey) { alert('Please enter your Google API key.'); return; }
    if (!location) { alert('Please enter a location.'); return; }
    if (categories.length === 0 && !customQueries) {
        alert('Please select at least one category or enter a custom query.');
        return;
    }

    // Disable form & show progress
    const submitBtn = document.getElementById('submitBtn');
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner"></span> Starting...';

    try {
        const resp = await fetch('/api/scrape', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                api_key: apiKey,
                location: location,
                radius: radius,
                categories: categories,
                custom_queries: customQueries,
            }),
        });

        const data = await resp.json();

        if (!resp.ok) {
            throw new Error(data.error || 'Failed to start scraping');
        }

        currentJobId = data.job_id;
        showProgressPanel();
        connectSSE(data.job_id);

    } catch (err) {
        showError(err.message);
        submitBtn.disabled = false;
        submitBtn.innerHTML = `
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
            Start Scraping
        `;
    }
}

// ─── SSE Progress ────────────────────────────────────────────────────────

function connectSSE(jobId) {
    if (eventSource) {
        eventSource.close();
    }

    eventSource = new EventSource(`/api/progress/${jobId}`);

    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);

        switch (data.type) {
            case 'log':
                addLogLine(data.message);
                document.getElementById('statusLine').textContent = data.message;
                break;

            case 'progress':
                updateProgressBar(data.percent);
                break;

            case 'completed':
                eventSource.close();
                eventSource = null;
                updateProgressBar(100);
                showResults(data.summary, data.has_file);
                break;

            case 'error':
                eventSource.close();
                eventSource = null;
                showError(data.message);
                break;
        }
    };

    eventSource.onerror = () => {
        eventSource.close();
        eventSource = null;
        // Don't show error if we already completed
        const progressPanel = document.getElementById('progressPanel');
        if (!progressPanel.classList.contains('hidden')) {
            showError('Connection lost. The scrape may still be running.');
        }
    };
}

// ─── UI Updates ──────────────────────────────────────────────────────────

function showProgressPanel() {
    document.getElementById('scrapeForm').classList.add('hidden');
    document.getElementById('progressPanel').classList.remove('hidden');
    document.getElementById('resultsPanel').classList.add('hidden');
    document.getElementById('errorPanel').classList.add('hidden');

    // Reset
    document.getElementById('logContent').innerHTML = '';
    document.getElementById('progressBar').style.width = '0%';
    document.getElementById('progressPercent').textContent = '0%';
    document.getElementById('progressTitle').textContent = 'Scraping in progress...';
    document.getElementById('statusLine').textContent = 'Initializing...';
}

function updateProgressBar(percent) {
    const bar = document.getElementById('progressBar');
    const pctText = document.getElementById('progressPercent');
    bar.style.width = percent + '%';
    pctText.textContent = percent + '%';
}

function addLogLine(message) {
    const container = document.getElementById('logContent');
    const line = document.createElement('div');
    line.className = 'log-line';
    line.textContent = message;
    container.appendChild(line);

    // Auto-scroll to bottom
    const logContainer = document.getElementById('logContainer');
    logContainer.scrollTop = logContainer.scrollHeight;
}

function showResults(summary, hasFile) {
    document.getElementById('progressTitle').textContent = 'Scraping complete!';
    document.getElementById('statusLine').textContent = 'All done!';
    document.getElementById('statusLine').style.setProperty('--dot-color', 'var(--success)');

    // Stop pulse animation
    const statusLine = document.getElementById('statusLine');
    statusLine.style.cssText = '';

    // Show results panel
    document.getElementById('resultsPanel').classList.remove('hidden');

    if (!summary || summary.total === 0) {
        document.getElementById('summaryGrid').innerHTML = `
            <div class="summary-stat" style="grid-column: 1 / -1;">
                <div class="stat-value">0</div>
                <div class="stat-label">No businesses found</div>
            </div>
        `;
        document.getElementById('downloadBtn').classList.add('hidden');
        return;
    }

    // Render summary stats
    const grid = document.getElementById('summaryGrid');
    let html = `
        <div class="summary-stat">
            <div class="stat-value">${summary.total}</div>
            <div class="stat-label">Total</div>
        </div>
    `;

    if (summary.avg_rating) {
        html += `
            <div class="summary-stat">
                <div class="stat-value">${summary.avg_rating} <span class="star">★</span></div>
                <div class="stat-label">Avg Rating</div>
            </div>
        `;
    }

    for (const [cat, count] of Object.entries(summary.by_category || {})) {
        html += `
            <div class="summary-stat">
                <div class="stat-value">${count}</div>
                <div class="stat-label">${cat}</div>
            </div>
        `;
    }

    grid.innerHTML = html;

    // Top rated
    if (summary.top5 && summary.top5.length > 0) {
        const topDiv = document.getElementById('topRated');
        topDiv.classList.remove('hidden');
        const list = document.getElementById('topRatedList');
        list.innerHTML = summary.top5.map(b => `
            <div class="top-rated-item">
                <span class="top-rated-name">${escapeHtml(b.name)}</span>
                <span class="top-rated-meta">
                    <span class="star">★</span> ${b.rating}
                    <span>(${b.reviews})</span>
                    <span>${escapeHtml(b.category)}</span>
                </span>
            </div>
        `).join('');
    }

    // Download button
    if (hasFile) {
        const downloadBtn = document.getElementById('downloadBtn');
        downloadBtn.classList.remove('hidden');
        downloadBtn.onclick = () => {
            window.location.href = `/api/download/${currentJobId}`;
        };
    }
}

function showError(message) {
    document.getElementById('progressPanel').classList.add('hidden');
    document.getElementById('errorPanel').classList.remove('hidden');
    document.getElementById('errorMessage').textContent = message;
}

function resetToForm() {
    // Reset UI
    document.getElementById('scrapeForm').classList.remove('hidden');
    document.getElementById('progressPanel').classList.add('hidden');
    document.getElementById('resultsPanel').classList.add('hidden');
    document.getElementById('errorPanel').classList.add('hidden');

    // Reset button
    const submitBtn = document.getElementById('submitBtn');
    submitBtn.disabled = false;
    submitBtn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
        Start Scraping
    `;

    // Close SSE if open
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }

    currentJobId = null;

    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ─── Helpers ─────────────────────────────────────────────────────────────

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
