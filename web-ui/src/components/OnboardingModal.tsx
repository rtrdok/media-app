import { useEffect, useState } from "react"
import { AppModal } from "@/components/ui/AppModal"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { useApp } from "@/context/AppProvider"
import { saveSettings } from "@/lib/api"

/** Первый запуск: папка, прокси, cookies. */
export function OnboardingModal() {
  const { state, refresh } = useApp()
  const settings = state?.settings
  const [open, setOpen] = useState(false)
  const [dir, setDir] = useState("")
  const [useProxy, setUseProxy] = useState(false)
  const [proxyList, setProxyList] = useState("")
  const [useCookies, setUseCookies] = useState(false)
  const [busy, setBusy] = useState(false)
  const [inited, setInited] = useState(false)

  useEffect(() => {
    if (!settings || inited) return
    setInited(true)
    if (settings.onboarding_done) return
    setDir(settings.download_dir || "")
    setUseProxy(!!settings.use_proxy)
    setProxyList(settings.proxy_list || "")
    setUseCookies(!!settings.use_cookies)
    setOpen(true)
  }, [settings, inited])

  if (!open || !settings) return null

  async function finish() {
    setBusy(true)
    try {
      await saveSettings({
        ...settings!,
        download_dir: dir.trim() || settings!.download_dir,
        use_proxy: useProxy,
        proxy_list: proxyList,
        use_cookies: useCookies,
        onboarding_done: true,
      })
      setOpen(false)
      void refresh()
    } finally {
      setBusy(false)
    }
  }

  return (
    <AppModal
      open={open}
      title="Добро пожаловать в Media App"
      description="Короткая настройка — потом можно изменить в «Настройки»."
      onClose={() => void finish()}
      footer={
        <Button disabled={busy} onClick={() => void finish()}>
          Готово
        </Button>
      }
    >
      <div className="space-y-4">
        <div>
          <Label className="mb-1.5 block">Папка загрузок</Label>
          <input
            className="border-input bg-background h-10 w-full rounded-xl border px-3 text-sm"
            value={dir}
            onChange={(e) => setDir(e.target.value)}
          />
        </div>
        <div className="flex items-center justify-between gap-4">
          <Label htmlFor="ob-proxy">Использовать прокси</Label>
          <Switch id="ob-proxy" checked={useProxy} onCheckedChange={setUseProxy} />
        </div>
        {useProxy ? (
          <textarea
            rows={3}
            className="border-input bg-background w-full rounded-xl border px-3 py-2 font-mono text-xs"
            placeholder="socks5://user:pass@host:1080"
            value={proxyList}
            onChange={(e) => setProxyList(e.target.value)}
          />
        ) : null}
        <div className="flex items-center justify-between gap-4">
          <div>
            <Label htmlFor="ob-cook" className="block">
              YouTube cookies
            </Label>
            <p className="text-muted-foreground text-xs">
              Если видео «не для бота» — включи и положи cookies.txt
            </p>
          </div>
          <Switch id="ob-cook" checked={useCookies} onCheckedChange={setUseCookies} />
        </div>
      </div>
    </AppModal>
  )
}
