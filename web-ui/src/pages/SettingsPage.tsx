import { CircleAlert, CircleCheck, Download, RefreshCw } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { useApp } from "@/context/AppProvider"
import {
  applyUpdate,
  backupExport,
  backupImport,
  checkUpdate,
  cookiesOpenFolder,
  cookiesStatus,
  extensionSave,
  openUrl,
  saveSettings,
  updateStatus,
  ytdlpUpdate,
} from "@/lib/api"
import type { AppSettings } from "@/types"

export function SettingsPage() {
  const { state, refresh } = useApp()
  const [draft, setDraft] = useState<AppSettings | null>(null)
  const [savedMsg, setSavedMsg] = useState("")
  const [updMsg, setUpdMsg] = useState("Установлена последняя версия")
  const [updChangelog, setUpdChangelog] = useState("")
  const [updBusy, setUpdBusy] = useState(false)
  const [updPct, setUpdPct] = useState(0)
  const [hasUpdate, setHasUpdate] = useState(false)
  const [updUrl, setUpdUrl] = useState("")
  const [updHtmlUrl, setUpdHtmlUrl] = useState(
    "https://github.com/rtrdok/media-app/releases/latest",
  )
  const [updOk, setUpdOk] = useState(true)
  const [cookieOk, setCookieOk] = useState(false)
  const [extMsg, setExtMsg] = useState("")
  const [ytdlpMsg, setYtdlpMsg] = useState("")
  const [ytdlpBusy, setYtdlpBusy] = useState(false)
  const dirtyRef = useRef(false)
  const pollRef = useRef(0)

  useEffect(() => {
    if (state?.settings && !dirtyRef.current) {
      setDraft({
        ...state.settings,
        check_disk_space: state.settings.check_disk_space ?? true,
        max_concurrent_downloads: state.settings.max_concurrent_downloads ?? 3,
        use_proxy: state.settings.use_proxy ?? false,
        proxy_list: state.settings.proxy_list ?? "",
      })
    }
  }, [state?.settings])

  useEffect(() => {
    void cookiesStatus().then((j) => setCookieOk(j.active))
  }, [])

  useEffect(() => {
    return () => window.clearInterval(pollRef.current)
  }, [])

  function patch(p: Partial<AppSettings>) {
    dirtyRef.current = true
    setDraft((d) => (d ? { ...d, ...p } : d))
  }

  async function commit() {
    if (!draft) return
    await saveSettings(draft)
    dirtyRef.current = false
    setSavedMsg("Сохранено")
    void refresh()
    window.setTimeout(() => setSavedMsg(""), 2500)
  }

  async function onCheckUpdate() {
    setUpdBusy(true)
    setUpdChangelog("")
    setUpdOk(true)
    try {
      const j = await checkUpdate(false)
      if (j.update?.version) {
        setHasUpdate(true)
        setUpdOk(true)
        setUpdMsg(`Доступна версия ${j.update.version}`)
        setUpdChangelog(j.update.changelog || j.changelog || "")
        setUpdUrl(j.update.url || "")
        const html =
          (j as { html_url?: string }).html_url ||
          (j.update as { html_url?: string }).html_url ||
          "https://github.com/rtrdok/media-app/releases/latest"
        setUpdHtmlUrl(html)
      } else {
        setHasUpdate(false)
        setUpdUrl("")
        setUpdOk(j.ok !== false)
        setUpdMsg(j.message || "Установлена последняя версия")
      }
    } catch (e) {
      setUpdOk(false)
      setHasUpdate(false)
      setUpdMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setUpdBusy(false)
    }
  }

  async function onApplyUpdate() {
    setUpdBusy(true)
    setUpdOk(true)
    setUpdPct(0)
    setUpdMsg("Скачивание обновления…")
    try {
      const j = await applyUpdate(updUrl || undefined)
      if (!j.ok && j.status === "error") {
        setUpdOk(false)
        setUpdMsg(j.message || "Ошибка обновления")
        setUpdBusy(false)
        return
      }
      setUpdMsg(j.message || "Скачивание…")
      window.clearInterval(pollRef.current)
      pollRef.current = window.setInterval(() => {
        void updateStatus()
          .then((s) => {
            if (typeof s.pct === "number") setUpdPct(s.pct)
            if (s.message) setUpdMsg(s.message)
            if (s.status === "error") {
              setUpdOk(false)
              setUpdBusy(false)
              window.clearInterval(pollRef.current)
            }
            if (s.status === "done" || s.restart) {
              setUpdOk(true)
              setUpdPct(100)
              setUpdMsg(s.message || "Перезапуск…")
              window.clearInterval(pollRef.current)
            }
          })
          .catch(() => {
            /* ignore transient */
          })
      }, 400)
      // если 45 с без прогресса — предложить ручную установку
      window.setTimeout(() => {
        void updateStatus().then((s) => {
          if (s.status === "downloading" && !(s.pct && s.pct > 0) && !(s.bytes_done && s.bytes_done > 0)) {
            setUpdOk(false)
            setUpdBusy(false)
            window.clearInterval(pollRef.current)
            setUpdMsg(
              "Автообновление зависло. Нажми «Скачать установщик» и поставь вручную — так надёжнее.",
            )
          }
        })
      }, 45000)
    } catch (e) {
      setUpdOk(false)
      setUpdMsg(e instanceof Error ? e.message : String(e))
      setUpdBusy(false)
    }
  }

  async function onYtdlpUpdate() {
    setYtdlpBusy(true)
    setYtdlpMsg("Обновление yt-dlp…")
    try {
      const j = await ytdlpUpdate()
      setYtdlpMsg(
        j.ok
          ? `yt-dlp обновлён: ${j.version || "ok"}. Настройки Media App не трогались.`
          : j.log || "Не удалось обновить yt-dlp",
      )
    } catch (e) {
      setYtdlpMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setYtdlpBusy(false)
    }
  }

  if (!draft) {
    return (
      <div className="text-muted-foreground flex min-h-[calc(100vh-4rem)] items-center justify-center p-8 text-sm">
        Загрузка настроек…
      </div>
    )
  }

  return (
    <div className="flex min-h-[calc(100vh-4rem)] w-full flex-col pt-8 pr-8 pb-32 pl-8">
      <div className="mb-6">
        <h1 className="mb-2 text-3xl font-semibold tracking-tight">Настройки</h1>
        <p className="text-muted-foreground text-sm">Настройте загрузки, хранение и поведение приложения.</p>
      </div>

      <div className="flex-1 space-y-4">
        <Card className="rounded-xl pt-6 pr-6 pb-6 pl-6">
          <CardHeader className="p-0 pb-4">
            <CardTitle className="text-lg">Основные</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5 p-0">
            <div className="flex items-center justify-between gap-8">
              <Label>Язык интерфейса</Label>
              <Select
                value={draft.ui_lang}
                onValueChange={(v) => v && patch({ ui_lang: v })}
                items={[
                  { value: "ru", label: "Русский" },
                  { value: "en", label: "English" },
                ]}
              >
                <SelectTrigger className="w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ru">Русский</SelectItem>
                  <SelectItem value="en">English</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center justify-between gap-8">
              <Label>Тема</Label>
              <Select
                value={draft.theme}
                onValueChange={(v) => v && patch({ theme: v })}
                items={[
                  { value: "dark", label: "Тёмная" },
                  { value: "light", label: "Светлая" },
                  { value: "system", label: "Как в системе" },
                ]}
              >
                <SelectTrigger className="w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="dark">Тёмная</SelectItem>
                  <SelectItem value="light">Светлая</SelectItem>
                  <SelectItem value="system">Как в системе</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center justify-between gap-8">
              <Label>Цвет акцента</Label>
              <Select
                value={draft.accent || "blue"}
                onValueChange={(v) => v && patch({ accent: v })}
                items={[
                  { value: "blue", label: "Синий" },
                  { value: "teal", label: "Бирюзовый" },
                  { value: "rose", label: "Розовый" },
                  { value: "amber", label: "Янтарный" },
                  { value: "violet", label: "Фиолетовый" },
                ]}
              >
                <SelectTrigger className="w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="blue">Синий</SelectItem>
                  <SelectItem value="teal">Бирюзовый</SelectItem>
                  <SelectItem value="rose">Розовый</SelectItem>
                  <SelectItem value="amber">Янтарный</SelectItem>
                  <SelectItem value="violet">Фиолетовый</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center justify-between gap-8">
              <Label htmlFor="autostart">Запускать Media App вместе с Windows</Label>
              <Switch
                id="autostart"
                checked={draft.autostart}
                onCheckedChange={(v) => patch({ autostart: v })}
              />
            </div>
          </CardContent>
        </Card>

        <Card className="rounded-xl pt-6 pr-6 pb-6 pl-6">
          <CardHeader className="p-0 pb-4">
            <CardTitle className="text-lg">Система</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5 p-0">
            <div className="flex items-center justify-between gap-8">
              <div>
                <Label className="mb-1 block">Папка загрузок</Label>
                <p className="text-muted-foreground text-sm">{draft.download_dir}</p>
              </div>
              <Button
                variant="outline"
                onClick={() => {
                  const next = window.prompt("Папка загрузок:", draft.download_dir)
                  if (next?.trim()) patch({ download_dir: next.trim() })
                }}
              >
                Изменить
              </Button>
            </div>
            <div className="flex items-center justify-between gap-8">
              <Label htmlFor="disk">Проверять свободное место перед загрузкой</Label>
              <Switch
                id="disk"
                checked={!!draft.check_disk_space}
                onCheckedChange={(v) => patch({ check_disk_space: v })}
              />
            </div>
            <div className="flex items-center justify-between gap-8">
              <div>
                <Label htmlFor="use-proxy" className="mb-1 block">
                  Использовать прокси
                </Label>
                <p className="text-muted-foreground text-xs">
                  Для YouTube / Instagram и т.п., если без прокси не открывается.
                  VK и Яндекс Музыка всегда идут напрямую (прокси к ним не нужен).
                  Системный VPN Windows не трогаем.
                </p>
              </div>
              <Switch
                id="use-proxy"
                checked={!!draft.use_proxy}
                onCheckedChange={(v) => patch({ use_proxy: v })}
              />
            </div>
            {draft.use_proxy ? (
              <div className="space-y-2">
                <Label htmlFor="proxy-list">Прокси (по одному на строку)</Label>
                <p className="text-muted-foreground text-xs">
                  HTTP и SOCKS5. Примеры: socks5://user:pass@host:1080 или socks5:host:1080:user:pass
                </p>
                <textarea
                  id="proxy-list"
                  rows={4}
                  value={draft.proxy_list || ""}
                  onChange={(e) => patch({ proxy_list: e.target.value })}
                  placeholder={
                    "socks5://user:pass@host:1080\nhttp://user:pass@host:8080\nhost:port:user:pass"
                  }
                  className="border-input bg-background placeholder:text-muted-foreground w-full rounded-lg border px-3 py-2 font-mono text-xs"
                />
              </div>
            ) : null}
            <div className="flex items-center justify-between gap-8">
              <Label>Одновременные загрузки</Label>
              <Select
                value={String(draft.max_concurrent_downloads ?? 3)}
                onValueChange={(v) => patch({ max_concurrent_downloads: Number(v) })}
              >
                <SelectTrigger className="w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {["1", "2", "3", "4"].map((n) => (
                    <SelectItem key={n} value={n}>
                      {n}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center justify-between gap-8">
              <div>
                <Label className="mb-1 block">Лимит скорости</Label>
                <p className="text-muted-foreground text-xs">Пусто = без лимита. Примеры: 2M, 500K</p>
              </div>
              <input
                value={draft.rate_limit || ""}
                onChange={(e) => patch({ rate_limit: e.target.value })}
                placeholder="например 2M"
                className="border-input bg-background w-56 rounded-lg border px-3 py-2 text-sm"
              />
            </div>
            <div className="flex items-center justify-between gap-8">
              <Label htmlFor="tray">Сворачивать в трей при закрытии окна</Label>
              <Switch
                id="tray"
                checked={!!draft.minimize_to_tray}
                onCheckedChange={(v) => patch({ minimize_to_tray: v })}
              />
            </div>
            <div className="flex items-center justify-between gap-8">
              <Label htmlFor="notify">Уведомление Windows, когда загрузка готова</Label>
              <Switch
                id="notify"
                checked={!!draft.notify_on_done}
                onCheckedChange={(v) => patch({ notify_on_done: v })}
              />
            </div>
            <div className="flex items-center justify-between gap-8">
              <div>
                <Label className="mb-1 block">Хранить кэш превью (дней)</Label>
                <p className="text-muted-foreground text-xs">Старые временные файлы удаляются автоматически</p>
              </div>
              <Select
                value={String(draft.cache_max_days ?? 7)}
                onValueChange={(v) => patch({ cache_max_days: Number(v) })}
              >
                <SelectTrigger className="w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {[3, 7, 14, 30, 90].map((n) => (
                    <SelectItem key={n} value={String(n)}>
                      {n}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        <Card className="rounded-xl pt-6 pr-6 pb-6 pl-6">
          <CardHeader className="p-0 pb-4">
            <CardTitle className="text-lg">yt-dlp</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 p-0">
            <p className="text-muted-foreground text-sm">
              Обновляет только движок скачивания. Прокси, cookies, папка загрузок и остальные
              настройки Media App не сбрасываются.
            </p>
            {ytdlpMsg ? <p className="text-sm">{ytdlpMsg}</p> : null}
            <Button
              variant="outline"
              size="sm"
              className="gap-2"
              disabled={ytdlpBusy}
              onClick={() => void onYtdlpUpdate()}
            >
              <RefreshCw className="size-3.5" />
              {ytdlpBusy ? "Обновление…" : "Обновить yt-dlp"}
            </Button>
          </CardContent>
        </Card>

        <Card className="rounded-xl pt-6 pr-6 pb-6 pl-6">
          <CardHeader className="p-0 pb-4">
            <CardTitle className="text-lg">Обновления</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 p-0">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex min-w-0 items-start gap-2 text-sm">
                {updOk ? (
                  <CircleCheck className="mt-0.5 size-5 shrink-0 text-emerald-500" />
                ) : (
                  <CircleAlert className="text-destructive mt-0.5 size-5 shrink-0" />
                )}
                <div className="min-w-0">
                  <p>{updMsg}</p>
                  {updBusy ? (
                    <div className="mt-3 max-w-md">
                      <div className="bg-muted h-2 overflow-hidden rounded-full">
                        <div
                          className="bg-primary h-full rounded-full transition-all duration-300"
                          style={{ width: `${Math.min(100, Math.max(0, updPct))}%` }}
                        />
                      </div>
                      <p className="text-muted-foreground mt-1 text-xs tabular-nums">
                        {updPct > 0 ? `${updPct}%` : updMsg.includes("Скачивание") ? updMsg : "Ожидание…"}
                      </p>
                    </div>
                  ) : null}
                  {updChangelog ? (
                    <p className="text-muted-foreground mt-2 max-h-32 overflow-y-auto whitespace-pre-wrap text-xs">
                      {updChangelog}
                    </p>
                  ) : null}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  className="gap-2"
                  disabled={updBusy}
                  onClick={() => void onCheckUpdate()}
                >
                  <RefreshCw className="size-3.5" />
                  Проверить обновления
                </Button>
                {hasUpdate ? (
                  <>
                    <Button
                      size="sm"
                      className="gap-2"
                      disabled={updBusy}
                      onClick={() => void openUrl(updUrl || updHtmlUrl)}
                    >
                      <Download className="size-3.5" />
                      Скачать установщик
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      className="gap-2"
                      disabled={updBusy}
                      onClick={() => void onApplyUpdate()}
                    >
                      Автообновление
                    </Button>
                  </>
                ) : null}
              </div>
            </div>
            <p className="text-muted-foreground text-xs">
              Если автообновление зависает — жми «Скачать установщик» (или открой{" "}
              <button
                type="button"
                className="text-primary underline"
                onClick={() => void openUrl(updHtmlUrl)}
              >
                GitHub Releases
              </button>
              ). Настройки и история не сбрасываются.
            </p>
          </CardContent>
        </Card>

        <Card className="rounded-xl pt-6 pr-6 pb-6 pl-6">
          <CardHeader className="p-0 pb-4">
            <CardTitle className="text-lg">Бэкап</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center justify-between gap-8 p-0">
            <p className="text-muted-foreground text-sm">Сохраните настройки и историю загрузок в файл.</p>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => backupExport()}>
                Экспортировать настройки
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  const inp = document.createElement("input")
                  inp.type = "file"
                  inp.accept = ".zip"
                  inp.onchange = () => {
                    const f = inp.files?.[0]
                    if (f) void backupImport(f).then(() => refresh())
                  }
                  inp.click()
                }}
              >
                Импорт
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="rounded-xl pt-6 pr-6 pb-6 pl-6">
          <CardHeader className="p-0 pb-4">
            <CardTitle className="text-lg">Cookies</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5 p-0">
            <div className="flex flex-wrap items-center justify-between gap-8">
              <p className="text-muted-foreground max-w-xl text-sm">
                Cookies помогают сохранять авторизацию на поддерживаемых платформах.
                {cookieOk ? " (файл cookies активен)" : ""}
              </p>
              <div className="flex items-center gap-3">
                <Label htmlFor="cookies">Разрешить Cookies</Label>
                <Switch
                  id="cookies"
                  checked={draft.use_cookies}
                  onCheckedChange={(v) => patch({ use_cookies: v })}
                />
              </div>
            </div>
            <div className="border-border space-y-3 border-t pt-4">
              <p className="text-sm font-medium">Расширение для браузера</p>
              <p className="text-muted-foreground text-sm">
                Из браузера: ссылка сразу в очередь Media App (качество и формат
                задаёшь один раз в попапе расширения) и/или cookies
                (YouTube, Instagram, VK, Яндекс…). Media App должно быть запущено.
                После установки: «Отправить в Media App» — ссылка в очередь;
                «Отправить cookies» — авторизация.
              </p>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    void extensionSave().then((j) => {
                      setExtMsg(j.folder ? `Папка: ${j.folder}` : "Готово")
                      void cookiesStatus().then((s) => setCookieOk(s.active))
                    })
                  }}
                >
                  Получить расширение (zip)
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    window.location.href = "/api/extension/download"
                  }}
                >
                  Скачать zip
                </Button>
                <Button variant="ghost" size="sm" onClick={() => void cookiesOpenFolder()}>
                  Папка cookies
                </Button>
              </div>
              {extMsg ? <p className="text-muted-foreground text-xs">{extMsg}</p> : null}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="border-border mt-8 flex items-center justify-end gap-3 border-t pt-5 pb-5">
        {savedMsg ? <span className="text-muted-foreground text-sm">{savedMsg}</span> : null}
        <Button
          variant="secondary"
          onClick={() => {
            dirtyRef.current = false
            if (state?.settings) {
              setDraft({
                ...state.settings,
                check_disk_space: state.settings.check_disk_space ?? true,
                max_concurrent_downloads: state.settings.max_concurrent_downloads ?? 3,
              })
            }
          }}
        >
          Отменить
        </Button>
        <Button onClick={() => void commit()}>Сохранить изменения</Button>
      </div>
    </div>
  )
}
