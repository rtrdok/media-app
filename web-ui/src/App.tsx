import { OnboardingModal } from "@/components/OnboardingModal"
import { AppShell } from "@/components/layout/AppShell"
import { useApp } from "@/context/AppProvider"
import { AnimePage } from "@/pages/AnimePage"
import { DownloadsPage } from "@/pages/DownloadsPage"
import { HomePage } from "@/pages/HomePage"
import { LibraryPage } from "@/pages/LibraryPage"
import { MusicPage } from "@/pages/MusicPage"
import { SettingsPage } from "@/pages/SettingsPage"

export default function App() {
  const { page } = useApp()

  let content = <HomePage />
  if (page === "downloads") content = <DownloadsPage />
  else if (page === "library") content = <LibraryPage />
  else if (page === "music") content = <MusicPage />
  else if (page === "anime") content = <AnimePage />
  else if (page === "settings") content = <SettingsPage />

  return (
    <AppShell>
      {content}
      <OnboardingModal />
    </AppShell>
  )
}
