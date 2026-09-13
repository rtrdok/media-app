const api = globalThis.chrome || globalThis.browser;
const btn = document.getElementById("send");
const status = document.getElementById("status");

btn.addEventListener("click", async () => {
  btn.disabled = true;
  status.className = "";
  status.textContent = "Отправляю…";
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
    btn.disabled = false;
  }
});
