Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strDir = fso.GetParentFolderName(WScript.ScriptFullName) & "\.."
WshShell.CurrentDirectory = strDir

guiExe = strDir & "\.venv\Scripts\katip-gui.exe"
pythonwExe = strDir & "\.venv\Scripts\pythonw.exe"

If fso.FileExists(guiExe) Then
    WshShell.Run """" & guiExe & """", 0, False
ElseIf fso.FileExists(pythonwExe) Then
    WshShell.Run """" & pythonwExe & """ -m katip", 0, False
Else
    WshShell.Run "pythonw -m katip", 0, False
End If
