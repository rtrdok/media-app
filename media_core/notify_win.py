"""Windows toast без внешних зависимостей (PowerShell + WinRT)."""



from __future__ import annotations



import subprocess

from media_core.logging_setup import log





def show_toast(title: str, body: str = "") -> bool:

    title = (title or "Media App").replace("'", "''")

    body = (body or "").replace("'", "''")

    # XML toast через Windows.UI.Notifications

    ps = f"""

$ErrorActionPreference = 'Stop'

try {{

  [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null

  [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

  $xml = New-Object Windows.Data.Xml.Dom.XmlDocument

  $xml.LoadXml(@'

<toast><visual><binding template="ToastGeneric">

  <text>{title}</text>

  <text>{body}</text>

</binding></visual></toast>

'@)

  $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)

  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Media App').Show($toast)

  exit 0

}} catch {{

  Add-Type -AssemblyName System.Windows.Forms

  $n = New-Object System.Windows.Forms.NotifyIcon

  $n.Icon = [System.Drawing.SystemIcons]::Information

  $n.Visible = $true

  $n.ShowBalloonTip(4000, '{title}', '{body}', [System.Windows.Forms.ToolTipIcon]::Info)

  Start-Sleep -Milliseconds 500

  $n.Dispose()

  exit 0

}}

"""

    try:

        from media_core.utils import subprocess_no_window_kwargs

        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=20,
            **subprocess_no_window_kwargs(),
        )

        return r.returncode == 0

    except Exception as e:

        log.warning("toast failed: %s", e)

        return False


