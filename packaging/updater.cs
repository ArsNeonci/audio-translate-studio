// App-only update, applied after the app has quit (it cannot replace the files it runs from).
//   updater.exe /apply <apply.json>
// Two kinds of package (apply.json "kind"): "app" is the zip described below; "installer" is the full installer, run silently (/Q) when a release needs a
// different runtime. The installer replaces the installation by itself and leaves the old copy untouched if it fails; this program then starts the
// app again (the new one on success, the old one on failure) and records the result the same way.
// The app (worker/audio_translate/api/app_update.py) downloads a package, verifies its signed manifest and SHA-256, and writes apply.json; the desktop
// shell starts this program when it exits. The package is the installation without runtime/ and providers/ (the 1.6 GB that rarely changes).
//
// What it does, in order, writing every step to <data>\updates\updater.log:
//   1. copies itself to the temp folder and runs from there, so that updater.exe in the installation can be replaced too;
//   2. waits for the app to be gone (stops what is left of it) and checks the package's SHA-256;
//   3. renames app\ to app.old\, copies the root files it will replace into app.old\_root\, unpacks the package over the installation;
//   4. starts the new app and waits (up to 150 s) for it to report ready (<data>\updates\health.json with the new version);
//   5. if it does not, or anything above fails, puts app.old\ back, restores the root files, starts the old app again and records the failure
//      (<data>\updates\last-update.json, and the version in failed-versions.json so that the app does not offer it again by itself).
// Exit codes: 0 updated, 1 rolled back (the old app is running again), 2 bad arguments or an unreadable plan.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using Microsoft.Win32;

static class Updater {
    const string Edition="@@EDITION@@";
    static string log;

    static void Log(string text) {
        try { File.AppendAllText(log,DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss")+" "+text+Environment.NewLine,new UTF8Encoding(false)); } catch { }
    }
    static string UninstallKey { get {
        string custom=Environment.GetEnvironmentVariable("AUDIO_UNINSTALL_ROOT");
        return (String.IsNullOrEmpty(custom)?@"Software\Microsoft\Windows\CurrentVersion\Uninstall":custom)+@"\AudioTranslate"+(Edition.Length>0?"-"+Edition:"");
    } }
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
    static void Wipe(string target) {
        for(int attempt=0;;attempt++) {
            try { if(Directory.Exists(target)) Directory.Delete(target,true); return; }
            catch { if(attempt>=6) throw; Thread.Sleep(1000); }
        }
    }
    static void Rename(string from,string to) {
        for(int attempt=0;;attempt++) {
            try { Directory.Move(from,to); return; }
            catch { if(attempt>=10) throw; Thread.Sleep(750); }
        }
    }
    static string Sha256(string path) {
        using(FileStream stream=File.OpenRead(path)) using(SHA256 hash=SHA256.Create()) {
            byte[] bytes=hash.ComputeHash(stream); StringBuilder text=new StringBuilder();
            foreach(byte b in bytes) text.Append(b.ToString("x2"));
            return text.ToString();
        }
    }
    static string Text(Dictionary<string,object> plan,string key) { object value; return plan.TryGetValue(key,out value) && value!=null ? value.ToString() : ""; }
    static Process Start(string root) {
        ProcessStartInfo start=new ProcessStartInfo(Path.Combine(root,"AudioTranslate.exe"));
        start.WorkingDirectory=root; start.UseShellExecute=false;
        return Process.Start(start);
    }
    static void SetRegisteredVersion(string version) {
        try {
            using(RegistryKey key=Registry.CurrentUser.OpenSubKey(UninstallKey,true)) {
                if(key!=null) { key.SetValue("DisplayVersion",version); key.SetValue("InstallDate",DateTime.Now.ToString("yyyyMMdd")); }
            }
        } catch { }
    }
    static string ReadInstalledVersion(string root) {
        try {
            Match m=Regex.Match(File.ReadAllText(Path.Combine(root,"installation.json"),Encoding.UTF8),"\"version\"\\s*:\\s*\"([^\"]+)\"");
            return m.Success?m.Groups[1].Value:"";
        } catch { return ""; }
    }
    static void Record(string data,bool ok,string version,string from,string error) {
        try {
            string folder=Path.Combine(data,"updates"); Directory.CreateDirectory(folder);
            File.WriteAllText(Path.Combine(folder,"last-update.json"),new JavaScriptSerializer().Serialize(new Dictionary<string,object>{
                {"ok",ok},{"version",version},{"from",from},{"error",error??""},{"at",DateTime.UtcNow.ToString("o")}}),new UTF8Encoding(false));
            if(!ok) {
                string path=Path.Combine(folder,"failed-versions.json");
                List<string> failed=new List<string>();
                try { failed.AddRange(new JavaScriptSerializer().Deserialize<string[]>(File.ReadAllText(path,Encoding.UTF8))); } catch { }
                if(!failed.Contains(version)) failed.Add(version);
                File.WriteAllText(path,new JavaScriptSerializer().Serialize(failed.ToArray()),new UTF8Encoding(false));
            }
        } catch { }
    }

    // Puts the old app back. Returns whether it could.
    static bool RollBack(string root,string from) {
        try {
            string app=Path.Combine(root,"app"), old=Path.Combine(root,"app.old");
            if(!Directory.Exists(old)) { Log("rollback: app.old is missing"); return false; }
            StopApp(root);
            Wipe(app);
            Rename(old,app);
            string saved=Path.Combine(app,"_root");
            if(Directory.Exists(saved)) {
                foreach(string file in Directory.GetFiles(saved)) File.Copy(file,Path.Combine(root,Path.GetFileName(file)),true);
                Wipe(saved);
            }
            SetRegisteredVersion(from);
            Log("rolled back to "+from);
            return true;
        } catch(Exception error) { Log("rollback failed: "+error.Message); return false; }
    }

    // The full installer: run it silently, then start the app and wait for it to report ready.
    static int RunInstaller(Dictionary<string,object> plan,string planFile,string root,string data,string package,string expected,string version,string from) {
        try {
            Thread.Sleep(1500);
            StopApp(root);
            if(!File.Exists(package) || !String.Equals(Sha256(package),expected,StringComparison.OrdinalIgnoreCase)) throw new IOException("The installer is missing or does not match its SHA-256");
            ProcessStartInfo start=new ProcessStartInfo(package,"/Q"+(Text(plan,"allow_downgrade")=="True"?" /FORCE":""));
            start.WorkingDirectory=Path.GetDirectoryName(package); start.UseShellExecute=false; start.CreateNoWindow=true;
            // The installer replaces exactly the folder this app runs from, whatever the environment says (the shortcut and the Installed-apps entry
            // already point there; the entry's version is updated below).
            start.EnvironmentVariables["AUDIO_INSTALL_DIR"]=root;
            using(Process installer=Process.Start(start)) {
                if(!installer.WaitForExit(30*60*1000)) { try { installer.Kill(); } catch { } throw new IOException("The installer did not finish"); }
                Log("the installer exited with code "+installer.ExitCode);
                if(installer.ExitCode!=0) throw new IOException("The installer failed (exit code "+installer.ExitCode+"); the installed copy was kept");
            }
            SetRegisteredVersion(version);
            string health=Path.Combine(data,"updates","health.json");
            try { File.Delete(health); } catch { }
            DateTime began=DateTime.UtcNow;
            Process shell=Start(root);
            bool ready=false;
            while((DateTime.UtcNow-began).TotalSeconds<150) {
                Thread.Sleep(500);
                try {
                    if(File.Exists(health)) {
                        Dictionary<string,object> report=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(health,Encoding.UTF8));
                        if(Text(report,"version")==version) { ready=true; break; }
                    }
                } catch { }
                if(shell.HasExited) break;
            }
            // The installer has already replaced the old copy, so there is nothing to roll back to: a new version that does not start is recorded as failed.
            Record(data,ready,version,from,ready?null:"The new version did not report ready");
            try { File.Delete(package); File.Delete(planFile); } catch { }
            return ready?0:1;
        } catch(Exception error) {
            Log("FAILED "+error.GetType().Name+": "+error.Message);
            try { Start(root); } catch { }          // the installer leaves the old copy as it was when it fails
            Record(data,false,version,from,error.Message);
            try { File.Delete(planFile); } catch { }
            return 1;
        }
    }

    [STAThread]
    static int Main(string[] args) {
        if(args.Length<2 || !args[0].Equals("/apply",StringComparison.OrdinalIgnoreCase)) return 2;
        string self=Assembly.GetExecutingAssembly().Location;
        // 1. Run from a temp copy of itself, so that this file in the installation can be replaced like any other.
        if(!Path.GetFileName(self).StartsWith("audio-translate-updater-",StringComparison.OrdinalIgnoreCase)) {
            try {
                string copy=Path.Combine(Path.GetTempPath(),"audio-translate-updater-"+Guid.NewGuid().ToString("N")+".exe");
                File.Copy(self,copy,true);
                ProcessStartInfo start=new ProcessStartInfo(copy,"/apply \""+args[1]+"\"");
                start.UseShellExecute=false; start.CreateNoWindow=true; Process.Start(start);
                return 0;
            } catch { return 2; }
        }
        Dictionary<string,object> plan;
        try { plan=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(args[1],Encoding.UTF8)); } catch { return 2; }
        string root=Text(plan,"install_root"), data=Text(plan,"data"), package=Text(plan,"package"), expected=Text(plan,"sha256"), version=Text(plan,"version"), from=Text(plan,"from_version");
        if(root.Length==0 || data.Length==0 || package.Length==0 || version.Length==0) return 2;
        Directory.CreateDirectory(Path.Combine(data,"updates"));
        log=Path.Combine(data,"updates","updater.log");
        Log("update "+from+" -> "+version+" in "+root);
        if(Text(plan,"kind")=="installer") return RunInstaller(plan,args[1],root,data,package,expected,version,from);
        string app=Path.Combine(root,"app"), old=Path.Combine(root,"app.old");
        bool replaced=false;
        try {
            // 2. The app has quit (the shell started this program as it exited); stop what is left, then check the package.
            Thread.Sleep(1500);
            StopApp(root);
            if(!File.Exists(package) || !String.Equals(Sha256(package),expected,StringComparison.OrdinalIgnoreCase)) throw new IOException("The package is missing or does not match its SHA-256");
            // 3. Swap.
            Wipe(old);
            Rename(app,old); replaced=true;
            string saved=Path.Combine(old,"_root"); Directory.CreateDirectory(saved);
            string rootPrefix=root.TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
            using(ZipArchive archive=ZipFile.OpenRead(package)) {
                foreach(ZipArchiveEntry entry in archive.Entries) {
                    string name=entry.FullName.Replace('/',Path.DirectorySeparatorChar);
                    string first=name.Split(Path.DirectorySeparatorChar)[0];
                    if(first.Equals("runtime",StringComparison.OrdinalIgnoreCase) || first.Equals("providers",StringComparison.OrdinalIgnoreCase)) throw new IOException("The package must not contain "+first);
                    string file=Path.GetFullPath(Path.Combine(root,name));
                    if(!file.StartsWith(rootPrefix,StringComparison.OrdinalIgnoreCase)) throw new IOException("Unsafe path in the package");
                    if(String.IsNullOrEmpty(entry.Name)) { Directory.CreateDirectory(file); continue; }
                    if(name.IndexOf(Path.DirectorySeparatorChar)<0 && File.Exists(file)) File.Copy(file,Path.Combine(saved,entry.Name),true);   // a root file: keep the old one for a rollback
                    Directory.CreateDirectory(Path.GetDirectoryName(file));
                    entry.ExtractToFile(file,true);
                }
            }
            string marker=Path.Combine(root,"installation.json");
            if(File.Exists(marker)) File.Copy(marker,Path.Combine(saved,"installation.json"),true);
            Match product=Regex.Match(File.Exists(marker)?File.ReadAllText(marker,Encoding.UTF8):"","\"product_id\"\\s*:\\s*\"([^\"]+)\"");
            File.WriteAllText(marker,"{\"product_id\":\""+(product.Success?product.Groups[1].Value:"")+"\",\"version\":\""+version+"\",\"installed_at\":\""+DateTime.UtcNow.ToString("o")+"\",\"updated_from\":\""+from+"\"}",new UTF8Encoding(false));
            SetRegisteredVersion(version);
            Log("files replaced; starting the new app");
            // 4. The new app must report ready.
            string health=Path.Combine(data,"updates","health.json");
            try { File.Delete(health); } catch { }
            DateTime began=DateTime.UtcNow;
            Process shell=Start(root);
            bool ready=false;
            while((DateTime.UtcNow-began).TotalSeconds<150) {
                Thread.Sleep(500);
                try {
                    if(File.Exists(health)) {
                        Dictionary<string,object> report=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(health,Encoding.UTF8));
                        if(Text(report,"version")==version) { ready=true; break; }
                    }
                } catch { }
                if(shell.HasExited) { Log("the new app exited with code "+shell.ExitCode+" before it was ready"); break; }
            }
            if(!ready) throw new IOException("The new version did not start");
            Log("the new app is ready");
            Record(data,true,version,from,null);
            try { File.Delete(package); File.Delete(args[1]); } catch { }
            return 0;
        } catch(Exception error) {
            Log("FAILED "+error.GetType().Name+": "+error.Message);
            bool back=replaced ? RollBack(root,from) : true;
            if(back) { try { Start(root); } catch { } }
            Record(data,false,version,from,error.Message);
            try { File.Delete(args[1]); } catch { }
            return 1;
        }
    }
}
