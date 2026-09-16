import {
  Bell,
  ChevronRight,
  Clapperboard,
  Cookie,
  Download,
  FolderOpen,
  Home,
  Library,
  Monitor,
  Music2,
  Search,
  Settings,
  Tv,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"
import type { PageId } from "@/types"
import { GlobalSearchModal } from "@/components/GlobalSearchModal"
import { useApp } from "@/context/AppProvider"
import { ackNotify, cookiesOpenFolder, cookiesStatus, openPath } from "@/lib/api"
import { pageLabel, t } from "@/lib/i18n"
import { isVideoSrc } from "@/lib/media"
import { cn } from "@/lib/utils"
import { PlayerBar, VIDEO_PLAYER_DOCK_PAD } from "./PlayerBar"

const NAV: { id: PageId; icon: typeof Home }[] = [
  { id: "home", icon: Home },
  { id: "downloads", icon: Download },
  { id: "library", icon: Library },
  { id: "music", icon: Music2 },
  { id: "anime", icon: Tv },
  { id: "settings", icon: Settings },
]

type PanelId = "notify" | "pc" | null

export function AppShell({ children }: { children: React.ReactNode }) {
  const {
    page,
    setPage,
    state,
    openGlobalSearch,
    closeGlobalSearch,
    globalSearchOpen,
    notifyDot,
    player,
    refresh,
    miniPlayer,
  } = useApp()
  const playerVisible = Boolean(player?.src)
  const videoPlaying =
    playerVisible && (player?.kind === "video" || (player?.src ? isVideoSrc(player.src) : false))
  const lang = state?.settings?.ui_lang ?? "ru"
  const [dragOver, setDragOver] = useState(false)
  const [panel, setPanel] = useState<PanelId>(null)
  const [cookieInfo, setCookieInfo] = useState<{ exists: boolean; count: number } | null>(null)
  const headerActionsRef = useRef<HTMLDivElement | null>(null)

  const lastMsg = state?.last?.message?.trim() || ""
  const lastErr = state?.last?.error?.trim() || ""
  const queueNotes = (state?.queue ?? []).filter(
    (q) => q.status === "done" || q.status === "error" || q.status === "running",
  )
  const hasNotifications = Boolean(notifyDot || lastMsg || lastErr || queueNotes.length)
  const pcUser = state?.pc?.user?.trim() || "Пользователь"
  const pcHost = state?.pc?.host?.trim() || "Этот ПК"

  useEffect(() => {
    if (!panel) return
    function onDoc(e: MouseEvent) {
      const root = headerActionsRef.current
      if (root && !root.contains(e.target as Node)) setPanel(null)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setPanel(null)
    }
    document.addEventListener("mousedown", onDoc)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onDoc)
      document.removeEventListener("keydown", onKey)
    }
  }, [panel])

  useEffect(() => {
    if (panel !== "pc") return
    void cookiesStatus()
      .then((j) => {
        const raw = j as { exists?: boolean; count?: number; active?: boolean }
        setCookieInfo({
          exists: Boolean(raw.exists ?? raw.active),
          count: Number(raw.count || 0),
        })
      })
      .catch(() => setCookieInfo(null))
  }, [panel])

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    const files = [...e.dataTransfer.files]
    const text = e.dataTransfer.getData("text") || e.dataTransfer.getData("text/plain")
    window.dispatchEvent(new CustomEvent("media-app-drop", { detail: { files, text } }))
  }

  async function openNotifyPanel() {
    setPanel((p) => (p === "notify" ? null : "notify"))
    if (notifyDot) {
      try {
        await ackNotify()
        await refresh(true)
      } catch {
        /* ignore */
      }
    }
  }

  return (
    <div
      className="bg-background text-foreground relative flex h-full min-h-0"
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
    >
      {dragOver && !miniPlayer ? (
        <div className="border-primary bg-primary/10 pointer-events-none absolute inset-0 z-50 flex items-center justify-center border-2 border-dashed">
          <p className="text-foreground text-sm font-medium">Отпустите ссылку или файл</p>
        </div>
      ) : null}

      {/* В мини-режиме скрываем оболочку — остаётся только плеер (аудио не размонтируется). */}
      <aside
        className={cn(
          "bg-sidebar border-border fixed z-30 top-0 bottom-0 left-0 flex w-[232px] flex-col border-r pt-5 pr-4 pb-5 pl-4",
          miniPlayer && "hidden",
        )}
      >
        <div className="flex items-center gap-3 pr-3 pb-8 pl-3">
          <div className="bg-primary text-primary-foreground flex size-9 items-center justify-center rounded-xl shadow-sm">
            <Clapperboard className="size-5 stroke-[2]" />
          </div>
          <span className="text-base font-semibold tracking-tight">Media App</span>
        </div>
        <nav className="flex flex-1 flex-col gap-2" aria-label="Основная навигация">
          {NAV.map(({ id, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => {
                setPanel(null)
                setPage(id)
              }}
              className={cn(
                "flex h-11 items-center gap-3 rounded-xl pr-3 pl-3 text-sm font-medium transition-colors",
                page === id
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
              )}
            >
              <Icon className="size-5" />
              <span>{t(`nav.${id === "music" ? "music" : id}`, lang)}</span>
            </button>
          ))}
        </nav>
        <div className="text-muted-foreground px-3 pt-4 text-xs">
          Media App v{state?.version ?? "…"}
        </div>
      </aside>

      <div
        className={cn(
          "ml-[232px] flex min-h-0 min-w-0 flex-1 flex-col",
          miniPlayer && "ml-0 hidden",
        )}
      >
        <header className="bg-background border-border relative z-40 flex h-16 shrink-0 items-center justify-between border-b pr-8 pl-8">
          <div className="text-muted-foreground flex items-center gap-2 text-sm">
            <span>Media App</span>
            <ChevronRight className="size-4" />
            <span className="text-foreground font-medium">{pageLabel(page, lang)}</span>
          </div>
          <div ref={headerActionsRef} className="relative flex items-center gap-3">
            <button
              type="button"
              aria-label="Глобальный поиск"
              title="Поиск (Ctrl+K)"
              onClick={() => {
                setPanel(null)
                openGlobalSearch()
              }}
              className="text-muted-foreground hover:text-foreground flex size-9 items-center justify-center rounded-lg transition-colors"
            >
              <Search className="size-4" />
            </button>

            <div className="relative">
              <button
                type="button"
                aria-label="Уведомления"
                title="Уведомления"
                aria-expanded={panel === "notify"}
                onClick={() => void openNotifyPanel()}
                className="text-muted-foreground hover:text-foreground relative flex size-9 items-center justify-center rounded-lg transition-colors"
              >
                <Bell className="size-4" />
                {notifyDot && (
                  <span className="bg-primary absolute top-2 right-2 size-1.5 rounded-full" />
                )}
              </button>
              {panel === "notify" ? (
                <div className="border-border bg-popover text-popover-foreground absolute top-11 right-0 z-50 w-80 overflow-hidden rounded-xl border shadow-lg">
                  <div className="border-border border-b px-3 py-2">
                    <p className="text-sm font-medium">Оповещения</p>
                    <p className="text-muted-foreground text-xs">Статус загрузок и события</p>
                  </div>
                  <div className="max-h-72 overflow-y-auto p-1">
                    {!hasNotifications ? (
                      <p className="text-muted-foreground px-2 py-6 text-center text-sm">
                        Пока нет оповещений
                      </p>
                    ) : (
                      <>
                        {lastMsg ? (
                          <div className="rounded-md px-2 py-2">
                            <p className="text-sm font-medium">{lastMsg}</p>
                            <p className="text-muted-foreground text-xs">Последнее событие</p>
                          </div>
                        ) : null}
                        {lastErr ? (
                          <div className="rounded-md px-2 py-2">
                            <p className="text-destructive text-sm font-medium">{lastErr}</p>
                            <p className="text-muted-foreground text-xs">Ошибка</p>
                          </div>
                        ) : null}
                        {queueNotes.slice(0, 8).map((q) => (
                          <div key={q.id} className="rounded-md px-2 py-2">
                            <p className="truncate text-sm font-medium">{q.title || q.url}</p>
                            <p className="text-muted-foreground text-xs">
                              {q.status === "running"
                                ? "Загрузка…"
                                : q.status === "done"
                                  ? "Готово"
                                  : q.error || "Ошибка"}
                            </p>
                          </div>
                        ))}
                      </>
                    )}
                  </div>
                  <div className="border-border border-t p-1">
                    <button
                      type="button"
                      className="hover:bg-accent flex w-full items-center rounded-md px-2 py-2 text-left text-sm"
                      onClick={() => {
                        setPanel(null)
                        setPage("downloads")
                      }}
                    >
                      Открыть загрузки
                    </button>
                  </div>
                </div>
              ) : null}
            </div>

            <div className="relative">
              <button
                type="button"
                aria-label="Этот компьютер"
                title="Этот компьютер"
                aria-expanded={panel === "pc"}
                onClick={() => setPanel((p) => (p === "pc" ? null : "pc"))}
                className="bg-muted text-foreground hover:bg-muted/80 flex size-9 items-center justify-center rounded-full transition-colors"
              >
                <Monitor className="size-4" />
              </button>
              {panel === "pc" ? (
                <div className="border-border bg-popover text-popover-foreground absolute top-11 right-0 z-50 w-80 overflow-hidden rounded-xl border shadow-lg">
                  <div className="border-border flex items-start gap-3 border-b px-3 py-3">
                    <div className="bg-muted flex size-10 shrink-0 items-center justify-center rounded-full">
                      <Monitor className="size-5" />
                    </div>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{pcUser}</p>
                      <p className="text-muted-foreground truncate text-xs">{pcHost}</p>
                      <p className="text-muted-foreground mt-1 text-xs">
                        Media App v{state?.version ?? "…"}
                      </p>
                    </div>
                  </div>
                  <div className="space-y-2 px-3 py-3">
                    <div>
                      <p className="text-muted-foreground text-xs">Папка загрузок</p>
                      <p className="mt-0.5 break-all text-xs leading-relaxed">
                        {state?.download_dir || "Не задана"}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground text-xs">Cookies</p>
                      <p className="mt-0.5 text-xs">
                        {cookieInfo == null
                          ? "Проверка…"
                          : cookieInfo.exists
                            ? `Активны${cookieInfo.count ? ` · ${cookieInfo.count}` : ""}`
                            : "Не загружены"}
                      </p>
                    </div>
                  </div>
                  <div className="border-border space-y-0.5 border-t p-1">
                    <button
                      type="button"
                      className="hover:bg-accent flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm"
                      onClick={() => {
                        void openPath(state?.download_dir || "")
                        setPanel(null)
                      }}
                    >
                      <FolderOpen className="size-4 shrink-0" />
                      Открыть папку загрузок
                    </button>
                    <button
                      type="button"
                      className="hover:bg-accent flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm"
                      onClick={() => {
                        void cookiesOpenFolder()
                        setPanel(null)
                      }}
                    >
                      <Cookie className="size-4 shrink-0" />
                      Папка cookies
                    </button>
                    <button
                      type="button"
                      className="hover:bg-accent flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm"
                      onClick={() => {
                        setPanel(null)
                        setPage("settings")
                      }}
                    >
                      <Settings className="size-4 shrink-0" />
                      Открыть настройки
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </header>

        <div
          className={cn(
            "relative min-h-0 flex-1 overflow-y-auto",
            playerVisible && (videoPlaying ? VIDEO_PLAYER_DOCK_PAD : "pb-28"),
          )}
        >
          {children}
        </div>
      </div>
      {/* PlayerBar всегда смонтирован — при мини просто меняет раскладку */}
      <PlayerBar showOnSettings />
      <GlobalSearchModal open={globalSearchOpen} onClose={closeGlobalSearch} />
    </div>
  )
}
