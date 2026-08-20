Option Explicit

' Launches the single-window desktop WebApp (toolkit_webapp.py) with a hidden,
' console-less Python (pythonw). The app opens its own native window via
' pywebview and shuts down completely when that window is closed.
'
' Standard user Python installs (which have pywebview, so the app gets a real
' native window) are tried first; the Codex runtime interpreter is last because
' it usually lacks pywebview and would force the Edge fallback.

Dim shell, files, rootDir, appFile, pythonw, candidates, i, command

Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")

rootDir = files.GetParentFolderName(WScript.ScriptFullName)
appFile = files.BuildPath(rootDir, "toolkit_webapp.py")

candidates = Array( _
    shell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe"), _
    shell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"), _
    shell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"), _
    shell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"), _
    shell.ExpandEnvironmentStrings("%USERPROFILE%\Envs\oldC-python310\Scripts\pythonw.exe"), _
    shell.ExpandEnvironmentStrings("%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe") _
)

pythonw = ""
For i = 0 To UBound(candidates)
    If files.FileExists(candidates(i)) Then
        pythonw = candidates(i)
        Exit For
    End If
Next

' Fall back to the Python launcher / PATH resolution when no absolute match.
If pythonw = "" Then
    If files.FileExists(shell.ExpandEnvironmentStrings("%WINDIR%\pyw.exe")) Then
        pythonw = shell.ExpandEnvironmentStrings("%WINDIR%\pyw.exe")
    Else
        pythonw = "pythonw.exe"
    End If
End If

If WScript.Arguments.Named.Exists("check") Then
    If Not files.FileExists(appFile) Then
        WScript.Echo "webapp-not-found"
        WScript.Quit 3
    End If
    WScript.Echo "launcher-ok using " & pythonw
    WScript.Quit 0
End If

If Not files.FileExists(appFile) Then
    MsgBox "toolkit_webapp.py was not found in the toolkit folder.", 48, "NIMBY Rails Toolkit"
    WScript.Quit 1
End If

shell.CurrentDirectory = rootDir
command = Chr(34) & pythonw & Chr(34) & " " & Chr(34) & appFile & Chr(34)
shell.Run command, 0, False
