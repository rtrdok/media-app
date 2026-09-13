const ru: Record<string, string> = {
  "nav.home": "Главная",
  "nav.downloads": "Загрузки",
  "nav.library": "Библиотека",
  "nav.music": "Музыка",
  "nav.anime": "Аниме",
  "nav.settings": "Настройки",
}

export function t(key: string, lang = "ru") {
  if (lang === "en") {
    const en: Record<string, string> = {
      "nav.home": "Home",
      "nav.downloads": "Downloads",
      "nav.library": "Library",
      "nav.music": "Music",
      "nav.anime": "Anime",
      "nav.settings": "Settings",
    }
    return en[key] ?? key
  }
  return ru[key] ?? key
}

export function pageLabel(page: string, lang = "ru") {
  return t(`nav.${page === "music" ? "music" : page}`, lang)
}
