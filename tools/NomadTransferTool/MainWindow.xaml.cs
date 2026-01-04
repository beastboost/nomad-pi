using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.IO.Compression;
using Microsoft.Win32;
using OpenFileDialog = Microsoft.Win32.OpenFileDialog;
using SaveFileDialog = Microsoft.Win32.SaveFileDialog;
using Newtonsoft.Json;

namespace NomadTransferTool
{
    public class NullToVisibilityConverter : System.Windows.Data.IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            return value != null ? Visibility.Visible : Visibility.Collapsed;
        }

        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            throw new NotImplementedException();
        }
    }

    public partial class MainWindow : Window, INotifyPropertyChanged
    {
        private const string APP_VERSION = "1.5.0";
        private static readonly HttpClient client = new HttpClient();
        private string API_BASE => $"http://{ServerIp}:8000/api";
        private string _serverIp = "nomadpi.local";
        public string ServerIp 
        { 
            get => _serverIp; 
            set { 
                _serverIp = value; 
                OnPropertyChanged(); 
                OnPropertyChanged(nameof(AppStatus)); 
            } 
        }

        private string _serverStatus = "Unknown";
        public string ServerStatus { get => _serverStatus; set { _serverStatus = value; OnPropertyChanged(); } }

        private System.Windows.Media.Brush _serverStatusColor = System.Windows.Media.Brushes.Gray;
        public System.Windows.Media.Brush ServerStatusColor { get => _serverStatusColor; set { _serverStatusColor = value; OnPropertyChanged(); } }
        private string OMDB_API_KEY = "";
        private string mediaServerDataPath = "";

        // UI State
        private bool _isTransferring;
        private string _currentStatus = "Ready";
        private string _transferSpeed = "";
        private string _fileProgress = "";
        private double _totalProgress;
        private string _appStatus = $"Nomad v{APP_VERSION} - Connected";
        private ObservableCollection<string> _transcodeQueue = new ObservableCollection<string>();
        private ObservableCollection<string> _processingLogs = new ObservableCollection<string>();
        private ObservableCollection<MediaItem> _reviewQueue = new ObservableCollection<MediaItem>();
        private ObservableCollection<EncodingPreset> _encodingPresets = new ObservableCollection<EncodingPreset>();
        private EncodingPreset? _selectedGlobalPreset;
        private double _currentFileProgress;
        private bool _isHandbrakeAvailable;
        private bool _deleteSourceAfterTransfer;
        private bool _isTranscodingEnabled = true;
        private string _detectedEncoder = "x264";
        private System.Threading.CancellationTokenSource? _processingCts;
        private HashSet<string> _connectedSambaPaths = new HashSet<string>();

        // Samba Properties
        private bool _useSamba;
        private string _sambaPath = "";
        private string _sambaUser = "";
        private string _sambaPassword = "";

        public bool UseSamba 
        { 
            get => _useSamba; 
            set { 
                _useSamba = value; 
                OnPropertyChanged(); 
                Dispatcher.BeginInvoke(new Action(() => RefreshDrives())); // Refresh drives when toggled
            } 
        }
        public string SambaPath 
        { 
            get => _sambaPath; 
            set { 
                _sambaPath = value; 
                OnPropertyChanged(); 
                Dispatcher.BeginInvoke(new Action(() => RefreshDrives())); // Refresh drives when path changes
            } 
        }
        public string SambaUser { get => _sambaUser; set { _sambaUser = value; OnPropertyChanged(); } }
        public string SambaPassword { get => _sambaPassword; set { _sambaPassword = value; OnPropertyChanged(); } }

        [DllImport("mpr.dll")]
        private static extern int WNetAddConnection2(NetResource netResource, string? password, string? username, int flags);

        [DllImport("mpr.dll")]
        private static extern int WNetCancelConnection2(string name, int flags, bool force);

        [StructLayout(LayoutKind.Sequential)]
        public class NetResource
        {
            public int Scope;
            public int Type;
            public int DisplayType;
            public int Usage;
            public string? LocalName;
            public string? RemoteName;
            public string? Comment;
            public string? Provider;
        }

        private async void TestSamba_Click(object sender, RoutedEventArgs e)
        {
            if (string.IsNullOrEmpty(SambaPath))
            {
                System.Windows.MessageBox.Show("Please enter a Samba path.");
                return;
            }

            AddLog($"Testing Samba connection to {SambaPath}...");
            
            // Check if already accessible first
            if (await Task.Run(() => IsPathAccessible(SambaPath)))
            {
                AddLog("Path is already accessible (likely already connected via Windows).");
                System.Windows.MessageBox.Show("Samba connection successful (already connected)!", "Success", MessageBoxButton.OK, MessageBoxImage.Information);
                return;
            }

            var (success, errorCode) = await Task.Run(() => ConnectToSamba(SambaPath, SambaUser, SambaPassword));
            
            if (success)
            {
                AddLog("Samba connection successful!");
                System.Windows.MessageBox.Show("Samba connection successful!", "Success", MessageBoxButton.OK, MessageBoxImage.Information);
            }
            else
            {
                string errorMsg = GetWNetErrorMessage(errorCode);
                AddLog($"Samba connection failed: {errorMsg} (Code: {errorCode})");
                System.Windows.MessageBox.Show($"Samba connection failed.\n\nError: {errorMsg}\nCode: {errorCode}", "Samba Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private bool IsPathAccessible(string path)
        {
            try
            {
                return Directory.Exists(path);
            }
            catch
            {
                return false;
            }
        }

        private string GetWNetErrorMessage(int code)
        {
            return code switch
            {
                5 => "Access Denied (Check Username/Password)",
                67 => "Network Name Not Found (Check Path)",
                85 => "Local Device Name Already in Use",
                86 => "Invalid Network Password",
                1219 => "Credential Conflict (You are already connected to this server with a different user. Log out of the share in Windows first.)",
                1203 => "Network Path Not Found / Invalid Format (Ensure path starts with \\\\ and uses the correct IP or hostname)",
                1326 => "Logon Failure: Unknown user name or bad password.",
                2250 => "Network Connection Not Found",
                _ => $"Unknown Windows Error {code}"
            };
        }

        private async void SyncSamba_Click(object sender, RoutedEventArgs e)
        {
            await SyncSambaSettings(true);
        }

        private async Task SyncSambaSettings(bool showMessages = false)
        {
            try
            {
                AddLog("Syncing Samba settings from Nomad Pi...");
                var res = await client.GetAsync($"{API_BASE}/system/samba/config");
                if (res.IsSuccessStatusCode)
                {
                    var content = await res.Content.ReadAsStringAsync();
                    var config = JsonConvert.DeserializeObject<dynamic>(content);
                    
                    if (config != null)
                    {
                        Dispatcher.Invoke(() => {
                            SambaUser = config.user;
                            
                            // Validate and fix path format
                            string path = config.path;
                            
                            // Use the ServerIp if provided, otherwise use the path from config
                            if (Regex.IsMatch(ServerIp, @"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$") || ServerIp.EndsWith(".local"))
                            {
                                // If the config path had a share, try to preserve it
                                string share = "";
                                if (path.Contains("\\"))
                                {
                                    var parts = path.Split('\\', StringSplitOptions.RemoveEmptyEntries);
                                    if (parts.Length > 1) share = parts[1];
                                }
                                
                                // Default to 'data' share if none found, as that's what setup.sh creates
                                if (string.IsNullOrEmpty(share)) share = "data";
                                
                                path = $"\\\\{ServerIp}\\{share}";
                            }
                            
                            // Ensure double backslashes for Windows UNC
                            if (!path.StartsWith("\\\\")) path = "\\\\" + path.TrimStart('\\');
                            
                            // Ensure 'data' is at the end if it's just the root
                            var pathParts = path.Split('\\', StringSplitOptions.RemoveEmptyEntries);
                            if (pathParts.Length == 1) // Just hostname/IP
                            {
                                path = path.TrimEnd('\\') + "\\data";
                            }
                            
                            SambaPath = path;
                            
                            if ((bool)config.is_default_password && string.IsNullOrEmpty(SambaPassword))
                            {
                                SambaPassword = "nomad";
                                SambaPassBox.Password = "nomad";
                            }
                            
                            UseSamba = true;
                        });
                        
                        AddLog("Samba settings synchronized successfully.");
                        if (showMessages) System.Windows.MessageBox.Show("Samba settings synchronized!", "Success", MessageBoxButton.OK, MessageBoxImage.Information);
                    }
                }
                else if (showMessages)
                {
                    System.Windows.MessageBox.Show($"Failed to sync: {res.StatusCode}", "Sync Error", MessageBoxButton.OK, MessageBoxImage.Warning);
                }
            }
            catch (Exception ex)
            {
                AddLog($"Sync failed: {ex.Message}");
                if (showMessages) System.Windows.MessageBox.Show($"Error syncing: {ex.Message}", "Sync Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private (bool success, int errorCode) ConnectToSamba(string path, string user, string pass)
        {
            var nr = new NetResource
            {
                Type = 1, // RESOURCETYPE_DISK
                RemoteName = path
            };

            // If user is empty, try connecting with null (guest/existing)
            int result = WNetAddConnection2(nr, string.IsNullOrEmpty(pass) ? null : pass, string.IsNullOrEmpty(user) ? null : user, 0);
            
            if (result == 0 || result == 1219) // 0 is success, 1219 is already connected
            {
                lock (_connectedSambaPaths)
                {
                    _connectedSambaPaths.Add(path);
                }
                return (true, result);
            }
            return (false, result);
        }

        private void SambaPassBox_PasswordChanged(object sender, RoutedEventArgs e)
        {
            SambaPassword = SambaPassBox.Password;
        }

        public bool IsTransferring { get => _isTransferring; set { _isTransferring = value; OnPropertyChanged(); } }
        public string CurrentStatus { get => _currentStatus; set { _currentStatus = value; OnPropertyChanged(); } }
        public string TransferSpeed { get => _transferSpeed; set { _transferSpeed = value; OnPropertyChanged(); } }
        public string FileProgress { get => _fileProgress; set { _fileProgress = value; OnPropertyChanged(); } }
        public double TotalProgress { get => _totalProgress; set { _totalProgress = value; OnPropertyChanged(); } }
        public double CurrentFileProgress { get => _currentFileProgress; set { _currentFileProgress = value; OnPropertyChanged(); } }
        public string AppStatus { get => _appStatus; set { _appStatus = value; OnPropertyChanged(); } }
        public ObservableCollection<string> TranscodeQueue { get => _transcodeQueue; set { _transcodeQueue = value; OnPropertyChanged(); } }
        public ObservableCollection<string> ProcessingLogs { get => _processingLogs; set { _processingLogs = value; OnPropertyChanged(); } }
        public ObservableCollection<MediaItem> ReviewQueue { get => _reviewQueue; set { _reviewQueue = value; OnPropertyChanged(); } }
        public ObservableCollection<EncodingPreset> EncodingPresets { get => _encodingPresets; set { _encodingPresets = value; OnPropertyChanged(); } }
        public EncodingPreset? SelectedGlobalPreset 
        { 
            get => _selectedGlobalPreset; 
            set { 
                _selectedGlobalPreset = value; 
                OnPropertyChanged();
                if (value != null) ApplyGlobalPreset(value);
            } 
        }
        public bool IsHandbrakeAvailable { get => _isHandbrakeAvailable; set { _isHandbrakeAvailable = value; OnPropertyChanged(); } }
        public bool DeleteSourceAfterTransfer { get => _deleteSourceAfterTransfer; set { _deleteSourceAfterTransfer = value; OnPropertyChanged(); } }
        public bool IsTranscodingEnabled { get => _isTranscodingEnabled; set { _isTranscodingEnabled = value; OnPropertyChanged(); } }

        public ObservableCollection<DriveInfoModel> Drives { get; set; } = new ObservableCollection<DriveInfoModel>();

        private long _totalRequiredSpace;
        private string _spaceWarning = "";

        public long TotalRequiredSpace { get => _totalRequiredSpace; set { _totalRequiredSpace = value; OnPropertyChanged(); OnPropertyChanged(nameof(TotalRequiredSpaceFormatted)); } }
        public string TotalRequiredSpaceFormatted => FormatSize(TotalRequiredSpace);
        public string SpaceWarning { get => _spaceWarning; set { _spaceWarning = value; OnPropertyChanged(); } }

        public MainWindow()
        {
            InitializeComponent();
            DataContext = this;
            
            _ = MonitorServerStatus();
            
            InitializePresets();
            
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
            // StartDriveWatcher();
            CheckHandbrakeStatus();

            ReviewQueue.CollectionChanged += (s, e) => UpdateSpaceRequirement();
        }

        private void UpdateSpaceRequirement()
        {
            long required = 0;
            foreach (var item in ReviewQueue)
            {
                if (IsVideoFile(item.SourcePath) && item.SelectedPreset != null && item.SelectedPreset.Bitrate > 0)
                {
                    double bytes = (item.SelectedPreset.Bitrate * 1024.0 * item.DurationSeconds) / 8.0;
                    required += (long)(bytes * 1.1); // 10% overhead
                }
                else
                {
                    try { required += new FileInfo(item.SourcePath).Length; } catch { }
                }
            }
            TotalRequiredSpace = required;

            if (DriveList.SelectedItem is DriveInfoModel drive)
            {
                // Only check space if it's a local drive (has a drive letter)
                if (Regex.IsMatch(drive.Name, @"^[a-zA-Z]:\\"))
                {
                    if (drive.AvailableFreeSpace < required)
                        SpaceWarning = $"⚠️ NOT ENOUGH SPACE! Need {FormatSize(required)}, have {FormatSize(drive.AvailableFreeSpace)}";
                    else
                        SpaceWarning = $"Estimated Space: {FormatSize(required)} / {FormatSize(drive.AvailableFreeSpace)} available";
                }
                else
                {
                    SpaceWarning = $"Estimated Space: {FormatSize(required)} (Network/Complex Drive)";
                }
            }
            else
            {
                SpaceWarning = $"Estimated Space: {FormatSize(required)}";
            }
        }

        private string FormatSize(long bytes)
        {
            string[] units = { "B", "KB", "MB", "GB", "TB" };
            double size = bytes;
            int unitIndex = 0;
            while (size >= 1024 && unitIndex < units.Length - 1)
            {
                size /= 1024;
                unitIndex++;
            }
            return $"{size:N2} {units[unitIndex]}";
        }

        private void InitializePresets()
        {
            EncodingPresets.Add(new EncodingPreset { 
                Name = "High Quality (1080p)", 
                Description = "Best for home cinema. High bitrate, original resolution.", 
                Bitrate = 4000, 
                Height = 1080,
                EstimatedReduction = "10-30%"
            });
            EncodingPresets.Add(new EncodingPreset { 
                Name = "Standard (720p)", 
                Description = "Perfect balance. Great for tablets and small TVs.", 
                Bitrate = 2000, 
                Height = 720,
                EstimatedReduction = "50-70%"
            });
            EncodingPresets.Add(new EncodingPreset { 
                Name = "Space Saver (480p)", 
                Description = "Maximize storage. Good for phones and old devices.", 
                Bitrate = 1000, 
                Height = 480,
                EstimatedReduction = "80-90%"
            });
            EncodingPresets.Add(new EncodingPreset { 
                Name = "Direct Copy (No Encode)", 
                Description = "Fastest. No quality loss, but takes most space.", 
                Bitrate = 0, 
                Height = 0,
                EstimatedReduction = "0%"
            });
            SelectedGlobalPreset = EncodingPresets[1]; // Default to 720p
        }

        private void ApplyGlobalPreset(EncodingPreset preset)
        {
            foreach (var item in ReviewQueue)
            {
                if (IsVideoFile(item.SourcePath))
                {
                    item.SelectedPreset = preset;
                }
            }
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
                client.DefaultRequestHeaders.UserAgent.ParseAdd($"NomadTransferTool/{APP_VERSION}");
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

                // 3. Verify Checksum
                if (!string.IsNullOrEmpty(checksumUrl))
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
                            if (actualHash != expectedHash) 
                            {
                                throw new Exception("Checksum verification failed! The downloaded file may be corrupted or tampered with. Extraction aborted.");
                            }
                        }
                    }
                    else
                    {
                        Debug.WriteLine("Warning: Could not find matching hash in checksum file, but continuing as checksum was present.");
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

        private void OpenWebUI_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                Process.Start(new ProcessStartInfo($"http://{ServerIp}:8000") { UseShellExecute = true });
            }
            catch (Exception ex)
            {
                System.Windows.MessageBox.Show($"Could not open browser: {ex.Message}");
            }
        }

        private async void ViewHealth_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                AddLog("Running remote health check...");
                var res = await client.GetAsync($"{API_BASE}/system/health");
                if (res.IsSuccessStatusCode)
                {
                    var content = await res.Content.ReadAsStringAsync();
                    var data = JsonConvert.DeserializeObject<dynamic>(content);
                    if (data != null)
                    {
                        AddLog($"--- Remote Health: {data.status} ---");
                        foreach (var check in data.checks)
                        {
                            string err = check.error != null ? $" (Error: {check.error})" : "";
                            AddLog($"[{check.status.ToString().ToUpper()}] {check.name}{err}");
                        }
                    }
                }
                else
                {
                    AddLog($"Health check failed: {res.StatusCode}");
                }
            }
            catch (Exception ex)
            {
                AddLog($"Error fetching health: {ex.Message}");
            }
        }

        private async void RestartRemoteService_Click(object sender, RoutedEventArgs e)
        {
            var result = System.Windows.MessageBox.Show("Are you sure you want to restart the Nomad Pi service? This will disconnect current users.", "Confirm Restart", MessageBoxButton.YesNo, MessageBoxImage.Warning);
            if (result != MessageBoxResult.Yes) return;

            try
            {
                AddLog("Sending restart command...");
                // Note: We use the standardized control endpoint. 
                // We'll add a 'reboot' action or specific 'service_restart' if needed, 
                // but usually reboot is what's wanted for a clean state.
                // However, our system.py has 'reboot' which reboots the whole Pi.
                // Let's check if we want just service restart.
                
                // Use the standardized body-based control endpoint
                var content = new StringContent(JsonConvert.SerializeObject(new { action = "restart" }), Encoding.UTF8, "application/json");
                var res = await client.PostAsync($"{API_BASE}/system/control", content);
                if (res.IsSuccessStatusCode)
                {
                    AddLog("Restart command accepted. Application is restarting...");
                    ServerStatus = "Restarting";
                    ServerStatusColor = System.Windows.Media.Brushes.Orange;
                }
                else
                {
                    AddLog($"Restart command failed: {res.StatusCode}");
                }
            }
            catch (Exception ex)
            {
                AddLog($"Error sending restart command: {ex.Message}");
            }
        }

        private async void ViewRemoteLogs_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                AddLog("Fetching remote logs...");
                var res = await client.GetAsync($"{API_BASE}/system/logs?lines=50");
                if (res.IsSuccessStatusCode)
                {
                    var content = await res.Content.ReadAsStringAsync();
                    var data = JsonConvert.DeserializeObject<dynamic>(content);
                    if (data?.logs != null)
                    {
                        AddLog("--- Remote Logs Start ---");
                        foreach (var log in data.logs)
                        {
                            AddLog($"REMOTE: {log}");
                        }
                        AddLog("--- Remote Logs End ---");
                    }
                }
                else
                {
                    AddLog($"Failed to fetch logs: {res.StatusCode}");
                }
            }
            catch (Exception ex)
            {
                AddLog($"Error fetching logs: {ex.Message}");
            }
        }

        private async Task MonitorServerStatus()
        {
            while (true)
            {
                try
                {
                    // Use the new public status endpoint
                    var res = await client.GetAsync($"{API_BASE}/system/status");
                    if (res.IsSuccessStatusCode)
                    {
                        var content = await res.Content.ReadAsStringAsync();
                        var data = JsonConvert.DeserializeObject<dynamic>(content);
                        
                        bool wasOffline = ServerStatus != "Online";
                        
                        Dispatcher.Invoke(() => {
                            ServerStatus = "Online";
                            ServerStatusColor = System.Windows.Media.Brushes.LightGreen;
                            AppStatus = $"Nomad v{data?.version ?? APP_VERSION} - Connected";
                        });

                        // Auto-sync Samba if not set
                        if (wasOffline && string.IsNullOrEmpty(SambaPath))
                        {
                            _ = SyncSambaSettings(false);
                        }
                    }
                    else
                    {
                        Dispatcher.Invoke(() => {
                            ServerStatus = "Error";
                            ServerStatusColor = System.Windows.Media.Brushes.Orange;
                            AppStatus = $"Server Error: {res.StatusCode}";
                        });
                    }
                }
                catch (Exception ex)
                {
                    Dispatcher.Invoke(() => {
                        ServerStatus = "Offline";
                        ServerStatusColor = System.Windows.Media.Brushes.Red;
                        AppStatus = "Server Offline / Unreachable";
                    });
                    Debug.WriteLine($"Status check failed: {ex.Message}");
                }
                await Task.Delay(10000); // Check every 10s
            }
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
            if (!Dispatcher.CheckAccess())
            {
                Dispatcher.Invoke(RefreshDrives);
                return;
            }

            var selectedName = (DriveList.SelectedItem as DriveInfoModel)?.Name;
            
            // Temporary list to avoid flickering/multiple UI updates
            var newDrives = new List<DriveInfoModel>();

            // 1. Add Local USB Drives
            foreach (var drive in DriveInfo.GetDrives())
            {
                if (drive.DriveType == DriveType.Removable && drive.IsReady)
                {
                    newDrives.Add(new DriveInfoModel
                    {
                        Name = drive.Name,
                        Label = string.IsNullOrEmpty(drive.VolumeLabel) ? "USB Drive" : drive.VolumeLabel,
                        TotalSize = drive.TotalSize,
                        AvailableFreeSpace = drive.AvailableFreeSpace,
                        IsMounted = Directory.Exists(Path.Combine(mediaServerDataPath, drive.Name.Replace(":\\", "")))
                    });
                }
            }

            // 2. Add Samba Share if enabled and path is valid
            if (UseSamba && !string.IsNullOrEmpty(SambaPath) && SambaPath.StartsWith("\\\\"))
            {
                try
                {
                    // For UNC paths, we use GetDiskFreeSpaceEx. 
                    // We don't use Directory.Exists here because it might block or fail if not authenticated.
                    // Instead, we try to get the space directly.
                    long freeBytes, totalBytes, totalFreeBytes;
                    bool spaceOk = GetDiskFreeSpaceEx(SambaPath, out freeBytes, out totalBytes, out totalFreeBytes);

                    newDrives.Add(new DriveInfoModel
                    {
                        Name = SambaPath,
                        Label = "Nomad Pi Network Share",
                        TotalSize = spaceOk ? totalBytes : 0,
                        AvailableFreeSpace = spaceOk ? freeBytes : 0,
                        IsMounted = true // We consider it "mounted" if Samba is enabled and path is set
                    });
                }
                catch { /* Ignore Samba drive errors */ }
            }

            // Update the ObservableCollection only if something changed
            bool changed = Drives.Count != newDrives.Count;
            if (!changed)
            {
                for (int i = 0; i < Drives.Count; i++)
                {
                    if (Drives[i].Name != newDrives[i].Name || 
                        Drives[i].AvailableFreeSpace != newDrives[i].AvailableFreeSpace ||
                        Drives[i].IsMounted != newDrives[i].IsMounted)
                    {
                        changed = true;
                        break;
                    }
                }
            }

            if (changed)
            {
                Drives.Clear();
                foreach (var d in newDrives) Drives.Add(d);
                
                if (selectedName != null)
                {
                    DriveList.SelectedItem = Drives.FirstOrDefault(d => d.Name == selectedName);
                }
            }
        }

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Auto)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetDiskFreeSpaceEx(string lpDirectoryName,
            out long lpFreeBytesAvailable,
            out long lpTotalNumberOfBytes,
            out long lpTotalNumberOfFreeBytes);

        private void StartDriveWatcher()
        {
            /* 
            try
            {
                ManagementEventWatcher watcher = new ManagementEventWatcher();
                WqlEventQuery query = new WqlEventQuery("SELECT * FROM Win32_VolumeChangeEvent WHERE EventType = 2 OR EventType = 3");
                watcher.EventArrived += (s, e) => Dispatcher.Invoke(RefreshDrives);
                watcher.Query = query;
                watcher.Start();
            }
            catch { }
            */
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
            var dialog = new Microsoft.Win32.OpenFileDialog { Multiselect = true };
            if (dialog.ShowDialog() == true) OnFilesDropped(dialog.FileNames);
        }

        private void SelectFolder_Click(object sender, RoutedEventArgs e)
        {
            var dialog = new Microsoft.Win32.OpenFileDialog { 
                CheckFileExists = false,
                CheckPathExists = true,
                FileName = "Select Folder",
                ValidateNames = false
            };
            if (dialog.ShowDialog() == true)
            {
                string? folder = Path.GetDirectoryName(dialog.FileName);
                if (folder != null) OnFilesDropped(new[] { folder });
            }
        }

        private void DropZone_DragOver(object sender, System.Windows.DragEventArgs e)
        {
            if (e.Data.GetDataPresent(System.Windows.DataFormats.FileDrop))
            {
                e.Effects = System.Windows.DragDropEffects.Copy;
            }
            else
            {
                e.Effects = System.Windows.DragDropEffects.None;
            }
            e.Handled = true;
        }

        private void Transfer_Drop(object sender, System.Windows.DragEventArgs e)
        {
            if (e.Data.GetDataPresent(System.Windows.DataFormats.FileDrop))
            {
                string[]? inputs = (string[]?)e.Data.GetData(System.Windows.DataFormats.FileDrop);
                if (inputs != null) OnFilesDropped(inputs);
            }
        }

        private void AddLog(string message)
        {
            Dispatcher.Invoke(() => {
                _processingLogs.Insert(0, $"[{DateTime.Now:HH:mm:ss}] {message}");
                if (_processingLogs.Count > 100) _processingLogs.RemoveAt(100);
            });
        }

        private void DriveList_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            UpdateDuplicateStatus();
            UpdateSpaceRequirement();
        }

        private void UpdateDuplicateStatus()
        {
            string? targetDrive = (DriveList.SelectedItem as DriveInfoModel)?.Name;
            if (targetDrive == null) return;

            foreach (var item in ReviewQueue)
            {
                UpdateItemDuplicateStatus(item, targetDrive);
            }
        }

        private void UpdateItemDuplicateStatus(MediaItem item, string targetDrive)
        {
            try
            {
                string safeTitle = string.Join("_", item.Title.Split(Path.GetInvalidFileNameChars()));
                string extension = Path.GetExtension(item.SourcePath);
                if (HandbrakeCheck.IsChecked == true && IsVideoFile(item.SourcePath)) extension = ".mp4";

                string dest;
                if (item.Category == "shows")
                {
                    dest = Path.Combine(targetDrive, item.Category, safeTitle, $"Season {item.Season.PadLeft(2, '0')}", $"{safeTitle} - S{item.Season.PadLeft(2, '0')}E{item.Episode.PadLeft(2, '0')}" + extension);
                }
                else
                {
                    string name = safeTitle;
                    if (!string.IsNullOrEmpty(item.Year)) name += $" ({item.Year})";
                    dest = Path.Combine(targetDrive, item.Category, name + extension);
                }
                item.IsDuplicate = File.Exists(dest);
            }
            catch { /* Ignore errors during status check */ }
        }

        private async void OnFilesDropped(string[] paths)
        {
            if (IsTransferring) return;

            AppStatus = "Scanning files...";
            AddLog("Scanning dropped paths...");

            // Discover files in background
            var allFiles = await Task.Run(() =>
            {
                var files = new List<string>();
                foreach (var path in paths)
                {
                    try
                    {
                        if (Directory.Exists(path))
                            files.AddRange(Directory.EnumerateFiles(path, "*.*", SearchOption.AllDirectories));
                        else if (File.Exists(path))
                            files.Add(path);
                    }
                    catch (Exception ex) { Debug.WriteLine($"Access error: {ex.Message}"); }
                }
                return files;
            });

            if (allFiles.Count == 0)
            {
                AppStatus = "No files found.";
                return;
            }

            ReviewQueue.Clear();
            AddLog($"Processing {allFiles.Count} files...");

            // Process metadata and add to UI in chunks
            int batchSize = 50;
            for (int i = 0; i < allFiles.Count; i += batchSize)
            {
                var batchFiles = allFiles.Skip(i).Take(batchSize).ToList();
                var batchItems = new List<MediaItem>();

                await Task.Run(async () =>
                {
                    foreach (var file in batchFiles)
                    {
                        try
                        {
                            var item = new MediaItem { SourcePath = file };
                            item.OriginalSize = new FileInfo(file).Length;
                            
                            string fileName = Path.GetFileNameWithoutExtension(file);
                            item.Title = fileName;
                            item.Category = GuessCategory(file);

                            if (IsVideoFile(file))
                            {
                                item.SelectedPreset = SelectedGlobalPreset;
                                item.DurationSeconds = EstimateDuration(file);
                            }

                            if (item.Category == "shows" || Regex.IsMatch(fileName, @"[sS]\d+[eE]\d+"))
                            {
                                item.Category = "shows";
                                var tvMatch = Regex.Match(fileName, @"[sS](?<sCount>\d+)[eE](?<eCount>\d+)", RegexOptions.IgnoreCase);
                                if (tvMatch.Success)
                                {
                                    item.Season = tvMatch.Groups["sCount"].Value.TrimStart('0');
                                    item.Episode = tvMatch.Groups["eCount"].Value.TrimStart('0');
                                    item.Title = fileName.Substring(0, tvMatch.Index).Trim(' ', '.', '-', '_');
                                }
                            }

                            if (!string.IsNullOrEmpty(OMDB_API_KEY) && (item.Category == "movies" || item.Category == "shows"))
                            {
                                var meta = await FetchOMDBMetadata(item.Title, item.Category);
                                if (meta != null)
                                {
                                    item.Title = meta.Title;
                                    item.Year = meta.Year;
                                }
                            }

                            batchItems.Add(item);
                        }
                        catch { }
                    }
                });

                string? targetDrive = (DriveList.SelectedItem as DriveInfoModel)?.Name;
                foreach (var item in batchItems)
                {
                    ReviewQueue.Add(item);
                    if (targetDrive != null) UpdateItemDuplicateStatus(item, targetDrive);
                    
                    if (IsHandbrakeAvailable && item.IsVideo)
                        _ = ScanTracks(item);

                    item.PropertyChanged += (s, e) => {
                        if (e.PropertyName == nameof(MediaItem.Title) || 
                            e.PropertyName == nameof(MediaItem.Category) || 
                            e.PropertyName == nameof(MediaItem.Season) || 
                            e.PropertyName == nameof(MediaItem.Episode) || 
                            e.PropertyName == nameof(MediaItem.Year))
                        {
                            var drive = (DriveList.SelectedItem as DriveInfoModel)?.Name;
                            if (drive != null) UpdateItemDuplicateStatus(item, drive);
                        }
                        
                        if (e.PropertyName == nameof(MediaItem.SelectedPreset))
                        {
                            UpdateSpaceRequirement();
                        }
                    };
                }

                AppStatus = $"Loaded {ReviewQueue.Count}/{allFiles.Count} files...";
                await Task.Yield();
            }

            AppStatus = "Ready";
            AddLog($"Finished adding {ReviewQueue.Count} items.");
        }

        private string GuessCategory(string filePath)
        {
            string ext = Path.GetExtension(filePath).ToLower();
            if (IsVideoFile(filePath)) return "movies";
            if (ext == ".mp3" || ext == ".flac" || ext == ".m4a") return "music";
            if (ext == ".jpg" || ext == ".jpeg" || ext == ".png") return "gallery";
            if (ext == ".pdf" || ext == ".epub" || ext == ".mobi") return "books";
            return "files";
        }

        private async void StartProcessing_Click(object sender, RoutedEventArgs e)
        {
            if (ReviewQueue.Count == 0 || IsTransferring) return;
            
            var items = ReviewQueue.ToList();
            ReviewQueue.Clear();
            
            _processingCts = new System.Threading.CancellationTokenSource();
            try
            {
                await ProcessMediaItems(items, _processingCts.Token);
            }
            catch (OperationCanceledException)
            {
                AddLog("Batch processing cancelled by user.");
            }
            finally
            {
                _processingCts.Dispose();
                _processingCts = null;
            }
        }

        private void StopProcessing_Click(object sender, RoutedEventArgs e)
        {
            if (IsTransferring && _processingCts != null)
            {
                _processingCts.Cancel();
                AddLog("Cancellation requested...");
                CurrentStatus = "Cancelling...";
            }
        }

        private void RemoveFromQueue_Click(object sender, RoutedEventArgs e)
        {
            if (sender is FrameworkElement element && element.DataContext is MediaItem item)
            {
                ReviewQueue.Remove(item);
                AddLog($"Removed {item.Title} from queue.");
            }
        }

        private void ClearReviewQueue_Click(object sender, RoutedEventArgs e)
        {
            ReviewQueue.Clear();
            AddLog("Review queue cleared.");
        }

        private void ApplyBulkCategory_Click(object sender, RoutedEventArgs e)
        {
            var selectedItems = ReviewListBox.SelectedItems.Cast<MediaItem>().ToList();
            if (selectedItems.Count == 0)
            {
                System.Windows.MessageBox.Show("Please select items in the list first (use Ctrl or Shift to select multiple).");
                return;
            }

            string category = (BulkCategoryCombo.SelectedItem as FrameworkElement)?.Tag?.ToString() ?? "movies";
            foreach (var item in selectedItems)
            {
                item.Category = category;
            }
            AddLog($"Applied category '{category}' to {selectedItems.Count} items.");
        }

        private async Task ScanTracks(MediaItem item)
        {
            if (!IsHandbrakeAvailable || !IsVideoFile(item.SourcePath)) return;

            try
            {
                string hbPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "HandbrakeCLI.exe");
                var process = new Process();
                process.StartInfo.FileName = hbPath;
                process.StartInfo.Arguments = $"-i \"{item.SourcePath}\" --scan";
                process.StartInfo.CreateNoWindow = true;
                process.StartInfo.UseShellExecute = false;
                process.StartInfo.RedirectStandardError = true;
                process.StartInfo.WorkingDirectory = Path.GetDirectoryName(hbPath);

                var output = new StringBuilder();
                process.ErrorDataReceived += (s, e) => { if (e.Data != null) output.AppendLine(e.Data); };
                
                process.Start();
                process.BeginErrorReadLine();
                await process.WaitForExitAsync();

                string scanData = output.ToString();
                
                // Parse Audio Tracks
                var audioMatches = Regex.Matches(scanData, @"\+ audio track (?<idx>\d+): (?<name>.*?) \((?<lang>.*?)\)");
                foreach (Match m in audioMatches)
                {
                    var track = new MediaTrack { 
                        Index = int.Parse(m.Groups["idx"].Value), 
                        Name = m.Groups["name"].Value.Trim(), 
                        Language = m.Groups["lang"].Value.Trim(),
                        Type = "audio"
                    };
                    Dispatcher.Invoke(() => item.AudioTracks.Add(track));
                }
                if (item.AudioTracks.Count > 0) item.SelectedAudioTrack = item.AudioTracks[0];

                // Parse Subtitle Tracks
                var subMatches = Regex.Matches(scanData, @"\+ subtitle track (?<idx>\d+): (?<name>.*?) \((?<lang>.*?)\)");
                foreach (Match m in subMatches)
                {
                    var track = new MediaTrack { 
                        Index = int.Parse(m.Groups["idx"].Value), 
                        Name = m.Groups["name"].Value.Trim(), 
                        Language = m.Groups["lang"].Value.Trim(),
                        Type = "subtitle"
                    };
                    Dispatcher.Invoke(() => item.SubtitleTracks.Add(track));
                }
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"Scan error: {ex.Message}");
            }
        }

        private void BulkCleanTitles_Click(object sender, RoutedEventArgs e)
        {
            var selectedItems = ReviewListBox.SelectedItems.Cast<MediaItem>().ToList();
            if (selectedItems.Count == 0)
            {
                System.Windows.MessageBox.Show("Please select items in the list first (use Ctrl or Shift to select multiple).");
                return;
            }

            foreach (var item in selectedItems)
            {
                string clean = item.Title;
                // Replace dots, underscores, dashes with spaces
                clean = Regex.Replace(clean, @"[\._\-]", " ");
                // Remove common release tags
                clean = Regex.Replace(clean, @"\b(1080p|720p|4k|2160p|bluray|web-dl|x264|h264|x265|hevc|aac|dts|remux|multi|subs|dual|extended|unrated|director.*cut)\b.*", "", RegexOptions.IgnoreCase).Trim();
                // Remove year if present at the end
                clean = Regex.Replace(clean, @"\s+\(?(19|20)\d{2}\)?$", "");
                // Clean up double spaces
                item.Title = Regex.Replace(clean, @"\s+", " ").Trim();
            }
            AddLog($"Cleaned titles for {selectedItems.Count} items.");
        }

        private async Task<(bool success, string error)> EnsurePathReady(string path)
         {
             if (string.IsNullOrEmpty(path)) return (false, "Path is empty");
             
             if (path.StartsWith("\\\\"))
             {
                 // It's a Samba path
                 if (await Task.Run(() => IsPathAccessible(path))) return (true, "");
                 
                 // Try connecting to the specific path first
                 var (success, errorCode) = await Task.Run(() => ConnectToSamba(path, SambaUser, SambaPassword));
                 if (success) return (true, "");
                 
                 // If that fails, try the base SambaPath
                 if (path != SambaPath && !string.IsNullOrEmpty(SambaPath))
                 {
                     (success, errorCode) = await Task.Run(() => ConnectToSamba(SambaPath, SambaUser, SambaPassword));
                     if (success) return (true, "");
                 }
                 
                 return (false, GetWNetErrorMessage(errorCode));
             }
             
             // For local drives, check if directory exists and is accessible
             bool exists = await Task.Run(() => IsPathAccessible(path));
             if (!exists) return (false, $"Path '{path}' is not accessible or doesn't exist.");

             return (true, "");
         }

        private async Task ProcessMediaItems(List<MediaItem> items, System.Threading.CancellationToken token)
        {
            if (items == null || items.Count == 0) return;

            string? targetPath = null;
            if (UseSamba)
            {
                if (string.IsNullOrEmpty(SambaPath))
                {
                    System.Windows.MessageBox.Show("Samba path is required when Samba transfer is enabled.", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
                    return;
                }

                // Ensure the path starts with \\
                if (!SambaPath.StartsWith("\\\\"))
                {
                    SambaPath = "\\\\" + SambaPath.TrimStart('\\');
                }
                
                // No pre-connection check here anymore. We'll connect right before moving.
                targetPath = SambaPath;
            }
            else
            {
                targetPath = (DriveList.SelectedItem as DriveInfoModel)?.Name;
            }
            
            // Disk space check (only for local drives - starts with drive letter like C:\)
            if (targetPath != null && !UseSamba && Regex.IsMatch(targetPath, @"^[a-zA-Z]:\\"))
            {
                try {
                    long requiredSpace = 0;
                    foreach (var item in items)
                    {
                        if (IsVideoFile(item.SourcePath) && item.SelectedPreset != null && item.SelectedPreset.Bitrate > 0)
                        {
                            // Use estimated size if transcoding
                            double bytes = (item.SelectedPreset.Bitrate * 1024.0 * item.DurationSeconds) / 8.0;
                            requiredSpace += (long)(bytes * 1.1); // 10% overhead
                        }
                        else
                        {
                            requiredSpace += new FileInfo(item.SourcePath).Length;
                        }
                    }
                    
                    var driveInfo = new DriveInfo(targetPath.Substring(0, 3));
                    if (driveInfo.AvailableFreeSpace < requiredSpace)
                    {
                        var result = System.Windows.MessageBox.Show(
                            $"Warning: Selected drive may not have enough space.\nRequired (est): {FormatSize(requiredSpace)}\nAvailable: {FormatSize(driveInfo.AvailableFreeSpace)}\n\nContinue anyway?", 
                            "Insufficient Space", System.Windows.MessageBoxButton.YesNo);
                        if (result == System.Windows.MessageBoxResult.No) return;
                    }
                } catch { /* Ignore space check errors for complex paths */ }
            }

            bool autoMove = targetPath != null;
            bool useHandbrake = IsHandbrakeAvailable && IsTranscodingEnabled;

            IsTransferring = true;
            TotalProgress = 0;
            TranscodeQueue.Clear();
            ProcessingLogs.Clear();
            AddLog($"Starting processing for {items.Count} items.");

            foreach (var item in items)
            {
                if (useHandbrake && IsVideoFile(item.SourcePath) && item.SelectedPreset != null && item.SelectedPreset.Bitrate > 0)
                {
                    TranscodeQueue.Add(item.FileName);
                }
            }

            int processedItems = 0;
            string tempDir = Path.Combine(Path.GetTempPath(), "NomadTranscode");
            if (!Directory.Exists(tempDir)) Directory.CreateDirectory(tempDir);

            try
            {
                foreach (var item in items)
                {
                    token.ThrowIfCancellationRequested();

                    try
                        {
                            string renamingInfo = item.Category;
                            if (!string.IsNullOrEmpty(item.Year)) renamingInfo += $" ({item.Year})";
                            AddLog($"Renaming/Sorting {item.Title} -> {renamingInfo} via OMDb data");
                            
                            item.IsProcessing = true;
                        item.StatusMessage = "Starting...";
                        item.Progress = 0;
                        
                        bool willTranscode = useHandbrake && IsVideoFile(item.SourcePath) && item.SelectedPreset != null && item.SelectedPreset.Bitrate > 0;
                        CurrentStatus = willTranscode ? $"Transcoding: {item.Title}" : $"Processing: {item.Title}";
                        CurrentFileProgress = 0;

                        string finalDest = "";
                        string safeTitle = string.Join("_", item.Title.Split(Path.GetInvalidFileNameChars()));
                        string effectiveTargetPath = targetPath ?? "";
                        
                        if (autoMove && targetPath != null)
                        {
                            // Construct the destination path
                            // User says: "connect to the main directory... use data/movie"
                            if (UseSamba)
                            {
                                // Ensure path starts with \\
                                if (!effectiveTargetPath.StartsWith("\\\\")) 
                                    effectiveTargetPath = "\\\\" + effectiveTargetPath.TrimStart('\\');

                                // Append 'data' if not already in the path
                                if (!effectiveTargetPath.ToLower().EndsWith("\\data") && !effectiveTargetPath.ToLower().Contains("\\data\\"))
                                {
                                    effectiveTargetPath = Path.Combine(effectiveTargetPath, "data");
                                }
                            }

                            string categoryDir = Path.Combine(effectiveTargetPath, item.Category);
                            string finalName = safeTitle;
                            
                            // Special handling for TV Shows (folders by Show Name -> Season)
                            if (item.Category == "shows")
                            {
                                string showDir = Path.Combine(categoryDir, safeTitle);
                                string seasonDir = Path.Combine(showDir, $"Season {item.Season.PadLeft(2, '0')}");
                                if (string.IsNullOrEmpty(item.Season)) seasonDir = showDir;
                                
                                categoryDir = seasonDir;
                                finalName = $"{safeTitle} - S{item.Season.PadLeft(2, '0')}E{item.Episode.PadLeft(2, '0')}";
                                if (string.IsNullOrEmpty(item.Season)) finalName = item.Title;
                            }
                            else if (!string.IsNullOrEmpty(item.Year))
                            {
                                finalName += $" ({item.Year})";
                            }
                            
                            string extension = Path.GetExtension(item.SourcePath);
                            if (willTranscode) extension = ".mp4";
                            
                            finalDest = Path.Combine(categoryDir, finalName + extension);

                            // Pre-check target path availability before starting long operations
                            var (ready, err) = await EnsurePathReady(effectiveTargetPath);
                            if (!ready)
                            {
                                AddLog($"Target path check failed: {err}");
                                // For local drives, if it's not ready now, it's likely disconnected
                                if (!UseSamba) throw new Exception($"Target drive '{effectiveTargetPath}' is not accessible.");
                            }
                        }

                        if (willTranscode)
                        {
                            string tempFile = Path.Combine(tempDir, Guid.NewGuid().ToString() + ".mp4");
                            try
                            {
                                AddLog($"Transcoding {item.Title}...");
                                await TranscodeWithHandbrake(item, tempFile, token);
                                
                                if (autoMove)
                                {
                                    if (string.IsNullOrEmpty(finalDest)) throw new Exception("Destination path could not be determined.");

                                    AddLog($"Moving {item.Title} to target...");
                                    CurrentStatus = $"Moving: {item.Title}";
                                    
                                    // ENSURE SAMBA CONNECTED HERE (Retry)
                                    var (ready, err) = await EnsurePathReady(effectiveTargetPath);
                                    if (!ready) throw new Exception($"Target path not ready after transcode: {err}");

                                    // CREATE DIRECTORY HERE
                                    string? finalDir = Path.GetDirectoryName(finalDest);
                                    if (finalDir != null && !Directory.Exists(finalDir)) 
                                    {
                                        AddLog($"Creating directory: {finalDir}");
                                        Directory.CreateDirectory(finalDir);
                                    }

                                    // Handle Poster if available
                                    if (!string.IsNullOrEmpty(OMDB_API_KEY) && (item.Category == "movies" || item.Category == "shows"))
                                    {
                                        try {
                                            var meta = await FetchOMDBMetadata(item.Title, item.Category);
                                            if (meta != null && !string.IsNullOrEmpty(meta.Poster) && meta.Poster != "N/A")
                                            {
                                                string safeTitleDir = string.Join("_", item.Title.Split(Path.GetInvalidFileNameChars()));
                                                string posterBase = item.Category == "shows" ? Path.Combine(effectiveTargetPath, item.Category, safeTitleDir) : Path.GetDirectoryName(finalDest)!;
                                                string posterName = item.Category == "shows" ? "poster" : Path.GetFileNameWithoutExtension(finalDest);
                                                string posterDest = Path.Combine(posterBase, posterName + ".jpg");
                                                if (!Directory.Exists(posterBase)) Directory.CreateDirectory(posterBase);
                                                await DownloadPoster(meta.Poster, posterDest);
                                            }
                                        } catch (Exception ex) { AddLog($"Poster download failed: {ex.Message}"); }
                                    }

                                    if (File.Exists(finalDest)) File.Delete(finalDest);
                                    
                                    // Retry logic for copy
                                    int retries = 3;
                                    while (retries > 0)
                                    {
                                        try {
                                            await CopyFileWithProgress(item, tempFile, finalDest, token);
                                            break;
                                        } catch (Exception ex) when (retries > 1) {
                                            retries--;
                                            AddLog($"Copy failed, retrying ({retries} left): {ex.Message}");
                                            await Task.Delay(2000, token);
                                            // Re-check path on retry
                                            await EnsurePathReady(effectiveTargetPath);
                                        }
                                    }
                                    
                                    // Delete temp file after successful transfer
                                    if (File.Exists(tempFile))
                                    {
                                        try { File.Delete(tempFile); } catch { }
                                    }
                                }
                                else
                                {
                                    AddLog($"Transcode complete for {item.Title}");
                                    string localDest = Path.Combine(Path.GetDirectoryName(item.SourcePath)!, safeTitle + ".mp4");
                                    if (File.Exists(localDest)) File.Delete(localDest);
                                    File.Move(tempFile, localDest);
                                    
                                    // Update source path to the transcoded file for consistency
                                    item.SourcePath = localDest;
                                }
                            }
                            catch (OperationCanceledException) { throw; }
                            catch (Exception ex)
                            {
                                AddLog($"Processing failed for {item.Title}: {ex.Message}");
                                item.StatusMessage = "Error: " + ex.Message;
                                if (File.Exists(tempFile))
                                {
                                    try { File.Delete(tempFile); } catch { }
                                }
                                continue; 
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
                            if (string.IsNullOrEmpty(finalDest)) throw new Exception("Destination path could not be determined.");

                            AddLog($"Copying {item.Title} to target...");
                            
                            // ENSURE SAMBA CONNECTED HERE
                            var (ready, err) = await EnsurePathReady(effectiveTargetPath);
                            if (!ready) throw new Exception($"Target path not ready: {err}");

                            // CREATE DIRECTORY HERE
                            string? finalDir = Path.GetDirectoryName(finalDest);
                            if (finalDir != null && !Directory.Exists(finalDir)) 
                            {
                                AddLog($"Creating directory: {finalDir}");
                                Directory.CreateDirectory(finalDir);
                            }

                            // Handle Poster if available
                             if (!string.IsNullOrEmpty(OMDB_API_KEY) && (item.Category == "movies" || item.Category == "shows"))
                             {
                                 try {
                                     var meta = await FetchOMDBMetadata(item.Title, item.Category);
                                     if (meta != null && !string.IsNullOrEmpty(meta.Poster) && meta.Poster != "N/A")
                                     {
                                         string safeTitleDir = string.Join("_", item.Title.Split(Path.GetInvalidFileNameChars()));
                                         string posterBase = item.Category == "shows" ? Path.Combine(effectiveTargetPath, item.Category, safeTitleDir) : Path.GetDirectoryName(finalDest)!;
                                         string posterName = item.Category == "shows" ? "poster" : Path.GetFileNameWithoutExtension(finalDest);
                                         string posterDest = Path.Combine(posterBase, posterName + ".jpg");
                                         if (!Directory.Exists(posterBase)) Directory.CreateDirectory(posterBase);
                                         await DownloadPoster(meta.Poster, posterDest);
                                     }
                                 } catch (Exception ex) { AddLog($"Poster download failed: {ex.Message}"); }
                             }

                            if (File.Exists(finalDest)) File.Delete(finalDest);
                            
                            // Retry logic for copy
                            int retries = 3;
                            while (retries > 0)
                            {
                                try {
                                    await CopyFileWithProgress(item, finalDest, token);
                                    break;
                                } catch (Exception ex) when (retries > 1) {
                                    retries--;
                                    AddLog($"Copy failed, retrying ({retries} left): {ex.Message}");
                                    await Task.Delay(2000, token);
                                    // Re-check path on retry
                                    await EnsurePathReady(effectiveTargetPath);
                                }
                            }
                        }

                        processedItems++;
                        item.IsProcessing = false;
                        item.StatusMessage = "Complete";
                        item.Progress = 100;
                        AddLog($"Completed: {item.Title}");
                        
                        // Safety check: Delete source if requested and file was actually moved/copied
                        if (DeleteSourceAfterTransfer && File.Exists(finalDest) && File.Exists(item.SourcePath))
                        {
                            try 
                            { 
                                File.Delete(item.SourcePath); 
                                AddLog($"Deleted source: {item.FileName}");
                            } 
                            catch (Exception ex) { AddLog($"Failed to delete source: {ex.Message}"); }
                        }

                        TotalProgress = (double)processedItems / items.Count * 100;
                    }
                    catch (OperationCanceledException) { throw; }
                    catch (Exception ex)
                    {
                        item.IsProcessing = false;
                        item.StatusMessage = "Error: " + ex.Message;
                        AddLog($"Error processing {item.Title}: {ex.Message}");
                    }
                }
            }
            finally
            {
                IsTransferring = false;
                CurrentStatus = "Ready";
                TotalProgress = 0;
                FileProgress = "";
                AddLog("Batch processing finished.");
                
                // Disconnect Samba if we used it
                lock (_connectedSambaPaths)
                {
                    foreach (var path in _connectedSambaPaths)
                    {
                        try { WNetCancelConnection2(path, 0, true); } catch { }
                    }
                    _connectedSambaPaths.Clear();
                }
            }
        }



        private async Task CopyFileWithProgress(MediaItem item, string source, string dest, System.Threading.CancellationToken token)
        {
            byte[] buffer = new byte[1024 * 1024]; // 1MB buffer
            long totalBytes = new FileInfo(source).Length;
            long totalRead = 0;
            
            try
            {
                using (var sourceStream = File.OpenRead(source))
                using (var destStream = File.Create(dest))
                {
                    Stopwatch sw = Stopwatch.StartNew();
                    int read;
                    while ((read = await sourceStream.ReadAsync(buffer, 0, buffer.Length, token)) > 0)
                    {
                        token.ThrowIfCancellationRequested();
                        await destStream.WriteAsync(buffer.AsMemory(0, read), token);
                        totalRead += read;
                        
                        double progress = (double)totalRead / totalBytes * 100;
                        double elapsed = sw.Elapsed.TotalSeconds;
                        double speed = elapsed > 0 ? totalRead / 1024.0 / 1024.0 / elapsed : 0;
                        
                        item.Progress = progress;
                        item.StatusMessage = $"Transferring: {progress:F1}% ({speed:F1} MB/s)";
                        
                        CurrentFileProgress = progress;
                        FileProgress = $"{totalRead / 1024 / 1024}MB / {totalBytes / 1024 / 1024}MB ({progress:F1}%)";
                        TransferSpeed = $"{speed:F1} MB/s";
                    }
                }
            }
            catch (Exception)
            {
                if (File.Exists(dest))
                {
                    try { File.Delete(dest); } catch { }
                }
                throw;
            }
        }

        private async Task CopyFileWithProgress(MediaItem item, string dest, System.Threading.CancellationToken token)
        {
            await CopyFileWithProgress(item, item.SourcePath, dest, token);
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

        public static bool IsVideoFile(string file)
        {
            string ext = Path.GetExtension(file).ToLower();
            string[] videoExts = { ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".m4v", ".flv" };
            return videoExts.Contains(ext);
        }

        private double EstimateDuration(string file)
        {
            try
            {
                long size = new FileInfo(file).Length;
                // Heuristic: typical video bitrate is ~5Mbps (625KB/s)
                // Duration = size / bitrate
                return size / (625 * 1024.0);
            }
            catch { return 0; }
        }

        private async Task TranscodeWithHandbrake(MediaItem item, string dest, System.Threading.CancellationToken token)
        {
            try
            {
                string hbPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "HandbrakeCLI.exe");
                if (!File.Exists(hbPath))
                {
                    throw new FileNotFoundException("HandbrakeCLI.exe not found. Please click 'Download' in the UI.");
                }

                var preset = item.SelectedPreset;
                if (preset == null || preset.Bitrate == 0) 
                {
                    preset = EncodingPresets[0]; // Fallback to High Quality
                }

                string encoderArgs = $"-e {_detectedEncoder}";
                int bitrate = preset.Bitrate;
                
                if (_detectedEncoder.Contains("nvenc")) 
                {
                    encoderArgs += $" -b {bitrate} -q 28 --encoder-preset slow --vfr";
                }
                else
                {
                    encoderArgs += $" -b {bitrate} -q 22 --encoder-preset fast --vfr";
                }
                
                string scaleArgs = preset.Height > 0 ? $"--maxHeight {preset.Height}" : "";
                
                string audioArgs = "-E av_aac -B 128 -6 dpl2";
                if (item.SelectedAudioTrack != null)
                {
                    audioArgs = $"-a {item.SelectedAudioTrack.Index} {audioArgs}";
                }
                
                string subArgs = "";
                if (item.SelectedSubtitleTrack != null)
                {
                    subArgs = $"--subtitle {item.SelectedSubtitleTrack.Index}";
                }
                
                string args = $"-i \"{item.SourcePath}\" -o \"{dest}\" {encoderArgs} {audioArgs} {subArgs} {scaleArgs} --format av_mp4";
                
                var process = new Process();
                process.StartInfo.FileName = hbPath;
                process.StartInfo.Arguments = args;
                process.StartInfo.CreateNoWindow = true;
                process.StartInfo.UseShellExecute = false;
                process.StartInfo.RedirectStandardError = true;
                process.StartInfo.RedirectStandardOutput = true;
                process.StartInfo.WorkingDirectory = Path.GetDirectoryName(hbPath);

                process.OutputDataReceived += (s, e) => {
                    if (e.Data != null)
                    {
                        var match = Regex.Match(e.Data, @"(\d+\.\d+)\s*%");
                        if (match.Success)
                        {
                            if (double.TryParse(match.Groups[1].Value, out double progress))
                            {
                                item.Progress = progress;
                                item.StatusMessage = $"Transcoding: {progress:F1}%";
                                
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

                using (token.Register(() => { try { process.Kill(); } catch { } }))
                {
                    var exitTask = process.WaitForExitAsync();
                    var timeoutTask = Task.Delay(TimeSpan.FromHours(4), token); // Increased timeout, added token
                    
                    var completedTask = await Task.WhenAny(exitTask, timeoutTask);
                    if (completedTask == timeoutTask)
                    {
                        if (token.IsCancellationRequested)
                        {
                            throw new OperationCanceledException(token);
                        }
                        try { process.Kill(); } catch { }
                        throw new Exception("Transcoding timed out after 4 hours.");
                    }

                    if (process.ExitCode != 0)
                    {
                        if (token.IsCancellationRequested) throw new OperationCanceledException(token);
                        throw new Exception($"Handbrake failed with exit code {process.ExitCode}");
                    }
                }
            }
            catch (OperationCanceledException) { throw; }
            catch (Exception ex)
            {
                throw new Exception($"Transcode error: {ex.Message}");
            }
        }

        private async Task TranscodeWithHandbrake(string source, string dest, System.Threading.CancellationToken token = default)
        {
            var item = new MediaItem { SourcePath = source };
            item.SelectedPreset = SelectedGlobalPreset;
            await TranscodeWithHandbrake(item, dest, token);
        }

        public class OmdbResult
        {
            public string Title { get; set; } = "";
            public string Year { get; set; } = "";
            public string Poster { get; set; } = "";
            public string Plot { get; set; } = "";
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
        
        public double PercentUsed => TotalSize > 0 ? (1.0 - (double)AvailableFreeSpace / TotalSize) * 100 : 0;
        public string SizeDisplay => $"{AvailableFreeSpace / 1024 / 1024 / 1024} GB free of {TotalSize / 1024 / 1024 / 1024} GB";
        public string StatusDisplay => IsMounted ? "Mounted to Library" : "Not Mounted";
    }

    public class EncodingPreset : INotifyPropertyChanged
    {
        public string Name { get; set; } = "";
        public string Description { get; set; } = "";
        public int Bitrate { get; set; } // kbps
        public int Height { get; set; } // 0 = original
        public string EstimatedReduction { get; set; } = "";

        public event PropertyChangedEventHandler? PropertyChanged;
        protected void OnPropertyChanged([CallerMemberName] string? name = null) => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }

    public class MediaTrack
    {
        public int Index { get; set; }
        public string Name { get; set; } = "";
        public string Language { get; set; } = "";
        public string Type { get; set; } = ""; // "audio" or "subtitle"
        public string Display => string.IsNullOrEmpty(Language) ? Name : $"[{Language}] {Name}";
    }

    public class MediaItem : INotifyPropertyChanged
    {
        private string _title = "";
        private string _year = "";
        private string _category = "movies";
        private string _plot = "";
        private string _season = "";
        private string _episode = "";
        private bool _isProcessing;
        private bool _isDuplicate;
        private double _progress;
        private string _statusMessage = "";
        private EncodingPreset? _selectedPreset;
        private long _originalSize;
        private double _durationSeconds; // estimated or fetched
        private ObservableCollection<MediaTrack> _audioTracks = new();
        private ObservableCollection<MediaTrack> _subtitleTracks = new();
        private MediaTrack? _selectedAudioTrack;
        private MediaTrack? _selectedSubtitleTrack;

        public string SourcePath { get => _sourcePath; set { _sourcePath = value; OnPropertyChanged(); OnPropertyChanged(nameof(FileName)); } }
        public string FileName => Path.GetFileName(SourcePath);
        
        private string _sourcePath = "";
        public string Title { get => _title; set { _title = value; OnPropertyChanged(); } }
        public string Year { get => _year; set { _year = value; OnPropertyChanged(); } }
        public string Category { get => _category; set { _category = value; OnPropertyChanged(); } }
        public string Plot { get => _plot; set { _plot = value; OnPropertyChanged(); } }
        public string Season { get => _season; set { _season = value; OnPropertyChanged(); } }
        public string Episode { get => _episode; set { _episode = value; OnPropertyChanged(); } }
        public bool IsProcessing { get => _isProcessing; set { _isProcessing = value; OnPropertyChanged(); } }
        public bool IsDuplicate { get => _isDuplicate; set { _isDuplicate = value; OnPropertyChanged(); } }
        public double Progress { get => _progress; set { _progress = value; OnPropertyChanged(); } }
        public string StatusMessage { get => _statusMessage; set { _statusMessage = value; OnPropertyChanged(); } }
        
        public bool IsVideo => MainWindow.IsVideoFile(SourcePath);

        public EncodingPreset? SelectedPreset 
        { 
            get => _selectedPreset; 
            set { _selectedPreset = value; OnPropertyChanged(); OnPropertyChanged(nameof(EstimatedSizeDisplay)); } 
        }

        public long OriginalSize { get => _originalSize; set { _originalSize = value; OnPropertyChanged(); OnPropertyChanged(nameof(OriginalSizeDisplay)); } }
        public double DurationSeconds { get => _durationSeconds; set { _durationSeconds = value; OnPropertyChanged(); OnPropertyChanged(nameof(EstimatedSizeDisplay)); } }

        public ObservableCollection<MediaTrack> AudioTracks { get => _audioTracks; set { _audioTracks = value; OnPropertyChanged(); } }
        public ObservableCollection<MediaTrack> SubtitleTracks { get => _subtitleTracks; set { _subtitleTracks = value; OnPropertyChanged(); } }
        
        public MediaTrack? SelectedAudioTrack { get => _selectedAudioTrack; set { _selectedAudioTrack = value; OnPropertyChanged(); } }
        public MediaTrack? SelectedSubtitleTrack { get => _selectedSubtitleTrack; set { _selectedSubtitleTrack = value; OnPropertyChanged(); } }

        public string OriginalSizeDisplay => $"{OriginalSize / 1024 / 1024} MB";
        
        public string EstimatedSizeDisplay 
        {
            get
            {
                if (SelectedPreset == null || SelectedPreset.Bitrate == 0 || DurationSeconds == 0) return OriginalSizeDisplay;
                // Size in bits = bitrate * seconds. 
                // Size in bytes = (bitrate * 1024 * seconds) / 8
                double bytes = (SelectedPreset.Bitrate * 1024.0 * DurationSeconds) / 8.0;
                // Add 10% for audio/container overhead
                bytes *= 1.1;
                return $"~{bytes / 1024 / 1024:F0} MB";
            }
        }

        public event PropertyChangedEventHandler? PropertyChanged;
        protected void OnPropertyChanged([CallerMemberName] string? name = null) => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }

    public class LongToVisibilityConverter : System.Windows.Data.IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            if (value is long l && l > 0) return Visibility.Visible;
            return Visibility.Collapsed;
        }
        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture) => throw new NotImplementedException();
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

    public class CategoryToVisibilityConverter : System.Windows.Data.IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            string category = value?.ToString() ?? "";
            string target = parameter?.ToString() ?? "";
            return category == target ? Visibility.Visible : Visibility.Collapsed;
        }
        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture) => throw new NotImplementedException();
    }

    public class InverseBooleanConverter : System.Windows.Data.IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            if (value is bool b) return !b;
            return true;
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

    public class CountToVisibilityConverter : System.Windows.Data.IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            int count = (int)value;
            int threshold = int.Parse(parameter?.ToString() ?? "0");
            
            if (threshold == 0) // Visible if 0
                return count == 0 ? Visibility.Visible : Visibility.Collapsed;
            
            return count >= threshold ? Visibility.Visible : Visibility.Collapsed;
        }
        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture) => throw new NotImplementedException();
    }

    public class IsVideoToVisibilityConverter : System.Windows.Data.IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            if (value is string path)
                return MainWindow.IsVideoFile(path) ? Visibility.Visible : Visibility.Collapsed;
            if (value is bool isVideo)
                return isVideo ? Visibility.Visible : Visibility.Collapsed;
            return Visibility.Collapsed;
        }
        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture) => throw new NotImplementedException();
    }

    public class VideoTranscodeVisibilityConverter : System.Windows.Data.IMultiValueConverter
    {
        public object Convert(object[] values, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            if (values.Length >= 2 && values[0] is bool isVideo && values[1] is bool isTranscodingEnabled)
            {
                return (isVideo && isTranscodingEnabled) ? Visibility.Visible : Visibility.Collapsed;
            }
            return Visibility.Collapsed;
        }
        public object[] ConvertBack(object value, Type[] targetTypes, object parameter, System.Globalization.CultureInfo culture) => throw new NotImplementedException();
    }
}
