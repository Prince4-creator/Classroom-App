Set WshShell = CreateObject("WScript.Shell")
ProjectFolder = "C:\Users\princ\OneDrive\Desktop\classroom_app"
WshShell.CurrentDirectory = ProjectFolder
cmd = """" & ProjectFolder & "\\venv\\Scripts\\python.exe" & """" & " public_server.py"
WshShell.Run cmd, 1, False
