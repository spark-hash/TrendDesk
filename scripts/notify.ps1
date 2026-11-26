Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$notice = New-Object System.Windows.Forms.NotifyIcon
$notice.Icon = [System.Drawing.SystemIcons]::Information
$notice.Visible = $true
$notice.BalloonTipTitle = $env:TREND_DESK_TITLE
$notice.BalloonTipText = $env:TREND_DESK_MESSAGE
$notice.ShowBalloonTip(8000)
Start-Sleep -Seconds 9
$notice.Dispose()
