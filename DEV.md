# Разработка (только для автора)

Не публикуется в описании для пользователей — см. основной [README.md](README.md).

## Запуск из исходников

```bash
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
cd web-ui && npm install && npm run build && cd ..
py -3.11 main.py
```

Нужен **ffmpeg** в PATH при запуске из исходников (в готовой сборке уже внутри).

## Сборка

```bat
build_exe.bat
```

или `scripts\build-exe.ps1` → `dist\MediaApp\MediaApp.exe`

Установщик: `build_installer.bat` или `scripts\pack-release-zip.ps1` (zip + installer).

Релиз на GitHub: тег `vX.Y.Z`, ассеты `MediaApp.zip` и `MediaApp-Installer.exe`, текст из `CHANGELOG.md`.

## Проверки надёжности

Из корня проекта:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B -m pip check
```

Тесты используют временные базы, настройки и файлы. Сетевые загрузки,
запуск установщика и завершение процессов заменены тестовыми заглушками.
Один тест выполняет PowerShell-скрипт обновления с заведомо повреждённым
архивом: он завершается до замены файлов или запуска приложения.

Проверочная сборка отдельно от обычного `dist/MediaApp`:

```powershell
Push-Location web-ui
npm run build
npm run lint
Pop-Location
.\.venv\Scripts\python.exe -B -m PyInstaller --noconfirm --distpath dist/audit --workpath build/audit MediaApp.spec
```

Результаты аудита и ограничения: [AUDIT_RELIABILITY.md](AUDIT_RELIABILITY.md).

Регрессия освобождения ресурсов плеера (Node.js, установленный Edge):

```powershell
Push-Location web-ui
npm exec --yes --package=playwright -- node tests/player-reliability.mjs
Pop-Location
```

При первом запуске npm загрузит Playwright в свой кэш. Браузер запускается
без окна, с отдельным временным профилем и тестовым WAV; API подменены,
пользовательские медиа и данные не затрагиваются. Для другого Chromium
можно задать путь к исполняемому файлу через `PLAYWRIGHT_BROWSER`.
