async function updateDashboardData() {
    try {
        const response = await fetch("/api/status");

        if (!response.ok) {
            console.warn("CMMS status API not available");
            return;
        }

        const data = await response.json();
        const line = data.line;

        updateText("temp-moulding", formatNumber(line.temp_moulding, 1));
        updateText("temp-furnace", formatNumber(line.temp_furnace, 1));
        updateText("parts-shipped", line.parts_shipped ?? 0);
        updateText("parts-produced", line.parts_produced ?? 0);
        updateText("parts-rejected", line.parts_rejected ?? 0);
        updateText("maintenance-count", line.maintenance_count ?? 0);

        const stateBox = document.getElementById("machine-state");
        if (stateBox) {
            stateBox.classList.remove("running", "faulted", "idle");
            stateBox.classList.add(String(line.state).toLowerCase());
            stateBox.innerHTML = `<span class="pulse-dot"></span>${line.state}`;
        }

    } catch (error) {
        console.warn("Dashboard live update failed:", error);
    }
}

function updateText(id, value) {
    const element = document.getElementById(id);

    if (element) {
        element.textContent = value;
    }
}

function formatNumber(value, decimals) {
    if (value === null || value === undefined) {
        return "0.0";
    }

    return Number(value).toFixed(decimals);
}

// Update only the numbers every 3 seconds.
// This does NOT reload the page, so forms will not lose typed text.
setInterval(updateDashboardData, 3000);

console.log("Utility Knife CMMS live frontend loaded.");