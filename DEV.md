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
