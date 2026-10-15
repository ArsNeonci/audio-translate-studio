// Windows .NET Framework bootstrap; appended ZIP contains only Product payload.
// One folder per edition (Programs\AudioTranslate\Plus): installing any newer release replaces the installed one in place, so there is never a
// second copy of the app. The new copy is unpacked beside the old one and swapped in by renames; if anything fails the old copy is untouched.
// Copies left by older installers (Plus-3.0.0, ...) are stopped and removed. A release older than the installed one is refused (/FORCE overrides).
// The running app is stopped first; user data lives outside this folder and is kept.
// /Q installs silently, /RUN starts the app afterwards (used by the app's own update). Exit codes: 0 done, 1 failed, 3 a newer release is installed.
// Without /Q a small window shows what is happening (stopping the old app, removing it, unpacking with a progress bar, creating the shortcut).
// For tests: AUDIO_INSTALL_LOG=<file> appends "percent|text" for every step, AUDIO_INSTALL_NOWAIT=1 closes the window by itself when done,
// AUDIO_INSTALL_PARENT=<folder> replaces Programs\AudioTranslate (the edition folder and the old versioned copies are looked for there) and
// AUDIO_UNINSTALL_ROOT=<registry path under HKCU> replaces the Installed-apps key path, so a test never touches a real installation.
using System;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.Text.RegularExpressions;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

sealed class PayloadStream : Stream {
    readonly Stream source;
    readonly long offset, length;
    long position;
    public PayloadStream(Stream input, long start, long size) { source=input; offset=start; length=size; }
    public override bool CanRead { get { return true; } }
    public override bool CanSeek { get { return true; } }
    public override bool CanWrite { get { return false; } }
    public override long Length { get { return length; } }
    public override long Position { get { return position; } set { Seek(value,SeekOrigin.Begin); } }
    public override int Read(byte[] buffer,int index,int count) {
        source.Position=offset+position;
        int read=source.Read(buffer,index,(int)Math.Min(count,length-position)); position+=read; return read;
    }
    public override long Seek(long value,SeekOrigin origin) {
        long next=origin==SeekOrigin.Begin?value:origin==SeekOrigin.Current?position+value:length+value;
        if(next<0 || next>length) throw new IOException("Invalid archive position");
        position=next; return position;
    }
    public override void Flush() { }
    public override void SetLength(long value) { throw new NotSupportedException(); }
    public override void Write(byte[] buffer,int offset,int count) { throw new NotSupportedException(); }
}

// The installer window. All updates come from the worker thread and are marshalled to the window's thread.
sealed class ProgressWindow : Form {
    readonly Label heading = new Label(), status = new Label(), detail = new Label();
    readonly ProgressBar bar = new ProgressBar();
    readonly Button open = new Button(), close = new Button();
    public Action OpenApp;
    readonly bool autoClose;
    public ProgressWindow(string title, bool autoClose) {
        this.autoClose = autoClose;
        Text = title; FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false; MinimizeBox = false; ControlBox = false;
        StartPosition = FormStartPosition.CenterScreen; ClientSize = new Size(520, 190); Font = new Font("Segoe UI", 9F);
        heading.Text = title; heading.Font = new Font("Segoe UI", 13F, FontStyle.Bold); heading.SetBounds(20, 14, 480, 28);
        status.SetBounds(20, 54, 480, 22);
        bar.SetBounds(20, 82, 480, 22); bar.Minimum = 0; bar.Maximum = 100; bar.Style = ProgressBarStyle.Marquee;
        detail.SetBounds(20, 110, 480, 22); detail.ForeColor = SystemColors.GrayText;
        open.SetBounds(290, 146, 120, 28); open.Visible = false; open.Click += delegate { if(OpenApp != null) OpenApp(); Close(); };
        close.SetBounds(420, 146, 80, 28); close.Visible = false; close.Click += delegate { Close(); };
        Controls.AddRange(new Control[] { heading, status, bar, detail, open, close });
    }
    // percent < 0: a step of unknown length (a moving bar).
    public void Report(int percent, string text, string more) {
        if(InvokeRequired) { try { BeginInvoke(new Action<int,string,string>(Report), percent, text, more); } catch { } return; }
        status.Text = text; detail.Text = more ?? "";
        if(percent < 0) { bar.Style = ProgressBarStyle.Marquee; }
        else { bar.Style = ProgressBarStyle.Continuous; bar.Value = Math.Max(0, Math.Min(100, percent)); }
    }
    public void Finish(bool ok, string message, string openText, string closeText) {
        if(InvokeRequired) { try { BeginInvoke(new Action<bool,string,string,string>(Finish), ok, message, openText, closeText); } catch { } return; }
        bar.Style = ProgressBarStyle.Continuous; bar.Value = ok ? 100 : bar.Value;
        status.Text = message; detail.Text = "";
        status.ForeColor = ok ? Color.FromArgb(20, 110, 50) : Color.FromArgb(170, 30, 30);
        close.Text = closeText; close.Visible = true; close.Focus();
        if(ok && OpenApp != null) { open.Text = openText; open.Visible = true; }
        ControlBox = true;
        if(autoClose) Close();
    }
}

static class Installer {
    const string Version="@@VERSION@@";
    const string Product="@@PRODUCT@@";
    // "Basic"/"Plus"; empty for the legacy single product. Data stays shared across editions.
    const string Edition="@@EDITION@@";
    static readonly bool Vietnamese = CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "vi";
    static string T(string vi, string en) { return Vietnamese ? vi : en; }
    static string Title { get { return Edition.Length>0?"Audio Translate "+Edition:"Audio Translate"; } }
    // One Installed-apps entry per edition (the version is only its DisplayVersion).
    static string UninstallRoot { get { string custom=Environment.GetEnvironmentVariable("AUDIO_UNINSTALL_ROOT"); return String.IsNullOrEmpty(custom)?@"Software\Microsoft\Windows\CurrentVersion\Uninstall":custom; } }
    static string UninstallKey { get { return UninstallRoot+@"\AudioTranslate"+(Edition.Length>0?"-"+Edition:""); } }
    // Where the edition folders live: Programs\AudioTranslate, or AUDIO_INSTALL_PARENT for tests.
    static string ParentFolder { get {
        string custom=Environment.GetEnvironmentVariable("AUDIO_INSTALL_PARENT");
        return Path.GetFullPath(String.IsNullOrEmpty(custom)?Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","AudioTranslate"):custom);
    } }
    static string TargetFolder { get {
        string custom=Environment.GetEnvironmentVariable("AUDIO_INSTALL_DIR");
        return Path.GetFullPath(String.IsNullOrEmpty(custom)?Path.Combine(ParentFolder,Edition.Length>0?Edition:"Standard"):custom);
    } }
    static void Set(object instance,string name,object value) {
        instance.GetType().InvokeMember(name,BindingFlags.SetProperty,null,instance,new object[]{value});
    }
    // Stops every process started from the installation folder (the web server, its workers, llama-server). Two passes: a worker may start another.
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
        // A running program or an open window can hold a file for a moment after it was stopped.
        for(int attempt=0;;attempt++) {
            try { if(Directory.Exists(target)) Directory.Delete(target,true); return; }
            catch { if(attempt>=5) throw; Thread.Sleep(1000); }
        }
    }
    // A folder rename can fail for a moment while Windows still holds a handle (an indexer, an antivirus scan).
    static void Rename(string from,string to) {
        for(int attempt=0;;attempt++) {
            try { Directory.Move(from,to); return; }
            catch { if(attempt>=8) throw; Thread.Sleep(750); }
        }
    }
    static long SizeOf(string folder) {
        long total=0;
        foreach(string file in Directory.GetFiles(folder,"*",SearchOption.AllDirectories)) { try { total+=new FileInfo(file).Length; } catch { } }
        return total;
    }
    static string MegaBytes(long bytes) { return (bytes/1048576.0).ToString("0", CultureInfo.InvariantCulture) + " MB"; }

    // x.y.z -> comparable number; anything else is 0.0.0.
    static long VersionNumber(string text) {
        Match m=Regex.Match(text??"",@"^(\d+)\.(\d+)\.(\d+)$");
        if(!m.Success) return 0;
        return long.Parse(m.Groups[1].Value)*1000000L*1000000L+long.Parse(m.Groups[2].Value)*1000000L+long.Parse(m.Groups[3].Value);
    }
    static string InstalledVersion(string folder) {
        try {
            string text=File.ReadAllText(Path.Combine(folder,"installation.json"),Encoding.UTF8);
            Match m=Regex.Match(text,"\"version\"\\s*:\\s*\"([^\"]+)\"");
            return m.Success?m.Groups[1].Value:null;
        } catch { return null; }
    }
    // Copies made by installers before 3.2.0: one folder per release (Plus-3.0.0, or just 3.0.0 for the single legacy product), each with its own marker.
    static string[] LegacyFolders() {
        string parent=ParentFolder;
        if(!Directory.Exists(parent)) return new string[0];
        Regex name=new Regex(Edition.Length>0?"^"+Regex.Escape(Edition)+@"-\d+\.\d+\.\d+$":@"^\d+\.\d+\.\d+$",RegexOptions.IgnoreCase);
        System.Collections.Generic.List<string> found=new System.Collections.Generic.List<string>();
        foreach(string folder in Directory.GetDirectories(parent))
            if(name.IsMatch(Path.GetFileName(folder)) && File.Exists(Path.Combine(folder,"installation.json"))) found.Add(folder);
        return found.ToArray();
    }

    static bool WebView2Present() {
        const string id="{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}";
        foreach(string path in new string[]{@"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\"+id,@"SOFTWARE\Microsoft\EdgeUpdate\Clients\"+id}) {
            foreach(RegistryKey hive in new RegistryKey[]{Registry.LocalMachine,Registry.CurrentUser}) {
                using(RegistryKey key=hive.OpenSubKey(path)) {
                    string version=key==null?null:key.GetValue("pv") as string;
                    if(!String.IsNullOrEmpty(version) && version!="0.0.0.0") return true;
                }
            }
        }
        return false;
    }

    sealed class NewerInstalled : IOException {
        public readonly string Newer;
        public NewerInstalled(string version) : base("A newer release ("+version+") is installed") { Newer=version; }
    }

    // The installation itself. report(percent, text, detail) may be null (silent). Returns whether this replaced an earlier installation.
    static bool Install(Action<int,string,string> report, bool quiet, bool force) {
        if(report == null) report = delegate { };
        string custom=Environment.GetEnvironmentVariable("AUDIO_INSTALL_DIR");
        string target=TargetFolder;
        string staging=target+".new", backup=target+".old";
        string marker=Path.Combine(target,"installation.json");
        bool replacing=File.Exists(marker);
        // The app window is the Microsoft Edge WebView2 Runtime (built into Windows 11 and current Windows 10). Without it the shortcut would
        // do nothing, so say so now instead of after the install.
        if(String.IsNullOrEmpty(custom) && String.IsNullOrEmpty(Environment.GetEnvironmentVariable("AUDIO_INSTALL_PARENT")) && !WebView2Present()) throw new IOException(T("Thiếu Microsoft Edge WebView2 Runtime. Hãy cài từ https://go.microsoft.com/fwlink/p/?LinkId=2124703 rồi chạy lại bộ cài.","The Microsoft Edge WebView2 Runtime is missing. Install it from https://go.microsoft.com/fwlink/p/?LinkId=2124703 and run this installer again."));
        // Only a folder this installer created (it has the marker) is ever replaced. The user's data is elsewhere (%LOCALAPPDATA%\AudioTranslate).
        if(Directory.Exists(target) && !replacing && Directory.GetFileSystemEntries(target).Length>0) throw new IOException("The folder "+target+" exists and is not an installation of this app.");
        string[] legacy=LegacyFolders();
        // A release older than the one installed is refused: its code does not know the newer data, and the person did not ask for it.
        if(!force) {
            long newest=VersionNumber(InstalledVersion(target));
            string newestText=InstalledVersion(target);
            foreach(string folder in legacy) { long v=VersionNumber(InstalledVersion(folder)); if(v>newest) { newest=v; newestText=InstalledVersion(folder); } }
            if(newest>VersionNumber(Version)) throw new NewerInstalled(newestText);
        }
        // 1. Unpack beside the installed copy. If this fails for any reason (disk full, a damaged installer) the installed copy is untouched.
        Wipe(staging); Wipe(backup);
        string prefix=staging.TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
        try {
            using(FileStream source=File.OpenRead(Assembly.GetExecutingAssembly().Location)) {
                if(source.Length<16) throw new IOException("Missing payload");
                source.Position=source.Length-16;
                byte[] footer=new byte[16];
                if(source.Read(footer,0,16)!=16 || Encoding.ASCII.GetString(footer,0,8)!="ATSETUP1") throw new IOException("Missing payload");
                long size=BitConverter.ToInt64(footer,8), offset=source.Length-16-size;
                if(size<=0 || offset<=0) throw new IOException("Invalid payload");
                Directory.CreateDirectory(staging);
                using(ZipArchive archive=new ZipArchive(new PayloadStream(source,offset,size),ZipArchiveMode.Read)) {
                    long total=0, done=0; int files=0, written=0;
                    foreach(ZipArchiveEntry entry in archive.Entries) { total+=entry.Length; if(!String.IsNullOrEmpty(entry.Name)) files++; }
                    if(total<1) total=1;
                    DateTime last=DateTime.MinValue;
                    foreach(ZipArchiveEntry entry in archive.Entries) {
                        string file=Path.GetFullPath(Path.Combine(staging,entry.FullName.Replace('/',Path.DirectorySeparatorChar)));
                        if(!file.StartsWith(prefix,StringComparison.OrdinalIgnoreCase)) throw new IOException("Unsafe archive path");
                        if(String.IsNullOrEmpty(entry.Name)) { Directory.CreateDirectory(file); continue; }
                        Directory.CreateDirectory(Path.GetDirectoryName(file));
                        using(Stream input=entry.Open()) using(FileStream output=File.Create(file)) {
                            byte[] buffer=new byte[131072]; int read;
                            while((read=input.Read(buffer,0,buffer.Length))>0) {
                                output.Write(buffer,0,read); done+=read;
                                if((DateTime.UtcNow-last).TotalMilliseconds>=120) {
                                    last=DateTime.UtcNow;
                                    // The unpacking takes the first 90 %; the swap, the shortcut and the registry entry are the rest.
                                    report((int)(done*90/total),T("Đang giải nén ứng dụng...","Unpacking the app..."),
                                           T("Tệp ","File ")+(written+1)+"/"+files+" - "+MegaBytes(done)+" / "+MegaBytes(total));
                                }
                            }
                        }
                        written++;
                    }
                    report(90,T("Đang giải nén ứng dụng...","Unpacking the app..."),T("Tệp ","File ")+files+"/"+files+" - "+MegaBytes(total)+" / "+MegaBytes(total));
                }
            }
            File.WriteAllText(Path.Combine(staging,"installation.json"),"{\"product_id\":\""+Product+"\",\"version\":\""+Version+"\",\"installed_at\":\""+DateTime.UtcNow.ToString("o")+"\"}",new UTF8Encoding(false));
        } catch {
            try { Wipe(staging); } catch { }
            throw;
        }
        // 2. Stop the running app and every older copy, then swap by renames: the old folder is kept until the new one is in place.
        report(-1,T("Đang dừng ứng dụng đang chạy...","Stopping the running app..."),"");
        StopApp(target);
        foreach(string folder in legacy) StopApp(folder);
        report(92,T("Đang thay thế phiên bản cũ (dữ liệu của bạn được giữ lại)...","Replacing the previous copy (your data is kept)..."),"");
        bool hadOld=Directory.Exists(target);
        try {
            if(hadOld) Rename(target,backup);
            Rename(staging,target);
        } catch {
            // Put the old copy back; the person keeps a working app.
            try { if(!Directory.Exists(target) && Directory.Exists(backup)) Rename(backup,target); } catch { }
            try { Wipe(staging); } catch { }
            throw;
        }
        try { Wipe(backup); } catch { }
        // 3. Old versioned copies (Plus-3.0.0, ...) and their Installed-apps entries.
        foreach(string folder in legacy) {
            string old=InstalledVersion(folder);
            try { Wipe(folder); } catch { }
            try { Registry.CurrentUser.DeleteSubKeyTree(UninstallRoot+@"\AudioTranslate-"+(Edition.Length>0?Edition+"-":"")+old,false); } catch { }
        }
        if(String.IsNullOrEmpty(custom) && String.IsNullOrEmpty(Environment.GetEnvironmentVariable("AUDIO_INSTALL_PARENT"))) {
            report(96,T("Đang tạo shortcut trong Start menu...","Creating the Start-menu shortcut..."),"");
            object shell=Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
            object shortcut=shell.GetType().InvokeMember("CreateShortcut",BindingFlags.InvokeMethod,null,shell,new object[]{
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs),Title+".lnk")});
            Set(shortcut,"TargetPath",Path.Combine(target,"AudioTranslate.exe"));
            Set(shortcut,"WorkingDirectory",target);
            Set(shortcut,"IconLocation",Path.Combine(target,"app.ico"));
            shortcut.GetType().InvokeMember("Save",BindingFlags.InvokeMethod,null,shortcut,new object[0]);
        }
        // Windows "Installed apps" entry (per user, so no administrator rights): its Uninstall button runs uninstall.exe from this folder.
        // Skipped for a custom install folder (tests) unless a test registry path was given.
        if((String.IsNullOrEmpty(custom) && String.IsNullOrEmpty(Environment.GetEnvironmentVariable("AUDIO_INSTALL_PARENT"))) || !String.IsNullOrEmpty(Environment.GetEnvironmentVariable("AUDIO_UNINSTALL_ROOT"))) {
            report(98,T("Đang đăng ký vào danh sách ứng dụng của Windows...","Registering with Windows Installed apps..."),"");
            string remover=Path.Combine(target,"uninstall.exe");
            using(RegistryKey key=Registry.CurrentUser.CreateSubKey(UninstallKey)) {
                key.SetValue("DisplayName",Title);
                key.SetValue("DisplayVersion",Version);
                key.SetValue("Publisher","Ars Neonci");
                key.SetValue("InstallLocation",target);
                key.SetValue("DisplayIcon",Path.Combine(target,"app.ico"));
                key.SetValue("UninstallString","\""+remover+"\"");
                key.SetValue("QuietUninstallString","\""+remover+"\" /Q");
                key.SetValue("InstallDate",DateTime.Now.ToString("yyyyMMdd"));
                key.SetValue("EstimatedSize",(int)Math.Min(int.MaxValue,SizeOf(target)/1024),RegistryValueKind.DWord);
                key.SetValue("NoModify",1,RegistryValueKind.DWord);
                key.SetValue("NoRepair",1,RegistryValueKind.DWord);
            }
        }
        report(100,T("Hoàn tất.","Done."),"");
        return replacing || legacy.Length>0;
    }
    static void StartApp(string folder) {
        try {
            ProcessStartInfo start=new ProcessStartInfo(Path.Combine(folder,"AudioTranslate.exe"));
            start.WorkingDirectory=folder; start.UseShellExecute=false; Process.Start(start);
        } catch { }
    }
    [STAThread]
    static int Main(string[] args) {
        bool quiet=Array.Exists(args,a=>a.Equals("/Q",StringComparison.OrdinalIgnoreCase));
        bool run=Array.Exists(args,a=>a.Equals("/RUN",StringComparison.OrdinalIgnoreCase));
        bool force=Array.Exists(args,a=>a.Equals("/FORCE",StringComparison.OrdinalIgnoreCase)) || Environment.GetEnvironmentVariable("AUDIO_ALLOW_DOWNGRADE")=="1";
        string log=Environment.GetEnvironmentVariable("AUDIO_INSTALL_LOG");
        Action<int,string,string> record=delegate(int percent,string text,string more) {
            if(!String.IsNullOrEmpty(log)) { try { File.AppendAllText(log,percent+"|"+text+"|"+more+Environment.NewLine,new UTF8Encoding(false)); } catch { } }
        };
        if(quiet) {
            try { Install(record,true,force); if(run) StartApp(TargetFolder); return 0; }
            catch(NewerInstalled error) { record(-1,"REFUSED NewerInstalled",error.Message); return 3; }
            catch(Exception error) { record(-1,"FAILED "+error.GetType().Name,error.Message); return 1; }
        }
        Application.EnableVisualStyles();
        ProgressWindow window=new ProgressWindow(T("Cài đặt ","Installing ")+Title+" "+Version,Environment.GetEnvironmentVariable("AUDIO_INSTALL_NOWAIT")=="1");
        int result=1;
        window.Shown += delegate {
            Thread worker=new Thread(delegate() {
                try {
                    bool update=Install(delegate(int percent,string text,string more) { record(percent,text,more); window.Report(percent,text,more); },false,force);
                    result=0;
                    string folder=TargetFolder;
                    window.OpenApp=delegate { StartApp(folder); };
                    if(run) StartApp(folder);
                    window.Finish(true,Title+T(update?" đã được cập nhật lên "+Version+".":" đã được cài đặt."," "+(update?"was updated to "+Version+".":"was installed.")),T("Mở ứng dụng","Open the app"),T("Đóng","Close"));
                } catch(NewerInstalled error) {
                    result=3; record(-1,"REFUSED NewerInstalled",error.Message);
                    window.Finish(false,T("Đã cài một bản mới hơn ("+error.Newer+"). Bộ cài này không thay thế bản mới hơn.","A newer release is already installed ("+error.Newer+"). This installer does not replace it."),"",T("Đóng","Close"));
                } catch(Exception error) {
                    record(-1,"FAILED "+error.GetType().Name,error.Message);
                    window.Finish(false,T("Cài đặt không thành công (bản cũ vẫn được giữ nguyên). Hãy đóng ","Installation failed (the previous copy was kept). Close ")+Title+T(" nếu đang mở, kiểm tra dung lượng ổ đĩa và quyền ghi, rồi chạy lại."," if it is open, check free disk space and write access, then run this again."),"",T("Đóng","Close"));
                }
            });
            worker.IsBackground=true; worker.SetApartmentState(ApartmentState.STA); worker.Start();
        };
        Application.Run(window);
        return result;
    }
}
