/**
 * Renewal Campaign Dashboard - Main JavaScript
 * Handles data loading, filtering, pagination, and WhatsApp sending.
 */

// Auto-detect base path from current URL (handles cPanel sub-path mounting)
const SCRIPT_PATH = document.currentScript ? document.currentScript.src : '';
const BASE_PATH = window.location.pathname.replace(/\/(renewals\/?)?$/, '');
const API_BASE = BASE_PATH + '/api/renewals';

// State
let state = {
    currentFilter: 'all',
    currentPage: 1,
    perPage: 50,
    search: '',
    zone: '',
    plan: '',
    selectedIds: new Set(),
    records: [],
    stats: {},
    currentRecord: null,
};

// Template mapping by category
const TEMPLATE_MAP = {
    expired: 'pack_expiry_alert',
    today: 'recharge_today1',
    upcoming: 'recharge_reminder',
};

// ============================================================
// Initialization
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
    loadStats();
    loadRecords();
    loadFilters();
    bindEvents();
});

function bindEvents() {
    // Sidebar filters
    document.querySelectorAll('.sidebar-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            document.querySelectorAll('.sidebar-link').forEach(l => l.classList.remove('active'));
            link.classList.add('active');
            state.currentFilter = link.dataset.filter;
            state.currentPage = 1;
            document.getElementById('page-title').textContent = link.textContent.trim().split('\n')[0].trim();
            loadRecords();
        });
    });

    // Search
    document.getElementById('search-input').addEventListener('keyup', debounce((e) => {
        state.search = e.target.value;
        state.currentPage = 1;
        loadRecords();
    }, 400));

    document.getElementById('btn-search').addEventListener('click', () => {
        state.search = document.getElementById('search-input').value;
        state.currentPage = 1;
        loadRecords();
    });

    // Zone/Plan filters
    document.getElementById('filter-zone').addEventListener('change', (e) => {
        state.zone = e.target.value;
        state.currentPage = 1;
        loadRecords();
    });

    document.getElementById('filter-plan').addEventListener('change', (e) => {
        state.plan = e.target.value;
        state.currentPage = 1;
        loadRecords();
    });

    // Select all
    document.getElementById('select-all').addEventListener('change', (e) => {
        toggleSelectAll(e.target.checked);
    });
    document.getElementById('th-select-all').addEventListener('change', (e) => {
        toggleSelectAll(e.target.checked);
    });

    // Bulk send
    document.getElementById('btn-bulk-send').addEventListener('click', () => {
        document.getElementById('bulk-count').textContent = state.selectedIds.size;
        new bootstrap.Modal(document.getElementById('bulkSendModal')).show();
    });

    document.getElementById('btn-confirm-bulk').addEventListener('click', confirmBulkSend);

    // Export
    document.getElementById('btn-export').addEventListener('click', exportCSV);

    // Refresh
    document.getElementById('btn-refresh').addEventListener('click', () => {
        loadStats();
        loadRecords();
    });

    // Sync
    document.getElementById('btn-sync').addEventListener('click', syncData);

    // Send modal confirm
    document.getElementById('btn-confirm-send').addEventListener('click', confirmSend);

    // Toggle sidebar on mobile
    document.getElementById('toggle-sidebar').addEventListener('click', () => {
        document.getElementById('sidebar').classList.toggle('show');
    });
}

// ============================================================
// Data Loading
// ============================================================

async function loadStats() {
    try {
        const res = await fetch(`${API_BASE}/stats`);
        const data = await res.json();
        if (data.success) {
            state.stats = data.stats;
            document.getElementById('stat-total').textContent = data.stats.total;
            document.getElementById('stat-expired').textContent = data.stats.expired;
            document.getElementById('stat-today').textContent = data.stats.today;
            document.getElementById('stat-upcoming').textContent = data.stats.upcoming;
            document.getElementById('count-all').textContent = data.stats.total;
            document.getElementById('count-expired').textContent = data.stats.expired;
            document.getElementById('count-today').textContent = data.stats.today;
            document.getElementById('count-upcoming').textContent = data.stats.upcoming;
            document.getElementById('count-sent').textContent = data.stats.sent_today;
            document.getElementById('count-failed').textContent = data.stats.failed_today;
        }
    } catch (err) {
        console.error('Failed to load stats:', err);
    }
}

async function loadRecords() {
    const tbody = document.getElementById('table-body');
    tbody.innerHTML = '<tr><td colspan="11" class="text-center py-4"><div class="spinner-border spinner-border-sm"></div> Loading...</td></tr>';

    const params = new URLSearchParams({
        page: state.currentPage,
        per_page: state.perPage,
    });

    if (state.currentFilter && state.currentFilter !== 'all' && state.currentFilter !== 'sent' && state.currentFilter !== 'failed') {
        params.set('category', state.currentFilter);
    }
    if (state.search) params.set('search', state.search);
    if (state.zone) params.set('zone', state.zone);
    if (state.plan) params.set('plan', state.plan);

    try {
        const res = await fetch(`${API_BASE}/?${params}`);
        const data = await res.json();
        if (data.success) {
            state.records = data.data;
            renderTable(data.data);
            renderPagination(data.pagination);
        }
    } catch (err) {
        tbody.innerHTML = '<tr><td colspan="11" class="text-center py-4 text-danger">Failed to load data</td></tr>';
        console.error('Failed to load records:', err);
    }
}

async function loadFilters() {
    try {
        const res = await fetch(`${API_BASE}/filters`);
        const data = await res.json();
        if (data.success) {
            const zoneSelect = document.getElementById('filter-zone');
            data.zones.forEach(z => {
                const opt = document.createElement('option');
                opt.value = z;
                opt.textContent = z;
                zoneSelect.appendChild(opt);
            });

            const planSelect = document.getElementById('filter-plan');
            data.plans.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p;
                opt.textContent = p.length > 25 ? p.substring(0, 25) + '...' : p;
                planSelect.appendChild(opt);
            });
        }
    } catch (err) {
        console.error('Failed to load filters:', err);
    }
}

// ============================================================
// Table Rendering
// ============================================================

function renderTable(records) {
    const tbody = document.getElementById('table-body');

    if (!records || records.length === 0) {
        tbody.innerHTML = '<tr><td colspan="11" class="text-center py-4 text-muted">No records found</td></tr>';
        return;
    }

    tbody.innerHTML = records.map(r => {
        const isSelected = state.selectedIds.has(r.id);
        const badge = getCategoryBadge(r.category);
        const template = TEMPLATE_MAP[r.category] || 'recharge_reminder';
        const daysText = getDaysText(r.days_remaining);

        return `
        <tr class="fade-in ${isSelected ? 'table-active' : ''}">
            <td><input type="checkbox" class="form-check-input row-check" data-id="${r.id}" ${isSelected ? 'checked' : ''}></td>
            <td class="fw-medium">${escapeHtml(r.customer_name || '--')}</td>
            <td><code>${escapeHtml(r.mobile || '--')}</code></td>
            <td><small>${escapeHtml(r.account_id || '--')}</small></td>
            <td><small>${escapeHtml(r.plan_name || '--')}</small></td>
            <td>${r.expiry_date || '--'}</td>
            <td>${daysText}</td>
            <td><small class="text-muted">${template}</small></td>
            <td>${badge}</td>
            <td>${getDeliveryBadge(r.delivery_status)}</td>
            <td><small class="text-muted">${r.last_sent_at || '--'}</small></td>
            <td>
                <button class="btn btn-sm btn-success btn-send" onclick="openSendModal(${r.id})" title="Send WhatsApp">
                    <i class="bi bi-whatsapp"></i>
                </button>
            </td>
        </tr>`;
    }).join('');

    // Bind row checkboxes
    tbody.querySelectorAll('.row-check').forEach(cb => {
        cb.addEventListener('change', (e) => {
            const id = parseInt(e.target.dataset.id);
            if (e.target.checked) {
                state.selectedIds.add(id);
            } else {
                state.selectedIds.delete(id);
            }
            updateSelectedCount();
        });
    });
}

function getCategoryBadge(category) {
    switch (category) {
        case 'expired': return '<span class="badge badge-expired">🔴 EXPIRED</span>';
        case 'today': return '<span class="badge badge-today">🟠 TODAY</span>';
        case 'upcoming': return '<span class="badge badge-upcoming">🟢 UPCOMING</span>';
        default: return '<span class="badge bg-secondary">--</span>';
    }
}

function getDaysText(days) {
    if (days === null || days === undefined) return '--';
    if (days < 0) return `<span class="text-danger fw-bold">${days}d</span>`;
    if (days === 0) return '<span class="text-warning fw-bold">Today</span>';
    return `<span class="text-success">${days}d</span>`;
}

function getDeliveryBadge(status) {
    if (!status) return '<small class="text-muted">--</small>';
    switch (status) {
        case 'sent': return '<span class="badge bg-secondary"><i class="bi bi-check"></i> Sent</span>';
        case 'delivered': return '<span class="badge bg-info"><i class="bi bi-check2-all"></i> Delivered</span>';
        case 'read': return '<span class="badge bg-primary"><i class="bi bi-eye"></i> Read</span>';
        case 'failed': return '<span class="badge bg-danger"><i class="bi bi-x-circle"></i> Failed</span>';
        default: return `<span class="badge bg-secondary">${status}</span>`;
    }
}

// ============================================================
// Pagination
// ============================================================

function renderPagination(pagination) {
    const { page, per_page, total, total_pages } = pagination;
    const start = (page - 1) * per_page + 1;
    const end = Math.min(page * per_page, total);

    document.getElementById('pagination-info').textContent =
        total > 0 ? `Showing ${start}-${end} of ${total}` : 'No records';

    const paginationEl = document.getElementById('pagination');
    if (total_pages <= 1) {
        paginationEl.innerHTML = '';
        return;
    }

    let html = '';
    // Previous
    html += `<li class="page-item ${page === 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${page - 1}">&laquo;</a></li>`;

    // Page numbers (show max 7)
    const startPage = Math.max(1, page - 3);
    const endPage = Math.min(total_pages, page + 3);

    if (startPage > 1) {
        html += `<li class="page-item"><a class="page-link" href="#" data-page="1">1</a></li>`;
        if (startPage > 2) html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
    }

    for (let i = startPage; i <= endPage; i++) {
        html += `<li class="page-item ${i === page ? 'active' : ''}">
            <a class="page-link" href="#" data-page="${i}">${i}</a></li>`;
    }

    if (endPage < total_pages) {
        if (endPage < total_pages - 1) html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        html += `<li class="page-item"><a class="page-link" href="#" data-page="${total_pages}">${total_pages}</a></li>`;
    }

    // Next
    html += `<li class="page-item ${page === total_pages ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${page + 1}">&raquo;</a></li>`;

    paginationEl.innerHTML = html;

    // Bind pagination clicks
    paginationEl.querySelectorAll('.page-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const p = parseInt(e.target.dataset.page);
            if (p && p >= 1 && p <= total_pages) {
                state.currentPage = p;
                loadRecords();
            }
        });
    });
}

// ============================================================
// Send Message
// ============================================================

function openSendModal(recordId) {
    const record = state.records.find(r => r.id === recordId);
    if (!record) return;

    state.currentRecord = record;

    document.getElementById('modal-customer').textContent = record.customer_name || '--';
    document.getElementById('modal-mobile').textContent = record.mobile || '--';

    // Set template based on category
    const template = TEMPLATE_MAP[record.category] || 'recharge_reminder';
    document.getElementById('modal-template').value = template;

    // Auto-fill params based on category
    document.getElementById('param-1').textContent = record.customer_name || 'Customer';
    document.getElementById('param-2').textContent = record.plan_name || '';
    document.getElementById('param-3').textContent = record.expiry_date || '';

    // Hide param-3 row for recharge_today1 (only 2 params)
    const param3Row = document.getElementById('param-3-row');
    if (template === 'recharge_today1') {
        param3Row.style.display = 'none';
    } else {
        param3Row.style.display = '';
    }

    // Check if already sent
    const warning = document.getElementById('modal-duplicate-warning');
    if (record.last_sent_at) {
        warning.classList.remove('d-none');
    } else {
        warning.classList.add('d-none');
    }

    document.getElementById('override-duplicate').checked = false;
    new bootstrap.Modal(document.getElementById('sendModal')).show();
}

async function confirmSend() {
    const record = state.currentRecord;
    if (!record) return;

    const btn = document.getElementById('btn-confirm-send');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Sending...';

    const templateName = document.getElementById('modal-template').value;
    const overrideDuplicate = document.getElementById('override-duplicate').checked;

    // Build params based on template
    let templateParams;
    if (templateName === 'recharge_today1') {
        templateParams = [
            record.customer_name || 'Customer',
            record.plan_name || '',
        ];
    } else {
        templateParams = [
            record.customer_name || 'Customer',
            record.plan_name || '',
            record.expiry_date || '',
        ];
    }

    const payload = {
        renewal_id: record.id,
        template_name: templateName,
        params: templateParams,
        operator_name: 'operator',  // TODO: get from session
        override_duplicate: overrideDuplicate,
    };

    try {
        const res = await fetch(`${API_BASE}/send`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();

        if (data.success) {
            showToast('Message sent successfully!', 'success');
            bootstrap.Modal.getInstance(document.getElementById('sendModal')).hide();
            loadRecords();
            loadStats();
        } else {
            showToast(data.error || 'Failed to send', 'danger');
        }
    } catch (err) {
        showToast('Network error', 'danger');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-send"></i> Send Message';
    }
}

// ============================================================
// Bulk Send
// ============================================================

async function confirmBulkSend() {
    const operatorName = document.getElementById('bulk-operator').value.trim();
    if (!operatorName) {
        showToast('Please enter operator name', 'warning');
        return;
    }

    const btn = document.getElementById('btn-confirm-bulk');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Sending...';

    const payload = {
        renewal_ids: Array.from(state.selectedIds),
        operator_name: operatorName,
        override_duplicate: false,
    };

    try {
        const res = await fetch(`${API_BASE}/bulk-send`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();

        if (data.success) {
            const r = data.results;
            showToast(`Bulk send: ${r.sent} sent, ${r.failed} failed, ${r.skipped} skipped`, 'success');
            bootstrap.Modal.getInstance(document.getElementById('bulkSendModal')).hide();
            state.selectedIds.clear();
            updateSelectedCount();
            loadRecords();
            loadStats();
        } else {
            showToast(data.error || 'Bulk send failed', 'danger');
        }
    } catch (err) {
        showToast('Network error', 'danger');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-send"></i> Confirm Send';
    }
}

// ============================================================
// Sync
// ============================================================

async function syncData() {
    const btn = document.getElementById('btn-sync');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

    try {
        const res = await fetch(`${API_BASE}/sync`, { method: 'POST' });
        const data = await res.json();

        if (data.success) {
            showToast(`Sync complete: ${data.sync.inserted} new, ${data.sync.updated} updated`, 'success');
            document.getElementById('last-sync').textContent = new Date().toLocaleTimeString();
            loadStats();
            loadRecords();
        } else {
            showToast(data.error || 'Sync failed', 'danger');
        }
    } catch (err) {
        showToast('Sync failed: network error', 'danger');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-arrow-repeat"></i> Sync Now';
    }
}

// ============================================================
// Export
// ============================================================

function exportCSV() {
    const params = new URLSearchParams();
    if (state.currentFilter && state.currentFilter !== 'all') {
        params.set('category', state.currentFilter);
    }
    if (state.search) params.set('search', state.search);

    window.open(`${API_BASE}/export?${params}`, '_blank');
}

// ============================================================
// Selection Helpers
// ============================================================

function toggleSelectAll(checked) {
    state.records.forEach(r => {
        if (checked) {
            state.selectedIds.add(r.id);
        } else {
            state.selectedIds.delete(r.id);
        }
    });

    document.querySelectorAll('.row-check').forEach(cb => {
        cb.checked = checked;
    });

    document.getElementById('select-all').checked = checked;
    document.getElementById('th-select-all').checked = checked;
    updateSelectedCount();
}

function updateSelectedCount() {
    const count = state.selectedIds.size;
    document.getElementById('selected-count').textContent = count;
    document.getElementById('btn-bulk-send').disabled = count === 0;
}

// ============================================================
// Utilities
// ============================================================

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    const body = document.getElementById('toast-body');
    body.textContent = message;

    toast.className = `toast align-items-center border-0 text-bg-${type}`;
    const bsToast = new bootstrap.Toast(toast, { delay: 4000 });
    bsToast.show();
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function debounce(func, wait) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}
