# Organize a drive into <Root>\Organized\<Type>\<Year>\ by extension and last-modified year.
# Never opens files and never deletes anything. Console output is aggregate counts only;
# file names go only to the undo log on the drive itself.
#
#   .\organize.ps1 -Drive E:\ -Mode Preview   # counts only, moves nothing
#   .\organize.ps1 -Drive E:\ -Mode Move      # moves files, writes undo log
#   -Labels <csv from classify.py> sorts images further into Images\<Label>\<Year>
param(
    [Parameter(Mandatory)] [string] $Drive,
    [ValidateSet('Preview', 'Move')] [string] $Mode = 'Preview',
    [string] $Labels
)

$ErrorActionPreference = 'Stop'
$Drive = (Resolve-Path $Drive).Path

# Never reorganize Windows itself or a whole user profile: programs and settings would break.
$profileDir = $env:USERPROFILE.TrimEnd('\') + '\'
if ((Test-Path (Join-Path $Drive 'Windows\System32')) -or $profileDir.StartsWith($Drive.TrimEnd('\') + '\', 'OrdinalIgnoreCase')) {
    throw "Refusing to organize '$Drive': it contains Windows or your user profile. Pick a data drive or a folder like Downloads."
}
$DestRoot = Join-Path $Drive 'Organized'
$UndoDir = Join-Path $DestRoot '_undo'

$Categories = [ordered]@{
    'Images'    = 'jpg jpeg png gif bmp tif tiff webp heic heif raw cr2 cr3 nef arw dng orf rw2 psd svg ico'
    'Videos'    = 'mp4 mkv avi mov wmv flv webm m4v 3gp mpg mpeg ts mts m2ts vob'
    'Audio'     = 'mp3 wav flac aac m4a ogg wma opus amr aiff mid midi'
    'Documents' = 'pdf doc docx txt rtf odt xls xlsx csv ods ppt pptx odp md epub mobi pages key numbers'
    'Archives'  = 'zip rar 7z tar gz tgz bz2 xz iso img'
    'Programs'  = 'exe msi apk xapk dmg bat cmd ps1 jar'
}
$ExtMap = @{}
foreach ($cat in $Categories.Keys) {
    foreach ($ext in $Categories[$cat].Split(' ')) { $ExtMap[".$ext"] = $cat }
}

$SkipDirNames = @('$RECYCLE.BIN', 'System Volume Information', 'Organized', 'FOUND.000')
$SkipFileNames = @('desktop.ini', 'thumbs.db', '.ds_store')

$LabelOf = @{}   # case-insensitive: path -> photo label
if ($Labels) { Import-Csv $Labels -Encoding UTF8 | ForEach-Object { $LabelOf[$_.Path] = $_.Label } }

$stats = @{}            # "Category|Year" -> [count, bytes]
$counters = @{ Files = 0; Bytes = 0L; Moved = 0; Errors = 0; SkippedBundles = 0; UnreadableDirs = 0 }

if ($Mode -eq 'Move') {
    New-Item -ItemType Directory -Force $UndoDir | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $logPath = Join-Path $UndoDir "move-log-$stamp.csv"
    $errPath = Join-Path $UndoDir "errors-$stamp.txt"
    $log = New-Object System.IO.StreamWriter($logPath, $false, [System.Text.Encoding]::UTF8)
    $log.AutoFlush = $true
    $log.WriteLine('"Source","Destination"')
    $err = New-Object System.IO.StreamWriter($errPath, $false, [System.Text.Encoding]::UTF8)
    $err.AutoFlush = $true
    Copy-Item (Join-Path $PSScriptRoot 'undo.ps1') $UndoDir -Force
}

function Get-FreePath([string] $dir, [string] $name) {
    $target = Join-Path $dir $name
    if (-not [System.IO.File]::Exists($target)) { return $target }
    $base = [System.IO.Path]::GetFileNameWithoutExtension($name)
    $ext = [System.IO.Path]::GetExtension($name)
    for ($i = 1; ; $i++) {
        $target = Join-Path $dir "$base ($i)$ext"
        if (-not [System.IO.File]::Exists($target)) { return $target }
    }
}

$stack = New-Object System.Collections.Generic.Stack[string]
$stack.Push($Drive)

while ($stack.Count -gt 0) {
    $dirPath = $stack.Pop()
    try {
        $dir = New-Object System.IO.DirectoryInfo($dirPath)
        $files = $dir.GetFiles()
        $subdirs = $dir.GetDirectories()
    } catch {
        $counters.UnreadableDirs++
        continue
    }

    # Folders that only work as a whole (apps, games, git repos) are left untouched.
    $isBundle = ($subdirs | Where-Object Name -eq '.git') -or ($files | Where-Object Extension -eq '.dll')
    if ($isBundle -and $dirPath -ne $Drive) { $counters.SkippedBundles++; continue }

    foreach ($sub in $subdirs) {
        if ($dirPath -eq $Drive -and $SkipDirNames -contains $sub.Name) { continue }
        if ($sub.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { continue }
        if ($sub.Attributes -band [System.IO.FileAttributes]::System) { continue }
        $stack.Push($sub.FullName)
    }

    foreach ($f in $files) {
        if ($SkipFileNames -contains $f.Name.ToLower()) { continue }
        if ($f.Attributes -band [System.IO.FileAttributes]::System) { continue }

        $cat = $ExtMap[$f.Extension.ToLower()]
        if (-not $cat) { $cat = 'Other' }
        if ($cat -eq 'Images' -and $LabelOf.ContainsKey($f.FullName)) { $cat = "Images\$($LabelOf[$f.FullName])" }
        $year = $f.LastWriteTime.Year
        if ($year -lt 1980) { $year = 'Unknown-Year' }   # 1601/1899/1970 = missing or reset timestamps
        $key = "$cat|$year"
        if (-not $stats.ContainsKey($key)) { $stats[$key] = @(0, 0L) }
        $stats[$key][0]++
        $stats[$key][1] += $f.Length
        $counters.Files++
        $counters.Bytes += $f.Length

        if ($Mode -eq 'Move') {
            try {
                $targetDir = Join-Path $DestRoot "$cat\$year"
                [System.IO.Directory]::CreateDirectory($targetDir) | Out-Null
                $target = Get-FreePath $targetDir $f.Name
                [System.IO.File]::Move($f.FullName, $target)
                $log.WriteLine('"' + $f.FullName.Replace('"', '""') + '","' + $target.Replace('"', '""') + '"')
                $counters.Moved++
            } catch {
                $counters.Errors++
                $err.WriteLine("$($f.FullName)`t$($_.Exception.Message)")
            }
        }

        if ($counters.Files % 20000 -eq 0) { Write-Host "... $($counters.Files) files processed" }
    }
}

if ($Mode -eq 'Move') { $log.Close(); $err.Close() }

# Summary: counts and sizes only.
"`n=== $Mode summary for $Drive ==="
$rows = foreach ($k in $stats.Keys) {
    $c, $y = $k.Split('|')
    [pscustomobject]@{ Type = $c; Year = $y; Files = $stats[$k][0]; SizeGB = [math]::Round($stats[$k][1] / 1GB, 2) }
}
"`n-- By type --"
$rows | Group-Object Type | ForEach-Object {
    [pscustomobject]@{ Type = $_.Name; Files = ($_.Group | Measure-Object Files -Sum).Sum; SizeGB = [math]::Round(($_.Group | Measure-Object SizeGB -Sum).Sum, 1) }
} | Sort-Object SizeGB -Descending | Format-Table -AutoSize | Out-String
"-- By type and year --"
$rows | Sort-Object Type, Year | Format-Table -AutoSize | Out-String
"Total files: $($counters.Files)  ($([math]::Round($counters.Bytes / 1GB, 1)) GB)"
"App/game/repo folders left untouched: $($counters.SkippedBundles)"
"Unreadable folders skipped: $($counters.UnreadableDirs)"
if ($Mode -eq 'Move') {
    "Moved: $($counters.Moved)   Errors: $($counters.Errors)"
    "Undo log: $logPath"
}
