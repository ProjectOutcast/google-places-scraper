// ─── State ────────────────────────────────────────────────────────────────

let currentJobId = null;
let eventSource = null;
let leafletMap = null;
let currentBusinesses = [];
let sortColumn = 'rating';
let sortAsc = false;
let licensingEnabled = false;
let checkoutUrl = '';

const CATEGORY_EMOJIS = {
    'restaurant': '🍽️', 'things-to-do': '🎯', 'spa': '💆',
    'hotel': '🏨', 'guest-house': '🏠', 'nightlife': '🌙',
    'coworking': '💻', 'gym': '💪', 'shopping': '🛍️', 'health': '🏥',
};

const CATEGORY_COLORS = {
    'Restaurant': '#ef4444', 'Things To Do': '#f59e0b', 'Spa': '#ec4899',
    'Hotel': '#3b82f6', 'Guest House': '#8b5cf6', 'Nightlife': '#6366f1',
    'Coworking': '#14b8a6', 'Gym': '#f97316', 'Shopping': '#84cc16', 'Health': '#06b6d4',
};

const DEFAULT_CATEGORIES = ['restaurant', 'things-to-do', 'spa', 'hotel', 'guest-house'];

// ─── Init ─────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    initLicenseGate();
});

// ─── License Gate ─────────────────────────────────────────────────────────

async function initLicenseGate() {
    try {
        const resp = await fetch('/api/license-config');
        const config = await resp.json();
        licensingEnabled = config.enabled;
        checkoutUrl = config.checkout_url || '';
    } catch (e) {
        // If config fails, assume no licensing (local dev)
        licensingEnabled = false;
    }

    if (!licensingEnabled) {
        // No gate — show scraper directly
        showScraperUI();
        return;
    }

    // Set up buy button
    const buyBtn = document.getElementById('buyBtn');
    if (buyBtn && checkoutUrl) {
        buyBtn.href = checkoutUrl;
    }

    // Set up activate button
    document.getElementById('activateBtn').addEventListener('click', handleActivation);
    document.getElementById('licenseKeyInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleActivation();
    });

    // Check if user already has a saved license
    const savedKey = localStorage.getItem('scraper_license_key');
    if (savedKey) {
        // Validate saved key
        showLicenseGate();
        setLicenseMessage('Verifying license...', '');
        try {
            const resp = await fetch('/api/validate-license', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ license_key: savedKey }),
            });
            const data = await resp.json();
            if (data.valid) {
                showScraperUI();
                return;
            }
        } catch (e) {
            // Network error — let them through if they had a key (grace)
            showScraperUI();
            return;
        }
        // Invalid saved key — clear and show gate
        localStorage.removeItem('scraper_license_key');
        setLicenseMessage('Your license key has expired or is invalid. Please re-enter it.', 'error');
    }

    showLicenseGate();
}

function showLicenseGate() {
    document.getElementById('licenseGate').classList.remove('hidden');
    document.getElementById('scraperContent').classList.add('hidden');
}

function showScraperUI() {
    document.getElementById('licenseGate').classList.add('hidden');
    document.getElementById('scraperContent').classList.remove('hidden');
    // Initialize scraper UI
    loadPresets();
    setupEventListeners();
    loadSavedApiKey();
}

function setLicenseMessage(text, type) {
    const el = document.getElementById('licenseMessage');
    el.textContent = text;
    el.className = 'license-message' + (type ? ' ' + type : '');
}

async function handleActivation() {
    const input = document.getElementById('licenseKeyInput');
    const btn = document.getElementById('activateBtn');
    const key = input.value.trim();

    if (!key) {
        setLicenseMessage('Please enter a license key.', 'error');
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Verifying...';
    setLicenseMessage('', '');

    try {
        const resp = await fetch('/api/validate-license', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ license_key: key }),
        });
        const data = await resp.json();

        if (data.valid) {
            localStorage.setItem('scraper_license_key', key);
            setLicenseMessage('License activated! Loading...', 'success');
            setTimeout(() => showScraperUI(), 600);
        } else {
            setLicenseMessage(data.error || 'Invalid license key.', 'error');
        }
    } catch (e) {
        setLicenseMessage('Network error. Please try again.', 'error');
    }

    btn.disabled = false;
    btn.textContent = 'Activate';
}

// ─── Category Presets ────────────────────────────────────────────────────

async function loadPresets() {
    try {
        const resp = await fetch('/api/presets');
        const data = await resp.json();
        renderCategories(data.presets, data.defaults);
    } catch (e) {
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
            <label for="cat-${key}"><span class="category-emoji">${emoji}</span>${label}</label>
        `;
        grid.appendChild(chip);
    });
}

// ─── localStorage: API Key ──────────────────────────────────────────────

function loadSavedApiKey() {
    const saved = localStorage.getItem('scraper_api_key');
    if (saved) {
        document.getElementById('apiKey').value = saved;
        document.getElementById('rememberKey').checked = true;
    }
}

function saveApiKeyIfNeeded() {
    const remember = document.getElementById('rememberKey').checked;
    const key = document.getElementById('apiKey').value.trim();
    if (remember && key) {
        localStorage.setItem('scraper_api_key', key);
    } else {
        localStorage.removeItem('scraper_api_key');
    }
}

// ─── Event Listeners ─────────────────────────────────────────────────────

function setupEventListeners() {
    document.getElementById('scrapeForm').addEventListener('submit', handleSubmit);

    document.getElementById('toggleApiKey').addEventListener('click', () => {
        const input = document.getElementById('apiKey');
        input.type = input.type === 'password' ? 'text' : 'password';
    });

    const radiusSlider = document.getElementById('radius');
    const radiusValue = document.getElementById('radiusValue');
    radiusSlider.addEventListener('input', () => {
        const val = parseInt(radiusSlider.value);
        radiusValue.textContent = val >= 1000
            ? (val / 1000).toFixed(val % 1000 === 0 ? 0 : 1) + ' km'
            : val + 'm';
    });

    document.getElementById('newScrapeBtn').addEventListener('click', resetToForm);
    document.getElementById('errorRetryBtn').addEventListener('click', resetToForm);

    // Setup guide toggle
    document.getElementById('toggleGuide').addEventListener('click', () => {
        const guide = document.querySelector('.setup-guide');
        const btn = document.getElementById('toggleGuide');
        const steps = guide.querySelector('.setup-steps');
        if (steps.classList.contains('hidden')) {
            steps.classList.remove('hidden');
            btn.textContent = 'Hide this guide';
            localStorage.removeItem('scraper_hide_guide');
        } else {
            steps.classList.add('hidden');
            btn.textContent = 'Show setup guide';
            localStorage.setItem('scraper_hide_guide', '1');
        }
    });

    // Restore guide visibility
    if (localStorage.getItem('scraper_hide_guide')) {
        const guide = document.querySelector('.setup-guide');
        guide.querySelector('.setup-steps').classList.add('hidden');
        document.getElementById('toggleGuide').textContent = 'Show setup guide';
    }

    // Table sorting — set initial indicator for default sort (rating desc)
    const ratingTh = document.querySelector('#previewTable th[data-sort="rating"]');
    if (ratingTh) ratingTh.classList.add('sort-desc');

    document.querySelectorAll('#previewTable th[data-sort]').forEach(th => {
        th.addEventListener('click', () => {
            const col = th.dataset.sort;
            if (sortColumn === col) { sortAsc = !sortAsc; }
            else { sortColumn = col; sortAsc = true; }
            renderTable(currentBusinesses);
            // Update sort indicators
            document.querySelectorAll('#previewTable th[data-sort]').forEach(t => t.classList.remove('sort-asc', 'sort-desc'));
            th.classList.add(sortAsc ? 'sort-asc' : 'sort-desc');
        });
    });
}

// ─── Form Submission ─────────────────────────────────────────────────────

async function handleSubmit(e) {
    e.preventDefault();
    saveApiKeyIfNeeded();

    const apiKey = document.getElementById('apiKey').value.trim();
    const location = document.getElementById('location').value.trim();
    const radius = parseInt(document.getElementById('radius').value);
    const customQueries = document.getElementById('customQueries').value.trim();
    const checkboxes = document.querySelectorAll('input[name="categories"]:checked');
    const categories = Array.from(checkboxes).map(cb => cb.value);

    if (!apiKey) { alert('Please enter your Google API key.'); return; }
    if (!location) { alert('Please enter a location.'); return; }
    if (categories.length === 0 && !customQueries) {
        alert('Please select at least one category or enter a custom query.');
        return;
    }

    const submitBtn = document.getElementById('submitBtn');
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner"></span> Starting...';

    try {
        const body = { api_key: apiKey, location, radius, categories, custom_queries: customQueries };
        // Include license key if licensing is enabled
        const savedLicense = localStorage.getItem('scraper_license_key');
        if (savedLicense) body.license_key = savedLicense;

        const resp = await fetch('/api/scrape', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await resp.json();

        // Handle license rejection
        if (resp.status === 403 && licensingEnabled) {
            localStorage.removeItem('scraper_license_key');
            showLicenseGate();
            setLicenseMessage('Your license key is no longer valid. Please re-enter it.', 'error');
            submitBtn.disabled = false;
            submitBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg> Start Scraping`;
            return;
        }

        if (!resp.ok) throw new Error(data.error || 'Failed to start scraping');

        currentJobId = data.job_id;
        showProgressPanel();
        connectSSE(data.job_id);
    } catch (err) {
        showError(err.message);
        submitBtn.disabled = false;
        submitBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg> Start Scraping`;
    }
}

// ─── SSE Progress ────────────────────────────────────────────────────────

function connectSSE(jobId) {
    if (eventSource) eventSource.close();
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
                // Auto-download CSV
                if (data.has_file && currentJobId) {
                    setTimeout(() => { window.location.href = `/api/download/${currentJobId}?format=csv`; }, 500);
                }
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
        const pp = document.getElementById('progressPanel');
        if (!pp.classList.contains('hidden')) {
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
    document.getElementById('logContent').innerHTML = '';
    document.getElementById('progressBar').style.width = '0%';
    document.getElementById('progressPercent').textContent = '0%';
    document.getElementById('progressTitle').textContent = 'Scraping in progress...';
    document.getElementById('statusLine').textContent = 'Initializing...';
}

function updateProgressBar(percent) {
    document.getElementById('progressBar').style.width = percent + '%';
    document.getElementById('progressPercent').textContent = percent + '%';
}

function addLogLine(message) {
    const container = document.getElementById('logContent');
    const line = document.createElement('div');
    line.className = 'log-line';
    line.textContent = message;
    container.appendChild(line);
    document.getElementById('logContainer').scrollTop = document.getElementById('logContainer').scrollHeight;
}

function showResults(summary, hasFile) {
    document.getElementById('progressTitle').textContent = 'Scraping complete!';
    document.getElementById('statusLine').textContent = 'All done!';
    document.getElementById('resultsPanel').classList.remove('hidden');

    if (!summary || summary.total === 0) {
        document.getElementById('summaryGrid').innerHTML = `
            <div class="summary-stat" style="grid-column: 1 / -1;">
                <div class="stat-value">0</div>
                <div class="stat-label">No businesses found</div>
            </div>`;
        document.getElementById('downloadCsvBtn').classList.add('hidden');
        return;
    }

    // Summary stats
    const grid = document.getElementById('summaryGrid');
    let html = `<div class="summary-stat"><div class="stat-value">${summary.total}</div><div class="stat-label">Total</div></div>`;
    if (summary.avg_rating) {
        html += `<div class="summary-stat"><div class="stat-value">${summary.avg_rating} <span class="star">★</span></div><div class="stat-label">Avg Rating</div></div>`;
    }
    for (const [cat, count] of Object.entries(summary.by_category || {})) {
        html += `<div class="summary-stat"><div class="stat-value">${count}</div><div class="stat-label">${escapeHtml(cat)}</div></div>`;
    }
    grid.innerHTML = html;

    // Map + Table (need businesses data)
    const businesses = summary.businesses || [];
    currentBusinesses = businesses;

    if (businesses.length > 0) {
        renderMap(businesses);
        renderTable(businesses);
        document.getElementById('tableCount').textContent = `${businesses.length} results`;
    }

    // Download button
    if (hasFile) {
        document.getElementById('downloadCsvBtn').classList.remove('hidden');
        document.getElementById('downloadCsvBtn').onclick = () => { window.location.href = `/api/download/${currentJobId}?format=csv`; };
    }
}

// ─── Interactive Map (Leaflet) ──────────────────────────────────────────

function renderMap(businesses) {
    const section = document.getElementById('mapSection');
    section.classList.remove('hidden');

    // Filter businesses with valid coordinates
    const withCoords = businesses.filter(b => b.latitude && b.longitude);
    if (withCoords.length === 0) {
        section.classList.add('hidden');
        return;
    }

    // Destroy existing map
    if (leafletMap) { leafletMap.remove(); leafletMap = null; }

    leafletMap = L.map('map');

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 19,
    }).addTo(leafletMap);

    const markers = [];
    withCoords.forEach(b => {
        const color = CATEGORY_COLORS[b.category] || '#6b7280';
        const icon = L.divIcon({
            className: 'map-marker-custom',
            html: `<div style="background:${color};width:12px;height:12px;border-radius:50%;border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,0.4);"></div>`,
            iconSize: [16, 16],
            iconAnchor: [8, 8],
        });

        const marker = L.marker([b.latitude, b.longitude], { icon });
        const rating = b.rating ? `<br>★ ${b.rating} (${b.reviews_count} reviews)` : '';
        const photo = b.photo_url ? `<img src="${b.photo_url}" style="width:140px;height:90px;object-fit:cover;border-radius:4px;margin-bottom:6px;display:block;">` : '';
        const gmapsLink = b.google_maps_url ? `<br><a href="${b.google_maps_url}" target="_blank" rel="noopener" style="color:#3b82f6;font-size:12px;text-decoration:none;font-weight:600;">View on Google Maps &rarr;</a>` : '';
        marker.bindPopup(`${photo}<b>${escapeHtml(b.name)}</b><br><span style="color:${color}">${escapeHtml(b.category)}</span>${rating}${gmapsLink}`, { maxWidth: 200 });
        marker.addTo(leafletMap);
        markers.push(marker);
    });

    // Fit bounds
    if (markers.length > 0) {
        const group = L.featureGroup(markers);
        leafletMap.fitBounds(group.getBounds().pad(0.1));
    }

    // Force resize after render
    setTimeout(() => { leafletMap.invalidateSize(); }, 200);
}

// ─── Preview Table ──────────────────────────────────────────────────────

function renderTable(businesses) {
    const section = document.getElementById('tableSection');
    section.classList.remove('hidden');

    // Sort
    let sorted = [...businesses];
    if (sortColumn) {
        sorted.sort((a, b) => {
            let va = a[sortColumn], vb = b[sortColumn];
            if (va == null) va = '';
            if (vb == null) vb = '';
            if (typeof va === 'number' && typeof vb === 'number') {
                return sortAsc ? va - vb : vb - va;
            }
            va = String(va).toLowerCase();
            vb = String(vb).toLowerCase();
            return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
        });
    }

    const tbody = document.getElementById('tableBody');
    tbody.innerHTML = sorted.map(b => {
        const photo = b.photo_url
            ? `<img src="${b.photo_url}" class="table-photo" loading="lazy" alt="">`
            : `<div class="table-photo-placeholder"></div>`;
        const rating = b.rating ? `<span class="star">★</span> ${b.rating}` : '-';
        const website = b.website
            ? `<a href="${b.website}" target="_blank" rel="noopener" class="table-link">Visit</a>`
            : '-';
        const catColor = CATEGORY_COLORS[b.category] || '#6b7280';

        return `<tr>
            <td>${photo}</td>
            <td><span class="table-name">${escapeHtml(b.name)}</span></td>
            <td><span class="table-cat" style="--cat-color:${catColor}">${escapeHtml(b.category)}</span></td>
            <td>${rating}</td>
            <td>${b.reviews_count || 0}</td>
            <td>${escapeHtml(b.phone || '-')}</td>
            <td>${website}</td>
        </tr>`;
    }).join('');
}

// ─── Error & Reset ──────────────────────────────────────────────────────

function showError(message) {
    document.getElementById('progressPanel').classList.add('hidden');
    document.getElementById('errorPanel').classList.remove('hidden');
    document.getElementById('errorMessage').textContent = message;
}

function resetToForm() {
    document.getElementById('scrapeForm').classList.remove('hidden');
    document.getElementById('progressPanel').classList.add('hidden');
    document.getElementById('resultsPanel').classList.add('hidden');
    document.getElementById('errorPanel').classList.add('hidden');

    // Reset results sub-sections
    document.getElementById('mapSection').classList.add('hidden');
    document.getElementById('tableSection').classList.add('hidden');

    const submitBtn = document.getElementById('submitBtn');
    submitBtn.disabled = false;
    submitBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg> Start Scraping`;

    if (eventSource) { eventSource.close(); eventSource = null; }
    if (leafletMap) { leafletMap.remove(); leafletMap = null; }
    currentJobId = null;
    currentBusinesses = [];
    sortColumn = 'rating';
    sortAsc = false;

    // Reset sort indicators
    document.querySelectorAll('#previewTable th[data-sort]').forEach(t => t.classList.remove('sort-asc', 'sort-desc'));
    const ratingTh = document.querySelector('#previewTable th[data-sort="rating"]');
    if (ratingTh) ratingTh.classList.add('sort-desc');

    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ─── Helpers ─────────────────────────────────────────────────────────────

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
