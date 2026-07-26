async function api(path, options) {
  const resp = await fetch(path, options);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.detail || `${resp.status} ${resp.statusText}`);
  }
  return data;
}

function statusDot(ok) {
  const dot = document.createElement("span");
  dot.className = `status-dot ${ok ? "status-dot--connected" : "status-dot--disconnected"}`;
  return dot;
}

// Health
const statusEl = document.getElementById("status");

async function refreshStatus() {
  statusEl.innerHTML = "";
  try {
    const { printer } = await api("/api/health");
    statusEl.appendChild(statusDot(printer.connected));
    statusEl.appendChild(document.createTextNode(printer.connected ? "Printer connected" : printer.detail || "Printer disconnected"));
  } catch (e) {
    statusEl.appendChild(statusDot(false));
    statusEl.appendChild(document.createTextNode("Print service unreachable"));
  }
}

// Tabs
const tabImageBtn = document.getElementById("tab-image-btn");
const tabTextBtn = document.getElementById("tab-text-btn");
const imagePanel = document.getElementById("image-panel");
const textPanel = document.getElementById("text-panel");

function showTab(tab) {
  const isImage = tab === "image";
  imagePanel.classList.toggle("hidden", !isImage);
  textPanel.classList.toggle("hidden", isImage);
  tabImageBtn.classList.toggle("active", isImage);
  tabTextBtn.classList.toggle("active", !isImage);
}

tabImageBtn.addEventListener("click", () => showTab("image"));
tabTextBtn.addEventListener("click", () => showTab("text"));

// Image upload
const imageInput = document.getElementById("image-input");
const imagePreview = document.getElementById("image-preview");
const imagePrintBtn = document.getElementById("image-print-btn");
const imageResult = document.getElementById("image-result");

imageInput.addEventListener("change", () => {
  const file = imageInput.files[0];
  imagePrintBtn.disabled = !file;
  imageResult.textContent = "";
  if (!file) {
    imagePreview.classList.add("hidden");
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    imagePreview.src = reader.result;
    imagePreview.classList.remove("hidden");
  };
  reader.readAsDataURL(file);
});

imagePrintBtn.addEventListener("click", async () => {
  const file = imageInput.files[0];
  if (!file) return;
  imagePrintBtn.disabled = true;
  imageResult.textContent = "Printing…";
  try {
    const formData = new FormData();
    formData.append("file", file);
    const data = await api("/api/print/image", { method: "POST", body: formData });
    imageResult.textContent = data.ok ? "Printed." : `Error: ${data.detail}`;
  } catch (e) {
    imageResult.textContent = `Error: ${e.message}`;
  } finally {
    imagePrintBtn.disabled = false;
  }
});

// Text upload
const textInput = document.getElementById("text-input");
const textSize = document.getElementById("text-size");
const textBoldTitle = document.getElementById("text-bold-title");
const textPrintBtn = document.getElementById("text-print-btn");
const textResult = document.getElementById("text-result");

textPrintBtn.addEventListener("click", async () => {
  const text = textInput.value.trim();
  if (!text) {
    textResult.textContent = "Enter some text first.";
    return;
  }
  textPrintBtn.disabled = true;
  textResult.textContent = "Printing…";
  try {
    const data = await api("/api/print/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        font_size: textSize.value,
        bold_title: textBoldTitle.checked,
      }),
    });
    textResult.textContent = data.ok ? "Printed." : `Error: ${data.detail}`;
  } catch (e) {
    textResult.textContent = `Error: ${e.message}`;
  } finally {
    textPrintBtn.disabled = false;
  }
});

refreshStatus();
setInterval(refreshStatus, 15000);
