/* FINAL dashboard.js – Combined: Big Chart + Online/Offline + Moving/Stopped + Map + Alerts + Rules */

(() => {
    const REFRESH_MS = 30_000;
    const ONLINE_THRESHOLD_MS = 15 * 60 * 1000; // 15 minutes

    const $ = id => document.getElementById(id);

    // Color definitions based on standard bootstrap/tile styles
    const CHART_COLORS = {
        primary: '#007bff',
        success: '#28a745',
        warning: '#ffc107',
        danger: '#dc3545',
        info: '#17a2b8',
        secondary: '#6c757d',
        // Sunburst specific:
        online: '#28a745', // Success
        offline: '#dc3545', // Danger
        engineOn: '#ffc107', // Warning
        engineOff: '#17a2b8', // Info
        moving: '#007bff', // Primary
        stopped: '#6c757d', // Secondary
    };

    let registered = [];
    let latest = [];
    let deviceIdToNameMap = {};

    // CHART VARIABLES (UPDATED)
    let bigChart = null; // Used for Sunburst (or temporary Doughnut for visual replacement)
    let onlineOfflineChart = null; // Used for the new Pie/Doughnut chart
    let map = null;
    let markerLayer = null;
    let autoTimer = null;
    let isRefreshing = false;
    let cachedCombinedReport = null;
    let cachedCombinedReportKey = null;
    let pinnedDeviceId = localStorage.getItem('dashboardPinnedDeviceId') || "";

    const filterDevice = $('filterDevice');
    const filterPeriod = $('filterPeriod');
    const btnShow = $('btnShow');
    const btnRefreshNow = $('btnRefreshNow');


    const sumDevices = $('sumDevices');
    const sumDistance = $('sumDistance');
    const sumEngineHours = $('sumEngineHours');
    const sumFuel = $('sumFuel');



    // ------------------------
    // API WRAPPERS (No Changes Needed Here)
    // ------------------------
    const loadVehicles = async () => {
        const r = await fetch('/vehicle-list-json');
        const j = await r.json();
        const vehicles = j.vehicles || [];

        // Populate deviceIdToNameMap here
        deviceIdToNameMap = {};
        vehicles.forEach(v => {
            if (v.unique_id) {
                deviceIdToNameMap[v.unique_id] = v.name || v.unique_id;
            }
        });

        return vehicles;
    };

    const getDevice = async uid => {
        try {
            const r = await fetch('/api/devices?uid=' + encodeURIComponent(uid) + '&_t=' + Date.now(), {
                cache: 'no-cache',
                credentials: 'same-origin'
            });
            if (!r.ok) return null;
            const arr = await r.json();
            return Array.isArray(arr) && arr.length ? arr[0] : null;
        } catch (err) {
            console.error(`Error fetching device ${uid}:`, err);
            return null;
        }
    };

    function getDateRange(period) {
        // Force Oman Now regardless of browser timezone
        const omanNow = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Muscat" }));
        let start, end;

        const year = omanNow.getFullYear();
        const month = omanNow.getMonth();
        const date = omanNow.getDate();

        switch (period) {
            case 'Today':
                start = new Date(year, month, date, 0, 0, 0, 0);
                end = new Date(year, month, date, 23, 59, 59, 999);
                break;
            case 'Yesterday':
                start = new Date(year, month, date - 1, 0, 0, 0, 0);
                end = new Date(year, month, date - 1, 23, 59, 59, 999);
                break;
            case 'This Week':
                // Reset to Monday
                const day = omanNow.getDay();
                const diff = date - day + (day === 0 ? -6 : 1);
                start = new Date(year, month, diff, 0, 0, 0, 0);
                end = new Date(year, month, date, 23, 59, 59, 999);
                break;
            case 'This Month':
                start = new Date(year, month, 1, 0, 0, 0, 0);
                end = new Date(year, month, date, 23, 59, 59, 999);
                break;
            default:
                start = new Date(year, month, date, 0, 0, 0, 0);
                end = new Date(year, month, date, 23, 59, 59, 999);
        }

        // IMPORTANT: The app expects UTC strings in 2024-01-01T00:00:00Z format for Traccar API
        // However, we need to convert our 'Oman' start/end back to UTC.
        // Oman is UTC+4. So we subtract 4 hours from our Oman dates to get UTC.
        const toUTC = (d) => {
            const utc = new Date(d.getTime() - (4 * 60 * 60 * 1000));
            return utc.toISOString().split('.')[0] + 'Z';
        };

        return { from: toUTC(start), to: toUTC(end) };
    }

    const getDistance = async (id, period = null) => {
        try {
            let url = '/api/dashboard/distance?id=' + id + '&_t=' + Date.now();
            if (period && period !== 'Custom') {
                const { from, to } = getDateRange(period);
                url += '&from=' + encodeURIComponent(from) + '&to=' + encodeURIComponent(to);
            }
            const r = await fetch(url, { cache: 'no-cache', credentials: 'same-origin' });
            if (!r.ok) return 0;
            const j = await r.json();
            return Number(j.distance || 0);
        } catch (err) {
            console.error(`Error fetching distance for device ${id}:`, err);
            return 0;
        }
    };

    const getBulkSync = async (period = 'Today', uid = null) => {
        try {
            let url = `/api/dashboard/bulk-sync?period=${period}&_t=${Date.now()}`;
            if (uid) url += `&uid=${encodeURIComponent(uid)}`;
            const r = await fetch(url, { cache: 'no-cache', credentials: 'same-origin' });
            if (!r.ok) {
                const errorData = await r.json().catch(() => ({}));
                console.error('Bulk sync failed:', r.status, errorData);
                return null;
            }
            return await r.json();
        } catch (err) {
            console.error('Error fetching bulk sync:', err);
            return null;
        }
    };

    const getCombinedReport = async (deviceId, period, useCache = true) => {
        const cacheKey = `${deviceId}_${period}`;
        if (useCache && cachedCombinedReport && cachedCombinedReportKey === cacheKey) {
            return cachedCombinedReport;
        }
        try {
            const { from, to } = getDateRange(period);
            const url = `/api/dashboard/combined-report?deviceId=${deviceId}&from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&_t=${Date.now()}`;
            const r = await fetch(url, { cache: 'no-cache', credentials: 'same-origin' });
            if (r.ok) {
                const data = await r.json();
                cachedCombinedReport = data;
                cachedCombinedReportKey = cacheKey;
                return data;
            } else {
                return null;
            }
        } catch (err) {
            console.error(`Error fetching combined report:`, err);
            return null;
        }
    };

    // ------------------------
    // NEW CHART INITIALIZATION & UPDATE
    // ------------------------

    // --- 1. Sunburst Chart (Nested Doughnut) ---
    function initBigChart() {
        const ctx = $('chartBig')?.getContext('2d');
        if (!ctx) return;

        bigChart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: [],
                datasets: []
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                layout: {
                    padding: { top: 10, bottom: 10 }
                },
                plugins: {
                    legend: {
                        display: false // Hide default legend
                    },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                return ` ${context.dataset.label || ''}: ${context.raw}`;
                            }
                        }
                    }
                }
            }
        });
    }

    // --- Helper: Robust Ignition Check ---
    function isVehicleIgnitionOn(d) {
        if (!d || !d.device) return false;
        const pos = d.device.position || {};
        const posAttrs = pos.attributes || {};
        const devAttrs = d.device.attributes || {};

        // Priority: Position Attributes -> Position Root -> Device Attributes -> Device Status (if exists)
        // Check all possible casing
        let ign = posAttrs.ignition ?? posAttrs.Ignition ?? pos.ignition ?? devAttrs.ignition ?? devAttrs.Ignition;

        if (ign === undefined || ign === null) {
            // Fallback: If ignition data is missing, assume Engine ON if the vehicle is moving significantly.
            // Speed is usually in knots in Traccar raw data, but let's check > 1 to be safe.
            const speed = Number(pos.speed ?? posAttrs.speed ?? 0);
            return speed > 2; // Threshold to avoid GPS drift noise
        }

        // Normalize
        return ign === true || ign === "true" || ign === 1 || ign === "1" || String(ign).toLowerCase() === "yes";
    }

    /**
     * Updates the main chart with 3-Level Nested Data
     * Level 1 (Inner): Status (Online/Offline)
     * Level 2 (Middle): Engine (ON/OFF)
     * Level 3 (Outer): Motion (Moving/Stopped)
     */
    function updateBigChart(allDevicesData) {
        if (!bigChart) return;

        // 1. Calculate Hierarchical Counts
        const stats = {
            online: 0, offline: 0,

            // Online Sub-states
            on_engOn: 0, on_engOff: 0,

            // Engine ON Sub-states
            on_engOn_mov: 0, on_engOn_stop: 0,

            // Engine OFF Sub-states (Assuming Engine OFF = Stopped)
            on_engOff_stop: 0,

            // Offline Sub-states (All unknown/neutral)
            off_unknown: 0
        };

        allDevicesData.forEach(d => {
            // Level 1: Status — trust Traccar's own status field (online/offline/unknown)
            const isOnline = d.device?.status && d.device.status !== 'offline';

            if (!isOnline) {
                stats.offline++;
                stats.off_unknown++; // Propagates through levels
                return;
            }
            stats.online++;

            // Level 2: Engine
            const isIgnOn = isVehicleIgnitionOn(d);

            if (isIgnOn) {
                stats.on_engOn++;
                // Level 3: Motion
                const pos = d.device?.position || {};
                const attrs = pos.attributes || {};
                const speed = Number(pos.speed ?? attrs.speed ?? 0);
                if (speed > 1) {
                    stats.on_engOn_mov++;
                } else {
                    stats.on_engOn_stop++;
                }
            } else {
                stats.on_engOff++;
                // Engine OFF implies Stopped for this chart
                stats.on_engOff_stop++;
            }
        });

        // 2. Build Datasets (Inner to Outer)

        // Dataset 1: Status
        const ds1 = {
            label: 'Status',
            data: [stats.online, stats.offline],
            backgroundColor: [CHART_COLORS.online, CHART_COLORS.offline],
            borderWidth: 2,
            weight: 1
        };

        // Dataset 2: Engine
        // Order must match ds1: [Online Subsegments, Offline Subsegments]
        // Online Breakdown: [Engine ON, Engine OFF]
        const ds2 = {
            label: 'Ignition',
            data: [
                stats.on_engOn, stats.on_engOff, // Under Online
                stats.offline                    // Under Offline (Preserve arc)
            ],
            backgroundColor: [
                CHART_COLORS.engineOn, CHART_COLORS.engineOff, // Online breakdown
                CHART_COLORS.offline                           // Offline block
            ],
            borderWidth: 2,
            weight: 1
        };

        // Dataset 3: Motion
        // Order must match ds2: [EngON Subsegments, EngOFF Subsegments, Offline Subsegments]
        // EngON Breakdown: [Moving, Stopped]
        const ds3 = {
            label: 'Motion',
            data: [
                stats.on_engOn_mov, stats.on_engOn_stop, // Under Engine ON
                stats.on_engOff_stop,                    // Under Engine OFF
                stats.offline                            // Under Offline
            ],
            backgroundColor: [
                CHART_COLORS.moving, CHART_COLORS.stopped, // EngON breakdown
                CHART_COLORS.stopped,                      // EngOFF breakdown
                CHART_COLORS.offline                       // Offline block
            ],
            borderWidth: 2,
            weight: 1
        };

        bigChart.data.datasets = [ds1, ds2, ds3];
        bigChart.data.labels = ['Status', 'Ignition', 'Motion']; // Generic labels
        bigChart.update();

        // 3. Render Custom Legend
        renderCustomChartLegend();
    }

    function renderCustomChartLegend() {
        let legend = $('customChartLegend');

        // Auto-inject legend container if missing (handles cached HTML issues)
        if (!legend) {
            const chartCanvas = $('chartBig');
            if (chartCanvas && chartCanvas.parentElement) {
                const container = document.createElement('div');
                container.id = 'customChartLegend';
                container.className = 'd-flex justify-content-center flex-wrap gap-3 mt-3 small text-muted';
                chartCanvas.parentElement.parentElement.appendChild(container); // Append to card
                legend = container;

                // Also fix title if we are injecting (likely means HTML is old)
                const title = $('bigChartTitle');
                if (title) title.innerHTML = '<i class="fas fa-chart-pie me-2 text-primary"></i>Fleet Movement & Utilization (3-Level)';
            } else {
                return;
            }
        }

        const items = [
            { label: 'Online', color: CHART_COLORS.online },
            { label: 'Offline', color: CHART_COLORS.offline },
            { label: 'Engine ON', color: CHART_COLORS.engineOn },
            { label: 'Engine OFF', color: CHART_COLORS.engineOff },
            { label: 'Moving', color: CHART_COLORS.moving },
            { label: 'Stopped', color: CHART_COLORS.stopped }
        ];

        legend.innerHTML = items.map(i => `
            <div class="d-flex align-items-center">
                <span style="width:12px; height:12px; background-color:${i.color}; border-radius:3px; display:inline-block; margin-right:6px;"></span>
                <span>${i.label}</span>
            </div>
        `).join('');
    }


    // --- 2. Online/Offline Pie Chart ---
    function initOnlineOfflineChart() {
        const ctx = $('chartPieOnlineOffline')?.getContext('2d');
        if (!ctx) return;

        onlineOfflineChart = new Chart(ctx, {
            type: 'pie',
            data: {
                labels: ['Online', 'Offline'],
                datasets: [{
                    data: [0, 0], // Initial data
                    backgroundColor: [CHART_COLORS.online, CHART_COLORS.offline],
                    hoverBackgroundColor: [CHART_COLORS.online, CHART_COLORS.offline]
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            boxWidth: 10,
                            font: { size: 10 }
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                let label = context.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                if (context.parsed !== null) {
                                    label += context.parsed;
                                }
                                return label;
                            }
                        }
                    }
                }
            }
        });
    }

    function updateOnlineOfflineChart(onlineCount, offlineCount) {
        if (!onlineOfflineChart) return;
        onlineOfflineChart.data.datasets[0].data = [onlineCount, offlineCount];
        onlineOfflineChart.update('none');
    }

    // --- Map and Title Updates (Minor change to remove old title function) ---

    function initMap() {
        const mapEl = $('vehicleMap');
        if (!mapEl) return;
        map = L.map('vehicleMap').setView([0, 0], 2);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors'
        }).addTo(map);
        markerLayer = L.layerGroup().addTo(map);
    }

    function updateMap(data) {
        if (!map || !markerLayer) return;
        markerLayer.clearLayers();
        const bounds = [];
        const role = document.body.dataset.role;

        data.forEach(d => {
            if (!d.device?.position?.latitude || !d.device?.position?.longitude) return;
            const pos = d.device.position;
            const lat = pos.latitude, lng = pos.longitude;

            let displayName = d.registered.name || d.registered.unique_id;
            if (role === 'main_admin') {
                displayName = d.registered.company_name || "Assigned Company";
            }

            const isOnline = d.device?.status && d.device.status !== 'offline';
            const speed = Number(pos.speed ?? pos.attributes?.speed ?? 0);
            const isMoving = speed > 1;
            const color = isOnline && isMoving ? 'green' : isOnline ? 'orange' : 'red';

            // --- PHASE 5: Trust Hardening (Confidence) ---
            const confidence = d.device.confidence || d.confidence || (pos.attributes?.satellites >= 8 ? 1.0 : (pos.attributes?.satellites >= 4 ? 0.7 : 0.4));
            const confColor = confidence >= 0.9 ? 'text-success' : (confidence >= 0.6 ? 'text-warning' : 'text-danger');
            const confLabel = confidence >= 0.9 ? 'High' : (confidence >= 0.6 ? 'Medium' : 'Low');
            // ---------------------------------------------

            // Custom marker icon based on status
            const icon = L.divIcon({
                className: 'custom-marker',
                html: `
                    <div style="
                        width:18px;
                        height:18px;
                        border-radius:50%;
                        background:#fff;
                        border:1px solid rgba(0,0,0,0.2);
                        box-shadow:0 1px 4px rgba(0,0,0,0.35);
                        display:flex;
                        align-items:center;
                        justify-content:center;">
                        <i class="fas fa-car-side" style="font-size:10px;color:${color};"></i>
                    </div>
                `,
                iconSize: [18, 18],
                iconAnchor: [9, 9]
            });

            const marker = L.marker([lat, lng], { icon }).addTo(markerLayer);
            
            const driverName = d.device.driver_name || "No Driver";
            const rfid = d.device.position?.attributes?.rfid || d.device.rfid || "N/A";

            marker.bindPopup(`
                <div class="popup-content">
                    <strong class="d-block mb-1">${displayName}</strong>
                    <div class="small mb-1">
                        <i class="fas fa-user-circle me-1 text-primary"></i> <strong>Driver:</strong> ${driverName}
                    </div>
                    <div class="small mb-1">
                        <i class="fas fa-id-card me-1 text-secondary"></i> <strong>RFID:</strong> ${rfid}
                    </div>
                    <div class="small mb-1">
                        <i class="fas fa-info-circle me-1"></i> <strong>Status:</strong> ${isOnline ? 'Online' : 'Offline'}
                    </div>
                    <div class="small mb-1">
                        <i class="fas fa-tachometer-alt me-1"></i> <strong>Speed:</strong> ${speed.toFixed(1)} km/h
                    </div>
                    <div class="small mt-1 pt-1 border-top">
                        <i class="fas fa-shield-alt me-1 ${confColor}"></i> <strong class="${confColor}">Confidence:</strong> ${confLabel} (${(confidence * 100).toFixed(0)}%)
                    </div>
                </div>
            `);

            // Critical Fix: Attach unique ID for reliable looking up in focusOnVehicle
            marker.uniqueId = String(d.registered.unique_id);

            bounds.push([lat, lng]);
        });
        if (bounds.length > 0) map.fitBounds(bounds, { padding: [50, 50], maxZoom: 14 });
    }

    // ------------------------
    // TOP COUNTS & STATUS TILES (Used to calculate counts for charts)
    // ------------------------
    function populateDeviceList(elementId, devices) {
        const listEl = document.getElementById(elementId);
        if (!listEl) return;
        const role = document.body.dataset.role;

        if (devices.length === 0) {
            listEl.innerHTML = `<p class="text-muted small p-1 mb-0">No devices.</p>`;
            return;
        }

        const listHTML = devices.map(deviceData => {
            const uniqueId = deviceData.registered.unique_id;
            // Ensure ID is passed as string to avoid JS conversion issues
            let displayName = deviceIdToNameMap[uniqueId] || uniqueId;
            if (role === 'main_admin') {
                displayName = deviceData.registered.company_name || "Company Asset";
            }
            
            const driverName = deviceData.device.driver_name || "No Driver";
            return `
                <div class="device-item d-flex justify-content-between align-items-center" onclick="window.focusOnVehicle('${uniqueId}')">
                    <span>${displayName}</span>
                    <span class="small text-muted" style="font-size: 0.65rem;">
                        <i class="fas fa-user-circle me-1"></i>${driverName}
                    </span>
                </div>`;
        }).join('');

        listEl.innerHTML = listHTML;
    }

    // Expose focusOnVehicle globally for onclick handlers
    window.focusOnVehicle = (uniqueId) => {
        const targetId = String(uniqueId);

        // Persist selection so subsequent refreshes/websocket updates keep map scoped.
        pinnedDeviceId = targetId;
        localStorage.setItem('dashboardPinnedDeviceId', pinnedDeviceId);
        if (filterDevice) {
            filterDevice.value = targetId;
        }

        // Immediate focus if marker exists in current layer.
        if (markerLayer && map) {
            markerLayer.eachLayer(layer => {
                if (layer.uniqueId === targetId) {
                    map.setView(layer.getLatLng(), 16);
                    layer.openPopup();
                }
            });
        }

        // Trigger normal refresh flow (same as manual device filter change).
        if (filterDevice) {
            filterDevice.dispatchEvent(new Event('change'));
        } else {
            refreshAll();
        }

        const mapEl = $('vehicleMap');
        if (mapEl) mapEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    };

    function updateCounts(data) {
        const totalDevices = data.length;

        // 1. Calculate Live Status Metrics — trust Traccar's own status field
        const online = data.filter(d => d.device?.status && d.device.status !== 'offline').length;
        const offline = totalDevices - online;

        const ignOn = data.filter(d => isVehicleIgnitionOn(d)).length;
        const ignOff = totalDevices - ignOn;

        const stopped = data.filter(d => {
            // Check for position and speed <= 1
            if (d.device?.position) {
                const speed = Number(d.device.position.speed ?? d.device.position.attributes?.speed ?? 0);
                return speed <= 1;
            }
            // Offline/no pos is considered stopped if device is registered
            return true;
        }).length;

        const moving = totalDevices - stopped;

        // 2. Update Performance Overview (Top Row)
        if (sumDevices) sumDevices.textContent = totalDevices;
        // sumDistance, sumEngineHours, sumFuel are updated in refreshAll() using period data

        // 4. Update the hover lists for all status categories
        // MOVED UP to fix ReferenceError (TDZ)
        const onlineDevices = data.filter(d => d.device?.status && d.device.status !== 'offline');
        const offlineDevices = data.filter(d => !d.device?.status || d.device.status === 'offline');
        const stoppedDevices = data.filter(d => {
            if (d.device?.position) {
                const speed = Number(d.device.position.speed ?? d.device.position.attributes?.speed ?? 0);
                return speed <= 1;
            }
            return true;
        });
        const movingDevices = data.filter(d => {
            if (d.device?.position) {
                const speed = Number(d.device.position.speed ?? d.device.position.attributes?.speed ?? 0);
                return speed > 1;
            }
            return false;
        });
        const idleDevices = data.filter(d => {
            if (!d.device?.position) return false;
            const pos = d.device.position;
            const speed = Number(pos.speed ?? pos.attributes?.speed ?? 0);
            return isVehicleIgnitionOn(d) && speed <= 1;
        });

        // 3. Update Status Tiles (Middle Row)
        const metrics = {
            'metricOnline': online,
            'metricOffline': offline,
            'metricTotalDevices': totalDevices,
            'metricStopped': stopped,
            'metricMoving': moving,
            'metricIdle': idleDevices.length
        };

        Object.entries(metrics).forEach(([id, val]) => {
            const el = $(id);
            if (el) el.textContent = val;
        });

        // Also update sub-metrics if they exist
        if ($('metricEngineOn')) $('metricEngineOn').textContent = ignOn;
        if ($('metricEngineOff')) $('metricEngineOff').textContent = ignOff;

        populateDeviceList('onlineDeviceList', onlineDevices);
        populateDeviceList('offlineDeviceList', offlineDevices);
        populateDeviceList('totalDeviceList', data);
        populateDeviceList('stoppedDeviceList', stoppedDevices);
        populateDeviceList('movingDeviceList', movingDevices);
        populateDeviceList('idleDeviceList', idleDevices);

        // 5. UPDATE CHARTS WITH NEW COUNTS
        updateOnlineOfflineChart(online, offline);
        // updateBigChart is now called directly from refreshAll() with the full data array.
    }



    // ------------------------
    // ALERTS & RULES (PLACEHOLDERS) (No Changes Needed Here)
    // ------------------------
    async function loadAlerts() {
        const alertAreaEvents = $('alertAreaEvents');
        if (!alertAreaEvents) return;

        try {
            const r = await fetch('/api/alerts?_t=' + Date.now());
            if (!r.ok) throw new Error('Bad status');
            const events = await r.json();

            if (!events || events.length === 0) {
                alertAreaEvents.innerHTML = `<p class="text-muted small">No recent alerts.</p>`;
                return;
            }

            // Simple event display - can be enhanced later if needed
            alertAreaEvents.innerHTML = events.map(ev => {
                const date = new Date(ev.eventTime).toLocaleString();
                const type = ev.type === 'deviceOverspeed' ? 'Overspeed' : ev.type;
                const deviceName = deviceIdToNameMap[ev.uniqueId] || ev.deviceName || 'Unknown Device';
                return `
                    <div class="alert-item mb-2 pb-2 border-bottom">
                        <div class="d-flex justify-content-between align-items-center mb-1">
                            <span class="badge bg-danger rounded-pill x-small">${type}</span>
                            <span class="text-muted" style="font-size: 0.7rem;">${date}</span>
                        </div>
                        <div class="small fw-bold text-dark">${deviceName}</div>
                    </div>
                `;
            }).join('');

        } catch (err) {
            console.error('Failed to load alerts:', err);
            alertAreaEvents.innerHTML = `<p class="text-danger small">Alerts feed temporarily unavailable.</p>`;
        }
    }

    async function loadRules() {
        const tbody = $('rulesTable');
        if (!tbody) { /* Placeholder for your rules API logic */ return; }
    }

    async function updateAlertBadge() {
        const badge = $('alertBadge');
        if (!badge) { /* Placeholder for your badge update logic */ return; }
    }

    // ------------------------
    // MAIN REFRESH
    // ------------------------
    let isFirstLoad = true;

    async function refreshAll() {
        if (isRefreshing) return;
        isRefreshing = true;

        // Visual Feedback for Refresh Button
        const btnIcon = btnRefreshNow?.querySelector('i');
        if (btnIcon) btnIcon.classList.add('fa-spin');
        if (btnRefreshNow) btnRefreshNow.disabled = true;

        try {
            registered = await loadVehicles();

            if (registered.length === 0) {
                // Handle empty fleet case
                if (sumDevices) sumDevices.textContent = "0";
                if (sumDistance) sumDistance.textContent = "No data available";
                if (sumIgnOn) sumIgnOn.textContent = "--";
                if (sumIgnOff) sumIgnOff.textContent = "--";

                ['metricOnline', 'metricOffline', 'metricTotalDevices', 'metricStopped', 'metricMoving', 'metricIdle'].forEach(id => {
                    if ($(id)) $(id).textContent = "0";
                });

                if (onlineOfflineChart) {
                    onlineOfflineChart.data.datasets[0].data = [0, 0];
                    onlineOfflineChart.update();
                }

                const loader = $('dashboardLoader');
                if (loader) loader.classList.add('hidden');
                return;
            }

            // Populate filter if needed
            if (filterDevice && filterDevice.options.length <= 1) {
                const currentVal = pinnedDeviceId || filterDevice.value;
                filterDevice.innerHTML = '<option value="">All Devices</option>';
                registered.forEach(v => {
                    const opt = new Option(v.name || v.unique_id, v.unique_id);
                    filterDevice.appendChild(opt);
                });
                filterDevice.value = currentVal;
            }

            const selectedPeriod = filterPeriod?.value || 'Today';
            const selectedDeviceId = pinnedDeviceId || filterDevice?.value || "";

            // USE BULK SYNC INSTEAD OF N+1 CALLS
            const bulkData = await getBulkSync(selectedPeriod);
            if (!bulkData || !bulkData.devices) {
                console.warn("Bulk sync returned empty or error");
                return;
            }

            // Map bulk results to our required format
            const allDevicesData = bulkData.devices.map(d => {
                const uid = d.uniqueId || d.imei;
                const name = d.name || d.vehicle_name || "Unknown Vehicle";
                const reg = registered.find(v => String(v.unique_id) === String(uid)) || { unique_id: uid, name: name };
                const summary = bulkData.summaries[uid] || { distance: 0, engineHours: 0, fuelLiters: 0, fuelCost: 0 };
                
                // Add safe driver name fallback
                if (!d.driver_name || d.driver_name === 'None') {
                    d.driver_name = 'No Driver Assigned';
                }
                
                // Construct a Traccar-compatible device schema for the frontend
                const normalizedDevice = {
                    id: uid,
                    uniqueId: uid,
                    name: name,
                    status: d.status || 'offline',
                    lastUpdate: d.timestamp,
                    driver_name: d.driver_name,
                    rfid: d.rfid,
                    confidence: d.confidence || 1.0,
                    position: {
                        latitude: d.latitude,
                        longitude: d.longitude,
                        speed: d.speed || 0,
                        attributes: {
                            ignition: d.ignition,
                            satellites: 8,
                            batteryLevel: d.bat_v ? parseInt(d.bat_v * 10) : 0,
                            rfid: d.rfid
                        }
                    }
                };
                
                return { 
                    registered: reg, 
                    device: normalizedDevice, 
                    distance: summary.distance || 0,
                    engineHours: summary.engineHours || 0,
                    fuelLiters: summary.fuelLiters || 0,
                    fuelCost: summary.fuelCost || 0
                };
            });

            // Filter for displayed data if a specific device is selected
            if (selectedDeviceId) {
                latest = allDevicesData.filter(d => String(d.registered.unique_id) === String(selectedDeviceId));
            } else {
                latest = allDevicesData;
            }

            updateCounts(allDevicesData);
            updateBigChart(allDevicesData);
            updateMap(latest);

            const totals = latest.reduce((s, d) => {
                s.distance += (d.distance || 0);
                s.engineHours += (d.engineHours || 0);
                s.fuelLiters += (d.fuelLiters || 0);
                s.fuelCost += (d.fuelCost || 0);
                return s;
            }, { distance: 0, engineHours: 0, fuelLiters: 0, fuelCost: 0 });

            if (sumDistance) {
                sumDistance.textContent = totals.distance.toFixed(2) + " km";
            }
            if (sumEngineHours) {
                sumEngineHours.textContent = totals.engineHours.toFixed(1) + " h";
            }
            if (sumFuel) {
                sumFuel.textContent = `${totals.fuelLiters.toFixed(1)} L (${totals.fuelCost.toFixed(3)} OMR)`;
            }

            loadAlerts();
            updateAlertBadge();

        } catch (err) {
            console.error('Error in refreshAll:', err);
        } finally {
            isRefreshing = false;

            // Remove Visual Feedback
            if (btnIcon) btnIcon.classList.remove('fa-spin');
            if (btnRefreshNow) btnRefreshNow.disabled = false;

            // Hide global loader after first successful attempt
            if (isFirstLoad) {
                const loader = $('dashboardLoader');
                if (loader) loader.classList.add('hidden');
                isFirstLoad = false;
            }
        }
    }

    // ------------------------
    // EVENTS & AUTO REFRESH (No Changes Needed Here)
    // ------------------------
    btnShow?.addEventListener('click', () => { cachedCombinedReport = null; refreshAll(); });
    btnRefreshNow?.addEventListener('click', () => { cachedCombinedReport = null; refreshAll(); });
    filterDevice?.addEventListener('change', () => {
        pinnedDeviceId = filterDevice.value || "";
        localStorage.setItem('dashboardPinnedDeviceId', pinnedDeviceId);
        cachedCombinedReport = null;
        refreshAll();
    });
    filterPeriod?.addEventListener('change', () => { cachedCombinedReport = null; refreshAll(); });

    const startAuto = () => {
        clearInterval(autoTimer);
        autoTimer = setInterval(refreshAll, REFRESH_MS);
    };

    // Expose for WebSocket integration
    window.updateSingleVehicleLive = (data) => {
        // data format: {imei, latitude, longitude, speed, ...}
        const imei = String(data.imei);
        let found = false;
        
        // Update the 'latest' array which is used for rendering
        latest.forEach(d => {
            if (String(d.registered.unique_id) === imei) {
                if (data.status !== undefined) d.device.status = data.status;
                if (data.driver_id !== undefined) d.device.driver_id = data.driver_id;
                if (data.driver_name !== undefined) d.device.driver_name = data.driver_name;
                if (data.rfid !== undefined) d.device.rfid = data.rfid;
                
                // Only update position if it's a real telemetry packet
                if (data.latitude !== undefined && data.longitude !== undefined) {
                    d.device.position = {
                        deviceId: d.device.id,
                        latitude: data.latitude,
                        longitude: data.longitude,
                        speed: data.speed,
                        course: data.angle,
                        altitude: data.altitude,
                        deviceTime: data.timestamp,
                        attributes: {
                            sat: data.satellites,
                            batteryLevel: data.bat_v ? parseInt(data.bat_v * 10) : 0,
                            rfid: data.rfid
                        }
                    };
                }
                found = true;
            }
        });

        if (found) {
            const selectedDeviceId = pinnedDeviceId || (filterDevice?.value ? String(filterDevice.value) : "");
            const displayed = selectedDeviceId
                ? latest.filter(d => String(d.registered.unique_id) === selectedDeviceId)
                : latest;

            updateCounts(displayed);
            updateBigChart(displayed);
            updateMap(displayed);
        }
    };

    // ------------------------
    // INIT
    // ------------------------
    document.addEventListener('DOMContentLoaded', () => {
        initBigChart(); // Now initializes the mock Sunburst (Doughnut)
        initOnlineOfflineChart(); // NEW: Initializes the small Pie chart
        initMap();
        loadRules();
        refreshAll();
        startAuto();
        setInterval(loadAlerts, 30000);
        loadAlerts();
    });
})();