// Windows .NET Framework bootstrap; appended ZIP contains only Product payload.
// Installing again over the same version updates it in place (the running app is stopped first); user data lives outside this folder and is kept.
using System;
using System.Diagnostics;
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

static class Installer {
    const string Version="@@VERSION@@";
    const string Product="@@PRODUCT@@";
    // "Basic"/"Plus"; empty for the legacy single product. Data stays shared across editions.
    const string Edition="@@EDITION@@";
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
    [STAThread]
    static int Main(string[] args) {
        bool quiet=Array.Exists(args,a=>a.Equals("/Q",StringComparison.OrdinalIgnoreCase));
        try {
            string custom=Environment.GetEnvironmentVariable("AUDIO_INSTALL_DIR");
            string target=Path.GetFullPath(String.IsNullOrEmpty(custom)?Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","AudioTranslate",Edition.Length>0?Edition+"-"+Version:Version):custom);
            string marker=Path.Combine(target,"installation.json");
            bool update=File.Exists(marker);
            // Only a folder this installer created (it has the marker) is ever emptied. The user's data is elsewhere (%LOCALAPPDATA%\AudioTranslate).
            if(update) { StopApp(target); Wipe(target); }
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
                    foreach(ZipArchiveEntry entry in archive.Entries) {
                        string file=Path.GetFullPath(Path.Combine(target,entry.FullName.Replace('/',Path.DirectorySeparatorChar)));
                        if(!file.StartsWith(prefix,StringComparison.OrdinalIgnoreCase)) throw new IOException("Unsafe archive path");
                        if(String.IsNullOrEmpty(entry.Name)) { Directory.CreateDirectory(file); continue; }
                        Directory.CreateDirectory(Path.GetDirectoryName(file));
                        using(Stream input=entry.Open()) using(FileStream output=File.Create(file)) input.CopyTo(output,131072);
                    }
                }
            }
            if(String.IsNullOrEmpty(custom)) {
                object shell=Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
                object shortcut=shell.GetType().InvokeMember("CreateShortcut",BindingFlags.InvokeMethod,null,shell,new object[]{
                    Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs),Title+".lnk")});
                Set(shortcut,"TargetPath",Path.Combine(target,"runtime","python","pythonw.exe"));
                Set(shortcut,"Arguments","\""+Path.Combine(target,"launcher.py")+"\"");
                Set(shortcut,"WorkingDirectory",target);
                Set(shortcut,"IconLocation",Path.Combine(target,"app.ico"));
                shortcut.GetType().InvokeMember("Save",BindingFlags.InvokeMethod,null,shortcut,new object[0]);
                // Windows "Installed apps" entry (per user, so no administrator rights): its Uninstall button runs uninstall.exe from this folder.
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
            if(!quiet) MessageBox.Show(Title+(update?" updated. ":" installed. ")+"Open "+Title+" from the Start menu.",Title);
            return 0;
        } catch {
            if(!quiet) MessageBox.Show("Installation failed. Close "+Title+" if it is open, then check free disk space and write access to the install directory.",Title);
            return 1;
        }
    }
}
