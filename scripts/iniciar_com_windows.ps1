# Faz a Sexta-Feira abrir junto com o Windows (atalho na pasta Inicializar).
$Raiz = Split-Path -Parent $PSScriptRoot
$Shell = New-Object -ComObject WScript.Shell
$Pasta = [Environment]::GetFolderPath("Startup")
$Atalho = $Shell.CreateShortcut((Join-Path $Pasta "Sexta-Feira.lnk"))
$Atalho.TargetPath = Join-Path $Raiz ".venv\Scripts\pythonw.exe"
$Atalho.Arguments = "-m sexta"
$Atalho.WorkingDirectory = $Raiz
$Atalho.IconLocation = Join-Path $Raiz "scripts\sexta.ico"
$Atalho.Save()
Write-Host "    ok  A Sexta-Feira vai iniciar junto com o Windows." -ForegroundColor Green
Write-Host "        Para desfazer: scripts\remover_inicializacao.ps1"
