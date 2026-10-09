# Instalador da Sexta-Feira para Windows 11
$ErrorActionPreference = "Stop"
$Raiz = Split-Path -Parent $PSScriptRoot
Set-Location $Raiz
[Console]::OutputEncoding = [Text.Encoding]::UTF8

function Titulo($texto) { Write-Host ""; Write-Host "==  $texto" -ForegroundColor Yellow }
function Ok($texto) { Write-Host "    ok  $texto" -ForegroundColor Green }
function Aviso($texto) { Write-Host "    !!  $texto" -ForegroundColor Red }
function Pergunta($texto) { $r = Read-Host "    $texto (S/N)"; return ($r -match '^[sSyY]') }
function AtualizarPath {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

Write-Host ""
Write-Host "  Sexta-Feira — instalação" -ForegroundColor Yellow
Write-Host "  Pasta: $Raiz"

# ------------------------------------------------------------------ 1. Python
Titulo "1/6  Python 3.12"
$temPython = $false
try { & py -3.12 --version *> $null; $temPython = ($LASTEXITCODE -eq 0) } catch { $temPython = $false }
if (-not $temPython -and (Get-Command winget -ErrorAction SilentlyContinue)) {
  if (Pergunta "Python 3.12 não encontrado. Instalar agora (winget)?") {
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    AtualizarPath
    try { & py -3.12 --version *> $null; $temPython = ($LASTEXITCODE -eq 0) } catch { $temPython = $false }
  }
}
if (-not $temPython) {
  Aviso "Instale o Python 3.12 em https://www.python.org/downloads/ (marque 'Add to PATH') e rode o instalador de novo."
  exit 1
}
Ok (& py -3.12 --version)

# ------------------------------------------------------------------ 2. Dependências
Titulo "2/6  Ambiente virtual e bibliotecas (alguns minutos)"
if (-not (Test-Path ".venv\Scripts\python.exe")) { & py -3.12 -m venv .venv }
$Python = Join-Path $Raiz ".venv\Scripts\python.exe"
$PythonW = Join-Path $Raiz ".venv\Scripts\pythonw.exe"
& $Python -m pip install --upgrade pip --quiet
& $Python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Aviso "Falha ao instalar as bibliotecas. Veja a mensagem acima."; exit 1 }
Ok "bibliotecas instaladas"

# ------------------------------------------------------------------ 3. Configuração
Titulo "3/6  Configuração"
if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Ok "arquivo .env criado (ajuste modelo, voz e câmera quando quiser)"
} else {
  Ok ".env já existe (mantido)"
}

# ------------------------------------------------------------------ 4. Modelos
Titulo "4/6  Modelos de rosto, mãos e voz (~600 MB, só na primeira vez)"
& $Python -m sexta baixar
if ($LASTEXITCODE -ne 0) { Aviso "Algum modelo não baixou. Dá para rodar de novo depois: iniciar.bat baixar" }

# ------------------------------------------------------------------ 5. Ollama
Titulo "5/6  Cérebro local (Ollama)"
$linha = Select-String -Path ".env" -Pattern '^\s*OLLAMA_MODELO\s*=\s*(.+)$' | Select-Object -First 1
$Modelo = if ($linha) { $linha.Matches[0].Groups[1].Value.Trim() } else { "qwen3.5:9b" }
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  if ((Get-Command winget -ErrorAction SilentlyContinue) -and (Pergunta "Ollama não encontrado. Instalar agora (winget)?")) {
    winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
    AtualizarPath
  }
}
if (Get-Command ollama -ErrorAction SilentlyContinue) {
  Write-Host "    Baixando o modelo $Modelo (alguns GB, pode demorar)..."
  & ollama pull $Modelo
  if ($LASTEXITCODE -eq 0) { Ok "modelo $Modelo pronto" } else { Aviso "Não consegui baixar $Modelo. Abra o Ollama e rode: ollama pull $Modelo" }
} else {
  Aviso "Instale o Ollama em https://ollama.com/download e depois rode: ollama pull $Modelo"
}

# ------------------------------------------------------------------ 6. Atalhos
Titulo "6/6  Atalhos"
$Icone = Join-Path $Raiz "scripts\sexta.ico"
& $Python -c "from PIL import Image; Image.open(r'hud/public/icone-512.png').save(r'scripts/sexta.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(256,256)])"
$Shell = New-Object -ComObject WScript.Shell
$AreaDeTrabalho = [Environment]::GetFolderPath("Desktop")
$Atalho = $Shell.CreateShortcut((Join-Path $AreaDeTrabalho "Sexta-Feira.lnk"))
$Atalho.TargetPath = $PythonW
$Atalho.Arguments = "-m sexta"
$Atalho.WorkingDirectory = $Raiz
$Atalho.IconLocation = $Icone
$Atalho.Description = "Sexta-Feira"
$Atalho.Save()
Ok "atalho 'Sexta-Feira' criado na área de trabalho"
if (Pergunta "Iniciar a Sexta-Feira junto com o Windows?") {
  & (Join-Path $PSScriptRoot "iniciar_com_windows.ps1")
}

Write-Host ""
Write-Host "  Pronto!" -ForegroundColor Green
Write-Host "  - Abra pelo atalho 'Sexta-Feira' (sem janela) ou pelo iniciar.bat (com registros)."
Write-Host "  - Na primeira vez o Windows pergunta sobre o firewall: permita em 'Redes privadas' para o celular funcionar."
Write-Host "  - Para destravar o próprio Windows com o rosto, configure o Windows Hello (veja o README)."
