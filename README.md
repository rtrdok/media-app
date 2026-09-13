# Media App

Windows-приложение для скачивания видео/аудио, библиотеки, плейлистов, распознавания треков (Shazam) и поиска аниме по кадру.

---

## 🇷🇺 Русский

### Что умеет
- Скачивание с YouTube, TikTok, Instagram, Coub, VK, RuTube, X, SoundCloud, Яндекс Музыка
- Библиотека медиа, плейлисты, перемешивание без повторов до конца очереди
- Встроенный плеер (аудио/видео), добавление в плейлисты из плеера
- Cookies / прокси для регионов с ограничениями
- Автообновление с GitHub Releases (Настройки → Проверить / Скачать и обновить)
- Настройки и история сохраняются в `%APPDATA%\MediaApp` и **не сбрасываются** при обновлении

### Установка
1. Скачай последний релиз: [Releases](https://github.com/rtrdok/media-app/releases/latest)
2. Рекомендуется **MediaApp-Installer.exe** — установка в `%LOCALAPPDATA%\MediaApp`
3. Или распакуй **MediaApp.zip** и запусти `MediaApp.exe`
4. Нужен **ffmpeg** только при запуске из исходников; в готовой сборке уже внутри

### Обновление
Настройки → **Проверить обновления**. Если есть новая версия — **Скачать и обновить**.  
В каждом релизе на GitHub кратко описано, что добавлено.

### Разработка
```bash
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
cd web-ui && npm install && npm run build && cd ..
py -3.11 main.py
```
Сборка: `build_exe.bat` или `scripts\build-exe.ps1`  
Установщик: `build_installer.bat`

---

## 🇬🇧 English

### Features
- Download from YouTube, TikTok, Instagram, Coub, VK, RuTube, X, SoundCloud, Yandex Music
- Media library, playlists, shuffle without repeats until the queue ends
- Built-in player; add the current track to one or more playlists
- Cookies / proxy for restricted regions
- Auto-update via GitHub Releases (Settings → Check / Download & update)
- Settings and history live in `%APPDATA%\MediaApp` and **survive updates**

### Install
1. Download the latest [Release](https://github.com/rtrdok/media-app/releases/latest)
2. Prefer **MediaApp-Installer.exe** → installs to `%LOCALAPPDATA%\MediaApp`
3. Or unzip **MediaApp.zip** and run `MediaApp.exe`
4. **ffmpeg** is required only when running from source; release builds include it

### Updates
Settings → **Check for updates**, then **Download & update** if available.  
Each GitHub release includes a short changelog.

### Develop
```bash
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
cd web-ui && npm install && npm run build && cd ..
py -3.11 main.py
```
Build: `build_exe.bat` / `scripts\build-exe.ps1`  
Installer: `build_installer.bat`

---

## Security note / Безопасность

Друзьям отдаём **готовые релизы** (exe/zip), не папку с исходниками.  
Сборка PyInstaller упаковывает код в бинарный архив; UI минифицируется.  
Полностью «закрыть» Python-приложение от разбора нельзя — не храните секреты в репозитории (`.env`, cookies в `.gitignore`).
