Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
ProjectFolder = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = ProjectFolder
pythonPath = ProjectFolder & "\venv\Scripts\python.exe"
If FSO.FileExists(pythonPath) Then
    cmd = """" & pythonPath & """ app.py"
Else
    cmd = "python app.py"
End If
WshShell.Run cmd, 0, False
WshShell.Run "http://127.0.0.1:5000", 1, False
