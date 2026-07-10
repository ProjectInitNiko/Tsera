<#
  Installe PersonalWhisper comme app Windows :
    - raccourci sur le Bureau (lance en tray, sans console)
    - démarrage automatique au login (dossier shell:startup)

  Usage :
    powershell -ExecutionPolicy Bypass -File install.ps1            # Bureau + démarrage auto
    powershell -ExecutionPolicy Bypass -File install.ps1 -NoStartup # Bureau seulement
    powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall # retire les deux raccourcis
#>
param(
    [switch]$NoStartup,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$root    = Split-Path -Parent $MyInvocation.MyCommand.Definition
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
$icon    = Join-Path $root 'icon.ico'
$name    = 'PersonalWhisper.lnk'

$desktop = [Environment]::GetFolderPath('Desktop')
$startup = [Environment]::GetFolderPath('Startup')

# Bureau : ouvre la fenêtre. Démarrage auto (login) : « --tray » = démarre réduit.
$targets = @(
    [pscustomobject]@{ Path = (Join-Path $desktop $name); Args = 'app.py' }
)
if (-not $NoStartup) {
    $targets += [pscustomobject]@{ Path = (Join-Path $startup $name); Args = 'app.py --tray' }
}

if ($Uninstall) {
    foreach ($lnk in @((Join-Path $desktop $name), (Join-Path $startup $name))) {
        if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Host "Retiré : $lnk" }
    }
    return
}

if (-not (Test-Path $pythonw)) { throw "pythonw.exe introuvable : $pythonw" }

$shell = New-Object -ComObject WScript.Shell
foreach ($t in $targets) {
    $s = $shell.CreateShortcut($t.Path)
    $s.TargetPath       = $pythonw
    $s.Arguments        = $t.Args
    $s.WorkingDirectory = $root
    $s.WindowStyle      = 7           # aucune fenêtre console : pythonw n'en ouvre pas
    $s.Description       = 'PersonalWhisper — dictée vocale locale (Ctrl+Espace / Ctrl+Shift+Espace)'
    if (Test-Path $icon) { $s.IconLocation = $icon }
    $s.Save()
    Write-Host "Créé : $($t.Path)  [$($t.Args)]"
}
Write-Host ''
Write-Host 'Fait. Double-clic sur le raccourci du Bureau pour lancer (icône NK dans la barre système).'
if (-not $NoStartup) { Write-Host 'Se lancera aussi automatiquement à chaque démarrage de Windows.' }
