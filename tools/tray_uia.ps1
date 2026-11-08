Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$AE = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]

$root = $AE::RootElement
$taskbarCond = New-Object System.Windows.Automation.PropertyCondition($AE::ClassNameProperty, "Shell_TrayWnd")
$taskbar = $root.FindFirst($TS::Children, $taskbarCond)
if (-not $taskbar) { Write-Output '{"ok":false,"reason":"no taskbar"}'; exit 0 }

# 找“显示隐藏的图标”按钮：按 AutomationId 优先，退回名称匹配
$btn = $null
foreach ($id in @("ShowHiddenIcons", "OverflowButton")) {
    $c = New-Object System.Windows.Automation.PropertyCondition($AE::AutomationIdProperty, $id)
    $btn = $taskbar.FindFirst($TS::Descendants, $c)
    if ($btn) { break }
}
if (-not $btn) {
    $all = $taskbar.FindAll($TS::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($e in $all) {
        try {
            if ($e.Current.ControlType.ProgrammaticName -eq "ControlType.Button" -and
                ($e.Current.Name -match "隐藏的图标|hidden icons")) { $btn = $e; break }
        } catch {}
    }
}
if (-not $btn) { Write-Output '{"ok":false,"reason":"no overflow button"}'; exit 0 }

$inv = $btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
$inv.Invoke()
Start-Sleep -Milliseconds 1400

$fw = $null
foreach ($cls in @("NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland")) {
    $fwCond = New-Object System.Windows.Automation.PropertyCondition($AE::ClassNameProperty, $cls)
    $fw = $root.FindFirst($TS::Children, $fwCond)
    if ($fw) { break }
}
if (-not $fw) { Write-Output '{"ok":false,"reason":"no overflow window"}'; exit 0 }

$found = @()
$names = @()
$all = $fw.FindAll($TS::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
foreach ($e in $all) {
    try {
        $n = $e.Current.Name
        if ($n) { $names += $n }
        if ($n -and $n -match "cc-hud") {
            $r = $e.Current.BoundingRectangle
            $found += [pscustomobject]@{ name=$n; cls=$e.Current.ClassName;
                x=[int]$r.X; y=[int]$r.Y; w=[int]$r.Width; h=[int]$r.Height }
        }
    } catch {}
}

$inv.Invoke() | Out-Null   # 关闭溢出面板
if ($found.Count -eq 0) {
    $names | ConvertTo-Json -Compress | ForEach-Object { '{"ok":false,"reason":"overflow opened but no cc-hud item","names":' + $_ + '}' }
} else {
    $found | ConvertTo-Json -Compress
}
