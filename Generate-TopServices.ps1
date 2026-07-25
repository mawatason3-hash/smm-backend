# ============================================================
# Generate Top Services per Platform & Type (Corrected)
# ============================================================
$topN = 5
$csvFiles = Get-ChildItem -Filter "*-services.csv"
if ($csvFiles.Count -eq 0) { Write-Host "❌ No *-services.csv files found." -ForegroundColor Red; exit }
$allTopServices = @()
foreach ($file in $csvFiles) {
    $platform = $file.BaseName -replace "-services", ""
    Write-Host "🔍 Processing $platform..." -ForegroundColor Cyan
    $data = Import-Csv -Path $file.FullName
    if ($data.Count -eq 0) { continue }
    $groups = @{}
    foreach ($row in $data) {
        $name = $row.name
        $core = $name -replace '\[.*?\]' -replace '\(.*?\)' -replace '[\d,]+', '' -replace '[-+]', ''
        $keywords = @('Followers','Likes','Views','Comments','Subscribers','Saves','Reels','Plays','Impressions','Engagement','Messages','Members')
        $found = $false
        foreach ($kw in $keywords) {
            if ($core -match $kw) { $type = $kw; $found = $true; break }
        }
        if (-not $found) { $type = ($core -split '\s+')[0] }
        $key = "$platform-$type"
        if (-not $groups.ContainsKey($key)) { $groups[$key] = @() }
        $groups[$key] += $row
    }
    foreach ($key in $groups.Keys) {
        $services = $groups[$key]
        $sorted = $services | Sort-Object `
            @{ Expression = { if ($_.name -match 'Refill|♻️') { 1 } else { 0 } }; Ascending = $true },
            @{ Expression = { [double]$_.rate_per_1k }; Ascending = $true }
        $top = $sorted | Select-Object -First $topN
        $rank = 1
        foreach ($svc in $top) {
            $allTopServices += [PSCustomObject]@{
                Platform = $platform
                Type     = $key
                Rank     = $rank
                Provider = $svc.provider
                Name     = $svc.name
                Rate     = $svc.rate_per_1k
                Cost     = $svc.cost_per_1k
                Margin   = [double]$svc.rate_per_1k - [double]$svc.cost_per_1k
                MinQty   = $svc.min_qty
                MaxQty   = $svc.max_qty
                Id       = $svc.id
                Refill   = if ($svc.name -match 'Refill|♻️') { 'Yes' } else { 'No' }
            }
            $rank++
        }
    }
}
$allTopServices | Sort-Object Platform, Type, Rate | Export-Csv -Path "top-services-per-type.csv" -NoTypeInformation
Write-Host "`n✅ Exported top $topN services per type to top-services-per-type.csv" -ForegroundColor Green
Write-Host "📊 Total rows: $($allTopServices.Count)" -ForegroundColor Yellow
