const cmcInput = document.getElementById("cmc-input");
const cmcCountEl = document.getElementById("cmc-count");
const statusEl = document.getElementById("status");
const previewPanel = document.getElementById("preview-panel");
const previewImg = document.getElementById("preview-img");
const previewMeta = document.getElementById("preview-meta");
const printResult = document.getElementById("print-result");

let currentToken = null;
let cmcCounts = {};

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

async function refreshStatus() {
  try {
    const health = await api("/api/health");
    const printer = health.printer;
    statusEl.textContent = "";
    const dot = document.createElement("span");
    dot.className = `status-dot ${printer.connected ? "status-dot--connected" : "status-dot--disconnected"}`;
    dot.title = printer.connected ? "Printer connected" : "Printer disconnected";
    statusEl.appendChild(dot);
    statusEl.appendChild(
      document.createTextNode(`${health.card_count} cards · ${printer.driver} · v${health.version}`)
    );
  } catch (e) {
    statusEl.textContent = "offline";
  }
}

function showPreview(result) {
  currentToken = result.token;
  previewImg.src = result.image;
  const c = result.card;
  const cmcNote =
    result.card.actual_cmc !== result.card.requested_cmc
      ? ` (nothing at MV ${result.card.requested_cmc}, showing MV ${result.card.actual_cmc})`
      : "";
  const isToken = !!result.is_token;
  previewMeta.textContent = isToken
    ? c.type_line || ""
    : `${c.type_line || ""}${cmcNote}${result.art_used ? "" : " · no art available"}`;
  // Reroll/Regenerate only make sense for summoned cards, not tokens.
  document.getElementById("reroll-btn").classList.toggle("hidden", isToken);
  document.getElementById("regenerate-btn").classList.toggle("hidden", isToken);
  printResult.textContent = "";
  previewPanel.classList.remove("hidden");
  previewPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function summon() {
  const cmc = parseInt(cmcInput.value, 10) || 0;
  previewMeta.textContent = "Summoning…";
  try {
    const result = await api("/api/summon", {
      method: "POST",
      body: JSON.stringify({ cmc }),
    });
    showPreview(result);
  } catch (e) {
    previewPanel.classList.remove("hidden");
    previewMeta.textContent = `Error: ${e.message}`;
  }
}

async function regenerateCurrent() {
  if (!currentToken) return;
  previewMeta.textContent = "Regenerating…";
  try {
    const result = await api("/api/regenerate", {
      method: "POST",
      body: JSON.stringify({ token: currentToken }),
    });
    showPreview(result);
  } catch (e) {
    previewMeta.textContent = `Error: ${e.message}`;
  }
}

async function printCurrent() {
  if (!currentToken) return;
  printResult.textContent = "Printing…";
  try {
    const result = await api("/api/print", {
      method: "POST",
      body: JSON.stringify({ token: currentToken }),
    });
    printResult.textContent = result.ok ? "Printed." : `Failed: ${result.detail}`;
  } catch (e) {
    printResult.textContent = `Error: ${e.message}`;
  }
}

function updatePossibilities() {
  const cmc = parseInt(cmcInput.value, 10) || 0;
  const n = cmcCounts[cmc] || 0;
  cmcCountEl.textContent = `${n} possibilit${n === 1 ? "y" : "ies"} at mana value ${cmc}`;
}

async function loadCmcCounts() {
  try {
    cmcCounts = await api("/api/cmc_counts");
  } catch (e) {
    cmcCounts = {};
  }
  updatePossibilities();
}

document.getElementById("summon-btn").addEventListener("click", summon);
document.getElementById("reroll-btn").addEventListener("click", summon);
document.getElementById("regenerate-btn").addEventListener("click", regenerateCurrent);
document.getElementById("print-btn").addEventListener("click", printCurrent);
document.getElementById("cmc-up").addEventListener("click", () => {
  cmcInput.value = Math.min(20, (parseInt(cmcInput.value, 10) || 0) + 1);
  updatePossibilities();
});
document.getElementById("cmc-down").addEventListener("click", () => {
  cmcInput.value = Math.max(0, (parseInt(cmcInput.value, 10) || 0) - 1);
  updatePossibilities();
});
cmcInput.addEventListener("input", updatePossibilities);

// Search
const searchInput = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");
let searchDebounce = null;

searchInput.addEventListener("input", () => {
  clearTimeout(searchDebounce);
  const q = searchInput.value.trim();
  if (!q) {
    searchResults.innerHTML = "";
    return;
  }
  searchDebounce = setTimeout(async () => {
    try {
      const { results } = await api(`/api/search?q=${encodeURIComponent(q)}`);
      searchResults.innerHTML = "";
      results.forEach((card) => {
        const li = document.createElement("li");
        li.innerHTML = `<span>${card.name}</span><span>${card.mana_cost || ""}</span>`;
        li.addEventListener("click", async () => {
          const result = await api("/api/preview_card", {
            method: "POST",
            body: JSON.stringify({ card_id: card.id }),
          });
          showPreview(result);
        });
        searchResults.appendChild(li);
      });
    } catch (e) {
      searchResults.innerHTML = `<li>Error: ${e.message}</li>`;
    }
  }, 250);
});

// Tokens
const TOKEN_RECENT_KEY = "momir_token_recent_v2";
const MAX_RECENT_TOKENS = 3;
const MAX_TOKEN_RESULTS = 60;
const tokenSearch = document.getElementById("token-search");
const tokenGrid = document.getElementById("token-grid");
const tokenGridLabel = document.getElementById("token-grid-label");
const tokenRecentEl = document.getElementById("token-recent");
const tokenRecentLabel = document.getElementById("token-recent-label");
const tokenBuildBtn = document.getElementById("token-build-btn");
const tokenBuildStatus = document.getElementById("token-build-status");
let commonTokens = [];
let fullTokenCount = 0;
let recentTokens = []; // whole token objects, so a recent works for any token in the full list
let selectedTokenId = null;
let tokenSearchDebounce = null;

try {
  recentTokens = JSON.parse(localStorage.getItem(TOKEN_RECENT_KEY)) || [];
} catch (e) {
  recentTokens = [];
}

function tokenSubtitle(t) {
  const pt = t.power && t.toughness ? `${t.power}/${t.toughness}` : "";
  const kind = t.type_line.replace(/^Token /, "");
  const text = (t.text || "").replace(/\s+/g, " ");
  const snippet = text.length > 48 ? `${text.slice(0, 47)}…` : text;
  return [pt, kind, snippet].filter(Boolean).join(" · ");
}

function tokenTile(t) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "token-tile" + (t.id === selectedTokenId ? " token-tile--on" : "");
  btn.innerHTML =
    `<span class="token-name"></span><span class="token-sub"></span>` +
    `<span class="token-dots">${(t.colors || []).map((c) => `<i class="dot dot--${c}"></i>`).join("")}</span>`;
  btn.querySelector(".token-name").textContent = t.name;
  btn.querySelector(".token-sub").textContent = tokenSubtitle(t);
  btn.addEventListener("click", () => previewToken(t));
  return btn;
}

function fillGrid(el, list) {
  el.innerHTML = "";
  list.forEach((t) => el.appendChild(tokenTile(t)));
}

function renderTokenRecent(searching) {
  fillGrid(tokenRecentEl, recentTokens);
  const show = recentTokens.length > 0 && !searching;
  tokenRecentLabel.classList.toggle("hidden", !show);
  tokenRecentEl.classList.toggle("hidden", !show);
}

function renderCommonTokens() {
  tokenGridLabel.textContent = fullTokenCount ? `Common (search all ${fullTokenCount} tokens above)` : "Common";
  fillGrid(tokenGrid, commonTokens);
  renderTokenRecent(false);
}

async function runTokenSearch() {
  const q = tokenSearch.value.trim();
  if (!q) {
    renderCommonTokens();
    return;
  }
  try {
    const { results } = await api(`/api/tokens/search?q=${encodeURIComponent(q)}`);
    if (tokenSearch.value.trim() !== q) return; // a newer search superseded this one
    tokenGridLabel.textContent =
      results.length === 0
        ? "No tokens match"
        : `${results.length}${results.length >= MAX_TOKEN_RESULTS ? "+" : ""} match${results.length === 1 ? "" : "es"}`;
    fillGrid(tokenGrid, results);
    renderTokenRecent(true);
  } catch (e) {
    tokenGridLabel.textContent = `Error: ${e.message}`;
  }
}

function rememberToken(t) {
  recentTokens = [t, ...recentTokens.filter((x) => x.id !== t.id)].slice(0, MAX_RECENT_TOKENS);
  try {
    localStorage.setItem(TOKEN_RECENT_KEY, JSON.stringify(recentTokens));
  } catch (e) {
    // recents are a convenience only
  }
}

async function previewToken(t) {
  selectedTokenId = t.id;
  rememberToken(t);
  previewPanel.classList.remove("hidden");
  previewMeta.textContent = "Preparing token…";
  try {
    showPreview(await api("/api/tokens/preview", { method: "POST", body: JSON.stringify({ token_id: t.id }) }));
  } catch (e) {
    previewMeta.textContent = `Error: ${e.message}`;
  }
  runTokenSearch();
}

tokenSearch.addEventListener("input", () => {
  clearTimeout(tokenSearchDebounce);
  tokenSearchDebounce = setTimeout(runTokenSearch, 200);
});

document.getElementById("token-custom-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  selectedTokenId = null;
  previewPanel.classList.remove("hidden");
  previewMeta.textContent = "Preparing token…";
  try {
    showPreview(
      await api("/api/tokens/preview", {
        method: "POST",
        body: JSON.stringify({
          name: document.getElementById("tc-name").value,
          type_line: document.getElementById("tc-type").value,
          power: document.getElementById("tc-power").value,
          toughness: document.getElementById("tc-toughness").value,
          text: document.getElementById("tc-text").value,
        }),
      })
    );
  } catch (e) {
    previewMeta.textContent = `Error: ${e.message}`;
  }
});

function showTokenBuildState(status) {
  if (status.running) {
    tokenBuildBtn.disabled = true;
    tokenBuildStatus.textContent = `Downloading… ${status.done}/${status.total} sets`;
  } else {
    tokenBuildBtn.disabled = false;
    tokenBuildBtn.textContent = fullTokenCount ? "Update token list" : "Download full token list";
    tokenBuildStatus.textContent = status.error
      ? `Error: ${status.error}`
      : fullTokenCount
        ? `${fullTokenCount} tokens available.`
        : "Only the common tokens are available. Download the full list to search every token.";
  }
}

let tokenBuildPoll = null;
async function pollTokenBuild() {
  try {
    const status = await api("/api/tokens/build_status");
    const wasEmpty = fullTokenCount === 0;
    fullTokenCount = status.full_count;
    showTokenBuildState(status);
    if (status.running) {
      tokenBuildPoll = setTimeout(pollTokenBuild, 1500);
    } else if (wasEmpty && fullTokenCount) {
      renderCommonTokens();
    }
  } catch (e) {
    tokenBuildStatus.textContent = `Error: ${e.message}`;
    tokenBuildBtn.disabled = false;
  }
}

tokenBuildBtn.addEventListener("click", async () => {
  tokenBuildBtn.disabled = true;
  try {
    await api("/api/tokens/rebuild", { method: "POST" });
  } catch (e) {
    tokenBuildStatus.textContent = `Error: ${e.message}`;
    tokenBuildBtn.disabled = false;
    return;
  }
  clearTimeout(tokenBuildPoll);
  pollTokenBuild();
});

async function loadTokens() {
  try {
    const data = await api("/api/tokens");
    commonTokens = data.common;
    fullTokenCount = data.full_count;
  } catch (e) {
    commonTokens = [];
  }
  renderCommonTokens();
  pollTokenBuild();
}

// Settings
const settingsForm = document.getElementById("settings-form");
const settingsResult = document.getElementById("settings-result");

async function loadSettings() {
  try {
    const cfg = await api("/api/settings");
    document.getElementById("setting-driver").value = cfg.printer.driver;
    document.getElementById("setting-width").value = String(cfg.printer.paper_width_mm);
    document.getElementById("setting-layout").value = cfg.printer.card_layout;
    document.getElementById("setting-art").checked = cfg.art.enabled;
  } catch (e) {
    settingsResult.textContent = `Error loading settings: ${e.message}`;
  }
}

settingsForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  settingsResult.textContent = "Saving…";
  try {
    await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({
        printer: {
          driver: document.getElementById("setting-driver").value,
          paper_width_mm: parseInt(document.getElementById("setting-width").value, 10),
          card_layout: document.getElementById("setting-layout").value,
        },
        art: { enabled: document.getElementById("setting-art").checked },
      }),
    });
    settingsResult.textContent = "Saved.";
    refreshStatus();
  } catch (e) {
    settingsResult.textContent = `Error: ${e.message}`;
  }
});

// Card database rebuild
const rebuildDbBtn = document.getElementById("rebuild-db-btn");
const rebuildDbResult = document.getElementById("rebuild-db-result");

rebuildDbBtn.addEventListener("click", async () => {
  rebuildDbBtn.disabled = true;
  rebuildDbResult.textContent = "Downloading & rebuilding… this can take a minute.";
  try {
    const result = await api("/api/rebuild_db", { method: "POST" });
    rebuildDbResult.textContent = `Done — ${result.card_count} cards.`;
    refreshStatus();
    loadCmcCounts();
  } catch (e) {
    rebuildDbResult.textContent = `Error: ${e.message}`;
  } finally {
    rebuildDbBtn.disabled = false;
  }
});

refreshStatus();
loadSettings();
loadCmcCounts();
loadTokens();
setInterval(refreshStatus, 15000);

// Life / hand / land tracker (client-side only, no deck needed)
const TRACKER_KEY = "momir_tracker_state";
const MIN_PLAYERS = 1;
const MAX_PLAYERS = 8;
const DEFAULT_LIFE = 20;
const DEFAULT_HAND = 7;
const DEFAULT_LANDS = 0;

function defaultPlayer() {
  return { life: DEFAULT_LIFE, hand: DEFAULT_HAND, lands: DEFAULT_LANDS };
}

function loadTrackerState() {
  try {
    const parsed = JSON.parse(localStorage.getItem(TRACKER_KEY));
    if (parsed && Array.isArray(parsed.players) && parsed.players.length > 0) {
      return parsed;
    }
  } catch (e) {
    // ignore malformed/missing state, fall through to defaults
  }
  return { enabled: false, players: [defaultPlayer(), defaultPlayer()] };
}

const trackerState = loadTrackerState();

function saveTrackerState() {
  localStorage.setItem(TRACKER_KEY, JSON.stringify(trackerState));
}

function clampStat(stat, value) {
  return stat === "life" ? value : Math.max(0, value);
}

const trackerToggle = document.getElementById("tracker-toggle");
const trackerPanel = document.getElementById("tracker-panel");
const trackerPlayersEl = document.getElementById("tracker-players");
const addPlayerBtn = document.getElementById("tracker-add-player");
const trackerResetBtn = document.getElementById("tracker-reset");
const trackerIcons = {
  life: document.getElementById("icon-life"),
  hand: document.getElementById("icon-hand"),
  lands: document.getElementById("icon-lands") || document.getElementById("icon-land"),
};
const statLabels = { life: "life", hand: "cards in hand", lands: "lands" };

function buildStatRow(playerIdx, stat) {
  const row = document.createElement("div");
  row.className = `stat-row stat-row--${stat}`;
  row.title = statLabels[stat];
  row.appendChild(trackerIcons[stat].content.cloneNode(true));

  const down = document.createElement("button");
  down.type = "button";
  down.className = "stat-btn";
  down.textContent = "−";
  down.setAttribute("aria-label", `decrease ${statLabels[stat]} for player ${playerIdx + 1}`);

  const val = document.createElement("span");
  val.className = "stat-value";
  val.textContent = trackerState.players[playerIdx][stat];

  const up = document.createElement("button");
  up.type = "button";
  up.className = "stat-btn";
  up.textContent = "+";
  up.setAttribute("aria-label", `increase ${statLabels[stat]} for player ${playerIdx + 1}`);

  function applyDelta(delta) {
    const player = trackerState.players[playerIdx];
    player[stat] = clampStat(stat, player[stat] + delta);
    val.textContent = player[stat];
    saveTrackerState();
  }
  down.addEventListener("click", () => applyDelta(-1));
  up.addEventListener("click", () => applyDelta(1));

  row.appendChild(down);
  row.appendChild(val);
  row.appendChild(up);
  return row;
}

function renderTracker() {
  trackerPlayersEl.innerHTML = "";
  trackerState.players.forEach((player, idx) => {
    const card = document.createElement("div");
    card.className = "player-card";

    const header = document.createElement("div");
    header.className = "player-card-header";
    const name = document.createElement("span");
    name.textContent = `Player ${idx + 1}`;
    header.appendChild(name);
    if (trackerState.players.length > MIN_PLAYERS) {
      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "player-remove";
      removeBtn.textContent = "✕";
      removeBtn.setAttribute("aria-label", `Remove player ${idx + 1}`);
      removeBtn.addEventListener("click", () => {
        trackerState.players.splice(idx, 1);
        saveTrackerState();
        renderTracker();
      });
      header.appendChild(removeBtn);
    }
    card.appendChild(header);

    card.appendChild(buildStatRow(idx, "life"));
    card.appendChild(buildStatRow(idx, "hand"));
    card.appendChild(buildStatRow(idx, "lands"));

    trackerPlayersEl.appendChild(card);
  });
  addPlayerBtn.disabled = trackerState.players.length >= MAX_PLAYERS;
}

trackerToggle.checked = trackerState.enabled;
trackerPanel.classList.toggle("hidden", !trackerState.enabled);

trackerToggle.addEventListener("change", () => {
  trackerState.enabled = trackerToggle.checked;
  trackerPanel.classList.toggle("hidden", !trackerState.enabled);
  saveTrackerState();
});

addPlayerBtn.addEventListener("click", () => {
  if (trackerState.players.length >= MAX_PLAYERS) return;
  trackerState.players.push(defaultPlayer());
  saveTrackerState();
  renderTracker();
});

trackerResetBtn.addEventListener("click", () => {
  if (!window.confirm(`Reset all players to ${DEFAULT_LIFE} life, ${DEFAULT_HAND} cards, ${DEFAULT_LANDS} lands?`)) {
    return;
  }
  trackerState.players = trackerState.players.map(() => defaultPlayer());
  saveTrackerState();
  renderTracker();
});

renderTracker();
