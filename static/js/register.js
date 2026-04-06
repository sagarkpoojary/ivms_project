let deviceModels = [];

async function loadDeviceModels() {
    try {
        const res = await fetch("/static/data/device_models.json");
        const data = await res.json();
        deviceModels = data.models;
        console.log("Loaded models:", deviceModels.length);
    } catch (e) {
        console.error("Error loading models:", e);
    }
}

function setupSuggestions() {
    const input = document.getElementById("deviceModelInput");
    const box = document.getElementById("modelSuggestions");

    input.addEventListener("input", () => {
        const q = input.value.toLowerCase();
        if (!q) return (box.style.display = "none");

        const results = deviceModels.filter(m => m.toLowerCase().includes(q));

        box.innerHTML = "";
        results.forEach(m => {
            const div = document.createElement("div");
            div.className = "list-group-item list-group-item-action";
            div.textContent = m;
            div.onclick = () => {
                input.value = m;
                box.style.display = "none";
            };
            box.appendChild(div);
        });

        box.style.display = results.length ? "block" : "none";
    });

    document.addEventListener("click", (e) => {
        if (!input.contains(e.target) && !box.contains(e.target)) {
            box.style.display = "none";
        }
    });
}

document.addEventListener("DOMContentLoaded", async () => {
    await loadDeviceModels();
    setupSuggestions();
});
