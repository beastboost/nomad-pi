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
                else if (req.Url.AbsolutePath == "/api/debrid/search" && req.HttpMethod == "GET")
                {
                    var q = req.QueryString["q"];
                    if (!string.IsNullOrEmpty(q)) _mainWindow.DebridSearchTitlesCommand(q);
                    await SendJson(res, new { success = true });
                }
                else if (req.Url.AbsolutePath == "/api/debrid/torrents" && req.HttpMethod == "GET")
                {
                    var imdbId = req.QueryString["imdb_id"] ?? "";
                    var type = req.QueryString["type"] ?? "movie";
                    var season = req.QueryString["season"] ?? "1";
                    var episode = req.QueryString["episode"] ?? "1";
                    var filterType = req.QueryString["filter_type"] ?? "All";
                    var filterQuality = req.QueryString["filter_quality"] ?? "All";
                    _mainWindow.DebridLoadTorrentsCommand(imdbId, type, season, episode, filterType, filterQuality);
                    await SendJson(res, new { success = true });
                }
                else if (req.Url.AbsolutePath == "/api/debrid/download" && req.HttpMethod == "POST")
                {
                    string body = await new StreamReader(req.InputStream).ReadToEndAsync();
                    var data = JsonConvert.DeserializeObject<dynamic>(body);
                    string infoHash = data?.infoHash;
                    string name = data?.name;
                    if (!string.IsNullOrEmpty(infoHash)) _mainWindow.DebridDownloadCommand(infoHash, name);
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
                    activeDownloads = _mainWindow.DebridActiveDownloads.Select(x => new { file = x.FileName, progress = x.Progress }).ToList(),
                    debridStatus = _mainWindow.DebridStatus,
                    debridTitles = _mainWindow.DebridTitleResults.Select(x => new { title = x.Title, year = x.Year, type = x.Type, imdbId = x.ImdbId, poster = x.Poster }).ToList(),
                    debridTorrents = _mainWindow.DebridTorrentResults.Select(x => new { name = x.Name, meta = x.Meta, infoHash = x.InfoHash }).ToList(),
                    drives = _mainWindow.Drives.Select(x => new { name = x.Name, label = x.Label, size = x.SizeDisplay, percent = x.PercentUsed }).ToList()
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
        body { font-family: -apple-system, system-ui, sans-serif; background: #0D0D0D; color: white; margin: 0; padding: 0; padding-bottom: 70px; }
        .tab-bar { display: flex; background: #161616; position: fixed; bottom: 0; width: 100%; border-top: 1px solid #303030; z-index: 100; }
        .tab-btn { flex: 1; padding: 15px 0; text-align: center; background: none; border: none; color: #B0B0B0; font-size: 14px; cursor: pointer; }
        .tab-btn.active { color: #FF4081; border-top: 2px solid #FF4081; font-weight: bold; }
        .tab-content { display: none; padding: 20px; }
        .tab-content.active { display: block; }
        .card { background: #1E1E1E; border: 1px solid #303030; border-radius: 8px; padding: 15px; margin-bottom: 20px; }
        .header { color: #FF4081; font-weight: bold; margin-top: 0; font-size: 18px; }
        button { background: #FF4081; color: white; border: none; padding: 12px 15px; border-radius: 6px; font-weight: bold; cursor: pointer; width: 100%; margin-bottom: 10px; font-size: 14px; }
        button.danger { background: #f44336; }
        button.secondary { background: #303030; }
        input, select { width: 100%; background: #252525; color: white; border: 1px solid #303030; padding: 12px; border-radius: 6px; margin-bottom: 10px; box-sizing: border-box; font-size: 14px; }
        .progress-bar { background: #333; height: 12px; border-radius: 6px; overflow: hidden; margin-top: 5px; }
        .progress-fill { background: #FF4081; height: 100%; transition: width 0.3s; }
        .text-sm { font-size: 13px; color: #B0B0B0; margin-bottom: 5px; }
        .flex-row { display: flex; gap: 10px; }
        .title-card { display: flex; background: #252525; border-radius: 8px; margin-bottom: 10px; overflow: hidden; cursor: pointer; }
        .title-card.selected { border: 2px solid #FF4081; }
        .title-poster { width: 80px; height: 120px; background: #111; object-fit: cover; }
        .title-info { padding: 10px; flex: 1; }
        .torrent-card { background: #252525; padding: 10px; border-radius: 8px; margin-bottom: 10px; cursor: pointer; }
        .torrent-card.selected { border: 2px solid #FF4081; }
    </style>
</head>
<body>
    <h2 style='text-align:center; color:#FF4081; padding: 15px 0; margin: 0; background: #161616; border-bottom: 1px solid #303030;'>Nomad Transfer</h2>
    
    <!-- TRANSFER TAB -->
    <div id='tab-transfer' class='tab-content active'>
        <div class='card' id='transfer-card'>
            <h3 class='header'>Transfer Status</h3>
            <div id='status-text' style='margin-bottom: 10px; font-weight:bold;'>Idle</div>
            <div class='text-sm' id='file-text'></div>
            <div class='progress-bar'><div id='file-progress' class='progress-fill' style='width:0%'></div></div>
            
            <div style='display:flex; gap:10px; margin-top: 15px;'>
                <button id='btn-start' onclick='startQueue()'>Start Transfer</button>
                <button id='btn-stop' class='danger' onclick='stopQueue()' style='display:none;'>Stop Transfer</button>
            </div>
        </div>

        <div class='card'>
            <h3 class='header'>Transfer Queue (<span id='queue-count'>0</span>)</h3>
            <div id='queue-list' class='text-sm'></div>
        </div>
        
        <div class='card'>
            <h3 class='header'>Connected Drives</h3>
            <div id='drives-list' class='text-sm'>Loading...</div>
        </div>
    </div>

    <!-- DEBRID TAB -->
    <div id='tab-debrid' class='tab-content'>
        <div class='card'>
            <h3 class='header'>Search Debrid</h3>
            <div class='flex-row'>
                <input type='text' id='debrid-query' placeholder='Movie or TV Show name...' onkeypress='if(event.key === ""Enter"") searchDebrid()'>
                <button onclick='searchDebrid()' style='width: 80px;'>Search</button>
            </div>
            <div id='debrid-status' class='text-sm' style='margin-bottom: 15px; color: #4caf50;'></div>
            <div id='debrid-titles-list'></div>
        </div>

        <div class='card' id='torrents-card' style='display:none;'>
            <h3 class='header'>Available Torrents</h3>
            <div class='flex-row' style='margin-bottom: 10px;'>
                <select id='debrid-filter-type' onchange='reloadTorrents()'>
                    <option value='All'>All Types</option>
                    <option value='MP4'>MP4</option>
                    <option value='H264'>H264</option>
                    <option value='MKV'>MKV</option>
                </select>
                <select id='debrid-filter-quality' onchange='reloadTorrents()'>
                    <option value='All'>All Qualities</option>
                    <option value='2160p'>2160p (4K)</option>
                    <option value='1080p'>1080p</option>
                    <option value='720p'>720p</option>
                </select>
            </div>
            <div id='debrid-torrents-list'></div>
            <button id='btn-download-debrid' onclick='downloadSelectedTorrent()' style='margin-top: 15px; display: none;'>Download & Add to Queue</button>
        </div>

        <div class='card'>
            <h3 class='header'>Active Downloads</h3>
            <div id='downloads-list' class='text-sm'>None</div>
        </div>
    </div>

    <div class='tab-bar'>
        <button class='tab-btn active' onclick='switchTab(""transfer"")'>🚀 Hub</button>
        <button class='tab-btn' onclick='switchTab(""debrid"")'>🎬 Debrid</button>
    </div>

    <script>
        let selectedImdbId = null;
        let selectedType = 'movie';
        let selectedInfoHash = null;
        let selectedTorrentName = null;

        function switchTab(tab) {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            event.currentTarget.classList.add('active');
            document.getElementById('tab-' + tab).classList.add('active');
        }

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                
                document.getElementById('status-text').innerText = data.isTransferring ? data.currentStatus : 'Idle';
                document.getElementById('file-text').innerText = data.isTransferring ? data.fileProgress : '';
                document.getElementById('file-progress').style.width = data.currentFileProgress + '%';
                
                document.getElementById('btn-start').style.display = data.isTransferring ? 'none' : 'block';
                document.getElementById('btn-stop').style.display = data.isTransferring ? 'block' : 'none';

                if (data.reviewQueue) {
                    document.getElementById('queue-count').innerText = data.reviewQueue.length;
                    document.getElementById('queue-list').innerHTML = data.reviewQueue.map(q => `<div style='margin-bottom:8px; padding-bottom:8px; border-bottom:1px solid #303030;'><b>${q.title}</b> (${q.year})<br><span style='color:#888'>${q.category}</span></div>`).join('') || 'Empty';
                }

                if (data.drives) {
                    document.getElementById('drives-list').innerHTML = data.drives.map(d => `<div style='margin-bottom:8px;'><b>${d.label}</b> (${d.name})<br><div class='progress-bar'><div class='progress-fill' style='width:${d.percent}%'></div></div>${d.size}</div>`).join('') || 'None';
                }

                if (data.activeDownloads) {
                    document.getElementById('downloads-list').innerHTML = data.activeDownloads.map(d => `<div style='margin-bottom:8px;'><b>${d.file}</b><br><span style='color:#4caf50'>${d.progress}</span></div>`).join('') || 'None';
                }
                
                if (data.debridStatus) {
                    document.getElementById('debrid-status').innerText = data.debridStatus;
                }

            } catch (e) {
                console.error('Fetch status error:', e);
            }
        }

        async function searchDebrid() {
            const q = document.getElementById('debrid-query').value;
            if (!q) return;
            document.getElementById('debrid-status').innerText = 'Searching...';
            document.getElementById('torrents-card').style.display = 'none';
            await fetch('/api/debrid/search?q=' + encodeURIComponent(q));
            
            // Poll for results
            setTimeout(async () => {
                const res = await fetch('/api/status');
                const data = await res.json();
                renderTitles(data.debridTitles);
            }, 1500);
        }

        function renderTitles(titles) {
            const html = titles.map(t => `
                <div class='title-card' onclick='selectTitle(this, ""${t.imdbId}"", ""${t.type}"")'>
                    <img src='${t.poster}' class='title-poster' onerror=""this.style.display='none'"">
                    <div class='title-info'>
                        <div style='font-weight:bold; font-size:15px; margin-bottom:5px;'>${t.title}</div>
                        <div style='color:#FF4081; font-size:13px;'>${t.year}</div>
                        <div style='color:#888; font-size:12px; margin-top:5px; text-transform:uppercase;'>${t.type}</div>
                    </div>
                </div>
            `).join('');
            document.getElementById('debrid-titles-list').innerHTML = html;
        }

        async function selectTitle(el, imdbId, type) {
            document.querySelectorAll('.title-card').forEach(c => c.classList.remove('selected'));
            el.classList.add('selected');
            selectedImdbId = imdbId;
            selectedType = type;
            
            await reloadTorrents();
        }

        async function reloadTorrents() {
            if (!selectedImdbId) return;
            
            const filterType = document.getElementById('debrid-filter-type').value;
            const filterQuality = document.getElementById('debrid-filter-quality').value;
            
            document.getElementById('debrid-status').innerText = 'Loading torrents...';
            document.getElementById('torrents-card').style.display = 'block';
            document.getElementById('debrid-torrents-list').innerHTML = 'Loading...';
            
            await fetch(`/api/debrid/torrents?imdb_id=${selectedImdbId}&type=${selectedType}&filter_type=${encodeURIComponent(filterType)}&filter_quality=${encodeURIComponent(filterQuality)}`);
            
            setTimeout(async () => {
                const res = await fetch('/api/status');
                const data = await res.json();
                renderTorrents(data.debridTorrents);
                document.getElementById('debrid-status').innerText = '';
            }, 2000);
        }

        function renderTorrents(torrents) {
            document.getElementById('torrents-card').style.display = 'block';
            const html = torrents.map(t => `
                <div class='torrent-card' onclick='selectTorrent(this, ""${t.infoHash}"", ""${t.name.replace(/""/g, '&quot;')}"")'>
                    <div style='font-weight:bold; font-size:13px; margin-bottom:5px; word-break:break-all;'>${t.name}</div>
                    <div style='color:#4caf50; font-size:12px;'>${t.meta}</div>
                </div>
            `).join('');
            document.getElementById('debrid-torrents-list').innerHTML = html || 'No torrents found.';
            document.getElementById('btn-download-debrid').style.display = 'none';
            selectedInfoHash = null;
        }

        function selectTorrent(el, infoHash, name) {
            document.querySelectorAll('.torrent-card').forEach(c => c.classList.remove('selected'));
            el.classList.add('selected');
            selectedInfoHash = infoHash;
            selectedTorrentName = name;
            document.getElementById('btn-download-debrid').style.display = 'block';
        }

        async function downloadSelectedTorrent() {
            if (!selectedInfoHash) return;
            await fetch('/api/debrid/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ infoHash: selectedInfoHash, name: selectedTorrentName })
            });
            document.getElementById('btn-download-debrid').style.display = 'none';
            // Switch back to transfer tab after 1 second to see the download progress
            setTimeout(() => switchTab('transfer'), 1000);
        }

        async function startQueue() { await fetch('/api/queue/start', {method:'POST'}); fetchStatus(); }
        async function stopQueue() { await fetch('/api/queue/stop', {method:'POST'}); fetchStatus(); }

        setInterval(fetchStatus, 1500);
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