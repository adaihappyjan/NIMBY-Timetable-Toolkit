// Windows GUI launcher. No system Python, shell, elevation or PATH changes.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal static class NoviceLauncher {
    private const string RuntimeHash = "@@RUNTIME_SHA256@@";
    private static string Hash(string path) {
        using(var sha=SHA256.Create()) using(var file=File.OpenRead(path))
            return BitConverter.ToString(sha.ComputeHash(file)).Replace("-", "").ToLowerInvariant();
    }
    private static string Child(string root,string relative) {
        if(String.IsNullOrEmpty(relative)||relative.Contains(":")||relative.Contains("\\")||relative.StartsWith("/"))throw new IOException("Invalid runtime path / 运行库路径无效");
        foreach(var part in relative.Split('/'))if(part=="."||part==".."||part.Length==0)throw new IOException("Runtime path escapes its directory / 运行库路径越界");
        var path=Path.GetFullPath(Path.Combine(root,relative.Replace('/',Path.DirectorySeparatorChar)));
        if(!path.StartsWith(Path.GetFullPath(root)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new IOException("Runtime path escapes its directory / 运行库路径越界");
        // Do not follow a cache directory redirected through a junction/symlink.
        for(var parent=new DirectoryInfo(Path.GetDirectoryName(path));parent!=null;parent=parent.Parent)
            if(parent.Exists&&(parent.Attributes&FileAttributes.ReparsePoint)!=0)throw new IOException("Runtime directories cannot be symlinks or junctions / 运行库目录不能是链接");
        return path;
    }
    private static bool Valid(string root,Dictionary<string,string> files) {
        foreach(var pair in files) {
            var path=Child(root,pair.Key);
            if(!File.Exists(path)||(File.GetAttributes(path)&FileAttributes.ReparsePoint)!=0||Hash(path)!=pair.Value)return false;
        }
        return true;
    }
    private static string Prepare(string app) {
        var archive=Path.Combine(app,"runtime","runtime.zip");
        if(!File.Exists(archive))throw new IOException("Missing runtime\\runtime.zip. Extract the entire ZIP, not just the EXE. / 请完整解压安装包。");
        if(Hash(archive)!=RuntimeHash)throw new IOException("Runtime verification failed. Download a complete official release. / 运行库校验失败，请重新下载完整官方包。");
        var parent=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"NIMBY_Timetable_Toolkit","runtimes");
        var cache=Path.Combine(parent,RuntimeHash);
        Directory.CreateDirectory(parent);
        using(var mutex=new Mutex(false,"Local\\NIMBY-Runtime-"+RuntimeHash)) {
            bool owned=false;
            try {
                try{owned=mutex.WaitOne(TimeSpan.FromSeconds(90));}catch(AbandonedMutexException){owned=true;}
                if(!owned)throw new IOException("Another instance is preparing the runtime. Retry shortly. / 另一窗口正在准备运行库，请稍后重试。");
                using(var zip=ZipFile.OpenRead(archive)) {
                    var entry=zip.GetEntry("runtime-manifest.json");
                    if(entry==null||entry.Length>2000000)throw new IOException("Missing runtime manifest / 运行库清单缺失");
                    Dictionary<string,string> files;
                    using(var reader=new StreamReader(entry.Open(),Encoding.UTF8))files=new JavaScriptSerializer().Deserialize<Dictionary<string,string>>(reader.ReadToEnd());
                    if(files.Count>5000||!files.ContainsKey("python/pythonw.exe")||!files.ContainsKey("node.exe"))throw new IOException("Incomplete runtime manifest / 运行库清单不完整");
                    if(Directory.Exists(cache)&&Valid(cache,files))return cache;
                    // Preserve incomplete/damaged caches for diagnosis, never recursive-delete.
                    if(Directory.Exists(cache))cache=Path.Combine(parent,RuntimeHash+"-"+Guid.NewGuid().ToString("N"));
                    Directory.CreateDirectory(cache);
                    long total=0;
                    foreach(var pair in files) {
                        var item=zip.GetEntry(pair.Key);
                        if(item==null||(total+=item.Length)>300000000)throw new IOException("Invalid runtime size / 运行库大小无效");
                        var target=Child(cache,pair.Key);Directory.CreateDirectory(Path.GetDirectoryName(target));
                        using(var src=item.Open())using(var dst=new FileStream(target,FileMode.CreateNew))src.CopyTo(dst);
                    }
                    if(!Valid(cache,files))throw new IOException("Extracted runtime verification failed. Check disk space. / 解压校验失败，请检查磁盘空间。");
                    return cache;
                }
            } finally {if(owned)mutex.ReleaseMutex();}
        }
    }
    // Windows paths cannot contain quotes; trailing slash is doubled for argv.
    private static string Quote(string value){return "\""+value.TrimEnd('\\')+"\"";}
    [STAThread] private static int Main(string[] args) {
        string report=null;bool selfTest=false;
        try {
            for(int i=0;i<args.Length;i++) {
                if(args[i]=="--self-test")selfTest=true;
                else if(args[i]=="--report"&&i+1<args.Length)report=Path.GetFullPath(args[++i]);
                else throw new ArgumentException("Unsupported launch argument / 不支持的启动参数");
            }
            if(!Environment.Is64BitOperatingSystem)throw new IOException("This package requires Windows 10/11 x64. / 需要 64 位 Windows。");
            var app=AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
            if(!File.Exists(Path.Combine(app,"toolkit_start.py")))throw new IOException("Missing application files. Extract the entire ZIP. / 程序文件缺失，请完整解压。");
            var cache=Prepare(app);
            var command=Quote(Path.Combine(app,"toolkit_start.py"));
#if DIAGNOSTIC
            command+=" --diagnose";
#endif
            if(selfTest)command+=" --self-test";
            if(report!=null)command+=" --report "+Quote(report);
            var start=new ProcessStartInfo(Path.Combine(cache,"python","pythonw.exe"),command);
            start.WorkingDirectory=app;start.UseShellExecute=false;start.CreateNoWindow=true;start.WindowStyle=ProcessWindowStyle.Hidden;
            start.EnvironmentVariables["NIMBY_TOOLKIT_RUNTIME"]=cache;
            start.EnvironmentVariables.Remove("PYTHONHOME");start.EnvironmentVariables.Remove("PYTHONPATH");
            using(var child=Process.Start(start)) {
                if(selfTest) {if(!child.WaitForExit(60000)){child.Kill();throw new IOException("Startup self-test exceeded 60 seconds / 启动自检超时");}return child.ExitCode;}
            }
            return 0;
        } catch(Exception error) {
            if(selfTest&&report!=null)File.WriteAllText(report,"Launcher error: "+error,Encoding.UTF8);
            else MessageBox.Show("The toolkit could not start / 工具箱无法启动：\n\n"+error.Message+"\n\nRead START HERE.txt / 先看这里.txt. Do not disable system security.","NIMBY Timetable Toolkit",MessageBoxButtons.OK,MessageBoxIcon.Error);
            return 1;
        }
    }
}
