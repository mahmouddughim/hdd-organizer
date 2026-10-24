# Reverse a move made by organize.ps1 or plan.py, using its move-log CSV. Handles files and
# whole folders. Safe to re-run: items already back in place are skipped, nothing is overwritten.
#
#   .\undo.ps1 -Log "E:\Organized\_undo\move-log-YYYYMMDD-HHMMSS.csv"
param([Parameter(Mandatory)] [string] $Log)

$entries = Import-Csv $Log -Encoding UTF8
[array]::Reverse($entries)

$restored = 0; $skipped = 0; $errors = 0
$errPath = [System.IO.Path]::ChangeExtension($Log, '.undo-errors.txt')
$err = New-Object System.IO.StreamWriter($errPath, $false, [System.Text.Encoding]::UTF8)

foreach ($e in $entries) {
    $isDir = [System.IO.Directory]::Exists($e.Destination)
    $sourceTaken = [System.IO.File]::Exists($e.Source) -or [System.IO.Directory]::Exists($e.Source)
    if (-not ($isDir -or [System.IO.File]::Exists($e.Destination)) -or $sourceTaken) { $skipped++; continue }
    try {
        [System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($e.Source)) | Out-Null
        if ($isDir) { [System.IO.Directory]::Move($e.Destination, $e.Source) }
        else { [System.IO.File]::Move($e.Destination, $e.Source) }
        $restored++
    } catch {
        $errors++
        $err.WriteLine("$($e.Destination)`t$($_.Exception.Message)")
    }
    if (($restored + $skipped) % 20000 -eq 0) { Write-Host "... $($restored + $skipped) processed" }
}
$err.Close()

"Restored: $restored   Skipped (already in place / missing): $skipped   Errors: $errors"
