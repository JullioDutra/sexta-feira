# Desfaz a inicialização automática da Sexta-Feira.
$Arquivo = Join-Path ([Environment]::GetFolderPath("Startup")) "Sexta-Feira.lnk"
if (Test-Path $Arquivo) {
  Remove-Item $Arquivo
  Write-Host "    ok  A Sexta-Feira não inicia mais com o Windows." -ForegroundColor Green
} else {
  Write-Host "    A Sexta-Feira já não estava na inicialização."
}
