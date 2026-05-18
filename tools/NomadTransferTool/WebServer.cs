using System;
using System.IO;
using System.Net;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json;
using System.Linq;

namespace NomadTransferTool
{
    public class WebServer
    {
        private readonly HttpListener _listener;
        private readonly MainWindow _mainWindow;
        private bool _isRunning;

        public WebServer(MainWindow mainWindow)
        {
            _mainWindow = mainWindow;
            _listener = new HttpListener();
            // Bind to all network interfaces on port 8080
            _listener.Prefixes.Add("http://+:8080/");
        }

        public void Start()
        {
            try
            {
                _listener.Start();
                _isRunning = true;
                Task.Run(ListenLoop);

                string localIp = "localhost";
                try
                {
                    using (System.Net.Sockets.Socket socket = new System.Net.Sockets.Socket(System.Net.Sockets.AddressFamily.InterNetwork, System.Net.Sockets.SocketType.Dgram, 0))
                    {
                        socket.Connect("8.8.8.8", 65530);
                        var endPoint = socket.LocalEndPoint as IPEndPoint;
                        localIp = endPoint?.Address.ToString() ?? "localhost";
                    }
                }
                catch { }

                _mainWindow.Dispatcher.Invoke(() => _mainWindow.AddLog($"Mobile Web UI is live at: http://{localIp}:8080/"));
            }
            catch (Exception ex)
            {
                _mainWindow.Dispatcher.Invoke(() => _mainWindow.AddLog($"Failed to start Web UI: {ex.Message}. Try running as Administrator."));
            }
        }

        public void Stop()
        {
            _isRunning = false;
            _listener.Stop();
        }

        private async Task ListenLoop()
        {
            while (_isRunning)
            {
                try
                {
                    var context = await _listener.GetContextAsync();
                    _ = Task.Run(() => HandleRequest(context));
                }
                catch
                {
                    // Listener stopped or error
                }
            }
        }

        private async Task HandleRequest(HttpListenerContext context)
        {
            var req = context.Request;
            var res = context.Response;

            res.AppendHeader("Access-Control-Allow-Origin", "*");
            res.AppendHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
            res.AppendHeader("Access-Control-Allow-Headers", "Content-Type");

            if (req.HttpMethod == "OPTIONS")
            {
                res.StatusCode = 200;
                res.Close();
                return;
            }

            try
            {
                if (req.Url!.AbsolutePath == "/")
                {
                    await ServeHtml(res);
                }
                else if (req.Url.AbsolutePath == "/api/status")
                {
                    await ServeStatus(res);
                }
                else if (req.Url.AbsolutePath == "/api/queue/start" && req.HttpMethod == "POST")
                {
                    _mainWindow.Dispatcher.Invoke(() => _mainWindow.StartProcessingCommand());
                    await SendJson(res, new { success = true });
                }
                else if (req.Url.AbsolutePath == "/api/queue/stop" && req.HttpMethod == "POST")
                {
                    _mainWindow.Dispatcher.Invoke(() => _mainWindow.StopProcessingCommand());
                    await SendJson(res, new { success = true });
                }
                else
                {
                    res.StatusCode = 404;
                    await SendJson(res, new { error = "Not found" });
                }
            }
            catch (Exception ex)
            {
                res.StatusCode = 500;
                await SendJson(res, new { error = ex.Message });
            }
        }

        private async Task ServeStatus(HttpListenerResponse res)
        {
            object status = null!;
            _mainWindow.Dispatcher.Invoke(() =>
            {
                status = new
                {
                    isTransferring = _mainWindow.IsTransferring,
                    currentStatus = _mainWindow.CurrentStatus,
                    transferSpeed = _mainWindow.TransferSpeed,
                    fileProgress = _mainWindow.FileProgress,
                    totalProgress = _mainWindow.TotalProgress,
                    currentFileProgress = _mainWindow.CurrentFileProgress,
                    reviewQueue = _mainWindow.ReviewQueue.Select(x => new { title = x.Title, year = x.Year, category = x.Category }).ToList(),
                    activeDownloads = _mainWindow.DebridActiveDownloads.Select(x => new { file = x.FileName, progress = x.Progress }).ToList()
                };
            });

            await SendJson(res, status);
        }

        private async Task SendJson(HttpListenerResponse res, object data)
        {
            res.ContentType = "application/json";
            var json = JsonConvert.SerializeObject(data);
            var bytes = Encoding.UTF8.GetBytes(json);
            res.ContentLength64 = bytes.Length;
            await res.OutputStream.WriteAsync(bytes, 0, bytes.Length);
            res.Close();
        }

        private async Task ServeHtml(HttpListenerResponse res)
        {
            res.ContentType = "text/html";
            var html = @"<!DOCTYPE html>
<html lang='en'>
<head>
    <meta charset='UTF-8'>
    <meta name='viewport' content='width=device-width, initial-scale=1.0'>
    <title>Nomad Transfer Web UI</title>
    <style>
        body { font-family: -apple-system, system-ui, sans-serif; background: #0D0D0D; color: white; margin: 0; padding: 20px; }
        .card { background: #1E1E1E; border: 1px solid #303030; border-radius: 8px; padding: 15px; margin-bottom: 20px; }
        .header { color: #FF4081; font-weight: bold; margin-top: 0; }
        button { background: #FF4081; color: white; border: none; padding: 10px 15px; border-radius: 4px; font-weight: bold; cursor: pointer; width: 100%; margin-bottom: 10px; }
        button.danger { background: #f44336; }
        .progress-bar { background: #333; height: 10px; border-radius: 5px; overflow: hidden; margin-top: 5px; }
        .progress-fill { background: #FF4081; height: 100%; transition: width 0.3s; }
        .text-sm { font-size: 12px; color: #B0B0B0; }
    </style>
</head>
<body>
    <h2 style='text-align:center; color:#FF4081;'>Nomad Transfer Tool</h2>
    
    <div class='card' id='transfer-card'>
        <h3 class='header'>Transfer Status</h3>
        <div id='status-text' style='margin-bottom: 10px; font-weight:bold;'>Idle</div>
        <div class='text-sm' id='file-text'></div>
        <div class='progress-bar'><div id='file-progress' class='progress-fill' style='width:0%'></div></div>
        
        <div style='display:flex; gap:10px; margin-top: 15px;'>
            <button id='btn-start' onclick='startQueue()'>Start Transfer</button>
            <button id='btn-stop' class='danger' onclick='stopQueue()' style='display:none;'>Stop</button>
        </div>
    </div>

    <div class='card'>
        <h3 class='header'>Queue (<span id='queue-count'>0</span>)</h3>
        <div id='queue-list' class='text-sm'></div>
    </div>

    <div class='card'>
        <h3 class='header'>Active Debrid Downloads</h3>
        <div id='downloads-list' class='text-sm'>None</div>
    </div>

    <script>
        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                
                document.getElementById('status-text').innerText = data.isTransferring ? data.currentStatus : 'Idle';
                document.getElementById('file-text').innerText = data.isTransferring ? data.fileProgress : '';
                document.getElementById('file-progress').style.width = data.currentFileProgress + '%';
                
                document.getElementById('btn-start').style.display = data.isTransferring ? 'none' : 'block';
                document.getElementById('btn-stop').style.display = data.isTransferring ? 'block' : 'none';

                document.getElementById('queue-count').innerText = data.reviewQueue.length;
                document.getElementById('queue-list').innerHTML = data.reviewQueue.map(q => `<div>• ${q.title} (${q.year})</div>`).join('') || 'Empty';

                document.getElementById('downloads-list').innerHTML = data.activeDownloads.map(d => `<div>• ${d.file} - <span style='color:#4caf50'>${d.progress}</span></div>`).join('') || 'None';

            } catch (e) {
                console.error(e);
            }
        }

        async function startQueue() { await fetch('/api/queue/start', {method:'POST'}); fetchStatus(); }
        async function stopQueue() { await fetch('/api/queue/stop', {method:'POST'}); fetchStatus(); }

        setInterval(fetchStatus, 1000);
        fetchStatus();
    </script>
</body>
</html>";
            var bytes = Encoding.UTF8.GetBytes(html);
            res.ContentLength64 = bytes.Length;
            await res.OutputStream.WriteAsync(bytes, 0, bytes.Length);
            res.Close();
        }
    }
}