# Step-by-step organize: classify photos, plan, review in the browser, confirm, move, program pages.
$ErrorActionPreference = 'Stop'
$Here = Split-Path $PSScriptRoot -Parent
$VPy = Join-Path $Here '.venv\Scripts\python.exe'
$env:PYTHONIOENCODING = 'utf-8'

Write-Host ''
Write-Host '=== 2-Organize: ترتيب قرص أو مجلد ===' -ForegroundColor Cyan
Write-Host ''
if (-not (Test-Path $VPy)) {
    Write-Host 'الجهاز غير مجهّز بعد. شغّل 1-Setup.bat أولًا.' -ForegroundColor Red
    exit 1
}
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
$organized = Join-Path $target 'Organized'
$planPy = Join-Path $PSScriptRoot 'plan.py'

# 1) Photos by content (optional, offline, resumable).
Write-Host ''
Write-Host 'هل تريد تصنيف الصور حسب محتواها (أشخاص، طبيعة، طعام، معدّلة...)؟'
Write-Host 'إذا اخترت N ستُرتّب الصور حسب السنة فقط.'
if ((Read-Host 'اكتب Y للموافقة أو N للرفض').Trim().ToUpper() -eq 'Y') {
    Write-Host ''
    Write-Host '[1/5] أصنّف الصور... (لا يُنقل أي ملف، ولا يحتاج إنترنت)' -ForegroundColor Yellow
    & $VPy -W ignore (Join-Path $PSScriptRoot 'classify.py') --root $target
    if ($LASTEXITCODE -ne 0) { throw 'توقف التصنيف بسبب خطأ. شغّل الأداة مرة أخرى وسيكمل من حيث توقف.' }
}

# 2) Plan: which folders stay whole, where every file goes.
Write-Host ''
Write-Host '[2/5] أخطط للترتيب: أي المجلدات تبقى كاملة وأين يذهب كل ملف... (لا يُنقل شيء)' -ForegroundColor Yellow
& $VPy $planPy --root $target
if ($LASTEXITCODE -ne 0) { throw 'فشل التخطيط.' }

# 3) You review the folders that will move whole, in the browser.
Write-Host ''
Write-Host '[3/5] سأفتح لك صفحة المراجعة في المتصفح.' -ForegroundColor Yellow
Write-Host '      اختر قرارك لكل مجلد لا يعجبك اقتراحه، ثم اضغط «حفظ اختياراتي» في أسفل الصفحة.'
$opened = Get-Date
& $VPy (Join-Path $PSScriptRoot 'review_page.py') --root $target
Read-Host 'بعد الحفظ (أو إذا لم تغيّر شيئًا) ارجع هنا واضغط Enter'

$downloads = Join-Path $env:USERPROFILE 'Downloads'
$choices = Get-ChildItem -LiteralPath $downloads -Filter 'review-choices*.csv' -ErrorAction SilentlyContinue |
           Where-Object LastWriteTime -gt $opened | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$choicesPath = if ($choices) { $choices.FullName } else { '' }
if (-not $choicesPath) {
    Write-Host 'لم أجد ملف الاختيارات في مجلد التنزيلات.'
    $choicesPath = (Read-Host 'إذا حفظته في مكان آخر اسحبه إلى هذه النافذة ثم اضغط Enter، أو اضغط Enter إذا لم تغيّر شيئًا').Trim().Trim('"')
}
$reviewArgs = @('--root', $target, '--review')
if ($choicesPath) { $reviewArgs += @('--choices', $choicesPath) }
& $VPy $planPy @reviewArgs
if ($LASTEXITCODE -ne 0) { throw 'فشل تحديث الخطة.' }

# 4) Confirm and move.
Write-Host ''
Write-Host 'هذه هي الخطة النهائية. لم يُنقل أي ملف بعد.' -ForegroundColor Cyan
if ((Read-Host 'لبدء النقل اكتب YES بالأحرف الكبيرة. لأي شيء آخر سألغي').Trim() -cne 'YES') {
    Write-Host 'ألغيت. لم يُنقل أي ملف.' -ForegroundColor Green
    exit 0
}
$inventory = Join-Path $organized '_programs\inventory.csv'
New-Item -ItemType Directory -Force (Split-Path $inventory) | Out-Null
& $VPy (Join-Path $PSScriptRoot 'programs.py') --root $target --inventory $inventory   # before the move: needs the old paths
Write-Host ''
Write-Host '[4/5] أنقل الملفات وأكتب سجل التراجع... لا تفصل القرص!' -ForegroundColor Yellow
& $VPy $planPy --root $target --execute
if ($LASTEXITCODE -ne 0) { throw 'توقف النقل بسبب خطأ. سجل التراجع صحيح حتى آخر ملف نُقل.' }

# 5) Info page next to every program.
Write-Host ''
Write-Host '[5/5] أكتب ملحق معلومات بجانب كل برنامج...' -ForegroundColor Yellow
$desc = Join-Path $organized '_programs\descriptions.json'
& $VPy (Join-Path $PSScriptRoot 'programs.py') --root $target --write $desc --inv $inventory

Write-Host ''
Write-Host 'انتهى الترتيب! ملفاتك الآن في:' -ForegroundColor Green
Write-Host $organized
Write-Host 'إذا لم يعجبك الترتيب شغّل 3-Undo.bat'
