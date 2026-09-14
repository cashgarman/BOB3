[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$h = [Windows.UI.Notifications.ToastNotificationManager]::History.GetHistory('Cash.Bob')
Write-Host ("history count=" + @($h).Count)
$h | ForEach-Object { Write-Host $_.Content.GetXml() }
