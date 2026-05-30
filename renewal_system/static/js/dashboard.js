/**
 * Renewal Campaign Dashboard - Main JavaScript
 * Handles data loading, filtering, pagination, WhatsApp sending,
 * customer detail panel, and zone statistics.
 */

// Auto-detect base path from current URL
const SCRIPT_PATH = document.currentScript ? document.currentScript.src : '';
const BASE_PATH = window.location.pathname.replace(/\/(renewals\/?)?$/, '');
const API_BASE = BASE_PATH + '/api/renewals';
const CUSTOMERS_API = BASE_PATH + '/api/customers';

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
    viewMode: 'renewals', // 'renewals' or 'customers'
    customerStats: null,
};

// Template mapping by category
const TEMPLATE_MAP = {
    expired: 'pack_expiry_alert',
    today: 'recharge_today1',
    upcoming: 'expiry_to_date',
};

// ============================================================
// Initialization
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
    loadStats();
    loadRecords();
    loadFilters();
    loadCustomerStats();
    bindEvents();
    startStatusPolling();
});

function bindEvents() {
    // Sidebar filters
    document.querySelectorAll('.sidebar-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            document.querySelectorAll('.sidebar-link').forEach(l => l.classList.remove('active'));
            link.classList.add('active');
            const filter = link.dataset.filter;
            state.currentFilter = filter;
            state.currentPage = 1;

            if (filter === 'customers') {
                state.viewMode = 'customers';
                document.getElementById('page-title').textContent = 'All Customers (IMS)';
                loadCustomers();
            } else {
                state.viewMode = 'renewals';
                document.getElementById('page-title').textContent = link.textContent.trim().split('\n')[0].trim();
                loadRecords();
            }
        });
    });

    // Search
    document.getElementById('search-input').addEventListener('keyup', debounce((e) => {
        state.search = e.target.value;
        state.currentPage = 1;
        if (state.viewMode === 'customers') loadCustomers();
        else loadRecords();
    }, 400));

    document.getElementById('btn-search').addEventListener('click', () => {
        state.search = document.getElementById('search-input').value;
        state.currentPage = 1;
        if (state.viewMode === 'customers') loadCustomers();
        else loadRecords();
    });

    // Zone/Plan filters
    document.getElementById('filter-zone').addEventListener('change', (e) => {
        state.zone = e.target.value;
        state.currentPage = 1;
        if (state.viewMode === 'customers') loadCustomers();
        else loadRecords();
    });

    document.getElementById('filter-plan').addEventListener('change', (e) => {
        state.plan = e.target.value;
        state.currentPage = 1;
        if (state.viewMode === 'customers') loadCustomers();
        else loadRecords();
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
        loadCustomerStats();
        if (state.viewMode === 'customers') loadCustomers();
        else loadRecords();
    });

    // Sync
    document.getElementById('btn-sync').addEventListener('click', syncData);

    // Send modal confirm
    document.getElementById('btn-confirm-send').addEventListener('click', confirmSend);

    // Toggle sidebar on mobile
    document.getElementById('toggle-sidebar').addEventListener('click', () => {
        document.getElementById('sidebar').classList.toggle('show');
    });

    // Zone stats toggle
    document.getElementById('toggle-zone-stats').addEventListener('click', () => {
        const bars = document.getElementById('zone-bars');
        bars.style.display = bars.style.display === 'none' ? 'flex' : 'none';
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
            document.getElementById('stat-sent-today').textContent = data.stats.sent_today || 0;
            document.getElementById('count-all').textContent = data.stats.total;
            document.getElementById('count-expired').textContent = data.stats.expired;
            document.getElementById('count-today').textContent = data.stats.today;
            document.getElementById('count-upcoming').textContent = data.stats.upcoming;
            document.getElementById('count-sent').textContent = data.stats.sent_today || 0;
            document.getElementById('count-failed').textContent = data.stats.failed_today || 0;
        }
    } catch (err) {
        console.error('Failed to load stats:', err);
    }
}

async function loadCustomerStats() {
    try {
        const res = await fetch(`${CUSTOMERS_API}/stats`);
        const data = await res.json();
        if (data.total !== undefined) {
            state.customerStats = data;
            document.getElementById('stat-customers').textContent = data.total;
            document.getElementById('count-customers').textContent = data.total;
            renderZoneBars(data.zones || {});
        }
    } catch (err) {
        console.error('Failed to load customer stats:', err);
    }
}

function renderZoneBars(zones) {
    const container = document.getElementById('zone-bars');
    if (!zones || Object.keys(zones).length === 0) {
        container.innerHTML = '<small class="text-muted">No zone data</small>';
        return;
    }

    const maxCount = Math.max(...Object.values(zones));
    const entries = Object.entries(zones).sort((a, b) => b[1] - a[1]).slice(0, 10);

    container.innerHTML = entries.map(([zone, count]) => {
        const height = Math.max(8, (count / maxCount) * 50);
        return `
            <div class="zone-bar-item" title="${zone}: ${count} customers">
                <span class="zone-bar-count">${count}</span>
                <div class="zone-bar" style="height:${height}px;"></div>
                <span class="zone-bar-label">${zone}</span>
            </div>`;
    }).join('');
}

async function loadRecords() {
    const tbody = document.getElementById('table-body');
    tbody.innerHTML = '<tr><td colspan="12" class="text-center py-4"><div class="spinner-border spinner-border-sm"></div> Loading...</td></tr>';

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
        tbody.innerHTML = '<tr><td colspan="12" class="text-center py-4 text-danger">Failed to load data</td></tr>';
        console.error('Failed to load records:', err);
    }
}

async function loadCustomers() {
    const tbody = document.getElementById('table-body');
    tbody.innerHTML = '<tr><td colspan="12" class="text-center py-4"><div class="spinner-border spinner-border-sm"></div> Loading...</td></tr>';

    const params = new URLSearchParams({
        page: state.currentPage,
        per_page: state.perPage,
        sort: 'expiry_date',
        order: 'asc',
    });

    if (state.search) params.set('search', state.search);
    if (state.zone) params.set('zone', state.zone);
    if (state.plan) params.set('plan', state.plan);

    try {
        const res = await fetch(`${CUSTOMERS_API}/?${params}`);
        const data = await res.json();
        if (data.data) {
            state.records = data.data;
            renderCustomerTable(data.data);
            renderPagination({ page: data.page, per_page: data.per_page, total: data.total, total_pages: data.pages });
        }
    } catch (err) {
        tbody.innerHTML = '<tr><td colspan="12" class="text-center py-4 text-danger">Failed to load customers</td></tr>';
        console.error('Failed to load customers:', err);
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
                opt.textContent = p.length > 20 ? p.substring(0, 20) + '...' : p;
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
    const isMobile = window.innerWidth < 768;

    if (!records || records.length === 0) {
        tbody.innerHTML = '<tr><td colspan="12" class="text-center py-4 text-muted">No records found</td></tr>';
        return;
    }

    tbody.innerHTML = records.map(r => {
        const isSelected = state.selectedIds.has(r.id);
        const badge = getCategoryBadge(r.category);
        const template = TEMPLATE_MAP[r.category] || 'expiry_to_date';
        const daysText = getDaysText(r.days_remaining);

        if (isMobile) {
            return renderMobileCard(r, isSelected, badge, template, daysText);
        }

        return `
        <tr class="fade-in ${isSelected ? 'table-active' : ''}">
            <td><input type="checkbox" class="form-check-input row-check" data-id="${r.id}" ${isSelected ? 'checked' : ''}></td>
            <td><a class="customer-name-link" onclick="openCustomerDetail(${r.id})">${escapeHtml(r.customer_name || '--')}</a></td>
            <td><code class="small">${escapeHtml(r.mobile || '--')}</code></td>
            <td class="d-none d-lg-table-cell"><small>${escapeHtml(r.account_id || '--')}</small></td>
            <td class="d-none d-md-table-cell"><small>${escapeHtml(r.plan_name || '--')}</small></td>
            <td>${r.expiry_date || '--'}</td>
            <td>${daysText}</td>
            <td class="d-none d-lg-table-cell"><small class="text-muted">${template}</small></td>
            <td>${badge}</td>
            <td>${getDeliveryBadge(r.delivery_status)}</td>
            <td class="d-none d-md-table-cell"><small class="text-muted">${r.last_sent_at || '--'}</small></td>
            <td>
                <div class="d-flex gap-1">
                    <button class="btn btn-sm btn-success btn-send" onclick="openSendModal(${r.id})" title="Send WhatsApp">
                        <i class="bi bi-whatsapp"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-primary btn-view" onclick="openCustomerDetail(${r.id})" title="View Details">
                        <i class="bi bi-eye"></i>
                    </button>
                </div>
            </td>
        </tr>`;
    }).join('');

    bindRowCheckboxes();
}

function renderMobileCard(r, isSelected, badge, template, daysText) {
    return `
    <tr class="fade-in mobile-card-row">
        <td colspan="12" class="p-0">
            <div class="mobile-card ${isSelected ? 'selected' : ''}" data-id="${r.id}">
                <div class="mobile-card-header">
                    <div class="d-flex align-items-center gap-2">
                        <input type="checkbox" class="form-check-input row-check" data-id="${r.id}" ${isSelected ? 'checked' : ''}>
                        <div class="flex-grow-1" onclick="openCustomerDetail(${r.id})">
                            <div class="fw-bold">${escapeHtml(r.customer_name || '--')}</div>
                            <small class="text-muted">${escapeHtml(r.mobile || '--')}</small>
                        </div>
                        ${badge}
                    </div>
                </div>
                <div class="mobile-card-body">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <small class="text-muted d-block">${escapeHtml(r.plan_name || '--')}</small>
                            <small>Expiry: <strong>${r.expiry_date || '--'}</strong> (${daysText})</small>
                        </div>
                        <div class="d-flex gap-1">
                            <button class="btn btn-sm btn-success btn-send" onclick="openSendModal(${r.id})">
                                <i class="bi bi-whatsapp"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-primary btn-view" onclick="openCustomerDetail(${r.id})">
                                <i class="bi bi-eye"></i>
                            </button>
                        </div>
                    </div>
                    <div class="d-flex gap-2 mt-1">
                        ${getDeliveryBadge(r.delivery_status)}
                        ${r.last_sent_at ? `<small class="text-muted">Sent: ${r.last_sent_at}</small>` : ''}
                    </div>
                </div>
            </div>
        </td>
    </tr>`;
}

function renderCustomerTable(records) {
    const tbody = document.getElementById('table-body');
    const isMobile = window.innerWidth < 768;

    if (!records || records.length === 0) {
        tbody.innerHTML = '<tr><td colspan="12" class="text-center py-4 text-muted">No customers found</td></tr>';
        return;
    }

    tbody.innerHTML = records.map(r => {
        const statusBadge = getCustomerStatusBadge(r.status);
        const daysText = getDaysText(r.days_remaining);

        if (isMobile) {
            return `
            <tr class="fade-in mobile-card-row">
                <td colspan="12" class="p-0">
                    <div class="mobile-card" onclick="openCustomerDetailFromData(${JSON.stringify(r).replace(/"/g, '&quot;')})">
                        <div class="mobile-card-header">
                            <div class="d-flex align-items-center gap-2">
                                <div class="flex-grow-1">
                                    <div class="fw-bold">${escapeHtml(r.customer_name || '--')}</div>
                                    <small class="text-muted">${escapeHtml(r.mobile || '--')}</small>
                                </div>
                                ${statusBadge}
                            </div>
                        </div>
                        <div class="mobile-card-body">
                            <small class="text-muted">${escapeHtml(r.plan_name || '--')}</small>
                            <div class="d-flex justify-content-between mt-1">
                                <small>Expiry: <strong>${r.expiry_date || '--'}</strong></small>
                                <small>${escapeHtml(r.zone_name || '')}</small>
                            </div>
                        </div>
                    </div>
                </td>
            </tr>`;
        }

        return `
        <tr class="fade-in">
            <td><input type="checkbox" class="form-check-input row-check" data-id="${r.id}" disabled></td>
            <td><a class="customer-name-link" onclick='openCustomerDetailFromData(${JSON.stringify(r).replace(/'/g, "&#39;")})'>${escapeHtml(r.customer_name || '--')}</a></td>
            <td><code class="small">${escapeHtml(r.mobile || '--')}</code></td>
            <td class="d-none d-lg-table-cell"><small>${escapeHtml(r.user_id || '--')}</small></td>
            <td class="d-none d-md-table-cell"><small>${escapeHtml(r.plan_name || '--')}</small></td>
            <td>${r.expiry_date || '--'}</td>
            <td>${daysText}</td>
            <td class="d-none d-lg-table-cell"><small>${escapeHtml(r.zone_name || '--')}</small></td>
            <td>${statusBadge}</td>
            <td>${escapeHtml(r.network_type || '--')}</td>
            <td class="d-none d-md-table-cell"><small>${escapeHtml(r.activation_date || '--')}</small></td>
            <td>
                <button class="btn btn-sm btn-outline-primary btn-view" onclick='openCustomerDetailFromData(${JSON.stringify(r).replace(/'/g, "&#39;")})' title="View">
                    <i class="bi bi-eye"></i>
                </button>
            </td>
        </tr>`;
    }).join('');

    bindRowCheckboxes();
}

function bindRowCheckboxes() {
    document.querySelectorAll('.row-check').forEach(cb => {
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
        case 'expired': return '<span class="badge badge-expired">EXPIRED</span>';
        case 'today': return '<span class="badge badge-today">TODAY</span>';
        case 'upcoming': return '<span class="badge badge-upcoming">UPCOMING</span>';
        default: return '<span class="badge bg-secondary">--</span>';
    }
}

function getCustomerStatusBadge(status) {
    if (!status) return '<span class="badge bg-secondary">--</span>';
    const s = String(status).toLowerCase();
    if (s === '1' || s === 'active') return '<span class="badge badge-active">Active</span>';
    if (s === '0' || s === 'inactive') return '<span class="badge badge-inactive">Inactive</span>';
    return `<span class="badge bg-secondary">${escapeHtml(status)}</span>`;
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
// Customer Detail Panel
// ============================================================

function openCustomerDetail(recordId) {
    const record = state.records.find(r => r.id === recordId);
    if (!record) return;

    // For renewal records, fetch full customer data from customers API
    if (record.mobile || record.account_id) {
        const searchTerm = record.account_id || record.mobile;
        fetch(`${CUSTOMERS_API}/?search=${encodeURIComponent(searchTerm)}&per_page=1`)
            .then(res => res.json())
            .then(data => {
                if (data.data && data.data.length > 0) {
                    populateCustomerDetail(data.data[0], record);
                } else {
                    populateCustomerDetail(record, record);
                }
            })
            .catch(() => populateCustomerDetail(record, record));
    } else {
        populateCustomerDetail(record, record);
    }

    const offcanvas = new bootstrap.Offcanvas(document.getElementById('customerDetail'));
    offcanvas.show();

    // Close sidebar on mobile when detail opens
    if (window.innerWidth < 768) {
        document.getElementById('sidebar').classList.remove('show');
    }
}

function openCustomerDetailFromData(customerData) {
    populateCustomerDetail(customerData, customerData);
    const offcanvas = new bootstrap.Offcanvas(document.getElementById('customerDetail'));
    offcanvas.show();

    if (window.innerWidth < 768) {
        document.getElementById('sidebar').classList.remove('show');
    }
}

function populateCustomerDetail(customer, renewal) {
    // Header
    document.getElementById('detail-name').textContent = customer.customer_name || '--';
    document.getElementById('detail-user-id').textContent = `ID: ${customer.user_id || customer.account_id || '--'}`;

    // Status badge
    const statusEl = document.getElementById('detail-status-badge');
    const status = String(customer.status || '').toLowerCase();
    if (status === '1' || status === 'active') {
        statusEl.className = 'badge ms-auto badge-active';
        statusEl.textContent = 'Active';
    } else if (status === '0' || status === 'inactive') {
        statusEl.className = 'badge ms-auto badge-inactive';
        statusEl.textContent = 'Inactive';
    } else if (renewal && renewal.category) {
        statusEl.className = `badge ms-auto badge-${renewal.category}`;
        statusEl.textContent = renewal.category.toUpperCase();
    } else {
        statusEl.className = 'badge ms-auto bg-secondary';
        statusEl.textContent = '--';
    }

    // Plan & Subscription
    document.getElementById('detail-plan').textContent = customer.plan_name || '--';
    document.getElementById('detail-plan-category').textContent = customer.plan_category || customer.category || '--';
    document.getElementById('detail-validity').textContent = customer.validity || '--';
    document.getElementById('detail-expiry').textContent = customer.expiry_date || '--';
    document.getElementById('detail-days').textContent = (renewal && renewal.days_remaining !== undefined) ? `${renewal.days_remaining} days` : '--';
    document.getElementById('detail-activation').textContent = customer.activation_date || '--';
    document.getElementById('detail-data-reset').textContent = customer.data_reset_date || '--';

    // Contact & Location
    document.getElementById('detail-mobile').textContent = customer.mobile || '--';
    document.getElementById('detail-email').textContent = customer.email || '--';
    document.getElementById('detail-zone').textContent = customer.zone_name || '--';
    document.getElementById('detail-area').textContent = customer.area || '--';
    document.getElementById('detail-building').textContent = customer.building || '--';
    document.getElementById('detail-flat').textContent = customer.flat_no || '--';
    document.getElementById('detail-address').textContent = customer.address || '--';

    // Network & Technical
    document.getElementById('detail-network-type').textContent = customer.network_type || '--';
    document.getElementById('detail-connectivity').textContent = customer.connectivity_mode || '--';
    document.getElementById('detail-mac').textContent = customer.mac || '--';
    document.getElementById('detail-onu').textContent = customer.onu_no || '--';
    document.getElementById('detail-static-ip').textContent = customer.static_ip || '--';
    document.getElementById('detail-kyc').textContent = customer.kyc_approved || '--';

    // Call button
    const callBtn = document.getElementById('detail-btn-call');
    if (customer.mobile) {
        callBtn.href = `tel:${customer.mobile}`;
    }

    // WhatsApp button - store record for sending
    const waBtn = document.getElementById('detail-btn-whatsapp');
    waBtn.onclick = () => {
        if (renewal && renewal.id) {
            openSendModal(renewal.id);
        } else {
            showToast('No renewal record linked to send message', 'warning');
        }
    };

    // Load message history
    loadMessageHistory(renewal ? renewal.id : null);
}

async function loadMessageHistory(renewalId) {
    const container = document.getElementById('detail-history');
    if (!renewalId) {
        container.innerHTML = '<p class="text-muted text-center small">No messages sent yet</p>';
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/logs?renewal_id=${renewalId}&per_page=10`);
        const data = await res.json();
        if (data.success && data.data && data.data.length > 0) {
            container.innerHTML = data.data.map(log => `
                <div class="msg-item ${log.status === 'failed' ? 'msg-failed' : ''}">
                    <div class="d-flex justify-content-between">
                        <span class="msg-template">${escapeHtml(log.template_name)}</span>
                        <span class="msg-status">${getDeliveryBadge(log.delivery_status || log.status)}</span>
                    </div>
                    <div class="msg-time">${log.sent_at || '--'} &bull; ${escapeHtml(log.operator_name || 'system')}</div>
                    ${log.error_message ? `<small class="text-danger">${escapeHtml(log.error_message)}</small>` : ''}
                </div>
            `).join('');
        } else {
            container.innerHTML = '<p class="text-muted text-center small">No messages sent yet</p>';
        }
    } catch (err) {
        container.innerHTML = '<p class="text-muted text-center small">Failed to load history</p>';
    }
}

// ============================================================
// Delivery Status Polling
// ============================================================

let statusPollInterval = null;

function startStatusPolling() {
    if (statusPollInterval) clearInterval(statusPollInterval);
    statusPollInterval = setInterval(refreshDeliveryStatuses, 30000);
}

async function refreshDeliveryStatuses() {
    if (state.viewMode !== 'renewals') return;

    const sentIds = state.records
        .filter(r => r.last_sent_at || r.delivery_status)
        .map(r => r.id);

    if (sentIds.length === 0) return;

    try {
        const res = await fetch(`${API_BASE}/delivery-status?ids=${sentIds.join(',')}`);
        const data = await res.json();

        if (data.success && data.statuses) {
            let updated = false;
            for (const record of state.records) {
                const statusInfo = data.statuses[record.id];
                if (statusInfo && statusInfo.delivery_status !== record.delivery_status) {
                    record.delivery_status = statusInfo.delivery_status;
                    record.last_sent_at = statusInfo.sent_at;
                    updated = true;
                }
            }
            if (updated) renderTable(state.records);
        }
    } catch (err) {
        console.debug('Status poll failed:', err);
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
    html += `<li class="page-item ${page === 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${page - 1}">&laquo;</a></li>`;

    const startPage = Math.max(1, page - 2);
    const endPage = Math.min(total_pages, page + 2);

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

    html += `<li class="page-item ${page === total_pages ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${page + 1}">&raquo;</a></li>`;

    paginationEl.innerHTML = html;

    paginationEl.querySelectorAll('.page-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const p = parseInt(e.target.dataset.page);
            if (p && p >= 1 && p <= total_pages) {
                state.currentPage = p;
                if (state.viewMode === 'customers') loadCustomers();
                else loadRecords();
                // Scroll to top on mobile
                window.scrollTo({ top: 0, behavior: 'smooth' });
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

    const template = TEMPLATE_MAP[record.category] || 'expiry_to_date';
    document.getElementById('modal-template').value = template;

    const param3Row = document.getElementById('param-3-row');
    if (template === 'recharge_today1') {
        document.getElementById('param-1').textContent = record.customer_name || 'Customer';
        document.getElementById('param-2').textContent = record.plan_name || '';
        document.getElementById('param-3').textContent = '';
        param3Row.style.display = 'none';
    } else if (template === 'expiry_to_date') {
        document.getElementById('param-1').textContent = record.plan_name || '';
        document.getElementById('param-2').textContent = record.expiry_date || '';
        document.getElementById('param-3').textContent = '';
        param3Row.style.display = 'none';
    } else {
        document.getElementById('param-1').textContent = record.customer_name || 'Customer';
        document.getElementById('param-2').textContent = record.plan_name || '';
        document.getElementById('param-3').textContent = record.expiry_date || '';
        param3Row.style.display = '';
    }

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

    let templateParams;
    if (templateName === 'recharge_today1') {
        templateParams = [record.customer_name || 'Customer', record.plan_name || ''];
    } else if (templateName === 'expiry_to_date') {
        templateParams = [record.plan_name || '', record.expiry_date || ''];
    } else {
        templateParams = [record.customer_name || 'Customer', record.plan_name || '', record.expiry_date || ''];
    }

    const payload = {
        renewal_id: record.id,
        template_name: templateName,
        params: templateParams,
        operator_name: 'operator',
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
            setTimeout(refreshDeliveryStatuses, 5000);
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
            loadCustomerStats();
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
    if (state.currentFilter && state.currentFilter !== 'all' && state.currentFilter !== 'customers') {
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

// Handle window resize - re-render table for mobile/desktop switch
let lastWidth = window.innerWidth;
window.addEventListener('resize', debounce(() => {
    const currentWidth = window.innerWidth;
    const crossedBreakpoint = (lastWidth < 768 && currentWidth >= 768) || (lastWidth >= 768 && currentWidth < 768);
    if (crossedBreakpoint) {
        if (state.viewMode === 'customers') renderCustomerTable(state.records);
        else renderTable(state.records);
    }
    lastWidth = currentWidth;
}, 250));

// Close sidebar when clicking outside on mobile
document.addEventListener('click', (e) => {
    if (window.innerWidth < 768) {
        const sidebar = document.getElementById('sidebar');
        const toggleBtn = document.getElementById('toggle-sidebar');
        if (sidebar.classList.contains('show') && !sidebar.contains(e.target) && !toggleBtn.contains(e.target)) {
            sidebar.classList.remove('show');
        }
    }
});
