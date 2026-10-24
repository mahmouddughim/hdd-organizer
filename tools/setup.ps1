# One-time setup on a computer: Python environment, libraries and the photo model.
$ErrorActionPreference = 'Stop'
$Here = Split-Path $PSScriptRoot -Parent
$Venv = Join-Path $Here '.venv'
$VPy = Join-Path $Venv 'Scripts\python.exe'

Write-Host ''
Write-Host '=== 1-Setup: تجهيز الجهاز (مرة واحدة فقط) ===' -ForegroundColor Cyan
Write-Host ''

# Find a real Python (the Microsoft Store alias in WindowsApps is only a shortcut, not Python).
$python = $null
foreach ($name in 'py', 'python') {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike '*WindowsApps*') { $python = $cmd.Source; break }
}
if (-not $python) {
    Write-Host 'لم أجد برنامج Python على هذا الجهاز.' -ForegroundColor Red
    Write-Host 'سأفتح لك صفحة التنزيل. ثبّته، ولا تنسَ تفعيل خيار: Add python.exe to PATH'
    Write-Host 'ثم شغّل 1-Setup.bat مرة أخرى.'
    Start-Process 'https://www.python.org/downloads/'
    exit 1
}
Write-Host "[1/5] وجدت Python: $(& $python --version)"

# A .venv copied from another computer or folder points at the wrong Python: rebuild it.
if ((Test-Path $VPy) -and -not (& $VPy -c "print(1)" 2>$null)) {
    Write-Host '      البيئة الموجودة منسوخة من مكان آخر ولا تعمل هنا. سأعيد إنشاءها.'
    Remove-Item $Venv -Recurse -Force
}
if (-not (Test-Path $VPy)) {
    Write-Host '[2/5] أنشئ البيئة الخاصة (.venv)...'
    & $python -m venv $Venv
} else {
    Write-Host '[2/5] البيئة الخاصة (.venv) موجودة مسبقًا.'
}
& $VPy -m pip install --upgrade pip -q

if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    Write-Host '[3/5] وجدت كرت شاشة NVIDIA. أنزّل PyTorch الخاص به (حوالي 3GB، قد يأخذ وقتًا)...'
    $index = 'https://download.pytorch.org/whl/cu126'
} else {
    Write-Host '[3/5] لا يوجد كرت NVIDIA. أنزّل PyTorch للمعالج العادي (أبطأ قليلًا لكنه يعمل)...'
    $index = 'https://download.pytorch.org/whl/cpu'
}
& $VPy -m pip install torch torchvision --index-url $index
if ($LASTEXITCODE -ne 0) { throw 'فشل تثبيت PyTorch. تأكد من الإنترنت وأعد المحاولة.' }

Write-Host '[4/5] أثبّت باقي المكتبات...'
& $VPy -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'فشل تثبيت المكتبات. تأكد من الإنترنت وأعد المحاولة.' }

Write-Host '[5/5] أنزّل نموذج تصنيف الصور (حوالي 600MB، مرة واحدة فقط)...'
& $VPy (Join-Path $PSScriptRoot 'classify.py') --download
if ($LASTEXITCODE -ne 0) { throw 'فشل تنزيل النموذج. تأكد من الإنترنت وأعد المحاولة.' }

$gpu = & $VPy -c "import torch; print('NVIDIA: ' + torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
(Get-Item $Venv -Force).Attributes = 'Directory, Hidden'

Write-Host ''
Write-Host "تم التجهيز بنجاح! سيعمل التصنيف على: $gpu" -ForegroundColor Green
Write-Host 'من الآن لا تحتاج إنترنت. الخطوة التالية: 2-Organize.bat'
