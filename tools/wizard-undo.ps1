# Step-by-step undo: pick a move log and put every file back where it was.
$ErrorActionPreference = 'Stop'

Write-Host ''
Write-Host '=== 3-Undo: إرجاع الملفات إلى أماكنها القديمة ===' -ForegroundColor Cyan
Write-Host ''
$target = (Read-Host 'اكتب حرف القرص أو مسار المجلد الذي رتّبته سابقًا').Trim().Trim('"')
if ($target -match '^[A-Za-z]:?$') { $target = $target.Substring(0, 1).ToUpper() + ':\' }
$undoDir = Join-Path $target 'Organized\_undo'
$logs = @(Get-ChildItem -LiteralPath $undoDir -Filter 'move-log-*.csv' -ErrorAction SilentlyContinue |
          Sort-Object LastWriteTime -Descending)
if ($logs.Count -eq 0) {
    Write-Host "لم أجد أي سجل تراجع في: $undoDir" -ForegroundColor Red
    exit 1
}

Write-Host 'سجلات الترتيب الموجودة (الأحدث أولًا):'
for ($i = 0; $i -lt $logs.Count; $i++) {
    Write-Host ("  {0}) {1}   ({2:yyyy-MM-dd HH:mm})" -f ($i + 1), $logs[$i].Name, $logs[$i].LastWriteTime)
}
$pick = (Read-Host 'اكتب رقم السجل (اضغط Enter لاختيار 1)').Trim()
if (-not $pick) { $pick = '1' }
$n = 0
if (-not [int]::TryParse($pick, [ref]$n) -or $n -lt 1 -or $n -gt $logs.Count) {
    Write-Host 'رقم غير صحيح. لم أغيّر شيئًا.' -ForegroundColor Red
    exit 1
}
$log = $logs[$n - 1].FullName

$ok = (Read-Host 'سأعيد كل ملف في هذا السجل إلى مكانه القديم. اكتب YES للبدء').Trim()
if ($ok -cne 'YES') {
    Write-Host 'ألغيت. لم أغيّر شيئًا.' -ForegroundColor Green
    exit 0
}
& (Join-Path $PSScriptRoot 'undo.ps1') -Log $log
Write-Host ''
Write-Host 'انتهى التراجع! الملفات عادت إلى أماكنها القديمة.' -ForegroundColor Green
