# Step-by-step organize: ask for the place, classify photos, preview, confirm, move.
$ErrorActionPreference = 'Stop'
$Here = Split-Path $PSScriptRoot -Parent
$VPy = Join-Path $Here '.venv\Scripts\python.exe'

Write-Host ''
Write-Host '=== 2-Organize: ترتيب قرص أو مجلد ===' -ForegroundColor Cyan
Write-Host ''
Write-Host 'أمثلة:  E   أو   E:\   أو   D:\Photos'
$target = (Read-Host 'اكتب حرف القرص أو مسار المجلد ثم اضغط Enter').Trim().Trim('"')
if ($target -match '^[A-Za-z]:?$') { $target = $target.Substring(0, 1).ToUpper() + ':\' }
if (-not $target -or -not (Test-Path -LiteralPath $target -PathType Container)) {
    Write-Host "لم أجد هذا المكان: $target" -ForegroundColor Red
    exit 1
}
$target = (Resolve-Path -LiteralPath $target).Path
$profileDir = $env:USERPROFILE.TrimEnd('\') + '\'
if ((Test-Path (Join-Path $target 'Windows\System32')) -or $profileDir.StartsWith($target.TrimEnd('\') + '\', 'OrdinalIgnoreCase')) {
    Write-Host 'هذا المكان فيه ويندوز أو مجلد المستخدم كاملًا. ترتيبه يخرّب البرامج، لذلك لن ألمسه.' -ForegroundColor Red
    Write-Host 'اختر قرص بيانات (مثل E) أو مجلدًا محددًا (مثل مجلد Downloads).'
    exit 1
}
$labels = Join-Path $target 'Organized\_labels\photo-labels.csv'

Write-Host ''
Write-Host 'هل تريد تصنيف الصور حسب محتواها (أشخاص، طبيعة، طعام، معدّلة...)؟'
Write-Host 'إذا اخترت N ستُرتّب الصور حسب النوع والسنة فقط.'
$photos = (Read-Host 'اكتب Y للموافقة أو N للرفض').Trim().ToUpper()

if ($photos -eq 'Y') {
    if (-not (Test-Path $VPy)) {
        Write-Host 'الجهاز غير مجهّز بعد. شغّل 1-Setup.bat أولًا.' -ForegroundColor Red
        exit 1
    }
    Write-Host ''
    Write-Host '[1/3] أصنّف الصور... (لا يُنقل أي ملف، ولا يحتاج إنترنت)' -ForegroundColor Yellow
    & $VPy -W ignore (Join-Path $PSScriptRoot 'classify.py') --root $target
    if ($LASTEXITCODE -ne 0) { throw 'توقف التصنيف بسبب خطأ. يمكنك تشغيله مرة أخرى وسيكمل من حيث توقف.' }
}

$params = @{ Drive = $target }
if ($photos -eq 'Y' -and (Test-Path $labels)) { $params.Labels = $labels }

Write-Host ''
Write-Host '[2/3] معاينة: أعدّ الملفات فقط ولا أنقل شيئًا...' -ForegroundColor Yellow
& (Join-Path $PSScriptRoot 'organize.ps1') @params -Mode Preview

Write-Host ''
Write-Host 'هذه الأرقام هي ما سيُنقل إلى المجلد Organized.' -ForegroundColor Cyan
$ok = (Read-Host 'لبدء النقل اكتب YES بالأحرف الكبيرة. لأي شيء آخر سألغي').Trim()
if ($ok -cne 'YES') {
    Write-Host 'ألغيت. لم يُنقل أي ملف.' -ForegroundColor Green
    exit 0
}

Write-Host ''
Write-Host '[3/3] أنقل الملفات وأكتب سجل التراجع... لا تفصل القرص!' -ForegroundColor Yellow
& (Join-Path $PSScriptRoot 'organize.ps1') @params -Mode Move

Write-Host ''
Write-Host 'انتهى الترتيب! ملفاتك الآن في:' -ForegroundColor Green
Write-Host (Join-Path $target 'Organized')
Write-Host 'إذا لم يعجبك الترتيب شغّل 3-Undo.bat'
