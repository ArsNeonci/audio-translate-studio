// Windows .NET Framework bootstrap; appended ZIP contains only Product payload.
using System;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

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
    static void Set(object instance,string name,object value) {
        instance.GetType().InvokeMember(name,BindingFlags.SetProperty,null,instance,new object[]{value});
    }
    [STAThread]
    static int Main(string[] args) {
        bool quiet=Array.Exists(args,a=>a.Equals("/Q",StringComparison.OrdinalIgnoreCase));
        try {
            string custom=Environment.GetEnvironmentVariable("AUDIO_INSTALL_DIR");
            string target=Path.GetFullPath(String.IsNullOrEmpty(custom)?Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","AudioTranslate",Version):custom);
            string marker=Path.Combine(target,"installation.json");
            if(File.Exists(marker)) return 0;
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
                    Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs),"Audio Translate.lnk")});
                Set(shortcut,"TargetPath",Path.Combine(target,"runtime","python","pythonw.exe"));
                Set(shortcut,"Arguments","\""+Path.Combine(target,"launcher.py")+"\"");
                Set(shortcut,"WorkingDirectory",target);
                shortcut.GetType().InvokeMember("Save",BindingFlags.InvokeMethod,null,shortcut,new object[0]);
            }
            File.WriteAllText(marker,"{\"product_id\":\"audio-translate\",\"version\":\""+Version+"\",\"installed_at\":\""+DateTime.UtcNow.ToString("o")+"\"}",new UTF8Encoding(false));
            if(!quiet) MessageBox.Show("Audio Translate installed. Open Audio Translate from the Start menu.","Audio Translate");
            return 0;
        } catch {
            if(!quiet) MessageBox.Show("Installation failed. Check available disk space and write access to the install directory.","Audio Translate");
            return 1;
        }
    }
}
