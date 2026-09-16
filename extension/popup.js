const api = globalThis.chrome || globalThis.browser;
const btnJob = document.getElementById("send-job");
const btnCookies = document.getElementById("send-cookies");
const status = document.getElementById("status");
const kindEl = document.getElementById("kind");
const qualityEl = document.getElementById("quality");
const fmtEl = document.getElementById("fmt");
const prefsSaved = document.getElementById("prefs-saved");

const DEFAULTS = { kind: "auto", quality: "best", fmt: "MP4" };

function setBusy(busy) {
  btnJob.disabled = busy;
  btnCookies.disabled = busy;
  kindEl.disabled = busy;
  qualityEl.disabled = busy;
  fmtEl.disabled = busy;
}

function currentPrefs() {
  return {
    kind: kindEl.value || DEFAULTS.kind,
    quality: qualityEl.value || DEFAULTS.quality,
    fmt: (fmtEl.value || DEFAULTS.fmt).toUpperCase(),
  };
}

async function loadPrefs() {
  const data = await api.storage.local.get({ downloadPrefs: DEFAULTS });
  const p = { ...DEFAULTS, ...(data.downloadPrefs || {}) };
  kindEl.value = p.kind;
  qualityEl.value = p.quality;
  fmtEl.value = String(p.fmt || "MP4").toUpperCase();
  syncFmtForKind();
}

let saveTimer = null;
function scheduleSave() {
  syncFmtForKind();
  prefsSaved.textContent = "Сохраняю…";
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    void api.storage.local.set({ downloadPrefs: currentPrefs() }).then(() => {
      prefsSaved.textContent = "Сохранено";
      setTimeout(() => {
        if (prefsSaved.textContent === "Сохранено") prefsSaved.textContent = "";
      }, 1200);
    });
  }, 150);
}

function syncFmtForKind() {
  if (kindEl.value === "video" && fmtEl.value === "MP3") {
    fmtEl.value = "MP4";
  }
  if (kindEl.value === "audio" && fmtEl.value !== "MP3") {
    fmtEl.value = "MP3";
  }
}

kindEl.addEventListener("change", scheduleSave);
qualityEl.addEventListener("change", scheduleSave);
fmtEl.addEventListener("change", scheduleSave);

async function activeTabUrl() {
  const tabs = await api.tabs.query({ active: true, currentWindow: true });
  const tab = tabs && tabs[0];
  return (tab && tab.url) || "";
}

btnJob.addEventListener("click", async () => {
  setBusy(true);
  status.className = "";
  status.textContent = "Отправляю ссылку…";
  try {
    // на всякий случай сохранить перед отправкой
    await api.storage.local.set({ downloadPrefs: currentPrefs() });
    const token = (globalThis.MEDIA_APP_BRIDGE && MEDIA_APP_BRIDGE.token) || "";
    const url = await activeTabUrl();
    const prefs = currentPrefs();
    const res = await api.runtime.sendMessage({
      type: "SEND_JOB",
      url,
      token,
      prefs,
    });
    if (!res || !res.ok) throw new Error((res && res.error) || "Не удалось");
    status.className = "ok";
    const q = res.quality || prefs.quality;
    const f = res.fmt || prefs.fmt;
    status.textContent = `В очереди (#${res.id}): ${f} · ${q}\n${res.title || url}`;
  } catch (e) {
    status.className = "err";
    status.textContent = String(e.message || e);
  } finally {
    setBusy(false);
  }
});

btnCookies.addEventListener("click", async () => {
  setBusy(true);
  status.className = "";
  status.textContent = "Отправляю cookies…";
  try {
    const token = (globalThis.MEDIA_APP_BRIDGE && MEDIA_APP_BRIDGE.token) || "";
    const res = await api.runtime.sendMessage({ type: "SEND_COOKIES", token });
    if (!res || !res.ok) throw new Error((res && res.error) || "Не удалось");
    status.className = "ok";
    status.textContent = `Готово: ${res.count} cookies → Media App (порт ${res.port})`;
  } catch (e) {
    status.className = "err";
    status.textContent = String(e.message || e);
  } finally {
    setBusy(false);
  }
});

void loadPrefs();
