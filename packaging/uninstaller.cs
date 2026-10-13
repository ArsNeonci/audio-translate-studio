// Windows uninstaller, shipped inside every installation as uninstall.exe and started by "Installed apps" > Uninstall.
//   uninstall.exe          asks first, and (when no other Audio Translate edition is installed) whether to delete the user's data too
//   uninstall.exe /Q       silent, keeps the user's data
//   uninstall.exe /Q /DATA silent, also deletes the user's data (activation, results, downloaded model)
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;
using Microsoft.Win32;

static class Uninstaller {
    const string Version="@@VERSION@@";
    const string Edition="@@EDITION@@";
    static string Title { get { return Edition.Length>0?"Audio Translate "+Edition:"Audio Translate"; } }
    static string UninstallKey { get { return @"Software\Microsoft\Windows\CurrentVersion\Uninstall\AudioTranslate-"+(Edition.Length>0?Edition+"-":"")+Version; } }
    static void StopApp(string root) {
        string prefix=root.TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
        int self=Process.GetCurrentProcess().Id;
        for(int pass=0;pass<2;pass++) {
            foreach(Process process in Process.GetProcesses()) {
                try {
                    if(process.Id==self) continue;
                    if(process.MainModule.FileName.StartsWith(prefix,StringComparison.OrdinalIgnoreCase)) { process.Kill(); process.WaitForExit(5000); }
                } catch { }
            }
        }
    }
    // Other installed copies (another edition or version): the user's data folder is shared by all of them.
    static bool OtherInstallExists(string target) {
        string parent=Path.GetDirectoryName(target.TrimEnd(Path.DirectorySeparatorChar));
        if(parent==null || !Directory.Exists(parent)) return false;
        foreach(string folder in Directory.GetDirectories(parent))
            if(!String.Equals(Path.GetFullPath(folder).TrimEnd(Path.DirectorySeparatorChar),target.TrimEnd(Path.DirectorySeparatorChar),StringComparison.OrdinalIgnoreCase)
               && File.Exists(Path.Combine(folder,"installation.json"))) return true;
        return false;
    }
    [STAThread]
    static int Main(string[] args) {
        bool quiet=Array.Exists(args,a=>a.Equals("/Q",StringComparison.OrdinalIgnoreCase));
        bool data=Array.Exists(args,a=>a.Equals("/DATA",StringComparison.OrdinalIgnoreCase));
        try {
            string target=Path.GetFullPath(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location));
            // Never delete a folder that is not one of our installations.
            if(!File.Exists(Path.Combine(target,"installation.json"))) throw new IOException("Not an installation folder");
            string userData=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"AudioTranslate");
            bool others=OtherInstallExists(target);
            if(!quiet) {
                if(MessageBox.Show("Uninstall "+Title+" "+Version+"?",Title,MessageBoxButtons.YesNo,MessageBoxIcon.Question)!=DialogResult.Yes) return 0;
                if(!others && Directory.Exists(userData))
                    data=MessageBox.Show("Also delete your data (licence activation, results and the downloaded translation model)?\n\nYes: delete everything. No: keep it, so a later install continues where you left off.",Title,MessageBoxButtons.YesNo,MessageBoxIcon.Warning,MessageBoxDefaultButton.Button2)==DialogResult.Yes;
            }
            if(others) data=false;  // the other copies still use it
            StopApp(target);
            // The Start-menu shortcut goes only if it still points into this folder (a newer version may have taken it over).
            string link=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs),Title+".lnk");
            if(File.Exists(link)) {
                try {
                    object shell=Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
                    object shortcut=shell.GetType().InvokeMember("CreateShortcut",BindingFlags.InvokeMethod,null,shell,new object[]{link});
                    string to=(string)shortcut.GetType().InvokeMember("TargetPath",BindingFlags.GetProperty,null,shortcut,new object[0]);
                    if(to.StartsWith(target.TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) File.Delete(link);
                } catch { }
            }
            try { Registry.CurrentUser.DeleteSubKeyTree(UninstallKey,false); } catch { }
            // This program lives inside the folder it removes, so a hidden command prompt deletes the folder after this process has exited.
            string command="/c ping -n 3 127.0.0.1 >nul & rmdir /s /q \""+target+"\""+(data?" & rmdir /s /q \""+userData+"\"":"");
            ProcessStartInfo start=new ProcessStartInfo("cmd.exe",command);
            start.WorkingDirectory=Path.GetTempPath(); start.CreateNoWindow=true; start.UseShellExecute=false; start.WindowStyle=ProcessWindowStyle.Hidden;
            Process.Start(start);
            if(!quiet) MessageBox.Show(Title+" was uninstalled."+(data?" Your data was deleted too.":(others?"":" Your data was kept.")),Title);
            return 0;
        } catch {
            if(!quiet) MessageBox.Show("Uninstall failed. Close "+Title+" if it is open and try again.",Title);
            return 1;
        }
    }
}
