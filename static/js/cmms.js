const LIVE_UPDATE_INTERVAL_MS = 5000;

function formatNumber(value) {
    if (value === null || value === undefined) {
        return "0";
    }
    return value;
}

function formatTemperature(value) {
    if (value === null || value === undefined) {
        return "— °C";
    }
    return `${Number(value).toFixed(1)} °C`;
}

function formatPercent(value) {
    if (value === null || value === undefined) {
        return "0.0%";
    }
    return `${Number(value).toFixed(1)}%`;
}

function clampPercent(value) {
    const numberValue = Number(value) || 0;
    return Math.max(0, Math.min(numberValue, 100));
}

function updateMachineStatus(state) {
    const pill = document.getElementById("machine-status-pill");
    const stateText = document.getElementById("machine-state");

    if (!pill || !stateText) {
        return;
    }

    stateText.textContent = state || "UNKNOWN";

    pill.classList.remove("status-running", "status-faulted", "status-idle");

    if (state === "RUNNING") {
        pill.classList.add("status-running");
    } else if (state === "FAULTED") {
        pill.classList.add("status-faulted");
    } else {
        pill.classList.add("status-idle");
    }
}

function updateLineData(line) {
    document.getElementById("parts-produced").textContent = formatNumber(line.parts_produced);
    document.getElementById("parts-shipped").textContent = formatNumber(line.parts_shipped);
    document.getElementById("parts-rejected").textContent = formatNumber(line.parts_rejected);
    document.getElementById("maintenance-count").textContent = formatNumber(line.maintenance_count);

    document.getElementById("temp-moulding").textContent = formatTemperature(line.temp_moulding);
    document.getElementById("temp-furnace").textContent = formatTemperature(line.temp_furnace);

    updateMachineStatus(line.state);
}

function updateStationCard(station) {
    const card = document.querySelector(`[data-station="${station.name}"]`);

    if (!card) {
        return;
    }

    const wearValue = card.querySelector(".wear-value");
    const wearBar = card.querySelector(".wear-bar");
    const defectValue = card.querySelector(".defect-value");
    const defectBar = card.querySelector(".defect-bar");
    const condition = card.querySelector(".station-condition");
    const reasonInput = card.querySelector(".reason-input");
    const priorityInput = card.querySelector(".priority-input");

    wearValue.textContent = formatPercent(station.wear_pct);
    wearBar.style.width = `${clampPercent(station.wear_pct)}%`;

    defectValue.textContent = formatPercent(station.defect_pct);
    defectBar.style.width = `${clampPercent(station.defect_pct)}%`;

    condition.textContent = station.condition;

    card.classList.remove("ok", "warn", "danger");
    card.classList.add(station.css_class);

    if (reasonInput) {
        reasonInput.value = `${station.condition}: wear ${Number(station.wear_pct).toFixed(1)}%, defect rate ${Number(station.defect_pct).toFixed(1)}%`;
    }

    if (priorityInput) {
        priorityInput.value = station.priority;
    }
}

async function updateLiveData() {
    try {
        const response = await fetch("/api/status");

        if (!response.ok) {
            throw new Error("Failed to fetch live status");
        }

        const data = await response.json();

        updateLineData(data.line);

        data.stations.forEach((station) => {
            updateStationCard(station);
        });
    } catch (error) {
        console.warn("Live update failed:", error);
    }
}

updateLiveData();
window.setInterval(updateLiveData, LIVE_UPDATE_INTERVAL_MS);