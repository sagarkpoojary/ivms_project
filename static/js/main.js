let VEHICLES = [];
let SERVER_DEVICES = [];
let TABLE = [];
let map = null;
let marker = null;

// Escape HTML
function esc(v) {
    if (v === null || v === undefined) return "-";
    return v.toString()
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

// Format Last Update
function formatTime(iso) {
    if (!iso || iso === "-") return "-";
    try {
        const d = new Date(iso);
        return d.toLocaleString();
    } catch (e) {
        return iso;
    }
}

// Load registered vehicles.json
async function loadLocalVehicles() {
    try {
        const res = await fetch("/vehicle-list-json");
        const js = await res.json();
        if (!res.ok) {
            console.error('loadLocalVehicles failed:', js);
            VEHICLES = [];
            return;
        }
        VEHICLES = js.vehicles || [];
    } catch (err) {
        console.error("loadLocalVehicles error:", err);
        VEHICLES = [];
    }
}

// Load full devices from backend (using /api/devices for positions)
async function loadServerDevices() {
    try {
        const res = await fetch("/api/devices");
        const data = await res.json();
        if (!res.ok) {
            console.error('loadServerDevices failed:', data);
            SERVER_DEVICES = [];
            return;
        }
        SERVER_DEVICES = Array.isArray(data) ? data : [];
    } catch (err) {
        console.error("loadServerDevices error:", err);
        SERVER_DEVICES = [];
    }
}

// Render table rows
function renderTable(list) {
    const body = document.getElementById("devicesBody");
    body.innerHTML = "";
    const role = document.body.dataset.role;

    if (list.length === 0) {
        body.innerHTML = `
            <tr><td colspan="10" class="text-center py-4 text-muted">No data available</td></tr>
        `;
        return;
    }

    if (role === 'main_admin') {
        // Group by company logic (preserved)
        const summary = {};
        list.forEach(v => {
            const c = v.company_name || "Unassigned";
            if (!summary[c]) summary[c] = { name: c, online: 0, offline: 0, total: 0 };
            summary[c].total++;
            if (v.status === 'online' || v.status === 'active') summary[c].online++;
            else summary[c].offline++;
        });

        Object.values(summary).forEach((c, i) => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td style="padding:14px 18px;">${i + 1}</td>
                <td style="padding:14px 18px;"><strong>${esc(c.name)}</strong></td>
                <td style="padding:14px 18px;"><span class="badge bg-primary">${c.total} Vehicles</span></td>
                <td style="padding:14px 18px;"><span class="text-success fw-bold">${c.online}</span></td>
                <td style="padding:14px 18px;"><span class="text-danger">${c.offline}</span></td>
                <td style="padding:14px 18px;">
                    <a href="/user-manager" class="btn btn-sm btn-outline-secondary">
                        <i class="fas fa-users-cog me-1"></i> Manage Company
                    </a>
                </td>
            `;
            body.appendChild(tr);
        });
    } else {
        list.forEach((v, i) => {
            const tr = document.createElement("tr");
            tr.id = `row-${v.unique_id}`;
            const hasPos = !!(v.position && v.position.latitude && v.position.longitude);
            const safeName = (v.name || "").replace(/'/g, "\\'").replace(/"/g, '&quot;');

            tr.innerHTML = `
                <td style="padding:14px 18px;">${i + 1}</td>
                <td style="padding:14px 18px;"><strong>${esc(v.name)}</strong></td>
                <td style="padding:14px 18px;">${esc(v.device_model || "-")}</td>
                <td style="padding:14px 18px;">${esc(v.unique_id)}</td>
                <td style="padding:14px 18px;">${esc(v.driver_name || "-")}</td>
                <td style="padding:14px 18px;">
                    <span id="status-${v.unique_id}" class="badge ${v.status === 'online' || v.status === 'active' ? 'bg-success' : 'bg-danger'}">
                        ${esc(v.status)}
                    </span>
                    <span id="ign-${v.unique_id}" class="ms-1" style="display:none;"><i class="fas fa-bolt text-warning" title="Ignition ON"></i></span>
                </td>
                <td id="time-${v.unique_id}" style="padding:14px 18px; font-size: 0.85rem;">${formatTime(v.lastUpdate)}</td>
                <td style="padding:14px 18px;">
                    <div id="btn-container-${v.unique_id}">
                    ${hasPos ?
                    `<button class="btn btn-sm btn-outline-primary" onclick="showMap(${v.position.latitude}, ${v.position.longitude}, '${safeName}')">
                            <i class="fas fa-map-marker-alt me-1"></i> View
                        </button>` :
                    `<span class="text-muted italic small">No location</span>`
                    }
                    </div>
                </td>
            `;
            body.appendChild(tr);
        });
    }
}

// WebSocket Integration
function initLiveUpdates() {
    const wsUrl = `ws://${window.location.hostname}:8000/ws/live`;
    const socket = new WebSocket(wsUrl);

    socket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            updateRowLive(data);
        } catch (e) {
            console.error("WS Parse Error:", e);
        }
    };

    socket.onclose = () => {
        console.log("WS closed, retrying in 5s...");
        setTimeout(initLiveUpdates, 5000);
    };
}

function updateRowLive(data) {
    const imei = data.imei;
    const statusBadge = document.getElementById(`status-${imei}`);
    const timeCell = document.getElementById(`time-${imei}`);
    const ignIcon = document.getElementById(`ign-${imei}`);
    const btnContainer = document.getElementById(`btn-container-${imei}`);

    if (statusBadge) {
        statusBadge.className = "badge bg-success";
        statusBadge.innerText = data.speed > 0 ? "moving" : "online";
        if (data.speed > 0) statusBadge.innerText += ` (${data.speed} km/h)`;
    }
    if (timeCell) {
        timeCell.innerText = formatTime(data.timestamp);
    }
    if (ignIcon) {
        ignIcon.style.display = data.ignition ? "inline" : "none";
    }
    
    // Update button to new location
    if (btnContainer && data.latitude && data.longitude) {
        const safeName = data.vehicle_name.replace(/'/g, "\\'").replace(/"/g, '&quot;');
        btnContainer.innerHTML = `
            <button class="btn btn-sm btn-outline-primary" onclick="showMap(${data.latitude}, ${data.longitude}, '${safeName}')">
                <i class="fas fa-map-marker-alt me-1"></i> View
            </button>
        `;
    }
}

// Refresh button logic (preserved)
async function refresh() {
    const body = document.getElementById("devicesBody");
    if (!body) return;
    
    body.innerHTML = `
        <tr><td colspan="6" class="text-center py-4 text-muted">Loading...</td></tr>
    `;

    await loadLocalVehicles();
    await loadServerDevices();

    TABLE = [];

    VEHICLES.forEach(v => {
        const dev = SERVER_DEVICES.find(d => String(d.uniqueId) === String(v.unique_id));

        TABLE.push({
            name: v.name,
            unique_id: v.unique_id,
            device_model: v.device_model,
            driver_name: v.driver_name,
            company_name: v.company_name || "Unassigned",
            status: dev ? dev.status : "offline",
            lastUpdate: dev ? dev.lastUpdate : "-",
            position: dev ? dev.position : null
        });
    });

    const countEl = document.getElementById("vehicleCount");
    if (countEl) countEl.innerText = `${TABLE.length} vehicles loaded`;

    renderTable(TABLE);
}

// Init
document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("refresh");
    if (btn) btn.addEventListener("click", refresh);

    const searchInput = document.getElementById("search");
    if (searchInput) {
        searchInput.addEventListener("input", (e) => {
            const q = e.target.value.toLowerCase();
            const filtered = TABLE.filter(v =>
                v.name.toLowerCase().includes(q) ||
                v.unique_id.toString().toLowerCase().includes(q) ||
                v.company_name.toLowerCase().includes(q)
            );
            renderTable(filtered);
        });
    }

    refresh();
    initLiveUpdates();
});
