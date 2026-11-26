using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Reflection;
using System.Collections.Generic;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal static class TrendDesk {
    const string Url = "http://127.0.0.1:8765";
    static readonly string UserId = WindowsIdentity.GetCurrent().User.Value;
    static readonly string StopName = @"Local\TrendDesk.Stop." + UserId;
    static readonly string Profile = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "TrendDesk");

    sealed class Health { public string app { get; set; } public int pid { get; set; } }
    static int ServicePid() {
        try {
            var req = (HttpWebRequest)WebRequest.Create(Url + "/api/health");
            req.Proxy = null; req.Timeout = 600; req.ReadWriteTimeout = 600; req.AllowAutoRedirect = false;
            using (var response = req.GetResponse())
            using (var reader = new StreamReader(response.GetResponseStream())) {
                var health = new JavaScriptSerializer().Deserialize<Health>(reader.ReadToEnd());
                return health != null && health.app == "trenddesk" ? health.pid : 0;
            }
        } catch (Exception) { return 0; }
    }
    static void OpenPage() { Process.Start(new ProcessStartInfo(Url) { UseShellExecute = true }); }
    static bool StartCachedRelease(bool quiet) {
        string cache = Path.Combine(Profile, "versions");
        if (!Directory.Exists(cache)) return false;
        Version current = Assembly.GetExecutingAssembly().GetName().Version;
        var candidates = new SortedList<Version, string>();
        foreach (string directory in Directory.GetDirectories(cache)) {
            Version tag;
            if (!Version.TryParse(Path.GetFileName(directory), out tag) || tag.Build < 0 || tag.Revision >= 0) continue;
            var version = new Version(tag.Major, tag.Minor, tag.Build, 0);
            if (version <= current) continue;
            string exe = Path.Combine(directory, "TrendDesk.exe");
            try {
                if (AssemblyName.GetAssemblyName(exe).Version == version) candidates[version] = exe;
            } catch (IOException) {} catch (BadImageFormatException) {}
        }
        for (int i = candidates.Count - 1; i >= 0; i--) {
            var info = new ProcessStartInfo(candidates.Values[i], "--cached-release" + (quiet ? " --no-browser" : "")) {
                UseShellExecute = false, WorkingDirectory = Path.GetDirectoryName(candidates.Values[i])
            };
            try {
                using (var next = Process.Start(info)) {
                    while (!next.WaitForExit(250)) {
                        if (ServicePid() > 0) return true;
                    }
                    if (next.ExitCode == 0) return true;
                }
            } catch (System.ComponentModel.Win32Exception) {}
        }
        return false;
    }
    static string DataFolder() {
        string config = Path.Combine(Profile, "data-location.txt");
        if (!File.Exists(config)) return Path.Combine(Profile, "data");
        string location = File.ReadAllText(config, Encoding.UTF8).Trim();
        if (!Path.IsPathRooted(location) || !Directory.Exists(location))
            throw new IOException("原数据目录无法访问，请检查 " + config);
        return location;
    }
    [STAThread]
    static int Main(string[] args) {
        bool quiet = Array.IndexOf(args, "--no-browser") >= 0;
        bool dispatched = Array.IndexOf(args, "--cached-release") >= 0;
        try {
            if (Array.IndexOf(args, "--stop") >= 0) {
                EventWaitHandle handle;
                if (!EventWaitHandle.TryOpenExisting(StopName, out handle)) return 0;
                using (handle) handle.Set();
                return 0;
            }
            Application.EnableVisualStyles();
            if (!dispatched && ServicePid() == 0 && StartCachedRelease(quiet)) return 0;
            bool owner;
            using (var mutex = new Mutex(true, @"Local\TrendDesk.Start." + UserId, out owner)) {
                if (!owner || ServicePid() > 0) {
                    for (int i = 0; i < 120; i++) {
                        if (ServicePid() > 0) { if (!quiet) OpenPage(); return 0; }
                        Thread.Sleep(250);
                    }
                    throw new IOException("已有启动进程，但本地服务未就绪。");
                }
                string root = AppDomain.CurrentDomain.BaseDirectory;
                string data = DataFolder();
                Directory.CreateDirectory(data);
                string logPath = Path.Combine(data, "desktop-server.log");
                if (File.Exists(logPath) && new FileInfo(logPath).Length > 5*1024*1024)
                    File.Copy(logPath, logPath + ".previous", true);
                using (var stop = new EventWaitHandle(false, EventResetMode.ManualReset, StopName))
                using (var log = new StreamWriter(logPath, new FileInfo(logPath).Exists && new FileInfo(logPath).Length <= 5*1024*1024, Encoding.UTF8))
                using (var child = new Process()) {
                    log.AutoFlush = true;
                    var write = TextWriter.Synchronized(log);
                    var info = new ProcessStartInfo(Path.Combine(root, "runtime", "python.exe"), "-I -B -X utf8 desktop_server.py");
                    info.WorkingDirectory = Path.Combine(root, "program");
                    info.EnvironmentVariables["TRENDDESK_DATA_DIR"] = data;
                    info.UseShellExecute = false; info.CreateNoWindow = true;
                    info.RedirectStandardInput = info.RedirectStandardOutput = info.RedirectStandardError = true;
                    info.StandardOutputEncoding = info.StandardErrorEncoding = Encoding.UTF8;
                    child.StartInfo = info;
                    DataReceivedEventHandler sink = (s,e) => { if(e.Data != null) write.WriteLine(e.Data); };
                    child.OutputDataReceived += sink; child.ErrorDataReceived += sink;
                    child.Start(); child.BeginOutputReadLine(); child.BeginErrorReadLine();
                    try {
                        var elapsed = Stopwatch.StartNew();
                        while (ServicePid() != child.Id) {
                            if (child.HasExited || elapsed.Elapsed.TotalSeconds > 45)
                                throw new IOException("后台启动失败。请检查 8765 端口和日志：" + logPath);
                            if (stop.WaitOne(200)) return 0;
                        }
                        using (var menu = new ContextMenuStrip())
                        using (var icon = new NotifyIcon())
                        using (var timer = new System.Windows.Forms.Timer()) {
                            menu.Items.Add("打开工作台", null, (s,e) => OpenPage());
                            menu.Items.Add("退出并停止服务", null, (s,e) => Application.ExitThread());
                            icon.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
                            icon.Text = "TrendDesk · 美股工作台"; icon.ContextMenuStrip = menu;
                            icon.DoubleClick += (s,e) => OpenPage(); icon.Visible = true;
                            timer.Interval = 500;
                            timer.Tick += (s,e) => { if (stop.WaitOne(0) || child.HasExited) Application.ExitThread(); };
                            timer.Start();
                            if (!quiet) OpenPage();
                            Application.Run();
                            icon.Visible = false;
                            if (child.HasExited && child.ExitCode != 0)
                                throw new IOException("本机服务意外退出。日志：" + logPath);
                        }
                    } finally {
                        child.StandardInput.Close();
                        if (!child.WaitForExit(20000)) child.Kill();
                        child.WaitForExit();
                    }
                }
            }
            return 0;
        } catch (Exception ex) {
            if (!quiet && !dispatched) MessageBox.Show(ex.Message, "TrendDesk", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
