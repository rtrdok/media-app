try {
  importScripts("config.js");
} catch (_) {}

const COOKIE_URLS = [
  "https://www.youtube.com",
  "https://youtube.com",
  "https://www.google.com",
  "https://instagram.com",
  "https://www.instagram.com",
  "https://www.facebook.com",
  "https://vk.com",
  "https://m.vk.com",
  "https://vk.ru",
  "https://m.vk.ru",
  "https://login.vk.ru",
  "https://login.vk.com",
  "https://id.vk.ru",
  "https://id.vk.com",
  "https://www.tiktok.com",
  "https://music.yandex.ru",
  "https://soundcloud.com",
];

function api() {
  return globalThis.chrome || globalThis.browser;
}

function bridgeConfig() {
  const b = globalThis.MEDIA_APP_BRIDGE || {};
  return {
    ports: Array.isArray(b.ports) && b.ports.length ? b.ports : [17865, 8765, 18765],
    token: String(b.token || ""),
  };
}

function netscapeLine(c) {
  const domain = c.domain.startsWith(".") ? c.domain : c.domain;
  const includeSub = domain.startsWith(".") ? "TRUE" : "FALSE";
  const path = c.path || "/";
  const secure = c.secure ? "TRUE" : "FALSE";
  const exp = c.expirationDate ? Math.floor(c.expirationDate) : 0;
  return `${domain}\t${includeSub}\t${path}\t${secure}\t${exp}\t${c.name || ""}\t${c.value || ""}`;
}

async function collectNetscape() {
  const a = api();
  const lines = ["# Netscape HTTP Cookie File", "# Media App extension", ""];
  const seen = new Set();
  for (const pageUrl of COOKIE_URLS) {
    let list = [];
    try {
      list = await a.cookies.getAll({ url: pageUrl });
    } catch (_) {
      list = [];
    }
    for (const c of list) {
      const key = `${c.domain}|${c.path}|${c.name}`;
      if (seen.has(key)) continue;
      seen.add(key);
      lines.push(netscapeLine(c));
    }
  }
  return { text: lines.join("\n") + "\n", count: seen.size };
}

async function findBridge(ports, token) {
  for (const port of ports) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/api/extension/ping`, {
        method: "GET",
        headers: token ? { "X-Media-Token": token } : {},
      });
      if (r.ok) return port;
    } catch (_) {}
  }
  return null;
}

async function sendCookies(overrideToken) {
  const { ports, token: cfgToken } = bridgeConfig();
  const token = String(overrideToken || cfgToken || "");
  const port = await findBridge(ports, token);
  if (!port) {
    throw new Error("Media App не найден. Открой приложение и попробуй снова.");
  }
  const { text, count } = await collectNetscape();
  if (!count) {
    throw new Error("Cookies пусты. Залогинься на YouTube/Instagram/VK в этом браузере.");
  }
  const r = await fetch(`http://127.0.0.1:${port}/api/cookies/from-extension`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { "X-Media-Token": token } : {}),
    },
    body: JSON.stringify({ netscape: text, source: "extension", count }),
  });
  let j = {};
  try {
    j = await r.json();
  } catch (_) {}
  if (!r.ok || !j.ok) {
    if (r.status === 403) {
      throw new Error(
        j.detail || j.error ||
        "Токен не совпал. В Media App снова нажми «Скачать расширение» и перезагрузи его в браузере."
      );
    }
    throw new Error(j.detail || j.error || `Ошибка сервера (${r.status})`);
  }
  return { port, count: j.count || count };
}

async function loadDownloadPrefs() {
  const a = api();
  try {
    const data = await a.storage.local.get({
      downloadPrefs: { kind: "auto", quality: "best", fmt: "MP4" },
    });
    const p = data.downloadPrefs || {};
    return {
      kind: String(p.kind || "auto"),
      quality: String(p.quality || "best"),
      fmt: String(p.fmt || "MP4").toUpperCase(),
    };
  } catch (_) {
    return { kind: "auto", quality: "best", fmt: "MP4" };
  }
}

async function sendJob(pageUrl, overrideToken, overridePrefs) {
  const url = String(pageUrl || "").trim();
  if (!url || !/^https?:\/\//i.test(url)) {
    throw new Error("Нет ссылки на странице");
  }
  const prefs = overridePrefs && typeof overridePrefs === "object"
    ? {
        kind: String(overridePrefs.kind || "auto"),
        quality: String(overridePrefs.quality || "best"),
        fmt: String(overridePrefs.fmt || "MP4").toUpperCase(),
      }
    : await loadDownloadPrefs();
  const { ports, token: cfgToken } = bridgeConfig();
  const token = String(overrideToken || cfgToken || "");
  const port = await findBridge(ports, token);
  if (!port) {
    throw new Error("Media App не найден. Открой приложение и попробуй снова.");
  }
  const r = await fetch(`http://127.0.0.1:${port}/api/extension/job`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { "X-Media-Token": token } : {}),
    },
    body: JSON.stringify({
      url,
      kind: prefs.kind === "auto" ? "" : prefs.kind,
      quality: prefs.quality,
      fmt: prefs.fmt,
    }),
  });
  let j = {};
  try {
    j = await r.json();
  } catch (_) {}
  if (!r.ok || !j.ok) {
    const detail = j.detail || j.error || `Ошибка сервера (${r.status})`;
    if (r.status === 403) {
      throw new Error(
        detail ||
        "Токен не совпал. В Media App снова нажми «Скачать расширение» и перезагрузи его."
      );
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return {
    port,
    id: j.id,
    kind: j.kind,
    quality: j.quality || prefs.quality,
    fmt: j.fmt || prefs.fmt,
    title: j.title || url,
    queue_len: j.queue_len,
  };
}

function ensureContextMenus() {
  const a = api();
  if (!a.contextMenus || !a.contextMenus.create) return;
  try {
    a.contextMenus.removeAll(() => {
      a.contextMenus.create({
        id: "media-app-send-page",
        title: "Отправить в Media App",
        contexts: ["page", "video", "audio"],
      });
      a.contextMenus.create({
        id: "media-app-send-link",
        title: "Отправить ссылку в Media App",
        contexts: ["link"],
      });
    });
  } catch (_) {}
}

api().runtime.onInstalled.addListener(() => ensureContextMenus());
api().runtime.onStartup.addListener(() => ensureContextMenus());
ensureContextMenus();

if (api().contextMenus && api().contextMenus.onClicked) {
  api().contextMenus.onClicked.addListener((info) => {
    const url = info.linkUrl || info.pageUrl || info.srcUrl || "";
    sendJob(url).catch(() => {});
  });
}

api().runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "SEND_COOKIES") {
    sendCookies(msg.token)
      .then((r) => sendResponse({ ok: true, ...r }))
      .catch((e) => sendResponse({ ok: false, error: String(e.message || e) }));
    return true;
  }
  if (msg && msg.type === "SEND_JOB") {
    sendJob(msg.url, msg.token, msg.prefs)
      .then((r) => sendResponse({ ok: true, ...r }))
      .catch((e) => sendResponse({ ok: false, error: String(e.message || e) }));
    return true;
  }
});
