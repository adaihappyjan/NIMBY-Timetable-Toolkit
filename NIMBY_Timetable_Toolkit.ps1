param([switch]$SmokeTest, [switch]$AsyncSmokeTest)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName Microsoft.VisualBasic
[System.Windows.Forms.Application]::EnableVisualStyles()

$ToolRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $ToolRoot 'toolkit_backend.py'
$SaveDir = Join-Path $env:USERPROFILE 'Saved Games\Weird and Wry\NIMBY Rails'
$script:Analysis = $null
$script:ExtensionNames = @{}
$script:ScheduleRiskByName = @{}
$script:ReferenceScan = $null
$script:TaskProcess = $null
$script:TaskResultFile = $null
$script:TaskProgressFile = $null
$script:TaskOnComplete = $null
$script:TaskCancelled = $false
$script:LastProgressLines = 0
$script:AsyncError = $null
$SettingsDir = Join-Path $env:LOCALAPPDATA 'NIMBY_Timetable_Toolkit'
$SettingsFile = Join-Path $SettingsDir 'settings.json'
$TaskDir = Join-Path ([IO.Path]::GetTempPath()) 'NIMBY_Timetable_Toolkit'
$defaultWorkers = [Math]::Max(1, [Math]::Min(4, [Environment]::ProcessorCount - 1))
$CleanupSettings = [PSCustomObject]@{ Enabled = $true; Days = 14; Keep = 5; Workers = $defaultWorkers }
if (Test-Path -LiteralPath $SettingsFile) {
    try {
        $savedSettings = Get-Content -LiteralPath $SettingsFile -Raw | ConvertFrom-Json
        if ($null -ne $savedSettings.Enabled) { $CleanupSettings.Enabled = [bool]$savedSettings.Enabled }
        if ($savedSettings.Days) { $CleanupSettings.Days = [int]$savedSettings.Days }
        if ($savedSettings.Keep) { $CleanupSettings.Keep = [int]$savedSettings.Keep }
        if ($savedSettings.Workers) { $CleanupSettings.Workers = [int]$savedSettings.Workers }
    } catch { }
}

function Find-Python {
    $candidates = @(
        (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'),
        (Join-Path $env:USERPROFILE 'Envs\oldC-python310\Scripts\python.exe')
    )
    foreach ($candidate in $candidates) { if (Test-Path -LiteralPath $candidate) { return $candidate } }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw '未找到 Python。请从 Codex 环境启动本工具。'
}
$Python = Find-Python

function New-Label($text, $x, $y, $width = 130, $height = 24) {
    $c = [System.Windows.Forms.Label]::new(); $c.Text = $text
    $c.Location = [System.Drawing.Point]::new($x, $y); $c.Size = [System.Drawing.Size]::new($width, $height)
    $c.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft; return $c
}
function New-Button($text, $x, $y, $width = 120, $height = 32) {
    $c = [System.Windows.Forms.Button]::new(); $c.Text = $text
    $c.Location = [System.Drawing.Point]::new($x, $y); $c.Size = [System.Drawing.Size]::new($width, $height); return $c
}
function Add-Status([string]$message) {
    $StatusText.AppendText("[$(Get-Date -Format 'HH:mm:ss')] $message`r`n")
    $StatusText.SelectionStart = $StatusText.TextLength; $StatusText.ScrollToCaret()
}
function Set-DefaultOutput([string]$kind = 'Toolkit') {
    if (-not $SaveText.Text) { return }
    $directory = Split-Path -Parent $SaveText.Text
    $base = [System.IO.Path]::GetFileNameWithoutExtension($SaveText.Text)
    $OutputText.Text = Join-Path $directory "${base}_${kind}_$(Get-Date -Format 'yyyyMMdd_HHmmss').nimbyrails5"
}
function Require-Scan {
    if (-not $script:Analysis) { throw '请先点击“扫描并检查”。' }
    if (-not (Test-Path -LiteralPath $SaveText.Text)) { throw '输入存档不存在。' }
    if (-not (Test-Path -LiteralPath $ExportText.Text)) { throw '导出 JSON 不存在。' }
    if ($script:Analysis.compatible_schedule_count -ne $script:Analysis.expected_schedule_count) {
        throw "存档与导出 JSON 未完全匹配（$($script:Analysis.compatible_schedule_count)/$($script:Analysis.expected_schedule_count)）。请从当前存档重新导出 JSON 后再操作。"
    }
}
function Show-Error([Exception]$error) {
    Add-Status "失败：$($error.Message)"
    if ($AsyncSmokeTest) { $script:AsyncError=$error; return }
    [System.Windows.Forms.MessageBox]::Show($error.Message, '操作未完成', 'OK', 'Warning') | Out-Null
}
function Get-ExpiredToolCopies([int]$days, [int]$keep) {
    if (-not (Test-Path -LiteralPath $SaveDir)) { return @() }
    $all = @(Get-ChildItem -LiteralPath $SaveDir -File |
        Where-Object { $_.Name -match '_(Toolkit|Extension|Recovery|Repair)_\d{8}_\d{6}\.nimbyrails5(\.partial)?$' } |
        Sort-Object LastWriteTime -Descending)
    if ($all.Count -le $keep) { return @() }
    $cutoff = (Get-Date).AddDays(-$days)
    return @($all | Select-Object -Skip $keep | Where-Object { $_.LastWriteTime -lt $cutoff })
}
function Move-ToolCopiesToRecycleBin([object[]]$files) {
    $moved = 0
    foreach ($file in $files) {
        if (-not $file -or -not (Test-Path -LiteralPath $file.FullName)) { continue }
        [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile(
            $file.FullName,
            [Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs,
            [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin
        )
        $manifest = [IO.Path]::ChangeExtension($file.FullName, '.manifest.json')
        if (Test-Path -LiteralPath $manifest) {
            [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile(
                $manifest,
                [Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs,
                [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin
            )
        }
        $moved++
    }
    return $moved
}

$Form = [System.Windows.Forms.Form]::new()
$Form.Text = 'NIMBY Rails 时刻表工具箱 · 多核增强版'
$Form.StartPosition = 'CenterScreen'; $Form.Size = [System.Drawing.Size]::new(1080, 850)
$Form.MinimumSize = [System.Drawing.Size]::new(1080, 850); $Form.Font = [System.Drawing.Font]::new('Microsoft YaHei UI', 9)
$Title = New-Label 'NIMBY Rails 时刻表工具箱' 20 8 500 36
$Title.Font = [System.Drawing.Font]::new('Microsoft YaHei UI', 18, [System.Drawing.FontStyle]::Bold); $Form.Controls.Add($Title)
$Guide = New-Label '① 选择文件   →   ② 扫描检查   →   ③ 选择要做的事   →   ④ 创建新存档并进游戏检查' 22 43 900 26
$Guide.ForeColor = [System.Drawing.Color]::FromArgb(35, 95, 155); $Guide.Font = [System.Drawing.Font]::new('Microsoft YaHei UI', 10, [System.Drawing.FontStyle]::Bold); $Form.Controls.Add($Guide)
$Safety = New-Label '安全规则：游戏需回到主菜单或关闭；工具只创建新文件，绝不覆盖原存档。' 22 69 900 24
$Safety.ForeColor = [System.Drawing.Color]::DarkRed; $Form.Controls.Add($Safety)

$Form.Controls.Add((New-Label '① 输入存档' 22 103 95))
$SaveText = [System.Windows.Forms.TextBox]::new(); $SaveText.Location = [System.Drawing.Point]::new(120, 103); $SaveText.Size = [System.Drawing.Size]::new(730, 25); $Form.Controls.Add($SaveText)
$SaveBrowse = New-Button '选择存档…' 865 99 165; $Form.Controls.Add($SaveBrowse)
$Form.Controls.Add((New-Label '导出 JSON' 22 139 95))
$ExportText = [System.Windows.Forms.TextBox]::new(); $ExportText.Location = [System.Drawing.Point]::new(120, 139); $ExportText.Size = [System.Drawing.Size]::new(730, 25); $Form.Controls.Add($ExportText)
$ExportBrowse = New-Button '选择导出文件…' 865 135 165; $Form.Controls.Add($ExportBrowse)
$LatestButton = New-Button '自动选择最新文件' 120 174 180
$ScanButton = New-Button '② 扫描并检查' 310 174 180
$OpenFolderButton = New-Button '打开存档文件夹' 500 174 180
$Form.Controls.AddRange(@($LatestButton, $ScanButton, $OpenFolderButton))
$HealthPanel = [System.Windows.Forms.Panel]::new(); $HealthPanel.Location = [System.Drawing.Point]::new(700, 171); $HealthPanel.Size = [System.Drawing.Size]::new(330, 38); $HealthPanel.BorderStyle = 'FixedSingle'
$HealthLabel = New-Label '尚未扫描' 8 5 310 27; $HealthLabel.Font = [System.Drawing.Font]::new('Microsoft YaHei UI', 9, [System.Drawing.FontStyle]::Bold); $HealthPanel.Controls.Add($HealthLabel); $Form.Controls.Add($HealthPanel)

$Tabs = [System.Windows.Forms.TabControl]::new(); $Tabs.Location = [System.Drawing.Point]::new(20, 220); $Tabs.Size = [System.Drawing.Size]::new(1010, 410); $Form.Controls.Add($Tabs)
$BatchTab = [System.Windows.Forms.TabPage]::new('③ 智能批量配置'); $Tabs.TabPages.Add($BatchTab)
$BatchTab.Controls.Add((New-Label '把已有时刻表的全部班次和列车，搬到你在游戏里做好的空白 Daily 模板。可一次处理多条线路。' 16 10 940 28))
$PairGrid = [System.Windows.Forms.DataGridView]::new(); $PairGrid.Location = [System.Drawing.Point]::new(16, 43); $PairGrid.Size = [System.Drawing.Size]::new(960, 230)
$PairGrid.AllowUserToAddRows = $false; $PairGrid.AllowUserToDeleteRows = $false; $PairGrid.RowHeadersVisible = $false; $PairGrid.AutoSizeColumnsMode = 'Fill'; $PairGrid.SelectionMode = 'FullRowSelect'; $PairGrid.MultiSelect = $false
$checkColumn = [System.Windows.Forms.DataGridViewCheckBoxColumn]::new(); $checkColumn.Name = 'Use'; $checkColumn.HeaderText = '处理'; $checkColumn.FillWeight = 35; [void]$PairGrid.Columns.Add($checkColumn)
[void]$PairGrid.Columns.Add('Source', '现有时刻表（来源）'); [void]$PairGrid.Columns.Add('Target', '空白 Daily 模板（目标）'); [void]$PairGrid.Columns.Add('Fleet', '列车数'); [void]$PairGrid.Columns.Add('Reason', '为什么这样匹配')
$PairGrid.Columns['Fleet'].FillWeight = 45; $PairGrid.Columns['Reason'].FillWeight = 150; $BatchTab.Controls.Add($PairGrid)
$BatchTab.Controls.Add((New-Label '手动添加：来源' 16 282 115))
$SourceCombo = [System.Windows.Forms.ComboBox]::new(); $SourceCombo.Location = [System.Drawing.Point]::new(130, 282); $SourceCombo.Size = [System.Drawing.Size]::new(250, 25); $SourceCombo.DropDownStyle = 'DropDownList'; $BatchTab.Controls.Add($SourceCombo)
$BatchTab.Controls.Add((New-Label '目标模板' 395 282 80))
$TargetCombo = [System.Windows.Forms.ComboBox]::new(); $TargetCombo.Location = [System.Drawing.Point]::new(475, 282); $TargetCombo.Size = [System.Drawing.Size]::new(250, 25); $TargetCombo.DropDownStyle = 'DropDownList'; $BatchTab.Controls.Add($TargetCombo)
$AddPairButton = New-Button '加入列表' 740 278 110; $RemovePairButton = New-Button '移除所选' 860 278 110; $BatchTab.Controls.AddRange(@($AddPairButton, $RemovePairButton))
$GarageCheck = [System.Windows.Forms.CheckBox]::new(); $GarageCheck.Text = '同时给这些列车加入 Timetable garage join（车库接班扩展）'; $GarageCheck.Location = [System.Drawing.Point]::new(20, 326); $GarageCheck.Size = [System.Drawing.Size]::new(520, 28); $GarageCheck.Checked = $true; $BatchTab.Controls.Add($GarageCheck)
$BatchRun = New-Button '④ 一键创建新存档' 720 320 250 40; $BatchRun.BackColor = [System.Drawing.Color]::FromArgb(215, 240, 220); $BatchTab.Controls.Add($BatchRun)

$ExtensionTab = [System.Windows.Forms.TabPage]::new('车库扩展管理'); $Tabs.TabPages.Add($ExtensionTab)
$ExtensionTab.Controls.Add((New-Label '勾选一个或多个时刻表。只影响其中已分配的列车；重复加入不会产生重复扩展。' 16 10 920 28))
$ScheduleList = [System.Windows.Forms.CheckedListBox]::new(); $ScheduleList.Location = [System.Drawing.Point]::new(16, 43); $ScheduleList.Size = [System.Drawing.Size]::new(600, 255); $ScheduleList.CheckOnClick = $true; $ExtensionTab.Controls.Add($ScheduleList)
$SelectAllButton = New-Button '全选' 16 307 78; $SelectRiskButton = New-Button '只选风险项' 102 307 110; $ClearAllButton = New-Button '清空' 220 307 78
$ExtensionHelp = New-Label "左侧用于单独车库操作；右侧把不同严重问题合并进一个修复存档。" 315 305 300 48
$AddExtensionButton = New-Button '加入车库扩展' 640 43 155 38; $RemoveExtensionButton = New-Button '移除车库扩展' 810 43 155 38
$RepairDepotButton = New-Button '修复严重车库循环（x1）' 640 89 325 38
$RepairSafeButton = New-Button '车库 x1 + 接班扩展' 640 135 325 38
$ExtensionTab.Controls.Add((New-Label '可修复任务：勾选后一次完成' 640 182 325 26))
$OverlapList = [System.Windows.Forms.CheckedListBox]::new(); $OverlapList.Location = [System.Drawing.Point]::new(640, 210); $OverlapList.Size = [System.Drawing.Size]::new(325, 96); $OverlapList.CheckOnClick = $true; $ExtensionTab.Controls.Add($OverlapList)
$RetireOverlapButton = New-Button '一键修复勾选的问题' 640 315 325 40
$ExtensionTab.Controls.AddRange(@($SelectAllButton, $SelectRiskButton, $ClearAllButton, $AddExtensionButton, $RemoveExtensionButton, $RepairDepotButton, $RepairSafeButton, $RetireOverlapButton, $ExtensionHelp))

$RecoveryTab = [System.Windows.Forms.TabPage]::new('模板恢复'); $Tabs.TabPages.Add($RecoveryTab)
$RecoveryTab.Controls.Add((New-Label '当旧自动表已经清空时：使用历史 JSON 取回车队名单，用当前空白 Daily 模板重建全部错峰班次。' 16 12 940 28))
$RecoveryTab.Controls.Add((New-Label '历史导出 JSON' 18 58 110))
$ReferenceExportText = [Windows.Forms.TextBox]::new(); $ReferenceExportText.Location = [Drawing.Point]::new(130, 58); $ReferenceExportText.Size = [Drawing.Size]::new(650, 25); $RecoveryTab.Controls.Add($ReferenceExportText)
$ReferenceBrowse = New-Button '选择…' 795 54 85; $ReferenceAuto = New-Button '自动查找' 888 54 85; $RecoveryTab.Controls.AddRange(@($ReferenceBrowse,$ReferenceAuto))
$RecoveryTab.Controls.Add((New-Label '历史车队来源表' 18 110 125))
$ReferenceSourceCombo = [Windows.Forms.ComboBox]::new(); $ReferenceSourceCombo.Location = [Drawing.Point]::new(145, 110); $ReferenceSourceCombo.Size = [Drawing.Size]::new(330, 25); $ReferenceSourceCombo.DropDownStyle = 'DropDownList'; $RecoveryTab.Controls.Add($ReferenceSourceCombo)
$RecoveryTab.Controls.Add((New-Label '当前空白目标表' 500 110 125))
$RecoveryTargetCombo = [Windows.Forms.ComboBox]::new(); $RecoveryTargetCombo.Location = [Drawing.Point]::new(625, 110); $RecoveryTargetCombo.Size = [Drawing.Size]::new(335, 25); $RecoveryTargetCombo.DropDownStyle = 'DropDownList'; $RecoveryTab.Controls.Add($RecoveryTargetCombo)
$RecoveryInfo = New-Label '工具会复制“当前目标模板”的运行逻辑，历史 JSON 只提供列车、班次 ID 和相位顺序。不会复制历史循环内容。' 20 162 930 55
$RecoveryInfo.ForeColor = [Drawing.Color]::FromArgb(35,95,155); $RecoveryTab.Controls.Add($RecoveryInfo)
$RecoveryGarage = [Windows.Forms.CheckBox]::new(); $RecoveryGarage.Text = '确保整支恢复车队启用 Timetable garage join'; $RecoveryGarage.Location = [Drawing.Point]::new(22, 235); $RecoveryGarage.Size = [Drawing.Size]::new(430, 28); $RecoveryGarage.Checked = $true; $RecoveryTab.Controls.Add($RecoveryGarage)
$RecoveryRun = New-Button '重建车队并创建新存档' 650 225 310 46; $RecoveryRun.BackColor = [Drawing.Color]::FromArgb(215,240,220); $RecoveryTab.Controls.Add($RecoveryRun)
$RecoveryWarning = New-Label '要求：当前存档与当前 JSON 完全匹配；目标表只有一个未分配模板班次；历史班次 ID 在当前存档中已不存在。' 20 300 930 45
$RecoveryWarning.ForeColor = [Drawing.Color]::DarkRed; $RecoveryTab.Controls.Add($RecoveryWarning)

$HelpTab = [System.Windows.Forms.TabPage]::new('诊断与说明'); $Tabs.TabPages.Add($HelpTab)
$DiagnosisText = [System.Windows.Forms.TextBox]::new(); $DiagnosisText.Location = [System.Drawing.Point]::new(16, 12); $DiagnosisText.Size = [System.Drawing.Size]::new(950, 92); $DiagnosisText.Multiline = $true; $DiagnosisText.ReadOnly = $true; $DiagnosisText.ScrollBars = 'Vertical'; $DiagnosisText.Font = [System.Drawing.Font]::new('Microsoft YaHei UI', 9); $HelpTab.Controls.Add($DiagnosisText)
$FindingsGrid = [System.Windows.Forms.DataGridView]::new(); $FindingsGrid.Location = [System.Drawing.Point]::new(16, 112); $FindingsGrid.Size = [System.Drawing.Size]::new(950, 175)
$FindingsGrid.AllowUserToAddRows = $false; $FindingsGrid.AllowUserToDeleteRows = $false; $FindingsGrid.ReadOnly = $true; $FindingsGrid.RowHeadersVisible = $false; $FindingsGrid.AutoSizeColumnsMode = 'Fill'; $FindingsGrid.SelectionMode = 'FullRowSelect'
[void]$FindingsGrid.Columns.Add('Severity','级别'); [void]$FindingsGrid.Columns.Add('Schedule','时刻表'); [void]$FindingsGrid.Columns.Add('Issue','发现的问题'); [void]$FindingsGrid.Columns.Add('Action','建议操作')
$FindingsGrid.Columns['Severity'].FillWeight = 40; $FindingsGrid.Columns['Schedule'].FillWeight = 90; $FindingsGrid.Columns['Issue'].FillWeight = 120; $FindingsGrid.Columns['Action'].FillWeight = 190; $HelpTab.Controls.Add($FindingsGrid)
$CopyDiagnosis = New-Button '复制诊断摘要' 800 298 165 30; $HelpTab.Controls.Add($CopyDiagnosis)
$AutoCleanupCheck = [System.Windows.Forms.CheckBox]::new(); $AutoCleanupCheck.Text = '自动清理工具创建的过期副本'; $AutoCleanupCheck.Location = [System.Drawing.Point]::new(18, 302); $AutoCleanupCheck.Size = [System.Drawing.Size]::new(245, 26); $AutoCleanupCheck.Checked = $CleanupSettings.Enabled; $HelpTab.Controls.Add($AutoCleanupCheck)
$HelpTab.Controls.Add((New-Label '超过' 270 302 42))
$CleanupDays = [System.Windows.Forms.NumericUpDown]::new(); $CleanupDays.Location = [System.Drawing.Point]::new(312, 303); $CleanupDays.Size = [System.Drawing.Size]::new(58, 25); $CleanupDays.Minimum = 1; $CleanupDays.Maximum = 365; $CleanupDays.Value = [Math]::Min(365, [Math]::Max(1, $CleanupSettings.Days)); $HelpTab.Controls.Add($CleanupDays)
$HelpTab.Controls.Add((New-Label '天，且保留最新' 374 302 112))
$CleanupKeep = [System.Windows.Forms.NumericUpDown]::new(); $CleanupKeep.Location = [System.Drawing.Point]::new(488, 303); $CleanupKeep.Size = [System.Drawing.Size]::new(58, 25); $CleanupKeep.Minimum = 1; $CleanupKeep.Maximum = 50; $CleanupKeep.Value = [Math]::Min(50, [Math]::Max(1, $CleanupSettings.Keep)); $HelpTab.Controls.Add($CleanupKeep)
$HelpTab.Controls.Add((New-Label '份' 550 302 30))
$CleanupNow = New-Button '立即检查清理' 600 298 165 30; $HelpTab.Controls.Add($CleanupNow)
$CleanupNote = New-Label '只处理工具生成的 Toolkit / Extension / Recovery / Repair 时间副本及 .partial；移入回收站，不碰正式存档。' 18 334 900 30
$CleanupNote.ForeColor = [System.Drawing.Color]::DimGray; $HelpTab.Controls.Add($CleanupNote)

$HistoryTab = [System.Windows.Forms.TabPage]::new('历史与性能'); $Tabs.TabPages.Add($HistoryTab)
$HistoryTab.Controls.Add((New-Label '并行后台进程' 18 18 105))
$WorkerCount = [System.Windows.Forms.NumericUpDown]::new(); $WorkerCount.Location = [System.Drawing.Point]::new(125, 19); $WorkerCount.Size = [System.Drawing.Size]::new(65, 25); $WorkerCount.Minimum = 1; $WorkerCount.Maximum = [Math]::Max(1, [Environment]::ProcessorCount); $WorkerCount.Value = [Math]::Min([decimal]$WorkerCount.Maximum, [Math]::Max(1, $CleanupSettings.Workers)); $HistoryTab.Controls.Add($WorkerCount)
$CpuLabel = New-Label "本机 $([Environment]::ProcessorCount) 个逻辑处理器；界面工作始终放在独立后台进程中。" 205 16 520 28; $CpuLabel.ForeColor = [Drawing.Color]::FromArgb(35,95,155); $HistoryTab.Controls.Add($CpuLabel)
$InventoryButton = New-Button '并行盘点最近文件' 745 12 220 36; $HistoryTab.Controls.Add($InventoryButton)
$HistoryText = [System.Windows.Forms.TextBox]::new(); $HistoryText.Location = [System.Drawing.Point]::new(16, 60); $HistoryText.Size = [System.Drawing.Size]::new(950, 245); $HistoryText.Multiline = $true; $HistoryText.ReadOnly = $true; $HistoryText.ScrollBars = 'Vertical'; $HistoryText.Font = [System.Drawing.Font]::new('Consolas', 9); $HistoryTab.Controls.Add($HistoryText)
$CompareButton = New-Button '对比“历史 JSON”和当前 JSON' 16 317 260 38; $HistoryTab.Controls.Add($CompareButton)
$HistoryHelp = New-Label '盘点会并行读取最近的导出，列出健康分、严重问题、残留临时文件和校验记录。对比功能复用“模板恢复”页选择的历史 JSON。' 295 315 660 45; $HistoryTab.Controls.Add($HistoryHelp)

$Form.Controls.Add((New-Label '新存档保存为' 22 647 105))
$OutputText = [System.Windows.Forms.TextBox]::new(); $OutputText.Location = [System.Drawing.Point]::new(130, 647); $OutputText.Size = [System.Drawing.Size]::new(720, 25); $Form.Controls.Add($OutputText)
$OutputBrowse = New-Button '更改位置…' 865 643 165; $Form.Controls.Add($OutputBrowse)
$TaskProgress = [System.Windows.Forms.ProgressBar]::new(); $TaskProgress.Location = [System.Drawing.Point]::new(20, 680); $TaskProgress.Size = [System.Drawing.Size]::new(620, 20); $TaskProgress.Minimum = 0; $TaskProgress.Maximum = 100; $Form.Controls.Add($TaskProgress)
$TaskLabel = New-Label '空闲' 650 677 265 25; $Form.Controls.Add($TaskLabel)
$CancelTaskButton = New-Button '取消任务' 925 675 105 28; $CancelTaskButton.Enabled = $false; $Form.Controls.Add($CancelTaskButton)
$StatusText = [System.Windows.Forms.TextBox]::new(); $StatusText.Location = [System.Drawing.Point]::new(20, 708); $StatusText.Size = [System.Drawing.Size]::new(1010, 82); $StatusText.Multiline = $true; $StatusText.ReadOnly = $true; $StatusText.ScrollBars = 'Vertical'; $StatusText.BackColor = [System.Drawing.Color]::White; $Form.Controls.Add($StatusText)

function Set-UiBusy([bool]$busy) {
    foreach ($control in @($LatestButton,$ScanButton,$BatchRun,$AddExtensionButton,$RemoveExtensionButton,$RepairDepotButton,$RepairSafeButton,$RetireOverlapButton,$RecoveryRun,$ReferenceAuto,$ReferenceBrowse,$InventoryButton,$CompareButton)) {
        if ($null -ne $control) { $control.Enabled = -not $busy }
    }
    $CancelTaskButton.Enabled = $busy
    if ($busy) { $Form.Cursor = 'AppStarting' } else { $Form.Cursor = 'Default' }
}

function Remove-TaskFiles {
    foreach ($path in @($script:TaskResultFile,$script:TaskProgressFile)) {
        if ($path -and (Test-Path -LiteralPath $path)) { Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue }
        if ($path -and (Test-Path -LiteralPath ($path + '.partial'))) { Remove-Item -LiteralPath ($path + '.partial') -Force -ErrorAction SilentlyContinue }
    }
}

function Start-BackendTask([string[]]$Arguments, [string]$title, [scriptblock]$OnComplete) {
    if ($script:TaskProcess -and -not $script:TaskProcess.HasExited) { throw '已有任务正在运行；请等待完成或点击“取消任务”。' }
    if (-not (Test-Path -LiteralPath $TaskDir)) { [void][IO.Directory]::CreateDirectory($TaskDir) }
    Remove-TaskFiles
    $token = [Guid]::NewGuid().ToString('N')
    $script:TaskResultFile = Join-Path $TaskDir "task_${token}.result.json"
    $script:TaskProgressFile = Join-Path $TaskDir "task_${token}.progress.jsonl"
    $script:TaskOnComplete = $OnComplete
    $script:TaskCancelled = $false
    $script:LastProgressLines = 0
    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $Python; $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
    $processArguments = [Collections.Generic.List[string]]::new()
    $processArguments.Add($Backend)
    foreach ($value in @('--workers',[string][int]$WorkerCount.Value,'--result-file',$script:TaskResultFile,'--progress-file',$script:TaskProgressFile)) { $processArguments.Add($value) }
    foreach ($argument in $Arguments) { $processArguments.Add($argument) }
    if ($psi.PSObject.Properties['ArgumentList']) {
        foreach ($argument in $processArguments) { [void]$psi.ArgumentList.Add($argument) }
    } else {
        # Windows PowerShell 5.1 has no ArgumentList collection. All normal
        # Windows paths are safe here; reject embedded quotes instead of
        # constructing an ambiguous command line.
        foreach ($argument in $processArguments) {
            if ($argument.Contains('"')) { throw '参数中包含旧版 PowerShell 无法安全传递的双引号；请使用新版 PowerShell 启动工具箱。' }
        }
        $psi.Arguments = ($processArguments | ForEach-Object { '"' + $_ + '"' }) -join ' '
    }
    $script:TaskProcess = [System.Diagnostics.Process]::Start($psi)
    $TaskProgress.Value = 0; $TaskLabel.Text = $title; Set-UiBusy $true; Add-Status $title
    $BackendTimer.Start()
}

$BackendTimer = [System.Windows.Forms.Timer]::new(); $BackendTimer.Interval = 250
$BackendTimer.Add_Tick({
    try {
        if ($script:TaskProgressFile -and (Test-Path -LiteralPath $script:TaskProgressFile)) {
            $progressLines = @(Get-Content -LiteralPath $script:TaskProgressFile -Encoding utf8 -ErrorAction SilentlyContinue)
            if ($progressLines.Count -gt $script:LastProgressLines) {
                $script:LastProgressLines = $progressLines.Count
                try {
                    $last = $progressLines[-1] | ConvertFrom-Json
                    $TaskProgress.Value = [Math]::Max(0,[Math]::Min(100,[int]$last.percent))
                    $TaskLabel.Text = [string]$last.message
                } catch { }
            }
        }
        if (-not $script:TaskProcess -or -not $script:TaskProcess.HasExited) { return }
        $BackendTimer.Stop(); $exitCode = $script:TaskProcess.ExitCode; Set-UiBusy $false
        if ($script:TaskCancelled) {
            Add-Status '后台任务已取消。'; $TaskLabel.Text = '已取消'; $TaskProgress.Value = 0; Remove-TaskFiles; $script:TaskProcess.Dispose(); $script:TaskProcess = $null; return
        }
        if (-not (Test-Path -LiteralPath $script:TaskResultFile)) { throw "核心程序没有返回结果（退出代码 $exitCode）。" }
        $result = Get-Content -LiteralPath $script:TaskResultFile -Raw -Encoding utf8 | ConvertFrom-Json
        if ($exitCode -ne 0 -or -not $result.ok) {
            if ($result.error) { throw [string]$result.error }
            throw '未知错误'
        }
        $callback = $script:TaskOnComplete
        $TaskProgress.Value = 100; $TaskLabel.Text = '完成'
        if ($callback) { & $callback $result }
        Remove-TaskFiles; $script:TaskProcess.Dispose(); $script:TaskProcess = $null
    } catch {
        $BackendTimer.Stop(); Set-UiBusy $false; $TaskLabel.Text = '失败'
        if ($script:TaskProcess) { $script:TaskProcess.Dispose(); $script:TaskProcess = $null }
        Remove-TaskFiles; Show-Error $_.Exception
    }
})

$CancelTaskButton.Add_Click({
    if ($script:TaskProcess -and -not $script:TaskProcess.HasExited) {
        $script:TaskCancelled = $true
        try { $script:TaskProcess.Kill($true) } catch { try { $script:TaskProcess.Kill() } catch { } }
        $TaskLabel.Text = '正在取消…'
    }
})

function Apply-Analysis($result) {
    $script:Analysis = $result
    $PairGrid.Rows.Clear()
    foreach ($pair in $script:Analysis.suggested_pairs) {
        $ready = $pair.ready -eq $true
        $rowIndex = $PairGrid.Rows.Add($ready, $pair.source, $pair.target, $pair.fleet_size, "$($pair.confidence)：$($pair.reason)")
        if (-not $ready) {
            $PairGrid.Rows[$rowIndex].Cells['Use'].ReadOnly = $true
            $PairGrid.Rows[$rowIndex].DefaultCellStyle.BackColor = [Drawing.Color]::LightYellow
        }
    }
    $SourceCombo.Items.Clear(); $TargetCombo.Items.Clear(); $RecoveryTargetCombo.Items.Clear()
    foreach ($schedule in $script:Analysis.schedules) {
        if ($schedule.is_source) { [void]$SourceCombo.Items.Add($schedule.name) }
        if ($schedule.is_blank_template) { [void]$TargetCombo.Items.Add($schedule.name); [void]$RecoveryTargetCombo.Items.Add($schedule.name) }
    }
    if ($SourceCombo.Items.Count) { $SourceCombo.SelectedIndex = 0 }; if ($TargetCombo.Items.Count) { $TargetCombo.SelectedIndex = 0 }; if ($RecoveryTargetCombo.Items.Count) { $RecoveryTargetCombo.SelectedIndex = 0 }
    $ScheduleList.Items.Clear(); $script:ExtensionNames = @{}; $script:ScheduleRiskByName = @{}
    foreach ($schedule in $script:Analysis.health_schedules) {
        if ($schedule.train_count -gt 0) {
            $riskMark = if ($schedule.risk_level -eq 'critical') { '⚠' } elseif ($schedule.risk_level -eq 'warning') { '△' } else { '✓' }
            $display = "$riskMark $($schedule.name)  ｜列车 $($schedule.train_count)｜扩展 $($schedule.garage_enabled)"
            $script:ExtensionNames[$display] = $schedule.name; $script:ScheduleRiskByName[$schedule.name] = $schedule.risk_level; [void]$ScheduleList.Items.Add($display)
        }
    }
    $OverlapList.Items.Clear(); $script:RepairTaskByDisplay = @{}
    foreach ($repair in $script:Analysis.repair_tasks) {
        $display = [string]$repair.label
        $script:RepairTaskByDisplay[$display] = $repair
        [void]$OverlapList.Items.Add($display, ($repair.selected_by_default -eq $true))
    }
    $matched = $script:Analysis.compatible_schedule_count -eq $script:Analysis.expected_schedule_count
    $crit = [int]$script:Analysis.severity_counts.critical; $warn = [int]$script:Analysis.severity_counts.warning
    if ($matched -and $crit -eq 0) { $HealthLabel.Text = "✓ 健康分 $($script:Analysis.health_score)｜$($script:Analysis.schedule_count) 表｜$($script:Analysis.train_count) 车"; $HealthLabel.ForeColor = [System.Drawing.Color]::DarkGreen }
    elseif ($matched) { $HealthLabel.Text = "⚠ 健康分 $($script:Analysis.health_score)｜严重 $crit｜提醒 $warn"; $HealthLabel.ForeColor = [System.Drawing.Color]::DarkOrange }
    else { $HealthLabel.Text = '⛔ 存档与 JSON 不匹配，已禁止写入'; $HealthLabel.ForeColor = [System.Drawing.Color]::DarkRed }
    $FindingsGrid.Rows.Clear()
    foreach ($finding in $script:Analysis.findings) {
        $level = if ($finding.severity -eq 'critical') { '严重' } elseif ($finding.severity -eq 'warning') { '提醒' } else { '信息' }
        $row = $FindingsGrid.Rows.Add($level,$finding.schedule,$finding.title,$finding.action)
        if ($finding.severity -eq 'critical') { $FindingsGrid.Rows[$row].DefaultCellStyle.BackColor = [Drawing.Color]::MistyRose }
        elseif ($finding.severity -eq 'warning') { $FindingsGrid.Rows[$row].DefaultCellStyle.BackColor = [Drawing.Color]::LightYellow }
    }
    $lines = [Collections.Generic.List[string]]::new(); $lines.Add("健康分：$($script:Analysis.health_score) / 100　严重：$crit　提醒：$warn")
    foreach ($warning in $script:Analysis.warnings) { $lines.Add("• $warning") }
    $lines.Add("共 $($script:Analysis.schedule_count) 个时刻表，$($script:Analysis.train_count) 列车，$($script:Analysis.blank_template_count) 个可用模板，$($script:Analysis.empty_daily_target_count) 个完全空的 Daily 表；车库接班扩展 $($script:Analysis.garage_enabled_total) 列车。")
    $DiagnosisText.Lines = $lines.ToArray(); Set-DefaultOutput 'Toolkit'; Add-Status "体检完成：健康分 $($script:Analysis.health_score)，发现 $crit 个严重问题。"
}

function Load-Analysis {
    if (-not (Test-Path -LiteralPath $SaveText.Text)) { throw '请选择有效的 .nimbyrails5 存档。' }
    if (-not (Test-Path -LiteralPath $ExportText.Text)) { throw '请选择当前存档导出的 JSON。' }
    Start-BackendTask @('analyze','--save',$SaveText.Text,'--export',$ExportText.Text) '正在后台体检；界面仍可响应…' { param($result) Apply-Analysis $result }
}

$LatestButton.Add_Click({
    try {
        $save = Get-ChildItem -LiteralPath $SaveDir -Filter '*.nimbyrails5' -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        $export = Get-ChildItem -LiteralPath $SaveDir -Filter '*Timetable Export*.json' -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if (-not $save -or -not $export) { throw '存档目录中没有同时找到存档和时刻表导出 JSON。' }
        $SaveText.Text = $save.FullName; $ExportText.Text = $export.FullName; Set-DefaultOutput; Add-Status "已选择最新文件：$($save.Name) / $($export.Name)"
    } catch { Show-Error $_.Exception }
})
$ScanButton.Add_Click({ try { Load-Analysis } catch { Show-Error $_.Exception } })
$OpenFolderButton.Add_Click({ Start-Process explorer.exe -ArgumentList $SaveDir })
$SaveBrowse.Add_Click({ $d = [System.Windows.Forms.OpenFileDialog]::new(); $d.Filter = 'NIMBY Rails 存档 (*.nimbyrails5)|*.nimbyrails5'; $d.InitialDirectory = $SaveDir; if ($d.ShowDialog() -eq 'OK') { $SaveText.Text = $d.FileName; Set-DefaultOutput } })
$ExportBrowse.Add_Click({ $d = [System.Windows.Forms.OpenFileDialog]::new(); $d.Filter = '时刻表导出 JSON (*.json)|*.json'; $d.InitialDirectory = $SaveDir; if ($d.ShowDialog() -eq 'OK') { $ExportText.Text = $d.FileName } })
$OutputBrowse.Add_Click({ $d = [System.Windows.Forms.SaveFileDialog]::new(); $d.Filter = 'NIMBY Rails 存档 (*.nimbyrails5)|*.nimbyrails5'; $d.InitialDirectory = $SaveDir; $d.FileName = [IO.Path]::GetFileName($OutputText.Text); if ($d.ShowDialog() -eq 'OK') { $OutputText.Text = $d.FileName } })
$AddPairButton.Add_Click({
    if ($SourceCombo.SelectedItem -and $TargetCombo.SelectedItem) {
        foreach ($row in $PairGrid.Rows) { if ($row.Cells['Target'].Value -eq $TargetCombo.SelectedItem) { Show-Error ([Exception]::new('这个目标模板已经在列表中。')); return } }
        $fleet = ($script:Analysis.schedules | Where-Object name -eq $SourceCombo.SelectedItem).train_count
        [void]$PairGrid.Rows.Add($true, $SourceCombo.SelectedItem, $TargetCombo.SelectedItem, $fleet, '手动选择')
    }
})
$RemovePairButton.Add_Click({ if ($PairGrid.SelectedRows.Count) { $PairGrid.Rows.Remove($PairGrid.SelectedRows[0]) } })
$BatchRun.Add_Click({
    try {
        Require-Scan; $arguments = [Collections.Generic.List[string]]::new()
        foreach ($value in @('batch-migrate','--save',$SaveText.Text,'--export',$ExportText.Text,'--output',$OutputText.Text)) { $arguments.Add($value) }
        $count = 0; $pairNames = [Collections.Generic.List[string]]::new()
        foreach ($row in $PairGrid.Rows) {
            if ($row.Cells['Use'].Value -eq $true) {
                $sourceName = [string]$row.Cells['Source'].Value; $targetName = [string]$row.Cells['Target'].Value
                $arguments.Add('--pair'); $arguments.Add("${sourceName}::${targetName}"); $pairNames.Add("• $sourceName  →  $($targetName.Trim())"); $count++
            }
        }
        if (-not $count) { throw '请至少勾选一组要处理的时刻表。' }; if ($GarageCheck.Checked) { $arguments.Add('--garage-join') }
        $confirmation = [Windows.Forms.MessageBox]::Show(
            "将清空以下来源表，并把班次和列车移入目标 Daily 表：`r`n`r`n$($pairNames -join "`r`n")`r`n`r`n输入存档不会被覆盖。是否继续？",
            '最后确认', 'YesNo', 'Question'
        )
        if ($confirmation -ne 'Yes') { Add-Status '操作已取消。'; return }
        Start-BackendTask $arguments.ToArray() "正在后台处理 $count 组时刻表…" {
            param($result)
            Add-Status "成功：新存档已创建：$($result.output_save)"
            [System.Windows.Forms.MessageBox]::Show("新存档已创建。`r`n`r`n请进游戏加载并检查，确认后再自行决定是否替换正式存档。", '完成', 'OK', 'Information') | Out-Null
            Set-DefaultOutput 'Toolkit'
        }
    } catch { Show-Error $_.Exception }
})
$SelectAllButton.Add_Click({ for ($i=0; $i -lt $ScheduleList.Items.Count; $i++) { $ScheduleList.SetItemChecked($i, $true) } })
$SelectRiskButton.Add_Click({
    for ($i=0; $i -lt $ScheduleList.Items.Count; $i++) {
        $display=[string]$ScheduleList.Items[$i]; $name=$script:ExtensionNames[$display]
        $ScheduleList.SetItemChecked($i, $script:ScheduleRiskByName[$name] -in @('critical','warning'))
    }
})
$ClearAllButton.Add_Click({ for ($i=0; $i -lt $ScheduleList.Items.Count; $i++) { $ScheduleList.SetItemChecked($i, $false) } })
function Run-Extension([string]$mode) {
    Require-Scan; if (-not $ScheduleList.CheckedItems.Count) { throw '请先勾选至少一个时刻表。' }
    $arguments = [Collections.Generic.List[string]]::new(); foreach ($value in @('extension','--save',$SaveText.Text,'--export',$ExportText.Text,'--mode',$mode,'--output',$OutputText.Text)) { $arguments.Add($value) }
    foreach ($display in $ScheduleList.CheckedItems) { $arguments.Add('--schedule'); $arguments.Add($script:ExtensionNames[[string]$display]) }
    $verb = if ($mode -eq 'add') { '加入' } else { '移除' }
    Start-BackendTask $arguments.ToArray() "正在后台${verb}车库扩展…" {
        param($result)
        Add-Status "成功：处理 $($result.extension.target_train_count) 列车，新存档：$($result.output_save)"
        [System.Windows.Forms.MessageBox]::Show('处理完成。请加载新存档检查。', '完成', 'OK', 'Information') | Out-Null; Set-DefaultOutput 'Extension'
    }
}
$AddExtensionButton.Add_Click({ try { Run-Extension 'add' } catch { Show-Error $_.Exception } })
$RemoveExtensionButton.Add_Click({ try { Run-Extension 'remove' } catch { Show-Error $_.Exception } })

function Run-SafeRepair([bool]$withGarage) {
    Require-Scan; if (-not $ScheduleList.CheckedItems.Count) { throw '请先勾选至少一个时刻表。' }
    $arguments=[Collections.Generic.List[string]]::new(); foreach($v in @('repair','--save',$SaveText.Text,'--export',$ExportText.Text,'--output',$OutputText.Text,'--depot-x1','--severe-only')){$arguments.Add($v)}
    foreach($display in $ScheduleList.CheckedItems){$arguments.Add('--schedule');$arguments.Add($script:ExtensionNames[[string]$display])}
    if($withGarage){$arguments.Add('--garage-join')}
    $answer=[Windows.Forms.MessageBox]::Show('将只在新存档中修复体检确认的严重车库循环。普通每日进出不会修改。是否继续？','确认安全修复','YesNo','Question')
    if($answer -ne 'Yes'){return}
    Start-BackendTask $arguments.ToArray() '正在后台执行安全修复…' {
        param($result)
        $changed=if($result.depot){$result.depot.changed_count}else{0}; Add-Status "安全修复完成：车库指令 $changed 处；新存档 $($result.output_save)"
        [Windows.Forms.MessageBox]::Show("安全修复完成。车库指令修改 $changed 处。`r`n请加载新存档检查。",'完成','OK','Information')|Out-Null; Set-DefaultOutput 'Repair'
    }
}
$RepairDepotButton.Add_Click({try{Run-SafeRepair $false}catch{Show-Error $_.Exception}})
$RepairSafeButton.Add_Click({try{Run-SafeRepair $true}catch{Show-Error $_.Exception}})
$RetireOverlapButton.Add_Click({
    try {
        Require-Scan
        if(-not $OverlapList.CheckedItems.Count){throw '请先在右侧勾选至少一个可修复任务。'}
        $tasks=@($OverlapList.CheckedItems | ForEach-Object { $script:RepairTaskByDisplay[[string]$_] })
        $display=($OverlapList.CheckedItems | ForEach-Object { "• $_" }) -join "`r`n"
        $answer=[Windows.Forms.MessageBox]::Show("将在一个新存档中执行：`r`n`r`n$display`r`n`r`n输入存档不会被覆盖。车库 x1 修复后需加载一次，让游戏重建七天运行。是否继续？",'确认一键修复','YesNo','Question')
        if($answer -ne 'Yes'){return}
        $args=[Collections.Generic.List[string]]::new(); foreach($v in @('fix-tasks','--save',$SaveText.Text,'--export',$ExportText.Text,'--output',$OutputText.Text)){$args.Add($v)}
        foreach($task in $tasks){
            if($task.type -eq 'retire_overlap'){$args.Add('--pair');$args.Add([string]$task.pair)}
            elseif($task.type -eq 'depot_x1'){$args.Add('--depot-schedule');$args.Add([string]$task.schedule)}
            else{throw "不支持的修复任务类型：$($task.type)"}
        }
        Start-BackendTask $args.ToArray() '正在后台执行勾选的修复任务…' {
            param($result)
            $retired=if($result.retired){$result.retired.retired_count}else{0}; $depot=if($result.depot){$result.depot.changed_count}else{0}
            Add-Status "一键修复完成：清空旧表 $retired 张，车库 x1 修改 $depot 处；新存档 $($result.output_save)"
            [Windows.Forms.MessageBox]::Show("修复完成：清空旧表 $retired 张，车库指令修改 $depot 处。`r`n`r`n请加载新存档，等待游戏重建时刻表，再导出 JSON 复检。",'完成','OK','Information')|Out-Null; Set-DefaultOutput 'Repair'
        }
    } catch { Show-Error $_.Exception }
})

function Load-ReferenceChoices([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { throw '历史导出 JSON 不存在。' }
    Start-BackendTask @('scan','--export',$path) '正在后台读取历史 JSON…' {
        param($result)
        $script:ReferenceScan = $result; $ReferenceExportText.Text = $result.export; $ReferenceSourceCombo.Items.Clear()
        foreach ($schedule in $result.schedules) { if ($schedule.is_source) { [void]$ReferenceSourceCombo.Items.Add($schedule.name) } }
        if ($ReferenceSourceCombo.Items.Count) { $ReferenceSourceCombo.SelectedIndex = 0 }
        Add-Status "历史 JSON 已读取：找到 $($ReferenceSourceCombo.Items.Count) 个有车队的来源表。"
    }
}
$ReferenceBrowse.Add_Click({
    try {
        $d=[Windows.Forms.OpenFileDialog]::new(); $d.Filter='历史时刻表导出 JSON (*.json)|*.json'; $d.InitialDirectory=$SaveDir
        if ($d.ShowDialog() -eq 'OK') { Load-ReferenceChoices $d.FileName }
    } catch { Show-Error $_.Exception }
})
$ReferenceAuto.Add_Click({
    try {
        Require-Scan
        if (-not $RecoveryTargetCombo.SelectedItem) { throw '当前没有空白目标模板。' }
        $targetName=[string]$RecoveryTargetCombo.SelectedItem
        Start-BackendTask @('find-reference','--directory',$SaveDir,'--current-export',$ExportText.Text,'--target',$targetName,'--limit','15') '正在多核查找历史车队…' {
            param($result)
            $ReferenceExportText.Text=$result.best.export; $ReferenceSourceCombo.Items.Clear(); [void]$ReferenceSourceCombo.Items.Add($result.best.source); $ReferenceSourceCombo.SelectedIndex=0
            Add-Status "已找到历史车队：$($result.best.source)，列车 $($result.best.train_count)，使用 $($result.workers_used) 个进程。"
        }
    } catch { Show-Error $_.Exception }
})
$RecoveryRun.Add_Click({
    try {
        Require-Scan
        if(-not $ReferenceExportText.Text -or -not $ReferenceSourceCombo.SelectedItem -or -not $RecoveryTargetCombo.SelectedItem){throw '请先选择历史 JSON、历史来源表和当前目标表。'}
        $source=[string]$ReferenceSourceCombo.SelectedItem; $target=[string]$RecoveryTargetCombo.SelectedItem
        $message='将使用当前模板「{0}」重建历史车队「{1}」。历史运行内容不会被复制。是否继续？' -f $target.Trim(),$source
        $answer=[Windows.Forms.MessageBox]::Show($message,'确认模板恢复','YesNo','Question')
        if($answer -ne 'Yes'){return}
        $args=[Collections.Generic.List[string]]::new(); foreach($v in @('recover-template','--save',$SaveText.Text,'--export',$ExportText.Text,'--reference-export',$ReferenceExportText.Text,'--reference-source',$source,'--target',$target,'--output',$OutputText.Text)){ $args.Add($v) }
        if($RecoveryGarage.Checked){$args.Add('--garage-join')}
        Start-BackendTask $args.ToArray() '正在后台用当前模板重建历史车队…' {
            param($result)
            Add-Status "恢复成功：$($result.migration.fleet_size) 列车，模板运行数 $($result.migration.target_template_run_count)。"
            [Windows.Forms.MessageBox]::Show('模板恢复完成，请加载新存档检查。','完成','OK','Information')|Out-Null; Set-DefaultOutput 'Recovery'
        }
    } catch { Show-Error $_.Exception }
})

$CopyDiagnosis.Add_Click({ if ($DiagnosisText.Text) { [Windows.Forms.Clipboard]::SetText($DiagnosisText.Text); Add-Status '诊断摘要已复制。' } })
$InventoryButton.Add_Click({
    try {
        Start-BackendTask @('inventory','--directory',$SaveDir,'--limit','12') '正在多核盘点最近文件…' {
            param($result)
            $lines=[Collections.Generic.List[string]]::new(); $lines.Add("并行：$($result.parallel)　使用 $($result.workers_used)/$($result.logical_cpu_count) 个逻辑处理器　耗时 $($result.elapsed_seconds) 秒")
            $lines.Add(''); $lines.Add('最近的时刻表导出：')
            foreach($item in $result.exports){
                if($item.ok){$critical=[int]$item.severity_counts.critical; $lines.Add(("  健康 {0,3}｜严重 {1,2}｜模板 {2,2}｜{3}" -f $item.health_score,$critical,$item.blank_template_count,$item.name)); if($item.critical_schedules.Count){$lines.Add('      ' + ($item.critical_schedules -join '、'))}}
                else{$lines.Add("  读取失败｜$($item.name)｜$($item.error)")}
            }
            $lines.Add(''); $lines.Add("存档：$($result.saves.Count) 份　残留临时文件：$($result.partial_files.Count)　校验记录：$($result.manifest_health.Count)")
            foreach($partial in $result.partial_files){$lines.Add("  临时残留：$partial")}
            foreach($manifest in $result.manifest_health | Where-Object {-not $_.verified -or -not $_.output_exists}){$lines.Add("  校验提醒：$($manifest.path)｜输出存在 $($manifest.output_exists)｜校验 $($manifest.verified)")}
            $HistoryText.Lines=$lines.ToArray(); Add-Status "多核盘点完成：使用 $($result.workers_used) 个进程，耗时 $($result.elapsed_seconds) 秒。"
        }
    } catch { Show-Error $_.Exception }
})
$CompareButton.Add_Click({
    try {
        if(-not (Test-Path -LiteralPath $ReferenceExportText.Text)){throw '请先在“模板恢复”页选择一份历史 JSON。'}
        if(-not (Test-Path -LiteralPath $ExportText.Text)){throw '当前 JSON 不存在。'}
        Start-BackendTask @('compare','--before',$ReferenceExportText.Text,'--after',$ExportText.Text) '正在后台对比两份导出…' {
            param($result)
            $lines=[Collections.Generic.List[string]]::new(); $lines.Add("健康分：$($result.before_health_score) → $($result.after_health_score)　变化 $($result.change_count) 项")
            $lines.Add("新增问题：$($result.new_findings.Count)　已解决：$($result.resolved_findings.Count)"); $lines.Add('')
            foreach($change in $result.changes | Select-Object -First 80){$lines.Add("  $($change.change)｜$($change.schedule)")}
            $HistoryText.Lines=$lines.ToArray(); Add-Status '历史对比完成。'
        }
    } catch { Show-Error $_.Exception }
})
$CleanupNow.Add_Click({
    try {
        $files = @(Get-ExpiredToolCopies ([int]$CleanupDays.Value) ([int]$CleanupKeep.Value))
        if (-not $files.Count) {
            [Windows.Forms.MessageBox]::Show('没有符合条件的过期工具副本。', '清理检查', 'OK', 'Information') | Out-Null
            return
        }
        $names = ($files | ForEach-Object Name) -join "`r`n"
        $answer = [Windows.Forms.MessageBox]::Show("以下 $($files.Count) 个副本将移入回收站：`r`n`r`n$names", '确认清理', 'YesNo', 'Question')
        if ($answer -eq 'Yes') { $moved = Move-ToolCopiesToRecycleBin $files; Add-Status "已将 $moved 个过期工具副本移入回收站。" }
    } catch { Show-Error $_.Exception }
})

$CleanupTimer = [System.Windows.Forms.Timer]::new()
$CleanupTimer.Interval = 21600000
$CleanupTimer.Add_Tick({
    if ($AutoCleanupCheck.Checked) {
        try {
            $files = @(Get-ExpiredToolCopies ([int]$CleanupDays.Value) ([int]$CleanupKeep.Value))
            if ($files.Count) { $moved = Move-ToolCopiesToRecycleBin $files; Add-Status "定期清理：$moved 个过期工具副本已移入回收站。" }
        } catch { Add-Status "定期清理失败：$($_.Exception.Message)" }
    }
})
$Form.Add_Shown({
    $CleanupTimer.Start()
    if ($AutoCleanupCheck.Checked) {
        try {
            $files = @(Get-ExpiredToolCopies ([int]$CleanupDays.Value) ([int]$CleanupKeep.Value))
            if ($files.Count) { $moved = Move-ToolCopiesToRecycleBin $files; Add-Status "启动清理：$moved 个过期工具副本已移入回收站。" }
        } catch { Add-Status "启动清理失败：$($_.Exception.Message)" }
    }
})
$Form.Add_FormClosing({
    try {
        if ($script:TaskProcess -and -not $script:TaskProcess.HasExited) { try { $script:TaskProcess.Kill($true) } catch { try { $script:TaskProcess.Kill() } catch { } } }
        $BackendTimer.Stop(); Remove-TaskFiles
        if ($AsyncSmokeTest) { return }
        if (-not (Test-Path -LiteralPath $SettingsDir)) { [void][IO.Directory]::CreateDirectory($SettingsDir) }
        [PSCustomObject]@{ Enabled=$AutoCleanupCheck.Checked; Days=[int]$CleanupDays.Value; Keep=[int]$CleanupKeep.Value; Workers=[int]$WorkerCount.Value } |
            ConvertTo-Json | Set-Content -LiteralPath $SettingsFile -Encoding utf8
    } catch { }
})

Add-Status '工具已就绪。建议先点“自动选择最新文件”，再点“扫描并检查”。'
if ($SmokeTest) {
    [PSCustomObject]@{ Title=$Form.Text; Width=$Form.Width; Height=$Form.Height; Tabs=$Tabs.TabPages.Count; PairColumns=$PairGrid.Columns.Count; HasHealth=[bool]$HealthLabel; HasMultiSelect=[bool]$ScheduleList; HasRepairTaskSelection=[bool]$OverlapList; HasCancel=[bool]$CancelTaskButton; Workers=[int]$WorkerCount.Value } | ConvertTo-Json -Compress
    exit 0
}
if ($AsyncSmokeTest) {
    $save = Get-ChildItem -LiteralPath $SaveDir -Filter '*.nimbyrails5' -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $export = Get-ChildItem -LiteralPath $SaveDir -Filter '*Timetable Export*.json' -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $save -or -not $export) { throw '异步测试缺少存档或导出 JSON。' }
    $AutoCleanupCheck.Checked=$false; $Form.ShowInTaskbar=$false; $Form.Opacity=0; $Form.Show(); [Windows.Forms.Application]::DoEvents()
    $SaveText.Text=$save.FullName; $ExportText.Text=$export.FullName; Load-Analysis
    $deadline=(Get-Date).AddSeconds(90)
    while($script:TaskProcess -and -not $script:AsyncError -and (Get-Date) -lt $deadline){ [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 50 }
    if($script:AsyncError){throw $script:AsyncError}
    if($script:TaskProcess){throw '异步测试超时。'}
    $summary=[PSCustomObject]@{Completed=[bool]$script:Analysis;Health=$script:Analysis.health_score;Compatible="$($script:Analysis.compatible_schedule_count)/$($script:Analysis.expected_schedule_count)";Progress=$TaskProgress.Value;Task=$TaskLabel.Text;Findings=$FindingsGrid.Rows.Count;RepairTasks=$OverlapList.Items.Count;SuggestedPairs=$PairGrid.Rows.Count;Tabs=$Tabs.TabPages.Count}
    $Form.Close(); [Windows.Forms.Application]::DoEvents(); $summary|ConvertTo-Json -Compress
    exit 0
}
[void]$Form.ShowDialog()
