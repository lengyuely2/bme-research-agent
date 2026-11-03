Option Explicit
Dim fso, sh, root, runtime, entry
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
runtime = fso.BuildPath(root, ".runtime\electron\electron.exe")
entry = fso.BuildPath(root, "desktop")
If Not fso.FileExists(runtime) Then
  MsgBox "Electron runtime missing. See README-BME.md.", 48, "Caelo BME"
  WScript.Quit 1
End If
sh.CurrentDirectory = root
sh.Run """" & runtime & """ """ & entry & """", 0, False
