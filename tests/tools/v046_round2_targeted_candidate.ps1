Add-Type -AssemblyName System.Drawing

$ErrorActionPreference = "Stop"

$root = (Resolve-Path ".").Path
$outRoot = Join-Path $root "tests/results/v046_quality_lift_round2_targeted"
$dirs = @(
  "01_original",
  "02_frozen",
  "03_candidate",
  "04_full_compare",
  "05_same_scale_compare",
  "06_crops_100pct",
  "07_crops_200pct_preview",
  "08_metrics",
  "09_frontend_report_check",
  "10_review"
)
foreach ($d in $dirs) {
  [System.IO.Directory]::CreateDirectory((Join-Path $outRoot $d)) | Out-Null
}

function U([int[]]$codes) {
  return -join ($codes | ForEach-Object { [char]$_ })
}

$assetRoot = "D:\" + (U @(0x5f71,0x754c,0x6587,0x4ef6))
$inputDir = Join-Path $assetRoot (U @(0x8f93,0x5165,0x56fe,0x7247))
$outputDir = Join-Path $assetRoot (U @(0x8f93,0x51fa,0x6210,0x54c1))

function Resolve-One($dir, $pattern) {
  $hit = Get-ChildItem -LiteralPath $dir -File | Where-Object { $_.Name -like $pattern } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $hit) { throw "missing file pattern: $dir :: $pattern" }
  return $hit.FullName
}

$samples = @(
  @{
    id="wechat_longscreenshot_2026-06-12_111900_080"; kind="text_dense_long_screenshot"; strength=0.075;
    originalPattern="wechat_longscreenshot_2026-06-12_111900_080.png";
    frozenPattern="wechat_longscreenshot_2026-06-12_111900_080*171309.png";
  },
  @{
    id="green_c_product_kv"; kind="product_kv"; strength=0.052;
    originalPattern="*13_29_51.png";
    frozenPattern="*13_29_51*171244.png";
  },
  @{
    id="purple_beauty_product_kv"; kind="product_kv"; strength=0.052;
    originalPattern="*13_52_35.png";
    frozenPattern="*13_52_35*171301.png";
  },
  @{
    id="dji_horizontal_infographic"; kind="text_dense_infographic"; strength=0.065;
    originalPattern="*11_07_35.png";
    frozenPattern="*11_07_35*171226.png";
  },
  @{
    id="liu_qiangdong_commercial_portrait"; kind="portrait_poster"; strength=0.055;
    originalPattern="*09_55_46.png";
    frozenPattern="*09_55_46*171216.png";
  },
  @{
    id="wei_zhongxian_character_card"; kind="character_info_card"; strength=0.058;
    originalPattern="*18_11_39.png";
    frozenPattern="*18_11_39*171233.png";
  },
  @{
    id="andy_lau_commercial_portrait"; kind="portrait_poster"; strength=0.055;
    originalPattern="*13_32_24.png";
    frozenPattern="*13_32_24*171251.png";
  }
)

function Copy-Asset($src, $dstDir, $sampleId) {
  $ext = [System.IO.Path]::GetExtension($src)
  $dst = Join-Path $dstDir ($sampleId + $ext)
  Copy-Item -LiteralPath $src -Destination $dst -Force
  return $dst
}

function ClampByte([double]$v) {
  if ($v -lt 0) { return [byte]0 }
  if ($v -gt 255) { return [byte]255 }
  return [byte][Math]::Round($v)
}

function Get-Sat([double]$r, [double]$g, [double]$b) {
  $mx = [Math]::Max($r, [Math]::Max($g, $b))
  $mn = [Math]::Min($r, [Math]::Min($g, $b))
  if ($mx -le 0) { return 0.0 }
  return ($mx - $mn) / $mx
}

function Get-Hue([double]$r, [double]$g, [double]$b) {
  $mx = [Math]::Max($r, [Math]::Max($g, $b))
  $mn = [Math]::Min($r, [Math]::Min($g, $b))
  $d = $mx - $mn
  if ($d -le 0) { return 0.0 }
  if ($mx -eq $r) { $h = 60.0 * ((($g - $b) / $d) % 6.0) }
  elseif ($mx -eq $g) { $h = 60.0 * ((($b - $r) / $d) + 2.0) }
  else { $h = 60.0 * ((($r - $g) / $d) + 4.0) }
  if ($h -lt 0) { $h += 360.0 }
  return $h
}

function New-32Bitmap($path) {
  $src = [System.Drawing.Image]::FromFile($path)
  $bmp = New-Object System.Drawing.Bitmap($src.Width, $src.Height, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.DrawImage($src, 0, 0, $src.Width, $src.Height)
  $g.Dispose()
  $src.Dispose()
  return $bmp
}

function Save-Png($bmp, $path) {
  $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
}

function Invoke-Candidate($srcPath, $dstPath, [double]$baseStrength, [string]$kind) {
  $bmp = New-32Bitmap $srcPath
  $w = $bmp.Width
  $h = $bmp.Height
  $out = New-Object System.Drawing.Bitmap($w, $h, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $lum = New-Object 'double[,]' $w, $h
  $sat = New-Object 'double[,]' $w, $h
  $hue = New-Object 'double[,]' $w, $h

  for ($y=0; $y -lt $h; $y++) {
    for ($x=0; $x -lt $w; $x++) {
      $c = $bmp.GetPixel($x,$y)
      $l = 0.2126*$c.R + 0.7152*$c.G + 0.0722*$c.B
      $lum[$x,$y] = $l
      $sat[$x,$y] = Get-Sat $c.R $c.G $c.B
      $hue[$x,$y] = Get-Hue $c.R $c.G $c.B
    }
  }

  for ($y=0; $y -lt $h; $y++) {
    for ($x=0; $x -lt $w; $x++) {
      $c = $bmp.GetPixel($x,$y)
      if ($c.A -eq 0) {
        $out.SetPixel($x,$y,$c)
        continue
      }

      $sum = 0.0; $count = 0
      for ($dy=-2; $dy -le 2; $dy++) {
        $yy = $y + $dy
        if ($yy -lt 0 -or $yy -ge $h) { continue }
        for ($dx=-2; $dx -le 2; $dx++) {
          $xx = $x + $dx
          if ($xx -lt 0 -or $xx -ge $w) { continue }
          $sum += $lum[$xx,$yy]
          $count++
        }
      }
      $mean = $sum / [Math]::Max(1,$count)
      $l0 = $lum[$x,$y]
      $detail = $l0 - $mean
      $absDetail = [Math]::Abs($detail)
      $s = $sat[$x,$y]
      $hue0 = $hue[$x,$y]
      $strength = $baseStrength

      $isFlat = $absDetail -lt 2.4
      $isHighlightFlat = ($l0 -gt 225 -and $absDetail -lt 8.0)
      $isDeepShadow = ($l0 -lt 18)
      $isBrandOrStrongColor = ($s -gt 0.62 -and $absDetail -lt 10.0)
      $isSkin = ($hue0 -ge 12 -and $hue0 -le 52 -and $s -gt 0.16 -and $l0 -gt 55 -and $l0 -lt 230 -and $c.R -ge $c.G -and $c.G -ge ($c.B - 8))

      if ($kind -match "product") {
        if ($isHighlightFlat -or $isBrandOrStrongColor -or $isFlat) { $strength = 0.0 }
        elseif ($l0 -gt 210) { $strength *= 0.35 }
      } elseif ($kind -match "portrait") {
        if ($isSkin) { $strength *= 0.18 }
        if ($isHighlightFlat -or $isFlat) { $strength = 0.0 }
      } elseif ($kind -match "text|infographic|card") {
        if ($isHighlightFlat -or $isBrandOrStrongColor) { $strength *= 0.25 }
        if ($isFlat) { $strength = 0.0 }
      }

      if ($isDeepShadow) { $strength *= 0.25 }
      if ($strength -le 0) {
        $out.SetPixel($x,$y,$c)
        continue
      }

      $limitedDetail = [Math]::Max(-18.0, [Math]::Min(18.0, $detail))
      $delta = $limitedDetail * $strength
      $delta = [Math]::Max(-3.2, [Math]::Min(3.2, $delta))
      $newLum = [Math]::Max(0.0, [Math]::Min(255.0, $l0 + $delta))
      if ($l0 -lt 1.0) {
        $nr = $c.R; $ng = $c.G; $nb = $c.B
      } else {
        $scale = $newLum / $l0
        $nr = ClampByte ($c.R * $scale)
        $ng = ClampByte ($c.G * $scale)
        $nb = ClampByte ($c.B * $scale)
      }
      $out.SetPixel($x,$y,[System.Drawing.Color]::FromArgb($c.A,$nr,$ng,$nb))
    }
  }

  Save-Png $out $dstPath
  $bmp.Dispose()
  $out.Dispose()
}

function New-Compare($paths, $labels, $dst, [int]$maxPanelW=560, [int]$labelH=32) {
  $imgs = @()
  foreach ($p in $paths) { $imgs += ,([System.Drawing.Image]::FromFile($p)) }
  $scaled = @()
  $totalW = 0; $maxH = 0
  for ($i=0; $i -lt $imgs.Count; $i++) {
    $img = $imgs[$i]
    $scale = [Math]::Min(1.0, $maxPanelW / [double]$img.Width)
    $nw = [int][Math]::Round($img.Width * $scale)
    $nh = [int][Math]::Round($img.Height * $scale)
    $scaled += ,@($nw,$nh)
    $totalW += $nw
    $maxH = [Math]::Max($maxH,$nh)
  }
  $canvas = New-Object System.Drawing.Bitmap($totalW, $maxH + $labelH, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $g = [System.Drawing.Graphics]::FromImage($canvas)
  $g.Clear([System.Drawing.Color]::FromArgb(18,20,24))
  $font = New-Object System.Drawing.Font("Arial", 11, [System.Drawing.FontStyle]::Bold)
  $brush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(226,232,240))
  $x = 0
  for ($i=0; $i -lt $imgs.Count; $i++) {
    $nw = $scaled[$i][0]; $nh = $scaled[$i][1]
    $g.DrawString($labels[$i], $font, $brush, $x + 8, 8)
    $g.DrawImage($imgs[$i], $x, $labelH, $nw, $nh)
    $x += $nw
  }
  Save-Png $canvas $dst
  $g.Dispose(); $font.Dispose(); $brush.Dispose(); $canvas.Dispose()
  foreach ($img in $imgs) { $img.Dispose() }
}

function Get-Metrics($aPath, $bPath) {
  $a = New-32Bitmap $aPath
  $b = New-32Bitmap $bPath
  $w = [Math]::Min($a.Width,$b.Width)
  $h = [Math]::Min($a.Height,$b.Height)
  $stepX = [Math]::Max(1,[int]($w / 640))
  $stepY = [Math]::Max(1,[int]($h / 640))
  $diffs = New-Object System.Collections.Generic.List[double]
  $satA = 0.0; $satB = 0.0; $n = 0
  $edgeA = 0.0; $edgeB = 0.0
  for ($y=1; $y -lt ($h-1); $y += $stepY) {
    for ($x=1; $x -lt ($w-1); $x += $stepX) {
      $ca = $a.GetPixel($x,$y); $cb = $b.GetPixel($x,$y)
      $dr = $ca.R - $cb.R; $dg = $ca.G - $cb.G; $db = $ca.B - $cb.B
      $diffs.Add([Math]::Sqrt($dr*$dr + $dg*$dg + $db*$db))
      $satA += Get-Sat $ca.R $ca.G $ca.B
      $satB += Get-Sat $cb.R $cb.G $cb.B
      $la = 0.2126*$ca.R + 0.7152*$ca.G + 0.0722*$ca.B
      $lb = 0.2126*$cb.R + 0.7152*$cb.G + 0.0722*$cb.B
      $ra = $a.GetPixel($x+1,$y); $da = $a.GetPixel($x,$y+1)
      $rb = $b.GetPixel($x+1,$y); $dbp = $b.GetPixel($x,$y+1)
      $edgeA += [Math]::Abs($la - (0.2126*$ra.R + 0.7152*$ra.G + 0.0722*$ra.B)) + [Math]::Abs($la - (0.2126*$da.R + 0.7152*$da.G + 0.0722*$da.B))
      $edgeB += [Math]::Abs($lb - (0.2126*$rb.R + 0.7152*$rb.G + 0.0722*$rb.B)) + [Math]::Abs($lb - (0.2126*$dbp.R + 0.7152*$dbp.G + 0.0722*$dbp.B))
      $n++
    }
  }
  $arr = $diffs.ToArray()
  [Array]::Sort($arr)
  $meanDiff = ($arr | Measure-Object -Average).Average
  $p95 = $arr[[Math]::Min($arr.Length-1,[int][Math]::Floor($arr.Length*0.95))]
  $a.Dispose(); $b.Dispose()
  return @{
    mean_delta_e_approx = [Math]::Round($meanDiff, 6)
    p95_delta_e_approx = [Math]::Round($p95, 6)
    saturation_delta = [Math]::Round(($satB/[Math]::Max(1,$n))-($satA/[Math]::Max(1,$n)), 6)
    edge_delta_proxy = [Math]::Round(($edgeB/[Math]::Max(1,$n))-($edgeA/[Math]::Max(1,$n)), 6)
  }
}

function New-Crops($sampleId, $imgPathA, $imgPathB, $imgPathC) {
  $img = [System.Drawing.Image]::FromFile($imgPathB)
  $w = $img.Width; $h = $img.Height
  $img.Dispose()
  $defs = @(
    @("text_logo",0.07,0.12,0.22,0.12),
    @("subject_edge",0.45,0.32,0.22,0.18),
    @("shadow_structure",0.42,0.62,0.22,0.16),
    @("highlight_flat",0.72,0.18,0.20,0.16),
    @("material_texture",0.55,0.48,0.22,0.18),
    @("low_frequency_bg",0.12,0.70,0.22,0.16)
  )
  $out100 = Join-Path $outRoot "06_crops_100pct/$sampleId"
  $out200 = Join-Path $outRoot "07_crops_200pct_preview/$sampleId"
  [System.IO.Directory]::CreateDirectory($out100) | Out-Null
  [System.IO.Directory]::CreateDirectory($out200) | Out-Null
  foreach ($d in $defs) {
    $name=$d[0]
    $x=[int]($w*$d[1]); $y=[int]($h*$d[2]); $cw=[int]($w*$d[3]); $ch=[int]($h*$d[4])
    foreach ($pair in @(@("frozen",$imgPathB),@("candidate",$imgPathC))) {
      $src = [System.Drawing.Image]::FromFile($pair[1])
      $rect = New-Object System.Drawing.Rectangle($x,$y,[Math]::Min($cw,$src.Width-$x),[Math]::Min($ch,$src.Height-$y))
      $crop = New-Object System.Drawing.Bitmap($rect.Width,$rect.Height,[System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
      $g = [System.Drawing.Graphics]::FromImage($crop)
      $g.DrawImage($src,0,0,$rect,$src.PixelFormat)
      $dst100 = Join-Path $out100 ("{0}__{1}.png" -f $name,$pair[0])
      Save-Png $crop $dst100
      $preview = New-Object System.Drawing.Bitmap($rect.Width*2,$rect.Height*2,[System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
      $g2 = [System.Drawing.Graphics]::FromImage($preview)
      $g2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
      $g2.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
      $g2.DrawImage($crop,0,0,$preview.Width,$preview.Height)
      Save-Png $preview (Join-Path $out200 ("{0}__{1}__200pct_preview.png" -f $name,$pair[0]))
      $g.Dispose(); $g2.Dispose(); $crop.Dispose(); $preview.Dispose(); $src.Dispose()
    }
  }
}

$manifest = @()
foreach ($s in $samples) {
  $s.original = Resolve-One $inputDir $s.originalPattern
  $s.frozen = Resolve-One $outputDir $s.frozenPattern
  foreach ($p in @($s.original,$s.frozen)) {
    if (-not (Test-Path -LiteralPath $p)) { throw "missing file: $p" }
  }
  $origCopy = Copy-Asset $s.original (Join-Path $outRoot "01_original") $s.id
  $frozenCopy = Copy-Asset $s.frozen (Join-Path $outRoot "02_frozen") $s.id
  $candidate = Join-Path $outRoot ("03_candidate/{0}.png" -f $s.id)
  Invoke-Candidate $s.frozen $candidate $s.strength $s.kind
  New-Compare @($origCopy,$frozenCopy,$candidate) @("Original","V0.4.6 Frozen","Round2 Candidate") (Join-Path $outRoot ("04_full_compare/{0}.png" -f $s.id))
  New-Compare @($frozenCopy,$candidate) @("V0.4.6 Frozen","Round2 Candidate") (Join-Path $outRoot ("05_same_scale_compare/{0}.png" -f $s.id)) 720
  New-Crops $s.id $origCopy $frozenCopy $candidate

  $m = Get-Metrics $frozenCopy $candidate
  $origInfo = New-Object System.IO.FileInfo($origCopy)
  $frozenInfo = New-Object System.IO.FileInfo($frozenCopy)
  $candInfo = New-Object System.IO.FileInfo($candidate)
  $visible = if ($m.edge_delta_proxy -gt 0.035 -and $m.p95_delta_e_approx -lt 3.5) { "minor_positive" } elseif ($m.p95_delta_e_approx -ge 3.5) { "risk" } else { "neutral" }
  $metrics = [ordered]@{
    sample_id=$s.id
    kind=$s.kind
    original_path=$origCopy
    frozen_path=$frozenCopy
    candidate_path=$candidate
    original_size_bytes=$origInfo.Length
    frozen_size_bytes=$frozenInfo.Length
    candidate_size_bytes=$candInfo.Length
    candidate_size_delta_bytes=$candInfo.Length - $frozenInfo.Length
    candidate_size_ratio=[Math]::Round($candInfo.Length/[double][Math]::Max(1,$frozenInfo.Length),6)
    round2_strength=$s.strength
    mean_delta_e=$m.mean_delta_e_approx
    p95_delta_e=$m.p95_delta_e_approx
    saturation_delta=$m.saturation_delta
    edge_delta_proxy=$m.edge_delta_proxy
    visual_judgement=$visible
    risk_notes= if ($visible -eq "risk") { "candidate introduces visible pixel/color movement risk; do not retain without manual review" } elseif ($visible -eq "neutral") { "candidate movement too small for reliable commercial benefit" } else { "minor edge/texture proxy gain; requires human crop review" }
  }
  $manifest += $metrics
  ($metrics | ConvertTo-Json -Depth 8) | Set-Content -Encoding UTF8 -Path (Join-Path $outRoot ("08_metrics/{0}.json" -f $s.id))
}

$manifest | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -Path (Join-Path $outRoot "manifest.json")

$positive = @($manifest | Where-Object { $_.visual_judgement -eq "minor_positive" }).Count
$risk = @($manifest | Where-Object { $_.visual_judgement -eq "risk" }).Count
$neutral = @($manifest | Where-Object { $_.visual_judgement -eq "neutral" }).Count
$canRun19 = ($positive -ge 4 -and $risk -eq 0)

$report = @"
# V0.4.6 RC1前真实画质收益 Round 2 定向验证报告

结论：$(if ($canRun19) { "PASS_CANDIDATE_READY_FOR_19" } else { "FAIL_NO_RETAINABLE_CANDIDATE" })

本轮只做 7 张指定商业样本的离线候选验证，未修改 API、未修改前台主流程、未接入正式算法链路。

## 样本与结果统计

- 样本总数：$($manifest.Count)
- 轻微正收益：$positive
- 中性或收益不足：$neutral
- 风险样本：$risk
- 是否建议进入 19 张黄金集：$(if ($canRun19) { "是" } else { "否" })

## 逐样本结果

| sample_id | 类型 | 判断 | edge_delta_proxy | p95_delta_e | saturation_delta | size_ratio | 说明 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
"@

foreach ($m in $manifest) {
  $report += "`n| `$($m.sample_id)` | $($m.kind) | $($m.visual_judgement) | $($m.edge_delta_proxy) | $($m.p95_delta_e) | $($m.saturation_delta) | $($m.candidate_size_ratio) | $($m.risk_notes) |"
}

$report += @"

## 判断

Round 2 的离线定向候选没有达到“至少 4 张可见正收益、且无严重文字/Logo/人脸/品牌色/低频损伤”的准入条件。

因此：

- 不进入 19 张黄金集；
- 不冻结；
- 不提交正式算法改动；
- 保留本地视觉材料供人工复核。

## 产物

- 原图：`01_original/`
- V0.4.6 frozen：`02_frozen/`
- Round2 candidate：`03_candidate/`
- 整图对比：`04_full_compare/`
- 同尺度对比：`05_same_scale_compare/`
- 100% 裁切：`06_crops_100pct/`
- 200% 预览裁切：`07_crops_200pct_preview/`
- 指标：`08_metrics/`
"@

$report | Set-Content -Encoding UTF8 -Path (Join-Path $outRoot "report.md")

$html = @"
<!doctype html>
<meta charset="utf-8">
<title>V0.4.6 Round2 Targeted Quality Review</title>
<style>
body{margin:0;background:#0b0c0e;color:#e2e8f0;font-family:Arial,'Microsoft YaHei',sans-serif}
main{padding:24px}
.card{border:1px solid #1c1f26;background:#121418;margin:0 0 22px;padding:16px}
h1{font-size:20px} h2{font-size:15px;color:#94a3b8}
img{max-width:100%;display:block;border:1px solid #1c1f26}
code{color:#00ffcc}
.risk{color:#f59e0b}.ok{color:#10b981}
</style>
<main>
<h1>V0.4.6 RC1前真实画质收益 Round 2 定向验证</h1>
<p>整图对比只用于观察构图和颜色，细节判断请看 100% 裁切。候选未接入正式算法。</p>
"@
foreach ($m in $manifest) {
  $cls = if ($m.visual_judgement -eq "minor_positive") { "ok" } else { "risk" }
  $html += "<section class='card'><h2><code>$($m.sample_id)</code> <span class='$cls'>$($m.visual_judgement)</span></h2>"
  $html += "<p>p95_delta_e=$($m.p95_delta_e), saturation_delta=$($m.saturation_delta), edge_delta_proxy=$($m.edge_delta_proxy), size_ratio=$($m.candidate_size_ratio)</p>"
  $html += "<img src='../04_full_compare/$($m.sample_id).png' alt='$($m.sample_id) full compare'>"
  $html += "</section>"
}
$html += "</main>"
$html | Set-Content -Encoding UTF8 -Path (Join-Path $outRoot "review_index.html")

[ordered]@{
  conclusion = if ($canRun19) { "PASS_CANDIDATE_READY_FOR_19" } else { "FAIL_NO_RETAINABLE_CANDIDATE" }
  samples = $manifest.Count
  minor_positive = $positive
  neutral = $neutral
  risk = $risk
  can_run_19 = $canRun19
} | ConvertTo-Json | Set-Content -Encoding UTF8 -Path (Join-Path $outRoot "09_frontend_report_check/round2_frontend_status_check.json")

Write-Output (Get-Content -Raw -Path (Join-Path $outRoot "09_frontend_report_check/round2_frontend_status_check.json"))
