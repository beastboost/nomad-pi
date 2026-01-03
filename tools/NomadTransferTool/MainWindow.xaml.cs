using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Management;
using System.Net.Http;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows;
using System.IO.Compression;
using Microsoft.Win32;
using System.Windows.Forms;
using OpenFileDialog = Microsoft.Win32.OpenFileDialog;
using SaveFileDialog = Microsoft.Win32.SaveFileDialog;
using Newtonsoft.Json;

namespace NomadTransferTool
{
    public partial class MainWindow : Window, INotifyPropertyChanged
    {
        private static readonly HttpClient client = new HttpClient();
        private const string API_BASE = "http://localhost:8000/api";
        private string OMDB_API_KEY = "";
        private string mediaServerDataPath = "";

        // UI State
        private bool _isTransferring;
        private string _currentStatus = "Ready";
        private string _transferSpeed = "";
        private string _fileProgress = "";
        private double _totalProgress;
        private string _appStatus = "Nomad v1.4.0 - Connected";
        private ObservableCollection<string> _transcodeQueue = new ObservableCollection<string>();
        private double _currentFileProgress;
        private bool _isHandbrakeAvailable;
        private string _detectedEncoder = "x264";

        public bool IsTransferring { get => _isTransferring; set { _isTransferring = value; OnPropertyChanged(); } }
        public string CurrentStatus { get => _currentStatus; set { _currentStatus = value; OnPropertyChanged(); } }
        public string TransferSpeed { get => _transferSpeed; set { _transferSpeed = value; OnPropertyChanged(); } }
        public string FileProgress { get => _fileProgress; set { _fileProgress = value; OnPropertyChanged(); } }
        public double TotalProgress { get => _totalProgress; set { _totalProgress = value; OnPropertyChanged(); } }
        public double CurrentFileProgress { get => _currentFileProgress; set { _currentFileProgress = value; OnPropertyChanged(); } }
        public string AppStatus { get => _appStatus; set { _appStatus = value; OnPropertyChanged(); } }
        public ObservableCollection<string> TranscodeQueue { get => _transcodeQueue; set { _transcodeQueue = value; OnPropertyChanged(); } }
        public bool IsHandbrakeAvailable { get => _isHandbrakeAvailable; set { _isHandbrakeAvailable = value; OnPropertyChanged(); } }

        public ObservableCollection<DriveInfoModel> Drives { get; set; } = new ObservableCollection<DriveInfoModel>();

        public MainWindow()
        {
            InitializeComponent();
            DataContext = this;
            
            // Load OMDB key if exists
            if (File.Exists("omdb.txt")) 
            {
                OMDB_API_KEY = File.ReadAllText("omdb.txt").Trim();
                OmdbKeyBox.Password = OMDB_API_KEY;
            }

            // Try to find the media server data path
            string currentDir = AppDomain.CurrentDomain.BaseDirectory;
            DirectoryInfo? dir = new DirectoryInfo(currentDir);
            while (dir != null && !Directory.Exists(Path.Combine(dir.FullName, "data")))
            {
                dir = dir.Parent;
            }
            if (dir != null)
            {
                mediaServerDataPath = Path.Combine(dir.FullName, "data");
            }

            RefreshDrives();
            StartDriveWatcher();
            CheckHandbrakeStatus();
        }

        private void CheckHandbrakeStatus()
        {
            string hbPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "HandbrakeCLI.exe");
            IsHandbrakeAvailable = File.Exists(hbPath);
            if (IsHandbrakeAvailable)
            {
                DetectHardwareEncoder(hbPath);
            }
            else
            {
                AppStatus = "HandbrakeCLI missing. Click 'Download' to enable transcoding.";
            }
        }

        private async void DetectHardwareEncoder(string hbPath)
        {
            try
            {
                var process = new Process();
                process.StartInfo.FileName = hbPath;
                process.StartInfo.Arguments = "--list-encoders";
                process.StartInfo.CreateNoWindow = true;
                process.StartInfo.UseShellExecute = false;
                process.StartInfo.RedirectStandardOutput = true;
                process.StartInfo.RedirectStandardError = true;
                process.StartInfo.WorkingDirectory = Path.GetDirectoryName(hbPath);
                process.Start();

                // Read both streams in parallel to avoid deadlocks
                var outputTask = process.StandardOutput.ReadToEndAsync();
                var errorTask = process.StandardError.ReadToEndAsync();
                
                await Task.WhenAll(outputTask, errorTask);
                await process.WaitForExitAsync();

                string fullOutput = (outputTask.Result + "\n" + errorTask.Result).ToLower();
                Debug.WriteLine($"Handbrake Encoders Found:\n{fullOutput}");

                // Priority: NVIDIA > Intel > AMD > Software
                // Note: Handbrake CLI might list them as nvenc_h264, h264_nvenc, or within NVIDIA descriptions
                if (fullOutput.Contains("nvenc") || fullOutput.Contains("nvidia") || fullOutput.Contains("h264_nvenc"))
                {
                    _detectedEncoder = "nvenc_h264";
                    AppStatus = "Handbrake Ready (NVIDIA GPU Acceleration)";
                }
                else if (fullOutput.Contains("qsv") || fullOutput.Contains("intel") || fullOutput.Contains("h264_qsv"))
                {
                    _detectedEncoder = "qsv_h264";
                    AppStatus = "Handbrake Ready (Intel QSV Acceleration)";
                }
                else if (fullOutput.Contains("vce") || fullOutput.Contains("amd") || fullOutput.Contains("h264_vce"))
                {
                    _detectedEncoder = "vce_h264";
                    AppStatus = "Handbrake Ready (AMD VCE Acceleration)";
                }
                else
                {
                    _detectedEncoder = "x264";
                    AppStatus = "Handbrake Ready (Software Encoding)";
                }
                OnPropertyChanged(nameof(AppStatus));
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"Encoder detection failed: {ex.Message}");
                _detectedEncoder = "x264";
            }
        }

        private async Task DownloadHandbrake()
        {
            string zipPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "hb.zip");
            try
            {
                IsTransferring = true;
                TotalProgress = 0;
                CurrentStatus = "Checking for latest Handbrake release...";

                // 1. Resolve latest release via GitHub API
                client.DefaultRequestHeaders.UserAgent.ParseAdd("NomadTransferTool/1.4");
                var apiResponse = await client.GetStringAsync("https://api.github.com/repos/HandBrake/HandBrake/releases/latest");
                var release = JsonConvert.DeserializeObject<GithubRelease>(apiResponse);
                if (release == null) throw new Exception("Failed to parse GitHub API response.");

                string? downloadUrl = null;
                string? checksumUrl = null;
                string version = release.TagName;

                foreach (var asset in release.Assets)
                {
                    string name = asset.Name;
                    string lowerName = name.ToLower();
                    
                    if (lowerName.Contains("handbrakecli") && 
                        (lowerName.Contains("win-x86_64") || (lowerName.Contains("x86_64") && lowerName.Contains("win"))) && 
                        lowerName.EndsWith(".zip"))
                    {
                        downloadUrl = asset.BrowserDownloadUrl;
                    }
                    else if (lowerName.EndsWith(".sha256") || lowerName.Contains("sha256sums"))
                    {
                        checksumUrl = asset.BrowserDownloadUrl;
                    }
                }

                if (string.IsNullOrEmpty(downloadUrl)) throw new Exception("Could not find HandbrakeCLI Windows zip in latest release.");

                // 2. Download Handbrake zip
                CurrentStatus = $"Downloading HandbrakeCLI {version}...";
                using (var response = await client.GetAsync(downloadUrl, HttpCompletionOption.ResponseHeadersRead))
                {
                    response.EnsureSuccessStatusCode();
                    var totalBytes = response.Content.Headers.ContentLength ?? -1L;
                    using (var stream = await response.Content.ReadAsStreamAsync())
                    using (var fileStream = new FileStream(zipPath, FileMode.Create, FileAccess.Write, FileShare.None, 8192, true))
                    {
                        var buffer = new byte[8192];
                        var totalRead = 0L;
                        int read;
                        while ((read = await stream.ReadAsync(buffer, 0, buffer.Length)) > 0)
                        {
                            await fileStream.WriteAsync(buffer, 0, read);
                            totalRead += read;
                            if (totalBytes != -1)
                            {
                                TotalProgress = (double)totalRead / totalBytes * 100;
                                FileProgress = $"Downloading: {totalRead / 1024 / 1024}MB / {totalBytes / 1024 / 1024}MB";
                            }
                        }
                    }
                }

                // 3. Verify Checksum (Optional but recommended)
                if (!string.IsNullOrEmpty(checksumUrl))
                {
                    try
                    {
                        CurrentStatus = "Verifying checksum...";
                        string expectedHash = "";
                        var hashData = await client.GetStringAsync(checksumUrl);
                        string zipName = Path.GetFileName(downloadUrl) ?? "";
                        
                        foreach (var line in hashData.Split('\n'))
                        {
                            if (!string.IsNullOrEmpty(zipName) && line.Contains(zipName))
                            {
                                expectedHash = line.Split(' ')[0].Trim().ToLower();
                                break;
                            }
                        }

                        if (!string.IsNullOrEmpty(expectedHash))
                        {
                            using (var sha256 = System.Security.Cryptography.SHA256.Create())
                            using (var stream = File.OpenRead(zipPath))
                            {
                                var hashBytes = sha256.ComputeHash(stream);
                                string actualHash = BitConverter.ToString(hashBytes).Replace("-", "").ToLower();
                                if (actualHash != expectedHash) throw new Exception("Checksum verification failed! The downloaded file may be corrupted or tampered with.");
                            }
                        }
                    }
                    catch (Exception ex)
                    {
                        Debug.WriteLine($"Checksum verification skipped/failed: {ex.Message}");
                    }
                }

                // 4. Safe Extraction
                CurrentStatus = "Extracting HandbrakeCLI safely...";
                string targetDir = AppDomain.CurrentDomain.BaseDirectory;
                using (ZipArchive archive = ZipFile.OpenRead(zipPath))
                {
                    foreach (ZipArchiveEntry entry in archive.Entries)
                    {
                        // Path Traversal Protection
                        string fullPath = Path.GetFullPath(Path.Combine(targetDir, entry.FullName));
                        if (!fullPath.StartsWith(targetDir, StringComparison.OrdinalIgnoreCase)) continue;

                        // Directory handling
                        if (string.IsNullOrEmpty(entry.Name))
                        {
                            Directory.CreateDirectory(fullPath);
                            continue;
                        }

                        // Skip if file exists (don't overwrite unless intended)
                        if (File.Exists(fullPath)) continue;

                        entry.ExtractToFile(fullPath);
                    }
                }

                CheckHandbrakeStatus();
                CurrentStatus = $"HandbrakeCLI {version} Ready!";
                FileProgress = "";
            }
            catch (Exception ex)
            {
                string errorLog = $"Handbrake Download Error:\nMessage: {ex.Message}\nStack: {ex.StackTrace}";
                Debug.WriteLine(errorLog);
                System.Windows.MessageBox.Show($"Failed to download Handbrake: {ex.Message}\n\nCheck logs for details.", "Download Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
            finally
            {
                IsTransferring = false;
                if (File.Exists(zipPath))
                {
                    try { File.Delete(zipPath); } catch { }
                }
            }
        }

        private async void DownloadHandbrake_Click(object sender, RoutedEventArgs e)
        {
            await DownloadHandbrake();
        }

        public event PropertyChangedEventHandler? PropertyChanged;
        protected void OnPropertyChanged([CallerMemberName] string? name = null) => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));

        private void OmdbKeyBox_PasswordChanged(object sender, RoutedEventArgs e)
        {
            if (OMDB_API_KEY == OmdbKeyBox.Password) return;
            OMDB_API_KEY = OmdbKeyBox.Password;
            try { File.WriteAllText("omdb.txt", OMDB_API_KEY); } catch { }
        }

        private void RefreshDrives()
        {
            var selectedName = (DriveList.SelectedItem as DriveInfoModel)?.Name;
            Drives.Clear();
            foreach (var drive in DriveInfo.GetDrives())
            {
                if (drive.DriveType == DriveType.Removable && drive.IsReady)
                {
                    var model = new DriveInfoModel
                    {
                        Name = drive.Name,
                        Label = string.IsNullOrEmpty(drive.VolumeLabel) ? "USB Drive" : drive.VolumeLabel,
                        TotalSize = drive.TotalSize,
                        AvailableFreeSpace = drive.AvailableFreeSpace,
                        IsMounted = Directory.Exists(Path.Combine(mediaServerDataPath, drive.Name.Replace(":\\", "")))
                    };
                    Drives.Add(model);
                    if (model.Name == selectedName) DriveList.SelectedItem = model;
                }
            }
        }

        private void StartDriveWatcher()
        {
            try
            {
                ManagementEventWatcher watcher = new ManagementEventWatcher();
                WqlEventQuery query = new WqlEventQuery("SELECT * FROM Win32_VolumeChangeEvent WHERE EventType = 2 OR EventType = 3");
                watcher.EventArrived += (s, e) => Dispatcher.Invoke(RefreshDrives);
                watcher.Query = query;
                watcher.Start();
            }
            catch { /* Ignore if management not available */ }
        }

        private void PrepareDrive_Click(object sender, RoutedEventArgs e)
        {
            if (DriveList.SelectedItem is DriveInfoModel drive)
            {
                try
                {
                    string[] folders = { "movies", "shows", "music", "books", "gallery", "files" };
                    foreach (var f in folders)
                    {
                        string path = Path.Combine(drive.Name, f);
                        if (!Directory.Exists(path)) Directory.CreateDirectory(path);
                    }
                    
                    System.Windows.MessageBox.Show("Drive prepared with standard folders!", "Success", MessageBoxButton.OK, MessageBoxImage.Information);
                }
                catch (Exception ex)
                {
                    System.Windows.MessageBox.Show($"Error preparing drive: {ex.Message}", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
                }
            }
        }

        private void FormatDrive_Click(object sender, RoutedEventArgs e)
        {
            if (DriveList.SelectedItem is DriveInfoModel drive)
            {
                var result = System.Windows.MessageBox.Show($"Are you sure you want to format {drive.Name} ({drive.Label})? ALL DATA WILL BE LOST. We recommend exFAT for compatibility with Pi.", 
                    "Confirm Format", MessageBoxButton.YesNo, MessageBoxImage.Warning);
                
                if (result == MessageBoxResult.Yes)
                {
                    try
                    {
                        string driveLetter = drive.Name.Replace(":\\", "");
                        var process = new Process();
                        process.StartInfo.FileName = "cmd.exe";
                        process.StartInfo.Arguments = $"/c format {driveLetter}: /FS:exFAT /Q /V:NOMAD /Y";
                        process.StartInfo.CreateNoWindow = false; 
                        process.StartInfo.UseShellExecute = true;
                        process.StartInfo.Verb = "runas"; 
                        process.Start();
                        process.WaitForExit();
                        
                        RefreshDrives();
                        System.Windows.MessageBox.Show("Format complete. Now click 'Prepare Folders'.");
                    }
                    catch (Exception ex)
                    {
                        System.Windows.MessageBox.Show($"Format failed: {ex.Message}");
                    }
                }
            }
        }

        private void SelectFiles_Click(object sender, RoutedEventArgs e)
        {
            var dialog = new OpenFileDialog();
            dialog.Multiselect = true;
            dialog.Filter = "Media Files|*.mp4;*.mkv;*.avi;*.mov;*.wmv;*.mp3;*.flac;*.jpg;*.png|All Files|*.*";
            if (dialog.ShowDialog() == true)
            {
                ProcessInputs(dialog.FileNames);
            }
        }

        private void SelectFolder_Click(object sender, RoutedEventArgs e)
        {
            using (var dialog = new FolderBrowserDialog())
            {
                if (dialog.ShowDialog() == System.Windows.Forms.DialogResult.OK)
                {
                    ProcessInputs(new[] { dialog.SelectedPath });
                }
            }
        }

        private void Transfer_Drop(object sender, System.Windows.DragEventArgs e)
        {
            if (e.Data.GetDataPresent(System.Windows.DataFormats.FileDrop))
            {
                string[]? inputs = (string[]?)e.Data.GetData(System.Windows.DataFormats.FileDrop);
                if (inputs != null) ProcessInputs(inputs);
            }
        }

        private async void ProcessInputs(string[] inputs)
        {
            bool useHandbrake = Dispatcher.Invoke(() => HandbrakeCheck.IsChecked == true);
            bool autoMove = Dispatcher.Invoke(() => AutoMoveCheck.IsChecked == true);
            var selectedDrive = DriveList.SelectedItem as DriveInfoModel;

            if (selectedDrive == null && autoMove)
            {
                System.Windows.MessageBox.Show("Please select a target drive for auto-move, or uncheck 'Auto-move' to just transcode.");
                return;
            }

            string category = (CategoryCombo.SelectedItem as FrameworkElement)?.Tag?.ToString() ?? "files";
            string destBase = selectedDrive != null ? Path.Combine(selectedDrive.Name, category) : Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Transcoded", category);
            
            if (!Directory.Exists(destBase)) Directory.CreateDirectory(destBase);

            // Collect all files recursively if folders were selected
            List<string> allFiles = new List<string>();
            foreach (var input in inputs)
            {
                if (Directory.Exists(input))
                {
                    allFiles.AddRange(Directory.GetFiles(input, "*.*", SearchOption.AllDirectories));
                }
                else if (File.Exists(input))
                {
                    allFiles.Add(input);
                }
            }

            if (allFiles.Count == 0) return;

            IsTransferring = true;
            TotalProgress = 0;
            TranscodeQueue.Clear();
            if (useHandbrake)
            {
                foreach (var f in allFiles) if (IsVideoFile(f)) TranscodeQueue.Add(Path.GetFileName(f));
            }

            int totalFiles = allFiles.Count;
            int processedFiles = 0;

            await Task.Run(async () => {
                string tempDir = Path.Combine(Path.GetTempPath(), "NomadTransferTemp");
                if (!Directory.Exists(tempDir)) Directory.CreateDirectory(tempDir);

                foreach (var file in allFiles)
                {
                    try
                    {
                        string fileName = Path.GetFileName(file);
                        CurrentStatus = useHandbrake && IsVideoFile(file) ? $"Transcoding: {fileName}" : $"Processing: {fileName}";
                        CurrentFileProgress = 0;
                        
                        string finalDest = Path.Combine(destBase, fileName);
                        string? posterUrl = null;

                        // Metadata Lookups
                        if (!string.IsNullOrEmpty(OMDB_API_KEY) && (category == "movies" || category == "shows"))
                        {
                            var meta = await FetchOMDBMetadata(fileName, category);
                            if (meta != null)
                            {
                                string metaTitle = meta.Title;
                                string metaYear = meta.Year;
                                string safeTitle = string.Join("_", metaTitle.Split(Path.GetInvalidFileNameChars()));
                                
                                if (category == "movies")
                                {
                                    string folderName = $"{safeTitle} ({metaYear})";
                                    string movieFolder = Path.Combine(destBase, folderName);
                                    Directory.CreateDirectory(movieFolder);
                                    string ext = useHandbrake ? ".mp4" : Path.GetExtension(file);
                                    finalDest = Path.Combine(movieFolder, $"{safeTitle} ({metaYear}){ext}");
                                    posterUrl = meta.Poster;
                                    if (!string.IsNullOrEmpty(posterUrl) && posterUrl != "N/A")
                                        await DownloadPoster(posterUrl, Path.Combine(movieFolder, "poster.jpg"));
                                }
                                else if (category == "shows")
                                {
                                    string showFolder = Path.Combine(destBase, safeTitle);
                                    Directory.CreateDirectory(showFolder);
                                    string ext = useHandbrake ? ".mp4" : Path.GetExtension(file);
                                    finalDest = Path.Combine(showFolder, Path.GetFileNameWithoutExtension(fileName) + ext);
                                    posterUrl = meta.Poster;
                                    if (!string.IsNullOrEmpty(posterUrl) && posterUrl != "N/A")
                                        await DownloadPoster(posterUrl, Path.Combine(showFolder, "poster.jpg"));
                                }
                            }
                        }

                        // Processing
                        if (useHandbrake && IsVideoFile(file))
                        {
                            try
                            {
                                string tempFile = Path.Combine(tempDir, Path.GetFileNameWithoutExtension(file) + ".mp4");
                                await TranscodeWithHandbrake(file, tempFile);
                                
                                if (autoMove)
                                {
                                    CurrentStatus = $"Moving to USB: {fileName}";
                                    if (File.Exists(finalDest)) File.Delete(finalDest);
                                    await Task.Run(() => File.Move(tempFile, finalDest));
                                }
                                else
                                {
                                    if (File.Exists(finalDest)) File.Delete(finalDest);
                                    File.Move(tempFile, finalDest);
                                }
                            }
                            finally
                            {
                                Dispatcher.Invoke(() => {
                                    if (TranscodeQueue.Count > 0) TranscodeQueue.RemoveAt(0);
                                });
                            }
                        }
                        else if (autoMove)
                        {
                            await CopyFileWithProgress(file, finalDest);
                        }

                        processedFiles++;
                        TotalProgress = (double)processedFiles / totalFiles * 100;
                    }
                    catch (Exception ex)
                    {
                        Debug.WriteLine($"Error processing {file}: {ex.Message}");
                    }
                }

                // Cleanup temp dir
                try { if (Directory.Exists(tempDir)) Directory.Delete(tempDir, true); } catch { }

                CurrentStatus = "Process Complete!";
                IsTransferring = false;
                Dispatcher.Invoke(RefreshDrives);
            });
        }

        private async Task CopyFileWithProgress(string source, string dest)
        {
            byte[] buffer = new byte[1024 * 1024]; // 1MB buffer
            long totalBytes = new FileInfo(source).Length;
            long totalRead = 0;
            
            using (var sourceStream = File.OpenRead(source))
            using (var destStream = File.Create(dest))
            {
                Stopwatch sw = Stopwatch.StartNew();
                int read;
                while ((read = await sourceStream.ReadAsync(buffer, 0, buffer.Length)) > 0)
                {
                    await destStream.WriteAsync(buffer, 0, read);
                    totalRead += read;
                    
                    double progress = (double)totalRead / totalBytes * 100;
                    double elapsed = sw.Elapsed.TotalSeconds;
                    double speed = elapsed > 0 ? totalRead / 1024.0 / 1024.0 / elapsed : 0;
                    
                    CurrentFileProgress = progress;
                    FileProgress = $"{totalRead / 1024 / 1024}MB / {totalBytes / 1024 / 1024}MB ({progress:F1}%)";
                    TransferSpeed = $"{speed:F1} MB/s";
                }
            }
        }

        private async Task<OmdbResult?> FetchOMDBMetadata(string fileName, string category)
        {
            try
            {
                string cleanName = Path.GetFileNameWithoutExtension(fileName);
                
                // 1. Extract Year
                string year = "";
                var yearMatch = Regex.Match(cleanName, @"(?<=[ \.\(\[])(19|20)\d{2}(?=[ \.\)\]]|$)");
                if (yearMatch.Success)
                {
                    year = yearMatch.Value;
                }

                // 2. Clean Title
                string titlePart = yearMatch.Success ? cleanName.Substring(0, yearMatch.Index) : cleanName;
                titlePart = Regex.Replace(titlePart, @"[\._\-]", " ");
                titlePart = Regex.Replace(titlePart, @"\b(1080p|720p|4k|2160p|bluray|web-dl|x264|h264|x265|hevc|aac|dts|remux|multi|subs|dual|extended|unrated|director.*cut)\b.*", "", RegexOptions.IgnoreCase).Trim();
                string title = Regex.Replace(titlePart, @"\s+", " ").Trim();
                
                if (string.IsNullOrEmpty(title)) return null;

                string type = category == "movies" ? "movie" : "series";
                string url = $"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&t={Uri.EscapeDataString(title)}&type={type}";
                if (!string.IsNullOrEmpty(year)) url += $"&y={year}";
                
                var response = await client.GetStringAsync(url);
                var result = JsonConvert.DeserializeObject<OmdbResult>(response);
                
                if ((result == null || result.Response != "True") && !string.IsNullOrEmpty(year))
                {
                    url = $"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&t={Uri.EscapeDataString(title)}&type={type}";
                    response = await client.GetStringAsync(url);
                    result = JsonConvert.DeserializeObject<OmdbResult>(response);
                }

                return result?.Response == "True" ? result : null;
            }
            catch { return null; }
        }

        private async Task DownloadPoster(string url, string destPath)
        {
            try
            {
                if (File.Exists(destPath)) return;
                var data = await client.GetByteArrayAsync(url);
                await File.WriteAllBytesAsync(destPath, data);
            }
            catch { }
        }

        private bool IsVideoFile(string file)
        {
            string ext = Path.GetExtension(file).ToLower();
            string[] videoExts = { ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".m4v", ".flv" };
            return videoExts.Contains(ext);
        }

        private async Task TranscodeWithHandbrake(string source, string dest)
        {
            try
            {
                string hbPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "HandbrakeCLI.exe");
                if (!File.Exists(hbPath))
                {
                    throw new FileNotFoundException("HandbrakeCLI.exe not found. Please click 'Download' in the UI.");
                }

                string encoderArgs = $"-e {_detectedEncoder}";
                if (_detectedEncoder.Contains("nvenc")) 
                {
                    // Use a bitrate limit (2500k) to guarantee smaller files than high-bitrate originals
                    // And set a higher CQ (30) as a fallback quality target
                    encoderArgs += " -b 2500 -q 30 --encoder-preset slow --vfr";
                }
                else
                {
                    // For CPU, 2000k is usually plenty for 1080p to stay under 1.5GB/hr
                    encoderArgs += " -b 2000 -q 25 --encoder-preset fast --vfr";
                }
                
                // Mix down to Stereo AAC (128k) to save space vs 5.1/DTS
                string audioArgs = "-E av_aac -B 128 -6 dpl2";
                
                string args = $"-i \"{source}\" -o \"{dest}\" {encoderArgs} {audioArgs} --maxHeight 1080 --format av_mp4";
                
                var process = new Process();
                process.StartInfo.FileName = hbPath;
                process.StartInfo.Arguments = args;
                process.StartInfo.CreateNoWindow = true;
                process.StartInfo.UseShellExecute = false;
                process.StartInfo.RedirectStandardError = true;
                process.StartInfo.RedirectStandardOutput = true;
                process.StartInfo.WorkingDirectory = Path.GetDirectoryName(hbPath);

                // Handle both output and error to prevent pipe clogging/hanging
                process.OutputDataReceived += (s, e) => {
                    if (e.Data != null)
                    {
                        var match = Regex.Match(e.Data, @"(\d+\.\d+)\s*%");
                        if (match.Success)
                        {
                            if (double.TryParse(match.Groups[1].Value, out double progress))
                            {
                                CurrentFileProgress = progress;
                                FileProgress = $"Transcoding: {progress:F1}%";
                            }
                        }
                    }
                };
                
                process.ErrorDataReceived += (s, e) => {
                    if (!string.IsNullOrEmpty(e.Data))
                    {
                        Debug.WriteLine($"Handbrake Error: {e.Data}");
                    }
                };

                process.Start();
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();

                // Wait for exit with a very long timeout (2 hours per file) to prevent infinite hangs
                var exitTask = process.WaitForExitAsync();
                var timeoutTask = Task.Delay(TimeSpan.FromHours(2));
                
                var completedTask = await Task.WhenAny(exitTask, timeoutTask);
                if (completedTask == timeoutTask)
                {
                    try { process.Kill(); } catch { }
                    throw new Exception("Transcoding timed out after 2 hours.");
                }

                if (process.ExitCode != 0)
                {
                    throw new Exception($"Handbrake failed with exit code {process.ExitCode}");
                }
            }
            catch (Exception ex)
            {
                throw new Exception($"Transcode error: {ex.Message}");
            }
        }

        public class OmdbResult
        {
            public string Title { get; set; } = "";
            public string Year { get; set; } = "";
            public string Poster { get; set; } = "";
            public string Response { get; set; } = "";
        }

        public class GithubRelease
        {
            [JsonProperty("tag_name")]
            public string TagName { get; set; } = "";
            [JsonProperty("assets")]
            public List<GithubAsset> Assets { get; set; } = new();
        }

        public class GithubAsset
        {
            [JsonProperty("name")]
            public string Name { get; set; } = "";
            [JsonProperty("browser_download_url")]
            public string BrowserDownloadUrl { get; set; } = "";
        }
    }

    public class DriveInfoModel
    {
        public string Name { get; set; } = "";
        public string Label { get; set; } = "";
        public long TotalSize { get; set; }
        public long AvailableFreeSpace { get; set; }
        public bool IsMounted { get; set; }
        
        public string SizeDisplay => $"{AvailableFreeSpace / 1024 / 1024 / 1024} GB free of {TotalSize / 1024 / 1024 / 1024} GB";
        public string StatusDisplay => IsMounted ? "Mounted to Library" : "Not Mounted";
    }

    public class BooleanToColorConverter : System.Windows.Data.IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            if (value is bool b)
                return b ? new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(76, 175, 80)) : new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(244, 67, 54));
            return new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(100, 100, 100));
        }
        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture) => throw new NotImplementedException();
    }

    public class InverseBooleanToVisibilityConverter : System.Windows.Data.IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            if (value is bool b)
                return b ? Visibility.Collapsed : Visibility.Visible;
            return Visibility.Visible;
        }
        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture) => throw new NotImplementedException();
    }
}
