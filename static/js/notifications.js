document.addEventListener('DOMContentLoaded', function () {
    loadRules();

    // Show/hide speed limit input based on type
    document.getElementById('ruleType').addEventListener('change', function () {
        const type = this.value;
        const speedContainer = document.getElementById('speed-limit-container');
        if (type === 'deviceOverspeed') {
            speedContainer.style.display = 'block';
        } else {
            speedContainer.style.display = 'none';
        }
    });
});

let addRuleModal;

function openAddRuleModal() {
    const modalEl = document.getElementById('addRuleModal');
    if (!addRuleModal) {
        addRuleModal = new bootstrap.Modal(modalEl);
    }

    // Reset form
    document.getElementById('addRuleForm').reset();
    document.getElementById('speed-limit-container').style.display = 'none';

    // Load devices and reset selection state
    loadDevicesForModal();
    toggleDeviceSelection();

    addRuleModal.show();
}

function toggleDeviceSelection() {
    const allDevices = document.getElementById('allDevices').checked;
    const deviceSelect = document.getElementById('deviceSelect');
    deviceSelect.disabled = allDevices;
}

function loadDevicesForModal() {
    fetch('/api/devices')
        .then(response => response.json())
        .then(devices => {
            const select = document.getElementById('deviceSelect');
            select.innerHTML = '';
            devices.forEach(device => {
                const option = document.createElement('option');
                option.value = device.id;
                option.textContent = device.name;
                select.appendChild(option);
            });
        })
        .catch(error => console.error('Error loading devices:', error));
}

function loadRules() {
    fetch('/api/notification-rules')
        .then(response => response.json())
        .then(rules => {
            const tbody = document.querySelector('#rules-table tbody');
            tbody.innerHTML = '';
            if (rules.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No rules found</td></tr>';
                return;
            }
            rules.forEach(rule => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${rule.type}</td>
                    <td>${rule.notificators ? rule.notificators.replace(/,/g, ', ') : ''}</td>
                    <td>${rule.description || '-'}</td>
                    <td>
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteRule(${rule.id})">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        })
        .catch(error => console.error('Error loading rules:', error));
}

function deleteRule(ruleId) {
    if (!confirm('Are you sure you want to delete this rule?')) return;

    fetch(`/api/notification-rules/${ruleId}`, {
        method: 'DELETE'
    })
        .then(response => {
            if (response.ok) {
                loadRules();
            } else {
                alert('Failed to delete rule');
            }
        })
        .catch(error => console.error('Error deleting rule:', error));
}

function handleAddRuleSubmit() {
    const type = document.getElementById('ruleType').value;
    if (!type) {
        alert('Please select a rule type');
        return;
    }

    const channels = [];
    if (document.getElementById('channel_web').checked) channels.push('web');
    if (document.getElementById('channel_mail').checked) channels.push('mail');
    if (document.getElementById('channel_command').checked) channels.push('command');

    if (channels.length === 0) {
        alert('Please select at least one channel');
        return;
    }

    const allDevices = document.getElementById('allDevices').checked;
    const deviceSelect = document.getElementById('deviceSelect');
    const deviceIds = Array.from(deviceSelect.selectedOptions).map(opt => opt.value);

    if (!allDevices && deviceIds.length === 0) {
        alert('Please select at least one device or check All Devices');
        return;
    }

    const description = document.getElementById('ruleDescription').value;
    const priority = document.getElementById('rulePriority').checked;

    const attributes = {};
    if (type === 'deviceOverspeed') {
        const speed = document.getElementById('speedLimit').value;
        if (speed) {
            attributes.speedLimit = parseFloat(speed);
        }
    }
    if (priority) {
        attributes.priority = "high";
    }

    const payload = {
        type: type,
        channels: channels,
        always: allDevices,
        deviceIds: deviceIds,
        description: description,
        attributes: attributes,
        priority: priority // Backend will handle moving this to attributes if needed
    };

    fetch('/api/notification-rules', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
    })
        .then(response => {
            if (response.ok) {
                addRuleModal.hide();
                loadRules();
                // Show success message
                const alertDiv = document.createElement('div');
                alertDiv.className = 'alert alert-success alert-dismissible fade show';
                alertDiv.innerHTML = 'Rule created successfully <button type="button" class="btn-close" data-bs-dismiss="alert"></button>';
                document.getElementById('alert-container').appendChild(alertDiv);

                // Auto dismiss alert
                setTimeout(() => {
                    alertDiv.remove();
                }, 3000);
            } else {
                return response.json().then(data => {
                    throw new Error(data.error || 'Failed to create rule');
                });
            }
        })
        .catch(error => {
            alert('Error: ' + error.message);
        });
}