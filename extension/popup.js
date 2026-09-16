const api = globalThis.chrome || globalThis.browser;
const btnJob = document.getElementById("send-job");
const btnCookies = document.getElementById("send-cookies");
const status = document.getElementById("status");

function setBusy(busy) {
  btnJob.disabled = busy;
  btnCookies.disabled = busy;
}

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
    const token = (globalThis.MEDIA_APP_BRIDGE && MEDIA_APP_BRIDGE.token) || "";
    const url = await activeTabUrl();
    const res = await api.runtime.sendMessage({ type: "SEND_JOB", url, token });
    if (!res || !res.ok) throw new Error((res && res.error) || "Не удалось");
    status.className = "ok";
    status.textContent = `В очереди (#${res.id}): ${res.title || url}`;
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
