// Windows .NET Framework bootstrap; appended ZIP contains only Product payload.
// Installing again over the same version updates it in place (the running app is stopped first); user data lives outside this folder and is kept.
// Without /Q a small window shows what is happening (stopping the old app, removing it, unpacking with a progress bar, creating the shortcut).
// For tests: AUDIO_INSTALL_LOG=<file> appends "percent|text" for every step, AUDIO_INSTALL_NOWAIT=1 closes the window by itself when done.
using System;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
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
    static string UninstallKey { get { return @"Software\Microsoft\Windows\CurrentVersion\Uninstall\AudioTranslate-"+(Edition.Length>0?Edition+"-":"")+Version; } }
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
    static long SizeOf(string folder) {
        long total=0;
        foreach(string file in Directory.GetFiles(folder,"*",SearchOption.AllDirectories)) { try { total+=new FileInfo(file).Length; } catch { } }
        return total;
    }
    static string MegaBytes(long bytes) { return (bytes/1048576.0).ToString("0", CultureInfo.InvariantCulture) + " MB"; }

    // The installation itself. report(percent, text, detail) may be null (silent). Returns whether this was an update.
    static bool Install(Action<int,string,string> report, bool quiet) {
        if(report == null) report = delegate { };
        string custom=Environment.GetEnvironmentVariable("AUDIO_INSTALL_DIR");
        string target=Path.GetFullPath(String.IsNullOrEmpty(custom)?Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","AudioTranslate",Edition.Length>0?Edition+"-"+Version:Version):custom);
        string marker=Path.Combine(target,"installation.json");
        bool update=File.Exists(marker);
        // Only a folder this installer created (it has the marker) is ever emptied. The user's data is elsewhere (%LOCALAPPDATA%\AudioTranslate).
        if(update) {
            report(-1,T("Đang dừng ứng dụng đang chạy...","Stopping the running app..."),"");
            StopApp(target);
            report(-1,T("Đang gỡ phiên bản cũ (dữ liệu của bạn được giữ lại)...","Removing the previous copy (your data is kept)..."),"");
            Wipe(target);
        }
        string prefix=target.TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
        using(FileStream source=File.OpenRead(Assembly.GetExecutingAssembly().Location)) {
            if(source.Length<16) throw new IOException("Missing payload");
            source.Position=source.Length-16;
            byte[] footer=new byte[16];
            if(source.Read(footer,0,16)!=16 || Encoding.ASCII.GetString(footer,0,8)!="ATSETUP1") throw new IOException("Missing payload");
            long size=BitConverter.ToInt64(footer,8), offset=source.Length-16-size;
            if(size<=0 || offset<=0) throw new IOException("Invalid payload");
            Directory.CreateDirectory(target);
            using(ZipArchive archive=new ZipArchive(new PayloadStream(source,offset,size),ZipArchiveMode.Read)) {
                long total=0, done=0; int files=0, written=0;
                foreach(ZipArchiveEntry entry in archive.Entries) { total+=entry.Length; if(!String.IsNullOrEmpty(entry.Name)) files++; }
                if(total<1) total=1;
                DateTime last=DateTime.MinValue;
                foreach(ZipArchiveEntry entry in archive.Entries) {
                    string file=Path.GetFullPath(Path.Combine(target,entry.FullName.Replace('/',Path.DirectorySeparatorChar)));
                    if(!file.StartsWith(prefix,StringComparison.OrdinalIgnoreCase)) throw new IOException("Unsafe archive path");
                    if(String.IsNullOrEmpty(entry.Name)) { Directory.CreateDirectory(file); continue; }
                    Directory.CreateDirectory(Path.GetDirectoryName(file));
                    using(Stream input=entry.Open()) using(FileStream output=File.Create(file)) {
                        byte[] buffer=new byte[131072]; int read;
                        while((read=input.Read(buffer,0,buffer.Length))>0) {
                            output.Write(buffer,0,read); done+=read;
                            if((DateTime.UtcNow-last).TotalMilliseconds>=120) {
                                last=DateTime.UtcNow;
                                // The unpacking takes the first 95 %; the shortcut and the registry entry are the rest.
                                report((int)(done*95/total),T("Đang giải nén ứng dụng...","Unpacking the app..."),
                                       T("Tệp ","File ")+(written+1)+"/"+files+" - "+MegaBytes(done)+" / "+MegaBytes(total));
                            }
                        }
                    }
                    written++;
                }
                report(95,T("Đang giải nén ứng dụng...","Unpacking the app..."),T("Tệp ","File ")+files+"/"+files+" - "+MegaBytes(total)+" / "+MegaBytes(total));
            }
        }
        if(String.IsNullOrEmpty(custom)) {
            report(96,T("Đang tạo shortcut trong Start menu...","Creating the Start-menu shortcut..."),"");
            object shell=Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
            object shortcut=shell.GetType().InvokeMember("CreateShortcut",BindingFlags.InvokeMethod,null,shell,new object[]{
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs),Title+".lnk")});
            Set(shortcut,"TargetPath",Path.Combine(target,"runtime","python","pythonw.exe"));
            Set(shortcut,"Arguments","\""+Path.Combine(target,"launcher.py")+"\"");
            Set(shortcut,"WorkingDirectory",target);
            Set(shortcut,"IconLocation",Path.Combine(target,"app.ico"));
            shortcut.GetType().InvokeMember("Save",BindingFlags.InvokeMethod,null,shortcut,new object[0]);
            // Windows "Installed apps" entry (per user, so no administrator rights): its Uninstall button runs uninstall.exe from this folder.
            report(98,T("Đang đăng ký vào danh sách ứng dụng của Windows...","Registering with Windows Installed apps..."),"");
            string remover=Path.Combine(target,"uninstall.exe");
            using(RegistryKey key=Registry.CurrentUser.CreateSubKey(UninstallKey)) {
                key.SetValue("DisplayName",Title+" "+Version);
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
        File.WriteAllText(marker,"{\"product_id\":\""+Product+"\",\"version\":\""+Version+"\",\"installed_at\":\""+DateTime.UtcNow.ToString("o")+"\"}",new UTF8Encoding(false));
        report(100,T("Hoàn tất.","Done."),"");
        return update;
    }
    [STAThread]
    static int Main(string[] args) {
        bool quiet=Array.Exists(args,a=>a.Equals("/Q",StringComparison.OrdinalIgnoreCase));
        string log=Environment.GetEnvironmentVariable("AUDIO_INSTALL_LOG");
        Action<int,string,string> record=delegate(int percent,string text,string more) {
            if(!String.IsNullOrEmpty(log)) { try { File.AppendAllText(log,percent+"|"+text+"|"+more+Environment.NewLine,new UTF8Encoding(false)); } catch { } }
        };
        if(quiet) {
            try { Install(record,true); return 0; } catch { return 1; }
        }
        Application.EnableVisualStyles();
        string custom=Environment.GetEnvironmentVariable("AUDIO_INSTALL_DIR");
        ProgressWindow window=new ProgressWindow(T("Cài đặt ","Installing ")+Title+" "+Version,Environment.GetEnvironmentVariable("AUDIO_INSTALL_NOWAIT")=="1");
        int result=1;
        window.Shown += delegate {
            Thread worker=new Thread(delegate() {
                try {
                    bool update=Install(delegate(int percent,string text,string more) { record(percent,text,more); window.Report(percent,text,more); },false);
                    result=0;
                    if(String.IsNullOrEmpty(custom)) {
                        string folder=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","AudioTranslate",Edition.Length>0?Edition+"-"+Version:Version);
                        window.OpenApp=delegate {
                            try {
                                ProcessStartInfo start=new ProcessStartInfo(Path.Combine(folder,"runtime","python","pythonw.exe"),"\""+Path.Combine(folder,"launcher.py")+"\"");
                                start.WorkingDirectory=folder; start.UseShellExecute=false; Process.Start(start);
                            } catch { }
                        };
                    }
                    window.Finish(true,Title+T(update?" đã được cập nhật.":" đã được cài đặt.",update?" was updated.":" was installed."),T("Mở ứng dụng","Open the app"),T("Đóng","Close"));
                } catch(Exception error) {
                    record(-1,"FAILED "+error.GetType().Name,error.Message);
                    window.Finish(false,T("Cài đặt không thành công. Hãy đóng ","Installation failed. Close ")+Title+T(" nếu đang mở, kiểm tra dung lượng ổ đĩa và quyền ghi, rồi chạy lại."," if it is open, check free disk space and write access, then run this again."),"",T("Đóng","Close"));
                }
            });
            worker.IsBackground=true; worker.SetApartmentState(ApartmentState.STA); worker.Start();
        };
        Application.Run(window);
        return result;
    }
}
