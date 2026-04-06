/* reports.js - Daily Reports Page */

(() => {
  // Chart instances
  let idleMovingChart = null;
  let engineStatusChart = null;

  // DOM elements
  const reportVehicle = document.getElementById('reportVehicle');
  const reportDate = document.getElementById('reportDate');
  const btnGenerateReport = document.getElementById('btnGenerateReport');
  const btnExportPDF = document.getElementById('btnExportPDF');
  
  const reportLoading = document.getElementById('reportLoading');
  const reportError = document.getElementById('reportError');
  const reportContent = document.getElementById('reportContent');

  // ========================================
  // INITIALIZE
  // ========================================
  async function init() {
    // Set today's date as default
    const today = new Date();
    reportDate.value = today.toISOString().split('T')[0];

    // Load vehicles
    await loadVehicles();

    // Initialize charts
    initIdleMovingChart();
    initEngineStatusChart();

    // Event listeners
    btnGenerateReport.addEventListener('click', generateReport);
  }

  // ========================================
  // LOAD VEHICLES
  // ========================================
  async function loadVehicles() {
    try {
      const res = await fetch('/vehicle-list-json');
      const data = await res.json();
      const vehicles = data.vehicles || [];

      vehicles.forEach(v => {
        const option = new Option(v.name, v.unique_id);
        reportVehicle.appendChild(option);
      });
    } catch (err) {
      console.error('Error loading vehicles:', err);
      showError('Failed to load vehicles list');
    }
  }

  // ========================================
  // CHART INITIALIZATION
  // ========================================
  function initIdleMovingChart() {
    const ctx = document.getElementById('idleMovingChart');
    if (!ctx) return;

    idleMovingChart = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: ['Idle Time', 'Moving Time'],
        datasets: [{
          data: [0, 0],
          backgroundColor: ['#ffc107', '#0d6efd'],
          borderWidth: 0
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom'
          },
          tooltip: {
            callbacks: {
              label: function(context) {
                const hours = (context.parsed / 3600).toFixed(2);
                return `${context.label}: ${hours} hours`;
              }
            }
          }
        }
      }
    });
  }

  function initEngineStatusChart() {
    const ctx = document.getElementById('engineStatusChart');
    if (!ctx) return;

    engineStatusChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: ['Engine ON', 'Engine OFF'],
        datasets: [{
          label: 'Time (hours)',
          data: [0, 0],
          backgroundColor: ['#198754', '#dc3545'],
          borderWidth: 0
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: {
            beginAtZero: true,
            title: {
              display: true,
              text: 'Hours'
            }
          }
        },
        plugins: {
          legend: {
            display: false
          }
        }
      }
    });
  }

  // ========================================
  // DATE RANGE CALCULATION
  // ========================================
  function getDateRange(dateStr) {
    const date = new Date(dateStr);
    const start = new Date(date.getFullYear(), date.getMonth(), date.getDate(), 0, 0, 0, 0);
    const end = new Date(date.getFullYear(), date.getMonth(), date.getDate(), 23, 59, 59, 999);
    
    return {
      from: start.toISOString(),
      to: end.toISOString()
    };
  }

  // ========================================
  // GENERATE REPORT
  // ========================================
  async function generateReport() {
    const vehicleId = reportVehicle.value;
    const dateStr = reportDate.value;

    if (!vehicleId) {
      showError('Please select a vehicle');
      return;
    }

    if (!dateStr) {
      showError('Please select a date');
      return;
    }

    // Show loading
    reportContent.style.display = 'none';
    reportError.style.display = 'none';
    reportLoading.style.display = 'block';
    btnExportPDF.disabled = true;

    try {
      // Get device info
      const device = await getDevice(vehicleId);
      if (!device) {
        throw new Error('Vehicle not found in Traccar system');
      }

      const dateRange = getDateRange(dateStr);

      // Fetch all report data
      const [combinedReport, distance] = await Promise.all([
        getCombinedReport(device.id, dateRange),
        getDistance(device.id, dateRange)
      ]);

      // Process and display report
      displayReport({
        vehicle: reportVehicle.options[reportVehicle.selectedIndex].text,
        vehicleId: vehicleId,
        date: dateStr,
        distance: distance,
        combinedReport: combinedReport
      });

      btnExportPDF.disabled = false;
      reportLoading.style.display = 'none';
      reportContent.style.display = 'block';

    } catch (err) {
      console.error('Error generating report:', err);
      reportLoading.style.display = 'none';
      showError(`Failed to generate report: ${err.message}`);
    }
  }

  // ========================================
  // API CALLS
  // ========================================
  async function getDevice(uid) {
    try {
      const res = await fetch(`/api/devices?uid=${encodeURIComponent(uid)}&_t=${Date.now()}`, {
        cache: 'no-cache'
      });
      if (!res.ok) return null;
      const arr = await res.json();
      return Array.isArray(arr) && arr.length ? arr[0] : null;
    } catch (err) {
      console.error('Error fetching device:', err);
      return null;
    }
  }

  async function getDistance(deviceId, dateRange) {
    try {
      const url = `/api/dashboard/distance?id=${deviceId}&from=${encodeURIComponent(dateRange.from)}&to=${encodeURIComponent(dateRange.to)}&_t=${Date.now()}`;
      const res = await fetch(url, { cache: 'no-cache' });
      if (!res.ok) return 0;
      const data = await res.json();
      return Number(data.distance || 0);
    } catch (err) {
      console.error('Error fetching distance:', err);
      return 0;
    }
  }

  async function getCombinedReport(deviceId, dateRange) {
    try {
      const url = `/api/dashboard/combined-report?deviceId=${deviceId}&from=${encodeURIComponent(dateRange.from)}&to=${encodeURIComponent(dateRange.to)}&_t=${Date.now()}`;
      
      for (let attempt = 1; attempt <= 3; attempt++) {
        try {
          const res = await fetch(url, { cache: 'no-cache' });
          if (res.ok) {
            return await res.json();
          }
          if (res.status === 404 || res.status === 401) break;
          if (attempt < 3) await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
        } catch (fetchErr) {
          if (attempt < 3) await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
        }
      }
      return null;
    } catch (err) {
      console.error('Error fetching combined report:', err);
      return null;
    }
  }

  // ========================================
  // DISPLAY REPORT
  // ========================================
  function displayReport(data) {
    const { vehicle, vehicleId, date, distance, combinedReport } = data;

    // Header
    document.getElementById('reportVehicleName').textContent = vehicle;
    document.getElementById('reportVehicleId').textContent = vehicleId;
    document.getElementById('reportDisplayDate').textContent = new Date(date).toLocaleDateString();
    document.getElementById('reportGeneratedTime').textContent = new Date().toLocaleString();

    // Activity metrics
    const trips = combinedReport?.trips || [];
    const stops = combinedReport?.stops || [];
    
    document.getElementById('reportTotalDistance').textContent = distance.toFixed(2) + ' km';
    document.getElementById('reportTotalTrips').textContent = trips.length;
    document.getElementById('reportTotalStops').textContent = stops.length;

    // Calculate time metrics
    let engineOnTime = 0;
    let idleTime = 0;
    let movingTime = 0;

    trips.forEach(trip => {
      if (trip.duration) {
        movingTime += trip.duration;
        engineOnTime += trip.duration;
      }
    });

    stops.forEach(stop => {
      if (stop.duration) {
        // Assume idle if stopped with engine on
        idleTime += stop.duration;
        engineOnTime += stop.duration;
      }
    });

    // Total time in day (24 hours)
    const totalSeconds = 24 * 3600;
    const engineOffTime = totalSeconds - engineOnTime;

    // Update summary
    document.getElementById('reportEngineOnTime').textContent = formatDuration(engineOnTime);
    document.getElementById('reportEngineOffTime').textContent = formatDuration(engineOffTime);
    document.getElementById('reportIdleTime').textContent = formatDuration(idleTime);
    document.getElementById('reportMovingTime').textContent = formatDuration(movingTime);

    // Update charts
    if (idleMovingChart) {
      idleMovingChart.data.datasets[0].data = [idleTime, movingTime];
      idleMovingChart.update('none');
    }

    if (engineStatusChart) {
      engineStatusChart.data.datasets[0].data = [
        (engineOnTime / 3600).toFixed(2),
        (engineOffTime / 3600).toFixed(2)
      ];
      engineStatusChart.update('none');
    }

    // Populate trips table
    const tripsTableBody = document.getElementById('tripsTableBody');
    if (trips.length > 0) {
      tripsTableBody.innerHTML = trips.map((trip, idx) => {
        const startTime = trip.startTime ? new Date(trip.startTime).toLocaleString() : 'N/A';
        const endTime = trip.endTime ? new Date(trip.endTime).toLocaleString() : 'N/A';
        const tripDistance = trip.distance ? (trip.distance / 1000).toFixed(2) : '0.00';
        const duration = trip.duration ? formatDuration(trip.duration) : 'N/A';
        const maxSpeed = trip.maxSpeed ? trip.maxSpeed.toFixed(1) : 'N/A';
        const avgSpeed = trip.averageSpeed ? trip.averageSpeed.toFixed(1) : 'N/A';
        
        return `<tr>
          <td>${idx + 1}</td>
          <td>${startTime}</td>
          <td>${endTime}</td>
          <td>${tripDistance}</td>
          <td>${duration}</td>
          <td>${maxSpeed} km/h</td>
          <td>${avgSpeed} km/h</td>
        </tr>`;
      }).join('');
    } else {
      tripsTableBody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No trips recorded</td></tr>';
    }

    // Populate stops table
    const stopsTableBody = document.getElementById('stopsTableBody');
    if (stops.length > 0) {
      stopsTableBody.innerHTML = stops.map((stop, idx) => {
        const startTime = stop.startTime ? new Date(stop.startTime).toLocaleString() : 'N/A';
        const endTime = stop.endTime ? new Date(stop.endTime).toLocaleString() : 'N/A';
        const duration = stop.duration ? formatDuration(stop.duration) : 'N/A';
        const address = stop.address || 'N/A';
        
        return `<tr>
          <td>${idx + 1}</td>
          <td>${startTime}</td>
          <td>${endTime}</td>
          <td>${duration}</td>
          <td>${address}</td>
        </tr>`;
      }).join('');
    } else {
      stopsTableBody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No stops recorded</td></tr>';
    }
  }

  // ========================================
  // UTILITY FUNCTIONS
  // ========================================
  function formatDuration(seconds) {
    if (!seconds || seconds === 0) return '0h 0m';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${minutes}m`;
  }

  function showError(message) {
    reportError.textContent = message;
    reportError.style.display = 'block';
    reportContent.style.display = 'none';
    reportLoading.style.display = 'none';
  }

  // ========================================
  // EXPORT PDF (Future Enhancement)
  // ========================================
  btnExportPDF?.addEventListener('click', () => {
    alert('PDF export feature coming soon! For now, use browser Print > Save as PDF');
    window.print();
  });

  // ========================================
  // INITIALIZE ON PAGE LOAD
  // ========================================
  document.addEventListener('DOMContentLoaded', init);

})();