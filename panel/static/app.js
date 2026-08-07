async function api(path, options) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.detail || `${resp.status} ${resp.statusText}`);
  }
  return data;
}

function statusDot(ok, neutral) {
  const dot = document.createElement("span");
  dot.className = `status-dot ${neutral ? "status-dot--neutral" : ok ? "status-dot--connected" : "status-dot--disconnected"}`;
  return dot;
}

// Managed services: print app, print upload app, shared print service, ESP32
// display service. Each has identical start/stop/enable-on-boot controls, so
// one function wires up all of them instead of repeating the same code.
function setupServiceCard(prefix, linkPort) {
  const statusEl = document.getElementById(`${prefix}-status`);
  const startBtn = document.getElementById(`${prefix}-start-btn`);
  const stopBtn = document.getElementById(`${prefix}-stop-btn`);
  const bootToggle = document.getElementById(`${prefix}-boot-toggle`);
  const actionResult = document.getElementById(`${prefix}-action-result`);
  const link = document.getElementById(`${prefix}-link`);

  if (link && linkPort) {
    link.href = `http://${location.hostname}:${linkPort}/`;
  }

  function render(status) {
    statusEl.innerHTML = "";
    if (!status.supported) {
      statusEl.textContent = "Not supported on this platform";
      startBtn.disabled = true;
      stopBtn.disabled = true;
      bootToggle.disabled = true;
      return;
    }
    statusEl.appendChild(statusDot(status.active));
    statusEl.appendChild(document.createTextNode(status.active ? "Running" : "Stopped"));
    startBtn.disabled = status.active;
    stopBtn.disabled = !status.active;
    bootToggle.checked = status.enabled;
    bootToggle.disabled = false;
  }

  async function refresh() {
    try {
      render(await api(`/api/${prefix}/status`));
    } catch (e) {
      statusEl.textContent = `Error: ${e.message}`;
    }
  }

  async function action(path) {
    actionResult.textContent = "";
    try {
      render(await api(path, { method: "POST" }));
    } catch (e) {
      actionResult.textContent = `Error: ${e.message}`;
      refresh();
    }
  }

  startBtn.addEventListener("click", () => action(`/api/${prefix}/start`));
  stopBtn.addEventListener("click", () => action(`/api/${prefix}/stop`));
  bootToggle.addEventListener("change", () =>
    action(bootToggle.checked ? `/api/${prefix}/enable` : `/api/${prefix}/disable`)
  );

  return refresh;
}

const refreshMomirStatus = setupServiceCard("momir", 8000);
const refreshUploadStatus = setupServiceCard("upload", 8001);
const refreshPrintsvcStatus = setupServiceCard("printsvc", null);
const refreshEsp32svcStatus = setupServiceCard("esp32svc", null);

// Network
const networkStatusEl = document.getElementById("network-status");
const networkListEl = document.getElementById("network-list");
const addForm = document.getElementById("add-network-form");
const addResult = document.getElementById("add-network-result");
const ssidInput = document.getElementById("add-ssid");
const ssidDatalist = document.getElementById("scanned-ssids");
const passwordInput = document.getElementById("add-password");
const rescanBtn = document.getElementById("rescan-btn");

function renderNetworkStatus(status) {
  networkStatusEl.innerHTML = "";
  if (!status.supported) {
    networkStatusEl.textContent = "Not supported on this platform";
    return;
  }
  const online = status.mode !== "disconnected";
  networkStatusEl.appendChild(statusDot(online));
  let label;
  if (status.mode === "wifi-client") label = `Connected to Wi-Fi: ${status.ssid}`;
  else if (status.mode === "ap") label = `Broadcasting own network: ${status.ap_ssid}`;
  else if (status.mode === "ethernet-only") label = "Connected via Ethernet";
  else label = "Disconnected";
  if (status.eth_connected && status.mode !== "ethernet-only") label += " · Ethernet also connected";
  networkStatusEl.appendChild(document.createTextNode(label));
}

async function refreshNetworkStatus() {
  try {
    renderNetworkStatus(await api("/api/network/status"));
  } catch (e) {
    networkStatusEl.textContent = `Error: ${e.message}`;
  }
}

function renderSavedNetworks(networks) {
  networkListEl.innerHTML = "";
  if (networks.length === 0) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "No saved networks yet.";
    networkListEl.appendChild(li);
    return;
  }
  networks.forEach((net, index) => {
    const li = document.createElement("li");
    li.appendChild(statusDot(net.in_range, !net.in_range));
    li.lastChild.title = net.in_range ? "In range" : "Not currently in range";

    const name = document.createElement("span");
    name.className = "network-name";
    name.textContent = net.ssid;
    li.appendChild(name);

    const controls = document.createElement("span");
    controls.className = "network-controls";

    const upBtn = document.createElement("button");
    upBtn.textContent = "↑";
    upBtn.setAttribute("aria-label", "Move up");
    upBtn.disabled = index === 0;
    upBtn.addEventListener("click", () => moveNetwork(networks, index, -1));
    controls.appendChild(upBtn);

    const downBtn = document.createElement("button");
    downBtn.textContent = "↓";
    downBtn.setAttribute("aria-label", "Move down");
    downBtn.disabled = index === networks.length - 1;
    downBtn.addEventListener("click", () => moveNetwork(networks, index, 1));
    controls.appendChild(downBtn);

    const removeBtn = document.createElement("button");
    removeBtn.textContent = "✕";
    removeBtn.setAttribute("aria-label", "Remove");
    removeBtn.addEventListener("click", () => removeNetwork(net.id));
    controls.appendChild(removeBtn);

    li.appendChild(controls);
    networkListEl.appendChild(li);
  });
}

async function refreshSavedNetworks() {
  try {
    const { networks } = await api("/api/network/saved");
    renderSavedNetworks(networks);
  } catch (e) {
    networkListEl.innerHTML = `<li class="empty">Error: ${e.message}</li>`;
  }
}

async function moveNetwork(networks, index, delta) {
  const order = networks.map((n) => n.id);
  const target = index + delta;
  [order[index], order[target]] = [order[target], order[index]];
  try {
    const { networks: updated } = await api("/api/network/saved/reorder", {
      method: "POST",
      body: JSON.stringify({ order }),
    });
    renderSavedNetworks(updated);
  } catch (e) {
    addResult.textContent = `Error: ${e.message}`;
  }
}

async function removeNetwork(id) {
  try {
    await api(`/api/network/saved/${encodeURIComponent(id)}`, { method: "DELETE" });
    addResult.textContent = "";
    refreshSavedNetworks();
    refreshNetworkStatus();
  } catch (e) {
    addResult.textContent = `Error: ${e.message}`;
  }
}

async function refreshScan() {
  try {
    const { ssids } = await api("/api/network/scan");
    ssidDatalist.innerHTML = "";
    ssids.forEach((ssid) => {
      const option = document.createElement("option");
      option.value = ssid;
      ssidDatalist.appendChild(option);
    });
  } catch (e) {
    // scan failures are non-fatal; leave whatever's already in the list
  }
}

addForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  addResult.textContent = "Adding…";
  try {
    await api("/api/network/saved", {
      method: "POST",
      body: JSON.stringify({ ssid: ssidInput.value.trim(), password: passwordInput.value }),
    });
    ssidInput.value = "";
    passwordInput.value = "";
    addResult.textContent = "Added.";
    refreshSavedNetworks();
    refreshNetworkStatus();
  } catch (e) {
    addResult.textContent = `Error: ${e.message}`;
  }
});

rescanBtn.addEventListener("click", () => {
  addResult.textContent = "Scanning…";
  Promise.all([refreshScan(), refreshNetworkStatus(), refreshSavedNetworks()]).then(() => {
    addResult.textContent = "";
  });
});

refreshMomirStatus();
refreshUploadStatus();
refreshPrintsvcStatus();
refreshEsp32svcStatus();
refreshNetworkStatus();
refreshSavedNetworks();
refreshScan();
setInterval(() => {
  refreshMomirStatus();
  refreshUploadStatus();
  refreshPrintsvcStatus();
  refreshEsp32svcStatus();
  refreshNetworkStatus();
  refreshSavedNetworks();
}, 15000);
