import { CircleCheck, Download, RefreshCw } from "lucide-react"
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
  saveSettings,
} from "@/lib/api"
import type { AppSettings } from "@/types"

export function SettingsPage() {
  const { state, refresh } = useApp()
  const [draft, setDraft] = useState<AppSettings | null>(null)
  const [savedMsg, setSavedMsg] = useState("")
  const [updMsg, setUpdMsg] = useState("Установлена последняя версия")
  const [updChangelog, setUpdChangelog] = useState("")
  const [updBusy, setUpdBusy] = useState(false)
  const [hasUpdate, setHasUpdate] = useState(false)
  const [cookieOk, setCookieOk] = useState(false)
  const [extMsg, setExtMsg] = useState("")
  const dirtyRef = useRef(false)

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

  if (!draft) return null

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
    try {
      const j = await checkUpdate(false)
      if (j.update?.version) {
        setHasUpdate(true)
        setUpdMsg(`Доступна версия ${j.update.version}`)
        setUpdChangelog(j.update.changelog || j.changelog || "")
      } else {
        setHasUpdate(false)
        setUpdMsg(j.message || "Установлена последняя версия")
      }
    } finally {
      setUpdBusy(false)
    }
  }

  async function onApplyUpdate() {
    setUpdBusy(true)
    setUpdMsg("Скачивание обновления…")
    try {
      const j = await applyUpdate()
      setUpdMsg(j.message || (j.ok ? "Готово" : "Ошибка обновления"))
      if (j.restart) {
        setUpdMsg("Обновление скачано — приложение перезапустится…")
      }
    } catch (e) {
      setUpdMsg(String(e))
    } finally {
      setUpdBusy(false)
    }
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
              <Select value={draft.ui_lang} onValueChange={(v) => v && patch({ ui_lang: v })}>
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
              <Select value={draft.theme} onValueChange={(v) => v && patch({ theme: v })}>
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
                  Для друзей из РФ и других регионов, где YouTube / сервисы недоступны.
                  Прокси применяется ко всем загрузкам (не только yt-dlp): сначала прокси из
                  списка, затем прямое соединение.
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
          </CardContent>
        </Card>

        <Card className="rounded-xl pt-6 pr-6 pb-6 pl-6">
          <CardHeader className="p-0 pb-4">
            <CardTitle className="text-lg">Обновления</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 p-0">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex min-w-0 items-start gap-2 text-sm">
                <CircleCheck className="mt-0.5 size-5 shrink-0 text-emerald-500" />
                <div className="min-w-0">
                  <p>{updMsg}</p>
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
                  <Button
                    size="sm"
                    className="gap-2"
                    disabled={updBusy}
                    onClick={() => void onApplyUpdate()}
                  >
                    <Download className="size-3.5" />
                    Скачать и обновить
                  </Button>
                ) : null}
              </div>
            </div>
            <p className="text-muted-foreground text-xs">
              Обновления берутся с GitHub Releases. Настройки и история хранятся отдельно и не
              сбрасываются.
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
                Экспортирует cookies из Chrome или Firefox в Media App (YouTube, Instagram и др.).
                После установки откройте расширение на нужном сайте и нажмите «Отправить в Media App».
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
