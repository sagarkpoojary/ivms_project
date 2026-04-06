const REPORT_API_BASE = '/api/devices'; // Adjust if needed
const ONLINE_THRESHOLD_MS_REPORT = 15 * 60 * 1000;

async function fetchAndDownloadReport(uniqueId, period) {
    if (!uniqueId) {
        alert('No vehicle selected.');
        return;
    }

    try {
        // Fetch specific device data
        const r = await fetch(`/api/devices?uid=${encodeURIComponent(uniqueId)}&_t=${Date.now()}`, {
            credentials: 'same-origin'
        });

        if (!r.ok) {
            alert('Failed to fetch device data for report.');
            return;
        };

        const devices = await r.json();
        if (!devices || devices.length === 0) {
            alert('Device not found.');
            return;
        }

        const dev = devices[0];
        // Fetch distance (mimicking dashboard logic)
        // We'll need a separate call for distance or just default to 0 if not easily available 
        // effectively duplicating getDistance logic or making a combined call.
        // For now, let's try to fetch distance similarly to dashboard.

        let distance = 0;
        try {
            let distUrl = '/api/dashboard/distance?id=' + dev.id + '&_t=' + Date.now();

            // Simple Period Logic duplicating dashboard.js
            // Helper for Date Range
            const getDateRange = (p) => {
                const now = new Date();
                let start, end;
                switch (p) {
                    case 'Today':
                        start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0);
                        end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999);
                        break;
                    case 'Yesterday':
                        start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 0, 0, 0, 0);
                        end = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 23, 59, 59, 999);
                        break;
                    case 'This Week':
                        const dayOfWeek = now.getDay();
                        const diff = now.getDate() - dayOfWeek + (dayOfWeek === 0 ? -6 : 1);
                        start = new Date(now.getFullYear(), now.getMonth(), diff, 0, 0, 0, 0);
                        end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999);
                        break;
                    case 'This Month':
                        start = new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0, 0);
                        end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999);
                        break;
                    default: // 'Custom' not fully supported in this simple extraction without UI inputs for dates, defaulting to Today if not standard
                        start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0);
                        end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999);
                }
                const formatDate = date => date.toISOString();
                return { from: formatDate(start), to: formatDate(end) };
            };

            if (period && period !== 'Custom') {
                const { from, to } = getDateRange(period);
                distUrl += '&from=' + encodeURIComponent(from) + '&to=' + encodeURIComponent(to);
            }

            const rDist = await fetch(distUrl, { credentials: 'same-origin' });
            if (rDist.ok) {
                const jDist = await rDist.json();
                distance = Number(jDist.distance || 0);
            }
        } catch (e) {
            console.error('Error fetching distance for report', e);
        }

        // prepare data object expected by download function
        // The dashboard logic expected an array of items with { registered, device, distance }
        // We construct one such item.
        const item = {
            registered: {
                name: dev.name,
                unique_id: dev.uniqueId
            },
            device: dev, // The full device object from API
            distance: distance
        };

        generateAndDownloadHtml([item], period || 'Today');

    } catch (e) {
        console.error('Report generation error:', e);
        alert('An error occurred while generating the report.');
    }
}

function generateAndDownloadHtml(data, period) {
    if (!data || data.length === 0) return;
    const item = data[0];
    const { registered, device, distance } = item;

    let report = `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Vehicle Report - ${registered.name || registered.unique_id}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }
        h1, h2, h3 { color: #0d6efd; }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
        th { background-color: #f8f9fa; }
        .badge { padding: 6px 12px; border-radius: 6px; color: white; font-size: 0.9em; }
        .bg-success { background: #198754; }
        .bg-danger { background: #dc3545; }
        .bg-warning { background: #ffc107; }
        .bg-info { background: #0dcaf0; }
        .bg-secondary { background: #6c757d; }
    </style>
</head>
<body>
    <h1>Vehicle Report</h1>
    <h2>${registered.name || 'N/A'} (${registered.unique_id || 'N/A'})</h2>
    <p><strong>Period:</strong> ${period}</p>
    <p><strong>Total Distance:</strong> ${distance.toFixed(2)} km</p>
    <p><strong>Generated on:</strong> ${new Date().toLocaleString()}</p>

    ${device ? `
    <h3>Device Status</h3>
    <table>
        <tr><th>Last Update</th><td>${device.lastUpdate || 'N/A'}</td></tr>
        <tr><th>Status</th><td> 
            <span class="badge ${device.lastUpdate && (Date.now() - new Date(device.lastUpdate).getTime()) <= ONLINE_THRESHOLD_MS_REPORT ? 'bg-success' : 'bg-danger'}">
                ${device.lastUpdate && (Date.now() - new Date(device.lastUpdate).getTime()) <= ONLINE_THRESHOLD_MS_REPORT ? 'Online' : 'Offline'}
            </span>
        </td></tr>
    </table>
    
    ${device.position ? `
    <h3>Latest Position & Movement</h3>
    <table>
        <tr><th>Latitude</th><td>${device.position.latitude?.toFixed(6) || 'N/A'}</td></tr>
        <tr><th>Longitude</th><td>${device.position.longitude?.toFixed(6) || 'N/A'}</td></tr>
        <tr><th>Speed</th><td>${(device.position.speed ?? device.position.attributes?.speed ?? 0).toFixed(2)} km/h 
            <span class="badge ${(device.position.speed ?? 0) > 1 ? 'bg-info' : 'bg-secondary'}">
                ${(device.position.speed ?? 0) > 1 ? 'Moving' : 'Stopped'}
            </span>
        </td></tr>
        <tr><th>Ignition</th><td>
            <span class="badge ${(() => {
                    const ign = device.position.attributes?.ignition ?? device.position.ignition;
                    const on = ign === true || ign === "true" || ign === 1 || String(ign).toLowerCase() === "yes";
                    return on ? 'bg-warning' : 'bg-secondary';
                })()}">
                ${(() => {
                    const ign = device.position.attributes?.ignition ?? device.position.ignition;
                    const on = ign === true || ign === "true" || ign === 1 || String(ign).toLowerCase() === "yes";
                    return on ? 'ON' : 'OFF';
                })()}
            </span>
        </td></tr>
        <tr><th>Coordinates</th><td>${device.position.latitude?.toFixed(6) || 'N/A'}, ${device.position.longitude?.toFixed(6) || 'N/A'}</td></tr>
    </table>
    ` : '<p>No position data available.</p>'}
    ` : '<p>No device data available.</p>'}
    
    <hr>
    <footer style="margin-top: 50px; color: #666; font-size: 0.9em;">
        Report generated from Fleet Dashboard
    </footer>
</body>
</html>`;

    const blob = new Blob([report], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `Report_${(registered.name || registered.unique_id).replace(/[^a-z0-9]/gi, '_')}_${period}_${new Date().toISOString().slice(0, 10)}.html`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}
