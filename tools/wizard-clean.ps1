# Remove folders left completely empty after organizing. Files are never touched:
# a folder with even one file (desktop.ini included) is kept. Undo recreates folders it needs.
$ErrorActionPreference = 'Stop'

Write-Host ''
Write-Host '=== 4-Clean-Empty-Folders: حذف المجلدات الفارغة فقط ===' -ForegroundColor Cyan
Write-Host ''
$target = (Read-Host 'اكتب حرف القرص أو مسار المجلد').Trim().Trim('"')
if ($target -match '^[A-Za-z]:?$') { $target = $target.Substring(0, 1).ToUpper() + ':\' }
if (-not $target -or -not (Test-Path -LiteralPath $target -PathType Container)) {
    Write-Host "لم أجد هذا المكان: $target" -ForegroundColor Red
    exit 1
}
$target = (Resolve-Path -LiteralPath $target).Path
if (Test-Path (Join-Path $target 'Windows\System32')) {
    Write-Host 'هذا قرص ويندوز. لن ألمسه.' -ForegroundColor Red
    exit 1
}

$skipAtRoot = @('$RECYCLE.BIN', 'System Volume Information', 'Organized', 'FOUND.000')
$empty = New-Object System.Collections.Generic.List[string]
$guard = [System.IO.FileAttributes]::ReparsePoint -bor [System.IO.FileAttributes]::System

# Returns $true when $dir holds no files at any depth; adds empty folders children-first.
function Find-Empty([string] $dir) {
    try {
        $files = [System.IO.Directory]::GetFiles($dir)
        $subs = [System.IO.Directory]::GetDirectories($dir)
    } catch { return $false }
    $allEmpty = $true
    foreach ($s in $subs) {
        if ($dir -eq $target -and $skipAtRoot -contains [System.IO.Path]::GetFileName($s)) { $allEmpty = $false; continue }
        if ([System.IO.File]::GetAttributes($s) -band $guard) { $allEmpty = $false; continue }
        if (Find-Empty $s) { $empty.Add($s) } else { $allEmpty = $false }
    }
    return ($files.Count -eq 0 -and $allEmpty)
}

Write-Host 'أبحث عن المجلدات الفارغة...'
Find-Empty $target | Out-Null
if ($empty.Count -eq 0) {
    Write-Host 'لا توجد مجلدات فارغة. كل شيء نظيف!' -ForegroundColor Green
    exit 0
}
Write-Host "وجدت $($empty.Count) مجلدًا فارغًا تمامًا (لا يوجد داخلها أي ملف)."
$ok = (Read-Host 'اكتب YES لحذف هذه المجلدات الفارغة فقط').Trim()
if ($ok -cne 'YES') {
    Write-Host 'ألغيت. لم أحذف شيئًا.' -ForegroundColor Green
    exit 0
}
$removed = 0; $failed = 0
foreach ($d in $empty) {
    try { [System.IO.Directory]::Delete($d, $false); $removed++ } catch { $failed++ }   # $false: refuses non-empty
}
Write-Host "حذفت $removed مجلدًا فارغًا. لم أستطع حذف: $failed" -ForegroundColor Green
