from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from runtime.logger import logs_dir
from runtime.system_info import app_root, is_pyinstaller, resource_root
from runtime.user_settings import settings_dir


def _ps_escape(value: str) -> str:
    return value.replace("'", "''")


def build_script(executable: Path) -> str:
    exe = _ps_escape(str(executable))
    main_script = _ps_escape(str(app_root() / "main.py"))
    frozen_value = "1" if is_pyinstaller() else "0"
    help_dir_value = _ps_escape(str(resource_root() / "help"))
    settings_dir_value = _ps_escape(str(settings_dir()))
    log_dir_value = _ps_escape(str(logs_dir()))
    return rf"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$exePath = '{exe}'
$mainScript = '{main_script}'
$isFrozen = '{frozen_value}'
$helpDir = '{help_dir_value}'
$settingsDir = '{settings_dir_value}'
$logDir = '{log_dir_value}'

function Read-HelpText([string]$fileName, [string]$fallback) {{
    $path = Join-Path $helpDir $fileName
    if (Test-Path -LiteralPath $path) {{
        return [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
    }}
    return $fallback
}}

function Show-HelpWindow([string]$title, [string]$fileName, [string]$fallback) {{
    $content = Read-HelpText $fileName $fallback
    $helpForm = New-Object System.Windows.Forms.Form
    $helpForm.Text = "VisualMasterPro V0.3 - $title"
    $helpForm.Size = New-Object System.Drawing.Size(720, 560)
    $helpForm.StartPosition = 'CenterParent'

    $box = New-Object System.Windows.Forms.TextBox
    $box.Multiline = $true
    $box.ReadOnly = $true
    $box.ScrollBars = 'Vertical'
    $box.WordWrap = $true
    $box.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 10)
    $box.Dock = 'Fill'
    $box.Text = $content
    $helpForm.Controls.Add($box)
    [void]$helpForm.ShowDialog()
}}

function Show-QuickGuideOnce {{
    if ($env:VISUALMASTERPRO_SKIP_GUIDE -eq '1') {{
        return
    }}
    New-Item -ItemType Directory -Force -Path $settingsDir | Out-Null
    $flag = Join-Path $settingsDir 'quick_guide_seen_v03.flag'
    if (-not (Test-Path -LiteralPath $flag)) {{
        $content = Read-HelpText '快速引导.txt' '欢迎使用 VisualMasterPro V0.3。请先添加图片或选择图片文件夹，再选择输出文件夹，最后点击开始处理。软件不会覆盖原图，默认不添加角标。'
        [System.Windows.Forms.MessageBox]::Show($content, 'VisualMasterPro V0.3 - 快速引导') | Out-Null
        Set-Content -Path $flag -Value 'seen' -Encoding UTF8
    }}
}}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'VisualMasterPro V0.3'
$form.Size = New-Object System.Drawing.Size(760, 540)
$form.StartPosition = 'CenterScreen'

$menu = New-Object System.Windows.Forms.MenuStrip
$helpMenu = New-Object System.Windows.Forms.ToolStripMenuItem('帮助')
$guideItem = New-Object System.Windows.Forms.ToolStripMenuItem('快速引导')
$guideItem.Add_Click({{ Show-HelpWindow '快速引导' '快速引导.txt' '欢迎使用 VisualMasterPro V0.3。请先添加图片或选择图片文件夹，再选择输出文件夹，最后点击开始处理。' }})
$guideItem | Out-Null
$userGuideItem = New-Object System.Windows.Forms.ToolStripMenuItem('使用说明')
$userGuideItem.Add_Click({{ Show-HelpWindow '使用说明' '使用说明.txt' '使用说明文件未找到。请检查 help/使用说明.txt 是否已随软件一起打包。' }})
$faqItem = New-Object System.Windows.Forms.ToolStripMenuItem('常见问题')
$faqItem.Add_Click({{ Show-HelpWindow '常见问题' 'FAQ.txt' '常见问题文件未找到。请检查 help/FAQ.txt 是否已随软件一起打包。' }})
$logHelpItem = New-Object System.Windows.Forms.ToolStripMenuItem('日志位置说明')
$logHelpItem.Add_Click({{ Show-HelpWindow '日志位置说明' '日志位置说明.txt' '日志说明文件未找到。请检查 help/日志位置说明.txt 是否已随软件一起打包。' }})
$openLogItem = New-Object System.Windows.Forms.ToolStripMenuItem('打开日志文件夹')
$openLogItem.Add_Click({{
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    Start-Process $logDir
}})
[void]$helpMenu.DropDownItems.Add($guideItem)
[void]$helpMenu.DropDownItems.Add((New-Object System.Windows.Forms.ToolStripSeparator))
[void]$helpMenu.DropDownItems.Add($userGuideItem)
[void]$helpMenu.DropDownItems.Add($faqItem)
[void]$helpMenu.DropDownItems.Add($logHelpItem)
[void]$helpMenu.DropDownItems.Add((New-Object System.Windows.Forms.ToolStripSeparator))
[void]$helpMenu.DropDownItems.Add($openLogItem)
[void]$menu.Items.Add($helpMenu)
$form.MainMenuStrip = $menu
$form.Controls.Add($menu)

$title = New-Object System.Windows.Forms.Label
$title.Text = 'VisualMasterPro V0.3'
$title.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 16, [System.Drawing.FontStyle]::Bold)
$title.Location = New-Object System.Drawing.Point(20, 34)
$title.Size = New-Object System.Drawing.Size(500, 32)
$form.Controls.Add($title)

$sub = New-Object System.Windows.Forms.Label
$sub.Text = '原图忠实增强 · 4K清晰优化 · 批量处理'
$sub.Location = New-Object System.Drawing.Point(22, 72)
$sub.Size = New-Object System.Drawing.Size(520, 24)
$form.Controls.Add($sub)

$list = New-Object System.Windows.Forms.ListBox
$list.Location = New-Object System.Drawing.Point(20, 108)
$list.Size = New-Object System.Drawing.Size(700, 172)
$form.Controls.Add($list)

$inputPaths = New-Object System.Collections.ArrayList
$outputBox = New-Object System.Windows.Forms.TextBox
$outputBox.Location = New-Object System.Drawing.Point(120, 305)
$outputBox.Size = New-Object System.Drawing.Size(500, 24)
$outputBox.Text = [System.IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), '雪原Ai增强引擎', '输出成品')
$form.Controls.Add($outputBox)

$outputLabel = New-Object System.Windows.Forms.Label
$outputLabel.Text = '输出文件夹'
$outputLabel.Location = New-Object System.Drawing.Point(20, 308)
$outputLabel.Size = New-Object System.Drawing.Size(90, 24)
$form.Controls.Add($outputLabel)

$modeLabel = New-Object System.Windows.Forms.Label
$modeLabel.Text = '增强模式'
$modeLabel.Location = New-Object System.Drawing.Point(20, 350)
$modeLabel.Size = New-Object System.Drawing.Size(90, 24)
$form.Controls.Add($modeLabel)

$mode = New-Object System.Windows.Forms.ComboBox
$mode.Location = New-Object System.Drawing.Point(120, 346)
$mode.Size = New-Object System.Drawing.Size(180, 24)
$mode.DropDownStyle = 'DropDownList'
$mode.Items.AddRange(@('fidelity', 'text_safe', 'ai_image_clean', 'sharp_4k'))
$mode.SelectedIndex = 0
$form.Controls.Add($mode)

$status = New-Object System.Windows.Forms.Label
$status.Text = '等待选择图片'
$status.Location = New-Object System.Drawing.Point(20, 392)
$status.Size = New-Object System.Drawing.Size(700, 28)
$form.Controls.Add($status)

$addFiles = New-Object System.Windows.Forms.Button
$addFiles.Text = '添加图片'
$addFiles.Location = New-Object System.Drawing.Point(20, 295)
$addFiles.Size = New-Object System.Drawing.Size(90, 30)
$addFiles.Visible = $false

$btnFiles = New-Object System.Windows.Forms.Button
$btnFiles.Text = '添加图片'
$btnFiles.Location = New-Object System.Drawing.Point(20, 430)
$btnFiles.Size = New-Object System.Drawing.Size(100, 34)
$btnFiles.Add_Click({{
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Filter = '图片文件|*.jpg;*.jpeg;*.png;*.webp;*.bmp;*.tif;*.tiff'
    $dialog.Multiselect = $true
    if ($dialog.ShowDialog() -eq 'OK') {{
        foreach ($file in $dialog.FileNames) {{
            [void]$inputPaths.Add($file)
            [void]$list.Items.Add($file)
        }}
        $status.Text = "已选择 $($inputPaths.Count) 张图片"
    }}
}})
$form.Controls.Add($btnFiles)

$btnFolder = New-Object System.Windows.Forms.Button
$btnFolder.Text = '选择文件夹'
$btnFolder.Location = New-Object System.Drawing.Point(135, 430)
$btnFolder.Size = New-Object System.Drawing.Size(100, 34)
$btnFolder.Add_Click({{
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    if ($dialog.ShowDialog() -eq 'OK') {{
        [void]$inputPaths.Add($dialog.SelectedPath)
        [void]$list.Items.Add($dialog.SelectedPath)
        $status.Text = "已选择输入文件夹"
    }}
}})
$form.Controls.Add($btnFolder)

$btnOutput = New-Object System.Windows.Forms.Button
$btnOutput.Text = '输出目录'
$btnOutput.Location = New-Object System.Drawing.Point(250, 430)
$btnOutput.Size = New-Object System.Drawing.Size(100, 34)
$btnOutput.Add_Click({{
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    if ($dialog.ShowDialog() -eq 'OK') {{
        $outputBox.Text = $dialog.SelectedPath
    }}
}})
$form.Controls.Add($btnOutput)

$btnStart = New-Object System.Windows.Forms.Button
$btnStart.Text = '开始处理'
$btnStart.Location = New-Object System.Drawing.Point(365, 430)
$btnStart.Size = New-Object System.Drawing.Size(100, 34)
$btnStart.Add_Click({{
    if ($inputPaths.Count -eq 0) {{
        [System.Windows.Forms.MessageBox]::Show('请先添加图片或选择图片文件夹。', 'VisualMasterPro')
        return
    }}
    New-Item -ItemType Directory -Force -Path $outputBox.Text | Out-Null
    $status.Text = '正在处理，请稍候...'
    foreach ($item in $inputPaths) {{
        if ($isFrozen -eq '1') {{
            $arguments = @('--input', $item, '--output', $outputBox.Text, '--mode', $mode.SelectedItem)
        }} else {{
            $arguments = @($mainScript, '--input', $item, '--output', $outputBox.Text, '--mode', $mode.SelectedItem)
        }}
        $p = Start-Process -FilePath $exePath -ArgumentList $arguments -Wait -PassThru
        if ($p.ExitCode -ne 0) {{
            [System.Windows.Forms.MessageBox]::Show("处理失败，请查看 logs/latest_crash.txt。", 'VisualMasterPro')
        }}
    }}
    $status.Text = '处理完成'
    [System.Windows.Forms.MessageBox]::Show('处理完成。', 'VisualMasterPro')
}})
$form.Controls.Add($btnStart)

$btnOpen = New-Object System.Windows.Forms.Button
$btnOpen.Text = '打开输出'
$btnOpen.Location = New-Object System.Drawing.Point(480, 430)
$btnOpen.Size = New-Object System.Drawing.Size(100, 34)
$btnOpen.Add_Click({{
    New-Item -ItemType Directory -Force -Path $outputBox.Text | Out-Null
    Start-Process $outputBox.Text
}})
$form.Controls.Add($btnOpen)

$btnLogs = New-Object System.Windows.Forms.Button
$btnLogs.Text = '查看日志'
$btnLogs.Location = New-Object System.Drawing.Point(595, 430)
$btnLogs.Size = New-Object System.Drawing.Size(100, 34)
$btnLogs.Add_Click({{
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    Start-Process $logDir
}})
$form.Controls.Add($btnLogs)

$form.Add_Shown({{ Show-QuickGuideOnce }})
[void]$form.ShowDialog()
"""


def run_powershell_gui() -> int:
    executable = Path(sys.executable).resolve()
    script = build_script(executable)
    temp_path = Path(tempfile.gettempdir()) / "VisualMasterPro_v03_gui.ps1"
    temp_path.write_text(script, encoding="utf-8-sig")
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(temp_path),
        ],
        close_fds=True,
    )
    return 0
