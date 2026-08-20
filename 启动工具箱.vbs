Option Explicit

Dim shell, files, rootDir, launcher, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")

rootDir = files.GetParentFolderName(WScript.ScriptFullName)
launcher = files.BuildPath(rootDir, "launcher.vbs")

If WScript.Arguments.Named.Exists("check") Then
    WScript.Echo "wrapper-ok"
    WScript.Quit 0
End If

If Not files.FileExists(launcher) Then
    MsgBox "launcher.vbs was not found in the toolkit folder.", 48, "NIMBY Rails Toolkit"
    WScript.Quit 1
End If

command = "wscript.exe " & Chr(34) & launcher & Chr(34)
shell.Run command, 0, False
