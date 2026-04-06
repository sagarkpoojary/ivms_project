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
        // Group by company
        const summary = {};
        list.forEach(v => {
            const c = v.company_name || "Unassigned";
            if (!summary[c]) summary[c] = { name: c, online: 0, offline: 0, total: 0 };
            summary[c].total++;
            if (v.status === 'online') summary[c].online++;
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
            const hasPos = !!(v.position && v.position.latitude && v.position.longitude);
            const safeName = v.name.replace(/'/g, "\\'").replace(/"/g, '&quot;');

            tr.innerHTML = `
                <td style="padding:14px 18px;">${i + 1}</td>
                <td style="padding:14px 18px;"><strong>${esc(v.name)}</strong></td>
                <td style="padding:14px 18px;">${esc(v.unique_id)}</td>
                <td style="padding:14px 18px;">
                    <span class="badge ${v.status === 'online' ? 'bg-success' : 'bg-danger'}">
                        ${esc(v.status)}
                    </span>
                </td>
                <td style="padding:14px 18px;">${formatTime(v.lastUpdate)}</td>
                <td style="padding:14px 18px;">
                    ${hasPos ?
                    `<button class="btn btn-sm btn-outline-primary" onclick="showMap(${v.position.latitude}, ${v.position.longitude}, '${safeName}')">
                            <i class="fas fa-map-marker-alt me-1"></i> View on Map
                        </button>` :
                    `<span class="text-muted italic small">No fixed position</span>`
                }
                </td>
            `;
            body.appendChild(tr);
        });
    }
}

// Map logic
function showMap(lat, lng, name) {
    const container = document.getElementById("mapContainer");
    container.style.display = "block";
    document.getElementById("mapDeviceName").innerText = name;

    // Scroll to map
    container.scrollIntoView({ behavior: 'smooth' });

    if (!map) {
        map = L.map('reportMap').setView([lat, lng], 15);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors'
        }).addTo(map);
        marker = L.marker([lat, lng]).addTo(map);
    } else {
        map.setView([lat, lng], 15);
        marker.setLatLng([lat, lng]);
    }

    // Ensure map displays correctly if it was hidden
    setTimeout(() => {
        map.invalidateSize();
        map.panTo([lat, lng]);
    }, 200);

    marker.bindPopup(`<b>${name}</b><br>Lat: ${lat}<br>Lng: ${lng}`).openPopup();
}

// Refresh button logic
async function refresh() {
    const body = document.getElementById("devicesBody");
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
            company_name: v.company_name || "Unassigned",
            status: dev ? dev.status : "offline",
            lastUpdate: dev ? dev.lastUpdate : "-",
            position: dev ? dev.position : null
        });
    });

    document.getElementById("vehicleCount").innerText =
        `${TABLE.length} vehicles loaded`;

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
});
