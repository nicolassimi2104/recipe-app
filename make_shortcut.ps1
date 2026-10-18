# Puts a "Recipe App" shortcut (with the app's icon) on your Desktop and in
# the Start menu. Run it once from PowerShell in this folder:
#     powershell -ExecutionPolicy Bypass -File make_shortcut.ps1
# To pin it to the taskbar: right-click the Desktop shortcut,
# Show more options, Pin to taskbar.

$here = $PSScriptRoot
$places = @(
    [Environment]::GetFolderPath("Desktop"),
    (Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs")
)
$shell = New-Object -ComObject WScript.Shell

foreach ($place in $places) {
    $link = $shell.CreateShortcut((Join-Path $place "Recipe App.lnk"))
    # Pointing at cmd.exe (not the .bat directly) is what lets Windows pin it to the taskbar
    $link.TargetPath = "$env:SystemRoot\System32\cmd.exe"
    $link.Arguments = "/c `"$here\start_app.bat`""
    $link.WorkingDirectory = $here
    $link.IconLocation = "$here\static\app.ico"
    $link.WindowStyle = 7          # start the black window minimized
    $link.Description = "Start the Recipe App and open it in your browser"
    $link.Save()
    Write-Output "Made $($link.FullName)"
}
