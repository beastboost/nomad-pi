using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Security.Cryptography;
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

    public partial class MainWindow : Window, INotifyPropertyChanged, IDisposable
    {
        private const string APP_VERSION = "1.5.1";
        private const string DEFAULT_SERVER_IP = "nomadpi.local";
        private const string STATUS_READY = "Ready";
        private const string DATA_SHARE = "data";
        private const string OMDB_FILE = "omdb.txt";
        
        public static class Categories
        {
            public const string Movies = "movies";
            public const string Shows = "shows";
            public const string Music = "music";
            public const string Books = "books";
            public const string Gallery = "gallery";
            public const string Files = "files";
            
            public static readonly string[] All = { Movies, Shows, Music, Books, Gallery, Files };
        }

        public void Dispose()
        {
            _driveRefreshTimer?.Dispose();
            _processingCts?.Dispose();
            GC.SuppressFinalize(this);
        }

        protected override void OnClosed(EventArgs e)
         {
             Dispose();
             base.OnClosed(e);
         }

         private static readonly HttpClient client = new HttpClient();

        private string EncryptString(string plainText)
        {
            if (string.IsNullOrEmpty(plainText)) return "";
            try
            {
                byte[] data = Encoding.UTF8.GetBytes(plainText);
                byte[] encrypted = ProtectedData.Protect(data, null, DataProtectionScope.CurrentUser);
                return Convert.ToBase64String(encrypted);
            }
            catch { return ""; }
        }

        private string DecryptString(string encryptedText)
        {
            if (string.IsNullOrEmpty(encryptedText)) return "";
            try
            {
                byte[] data = Convert.FromBase64String(encryptedText);
                byte[] decrypted = ProtectedData.Unprotect(data, null, DataProtectionScope.CurrentUser);
                return Encoding.UTF8.GetString(decrypted);
            }
            catch { return encryptedText; } // Return original if not encrypted/fails
        }
        private string API_BASE => $"http://{ServerIp}:8000/api";
        private string _serverIp = DEFAULT_SERVER_IP;
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
        private string _serverUsername = "admin";
        private string _serverPassword = "";
        private string _authToken = "";
        private string _authStatus = "Not logged in";
        private readonly System.Threading.SemaphoreSlim _authSemaphore = new System.Threading.SemaphoreSlim(1, 1);

        public string ServerUsername { get => _serverUsername; set { _serverUsername = value; OnPropertyChanged(); } }
        public string AuthStatus { get => _authStatus; set { _authStatus = value; OnPropertyChanged(); } }

        // UI State
        private bool _isTransferring;
        private string _currentStatus = STATUS_READY;
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
        private readonly object _sambaConnectionLock = new object();
        private ObservableCollection<FileManagerItem> _fileManagerItems = new ObservableCollection<FileManagerItem>();
        private string _fileManagerPath = "";
        private string _fileManagerStatus = "";
        private string _fileManagerRoot = "";

        // Samba Properties
        private bool _useSamba;
        private string _sambaPath = "";
        private string _sambaUser = "";
        private string _sambaPassword = "";
        private System.Threading.Timer? _driveRefreshTimer;

        public bool UseSamba 
        { 
            get => _useSamba; 
            set { 
                _useSamba = value; 
                OnPropertyChanged(); 
                
                // Trigger drive refresh soon
                _driveRefreshTimer?.Change(300, 30000);
            } 
        }
        public string SambaPath 
        { 
            get => _sambaPath; 
            set { 
                _sambaPath = value; 
                OnPropertyChanged(); 
                _driveRefreshTimer?.Change(300, 30000);
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
                AddLog("Syncing settings from Nomad Pi...");
                
                // 1. Sync Samba
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
                                if (string.IsNullOrEmpty(share)) share = DATA_SHARE;
                                
                                path = $"\\\\{ServerIp}\\{share}";
                            }
                            
                            // Ensure double backslashes for Windows UNC
                            if (!path.StartsWith("\\\\")) path = "\\\\" + path.TrimStart('\\');
                            
                            // Ensure 'data' is at the end if it's just the root
                            var pathParts = path.Split('\\', StringSplitOptions.RemoveEmptyEntries);
                            if (pathParts.Length == 1) // Just hostname/IP
                            {
                                path = path.TrimEnd('\\') + "\\" + DATA_SHARE;
                            }
                            
                            SambaPath = path;
                            
                            if ((bool)config.is_default_password && string.IsNullOrEmpty(SambaPassword))
                            {
                                SambaPassword = "nomad";
                                SambaPassBox.Password = "nomad";
                            }
                            
                            UseSamba = true;
                        });
                        
                        AddLog("Samba settings synchronized.");
                    }
                }

                // 2. Sync OMDb Key
                var omdbRes = await client.GetAsync($"{API_BASE}/system/settings/omdb");
                if (omdbRes.IsSuccessStatusCode)
                {
                    var content = await omdbRes.Content.ReadAsStringAsync();
                    var omdbData = JsonConvert.DeserializeObject<dynamic>(content);
                    string? key = null;
                    try { key = (string?)omdbData?.key; } catch { key = null; }
                    if (!string.IsNullOrEmpty(key))
                    {
                        Dispatcher.Invoke(() => {
                            OMDB_API_KEY = key!;
                            OmdbKeyBox.Password = key!;
                            File.WriteAllText(OMDB_FILE, EncryptString(key!));
                        });
                        AddLog("OMDb API Key synchronized from Pi.");
                    }
                }

                if (showMessages) System.Windows.MessageBox.Show("Settings synchronized from Nomad Pi!", "Success", MessageBoxButton.OK, MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                AddLog($"Sync failed: {ex.Message}");
                if (showMessages) System.Windows.MessageBox.Show($"Error syncing: {ex.Message}", "Sync Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private async void SaveOmdb_Click(object sender, RoutedEventArgs e)
        {
            string key = OmdbKeyBox.Password.Trim();
            if (string.IsNullOrEmpty(key)) return;

            try {
                AddLog("Saving OMDb key and syncing to Pi...");
                OMDB_API_KEY = key;
                File.WriteAllText(OMDB_FILE, EncryptString(key));

                // Push to Pi
                var content = new StringContent(JsonConvert.SerializeObject(new { key = key }), Encoding.UTF8, "application/json");
                var res = await client.PostAsync($"{API_BASE}/system/settings/omdb", content);
                
                if (res.IsSuccessStatusCode) {
                    AddLog("OMDb key saved and synced to Pi successfully.");
                    System.Windows.MessageBox.Show("OMDb key saved and synced to Nomad Pi!", "Success", MessageBoxButton.OK, MessageBoxImage.Information);
                } else {
                    AddLog($"OMDb key saved locally, but Pi sync failed: {res.StatusCode}");
                    System.Windows.MessageBox.Show("OMDb key saved locally, but failed to sync to Pi. Check if Pi is online.", "Sync Warning", MessageBoxButton.OK, MessageBoxImage.Warning);
                }
            } catch (Exception ex) {
                AddLog($"Error saving OMDb key: {ex.Message}");
            }
        }

        private (bool success, int errorCode) ConnectToSamba(string path, string user, string pass)
        {
            lock (_sambaConnectionLock)
            {
                // Check if already connected first
                if (_connectedSambaPaths.Contains(path))
                    return (true, 0);

                var nr = new NetResource
                {
                    Type = 1, // RESOURCETYPE_DISK
                    RemoteName = path
                };

                // If user is empty, try connecting with null (guest/existing)
                int result = WNetAddConnection2(nr, string.IsNullOrEmpty(pass) ? null : pass, string.IsNullOrEmpty(user) ? null : user, 0);
                
                if (result == 0 || result == 1219) // 0 = success, 1219 = already connected
                {
                    _connectedSambaPaths.Add(path);
                    return (true, result);
                }
                return (false, result);
            }
        }

        private void SambaPassBox_PasswordChanged(object sender, RoutedEventArgs e)
        {
            SambaPassword = SambaPassBox.Password;
        }

        private void NomadPassBox_PasswordChanged(object sender, RoutedEventArgs e)
        {
            _serverPassword = NomadPassBox.Password;
        }

        private async void Login_Click(object sender, RoutedEventArgs e)
        {
            await EnsureAuthenticated(true);
        }

        private async Task<bool> EnsureAuthenticated(bool showUserErrors = false)
        {
            await _authSemaphore.WaitAsync();
            try
            {
                string tokenToCheck = _authToken?.Trim() ?? "";
                if (!string.IsNullOrWhiteSpace(tokenToCheck))
                {
                    using var req = new HttpRequestMessage(HttpMethod.Get, $"{API_BASE}/auth/check");
                    req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", tokenToCheck);
                    var checkRes = await client.SendAsync(req);
                    if (checkRes.IsSuccessStatusCode)
                    {
                        var content = await checkRes.Content.ReadAsStringAsync();
                        var data = JsonConvert.DeserializeObject<dynamic>(content);
                        bool isAuthenticated = false;
                        try { isAuthenticated = (bool?)data?.authenticated == true; } catch { isAuthenticated = false; }
                        if (isAuthenticated)
                        {
                            _authToken = tokenToCheck;
                            client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", _authToken);
                            AuthStatus = $"Logged in as {ServerUsername}";
                            return true;
                        }

                        ClearAuth();
                    }
                    else if (checkRes.StatusCode == System.Net.HttpStatusCode.Unauthorized)
                    {
                        ClearAuth();
                    }
                }

                if (string.IsNullOrWhiteSpace(ServerUsername))
                {
                    AuthStatus = "Login failed";
                    if (showUserErrors) System.Windows.MessageBox.Show("Please enter a username.", "Login Required", MessageBoxButton.OK, MessageBoxImage.Warning);
                    return false;
                }

                if (string.IsNullOrWhiteSpace(_serverPassword))
                {
                    AuthStatus = "Login failed";
                    if (showUserErrors) System.Windows.MessageBox.Show("Please enter your Nomad password.", "Login Required", MessageBoxButton.OK, MessageBoxImage.Warning);
                    return false;
                }

                AuthStatus = "Logging in...";
                var payload = JsonConvert.SerializeObject(new { username = ServerUsername, password = _serverPassword });
                using var loginContent = new StringContent(payload, Encoding.UTF8, "application/json");
                var res = await client.PostAsync($"{API_BASE}/auth/login", loginContent);
                var resBody = await res.Content.ReadAsStringAsync();

                if (!res.IsSuccessStatusCode)
                {
                    AuthStatus = "Login failed";
                    if (showUserErrors) System.Windows.MessageBox.Show($"Login failed: {res.StatusCode}", "Login Failed", MessageBoxButton.OK, MessageBoxImage.Error);
                    AddLog($"Login failed: {res.StatusCode} {resBody}");
                    return false;
                }

                var data2 = JsonConvert.DeserializeObject<dynamic>(resBody);
                string? token = null;
                try { token = (string?)data2?.token; } catch { token = null; }
                if (string.IsNullOrWhiteSpace(token))
                {
                    AuthStatus = "Login failed";
                    if (showUserErrors) System.Windows.MessageBox.Show("Login response did not include a token.", "Login Failed", MessageBoxButton.OK, MessageBoxImage.Error);
                    AddLog("Login failed: No token returned from server.");
                    return false;
                }

                _authToken = token.Trim();
                client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", _authToken);
                AuthStatus = $"Logged in as {ServerUsername}";
                AddLog("Authenticated with Nomad Pi.");
                return true;
            }
            catch (Exception ex)
            {
                AuthStatus = "Login failed";
                AddLog($"Login error: {ex.Message}");
                if (showUserErrors) System.Windows.MessageBox.Show($"Login error: {ex.Message}", "Login Failed", MessageBoxButton.OK, MessageBoxImage.Error);
                return false;
            }
            finally
            {
                _authSemaphore.Release();
            }
        }

        private void ClearAuth()
        {
            _authToken = "";
            client.DefaultRequestHeaders.Authorization = null;
            AuthStatus = "Not logged in";
        }

        private async Task<HttpResponseMessage?> GetWithAuthRetry(string url, bool showUserErrors)
        {
            if (!await EnsureAuthenticated(showUserErrors)) return null;
            var res = await SendAuthedAsync(new HttpRequestMessage(HttpMethod.Get, url), null);
            if (res.StatusCode == System.Net.HttpStatusCode.Unauthorized)
            {
                ClearAuth();
                if (!await EnsureAuthenticated(showUserErrors)) return res;
                res = await SendAuthedAsync(new HttpRequestMessage(HttpMethod.Get, url), null);
            }
            return res;
        }

        private async Task<HttpResponseMessage?> PostWithAuthRetry(string url, HttpContent? content, bool showUserErrors)
        {
            if (!await EnsureAuthenticated(showUserErrors)) return null;
            var res = await SendAuthedAsync(new HttpRequestMessage(HttpMethod.Post, url), content);
            if (res.StatusCode == System.Net.HttpStatusCode.Unauthorized)
            {
                ClearAuth();
                if (!await EnsureAuthenticated(showUserErrors)) return res;
                res = await SendAuthedAsync(new HttpRequestMessage(HttpMethod.Post, url), content);
            }
            return res;
        }

        private static async Task<HttpContent?> CloneHttpContent(HttpContent? content)
        {
            if (content == null) return null;
            var bytes = await content.ReadAsByteArrayAsync();
            var clone = new ByteArrayContent(bytes);
            foreach (var header in content.Headers)
            {
                clone.Headers.TryAddWithoutValidation(header.Key, header.Value);
            }
            return clone;
        }

        private async Task<HttpResponseMessage> SendAuthedAsync(HttpRequestMessage request, HttpContent? content)
        {
            request.Headers.Authorization = string.IsNullOrWhiteSpace(_authToken)
                ? null
                : new AuthenticationHeaderValue("Bearer", _authToken);
            request.Content = await CloneHttpContent(content);
            return await client.SendAsync(request);
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
        public ObservableCollection<FileManagerItem> FileManagerItems { get => _fileManagerItems; set { _fileManagerItems = value; OnPropertyChanged(); } }
        public string FileManagerPath { get => _fileManagerPath; set { _fileManagerPath = value; OnPropertyChanged(); } }
        public string FileManagerStatus { get => _fileManagerStatus; set { _fileManagerStatus = value; OnPropertyChanged(); } }
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
            
            client.Timeout = TimeSpan.FromMinutes(10);
            
            _ = MonitorServerStatus();
            
            InitializePresets();
            
            // Load OMDB key if exists
            if (File.Exists(OMDB_FILE)) 
            {
                OMDB_API_KEY = DecryptString(File.ReadAllText(OMDB_FILE).Trim());
                OmdbKeyBox.Password = OMDB_API_KEY;
            }

            // Try to find the media server data path
            string currentDir = AppDomain.CurrentDomain.BaseDirectory;
            DirectoryInfo? dir = new DirectoryInfo(currentDir);
            while (dir != null && !Directory.Exists(Path.Combine(dir.FullName, DATA_SHARE)))
            {
                dir = dir.Parent;
            }
            if (dir != null)
            {
                mediaServerDataPath = Path.Combine(dir.FullName, DATA_SHARE);
            }

            RefreshDrives();
            
            // Start periodic drive refresh (every 30 seconds)
            _driveRefreshTimer = new System.Threading.Timer(_ => 
            {
                RefreshDrives();
            }, null, 30000, 30000);

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
                    required += item.FileSize;
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
                var res = await PostWithAuthRetry($"{API_BASE}/system/control", content, true);
                if (res == null) return;
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
                var res = await GetWithAuthRetry($"{API_BASE}/system/logs?lines=50", true);
                if (res == null) return;
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
            string systemDrive = Path.GetPathRoot(Environment.SystemDirectory) ?? "";
            foreach (var drive in DriveInfo.GetDrives())
            {
                bool isReady;
                try { isReady = drive.IsReady; } catch { continue; }
                if (!isReady) continue;

                if (drive.DriveType != DriveType.Removable && drive.DriveType != DriveType.Fixed && drive.DriveType != DriveType.Unknown) continue;
                if (!string.IsNullOrEmpty(systemDrive) && string.Equals(drive.Name, systemDrive, StringComparison.OrdinalIgnoreCase)) continue;

                string volumeLabel = "";
                try { volumeLabel = drive.VolumeLabel; } catch { }

                long totalSize = 0;
                long freeSpace = 0;
                try { totalSize = drive.TotalSize; } catch { }
                try { freeSpace = drive.AvailableFreeSpace; } catch { }

                string defaultLabel = drive.DriveType == DriveType.Removable ? "USB Drive" : "Drive";
                if (string.IsNullOrWhiteSpace(volumeLabel)) defaultLabel = drive.DriveType == DriveType.Removable ? "USB Drive" : drive.Name.TrimEnd('\\');

                newDrives.Add(new DriveInfoModel
                {
                    Name = drive.Name,
                    Label = string.IsNullOrEmpty(volumeLabel) ? defaultLabel : volumeLabel,
                    TotalSize = totalSize,
                    AvailableFreeSpace = freeSpace,
                    IsMounted = true
                });
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

        private async void PrepareDrive_Click(object sender, RoutedEventArgs e)
        {
            if (DriveList.SelectedItem is DriveInfoModel drive)
            {
                try
                {
                    var (ready, err) = await EnsurePathReady(drive.Name);
                    if (!ready) throw new Exception(err);

                    string[] folders = Categories.All;
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

        private async void DriveList_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            UpdateDuplicateStatus();
            UpdateSpaceRequirement();

            if (DriveList.SelectedItem is DriveInfoModel drive)
            {
                _fileManagerRoot = drive.Name;
                FileManagerPath = drive.Name;
                await LoadFileManagerDirectory(FileManagerPath);
            }
        }

        private async void FileManagerRefresh_Click(object sender, RoutedEventArgs e)
        {
            await LoadFileManagerDirectory(FileManagerPath);
        }

        private async void FileManagerOpen_Click(object sender, RoutedEventArgs e)
        {
            await LoadFileManagerDirectory(FileManagerPath);
        }

        private async void FileManagerRoot_Click(object sender, RoutedEventArgs e)
        {
            if (string.IsNullOrEmpty(_fileManagerRoot)) return;
            FileManagerPath = _fileManagerRoot;
            await LoadFileManagerDirectory(FileManagerPath);
        }

        private async void FileManagerUp_Click(object sender, RoutedEventArgs e)
        {
            if (string.IsNullOrEmpty(FileManagerPath)) return;
            string p = FileManagerPath.TrimEnd('\\', '/');
            string? parent = null;
            try { parent = Path.GetDirectoryName(p); } catch { parent = null; }
            if (string.IsNullOrEmpty(parent))
            {
                if (!string.IsNullOrEmpty(_fileManagerRoot))
                {
                    FileManagerPath = _fileManagerRoot;
                    await LoadFileManagerDirectory(FileManagerPath);
                }
                return;
            }
            FileManagerPath = parent;
            await LoadFileManagerDirectory(FileManagerPath);
        }

        private async void FileManagerList_DoubleClick(object sender, System.Windows.Input.MouseButtonEventArgs e)
        {
            if (FileManagerList.SelectedItem is not FileManagerItem item) return;
            if (!item.IsDirectory) return;
            FileManagerPath = item.FullPath;
            await LoadFileManagerDirectory(FileManagerPath);
        }

        private async Task LoadFileManagerDirectory(string path)
        {
            if (string.IsNullOrEmpty(path))
            {
                FileManagerStatus = "No path selected";
                return;
            }

            var (ready, err) = await EnsurePathReady(path);
            if (!ready)
            {
                FileManagerStatus = err;
                return;
            }

            bool exists = await Task.Run(() => Directory.Exists(path));
            if (!exists)
            {
                FileManagerStatus = "Folder not found";
                return;
            }

            List<FileManagerItem> items;
            try
            {
                items = await Task.Run(() =>
                {
                    var list = new List<FileManagerItem>();
                    foreach (var entry in Directory.EnumerateFileSystemEntries(path))
                    {
                        try
                        {
                            var name = Path.GetFileName(entry);
                            if (string.IsNullOrEmpty(name)) continue;
                            bool isDir = Directory.Exists(entry);
                            long size = 0;
                            DateTime modified = DateTime.MinValue;
                            if (isDir)
                            {
                                try { modified = Directory.GetLastWriteTime(entry); } catch { modified = DateTime.MinValue; }
                            }
                            else
                            {
                                try
                                {
                                    var fi = new FileInfo(entry);
                                    size = fi.Length;
                                    modified = fi.LastWriteTime;
                                }
                                catch
                                {
                                    size = 0;
                                    modified = DateTime.MinValue;
                                }
                            }

                            list.Add(new FileManagerItem
                            {
                                Name = name,
                                FullPath = entry,
                                IsDirectory = isDir,
                                SizeBytes = size,
                                Modified = modified
                            });
                        }
                        catch { }
                    }

                    return list
                        .OrderByDescending(x => x.IsDirectory)
                        .ThenBy(x => x.Name, StringComparer.OrdinalIgnoreCase)
                        .ToList();
                });
            }
            catch (Exception ex)
            {
                FileManagerStatus = $"Failed to list folder: {ex.Message}";
                return;
            }

            Dispatcher.Invoke(() =>
            {
                FileManagerItems.Clear();
                foreach (var i in items) FileManagerItems.Add(i);
                FileManagerStatus = $"{items.Count} items";
            });
        }

        private async void DeleteSelected_Click(object sender, RoutedEventArgs e)
        {
            var selected = FileManagerList.SelectedItems.Cast<FileManagerItem>().ToList();
            if (selected.Count == 0)
            {
                System.Windows.MessageBox.Show("Select files/folders first (Ctrl/Shift for multi-select).");
                return;
            }

            var confirm = System.Windows.MessageBox.Show($"Delete {selected.Count} selected item(s)?", "Confirm Delete", MessageBoxButton.YesNo, MessageBoxImage.Warning);
            if (confirm != MessageBoxResult.Yes) return;

            int deleted = 0;
            int failed = 0;
            foreach (var item in selected)
            {
                try
                {
                    if (item.IsDirectory)
                    {
                        await Task.Run(() => Directory.Delete(item.FullPath, recursive: true));
                    }
                    else
                    {
                        await Task.Run(() => File.Delete(item.FullPath));
                    }
                    deleted++;
                }
                catch
                {
                    failed++;
                }
            }

            AddLog($"File manager delete: {deleted} deleted, {failed} failed.");
            await LoadFileManagerDirectory(FileManagerPath);
        }

        private async void RenameSelected_Click(object sender, RoutedEventArgs e)
        {
            var selected = FileManagerList.SelectedItems.Cast<FileManagerItem>().ToList();
            if (selected.Count == 0)
            {
                System.Windows.MessageBox.Show("Select files/folders first (Ctrl/Shift for multi-select).");
                return;
            }

            if (selected.Count == 1)
            {
                var item = selected[0];
                var newName = PromptForText("Rename", item.Name);
                if (string.IsNullOrWhiteSpace(newName) || newName == item.Name) return;

                string? parent;
                try { parent = Path.GetDirectoryName(item.FullPath); } catch { parent = null; }
                if (string.IsNullOrEmpty(parent)) return;

                string dest = Path.Combine(parent, newName);
                dest = EnsureUniquePath(dest, item.IsDirectory);

                try
                {
                    if (item.IsDirectory)
                        await Task.Run(() => Directory.Move(item.FullPath, dest));
                    else
                        await Task.Run(() => File.Move(item.FullPath, dest));

                    AddLog($"Renamed: {item.Name} -> {Path.GetFileName(dest)}");
                }
                catch (Exception ex)
                {
                    System.Windows.MessageBox.Show($"Rename failed: {ex.Message}");
                }

                await LoadFileManagerDirectory(FileManagerPath);
                return;
            }

            var confirm = System.Windows.MessageBox.Show($"Clean names for {selected.Count} selected item(s)?", "Batch Rename", MessageBoxButton.YesNo, MessageBoxImage.Question);
            if (confirm != MessageBoxResult.Yes) return;

            int renamed = 0;
            int skipped = 0;
            int failed = 0;

            foreach (var item in selected.OrderByDescending(x => x.IsDirectory).ThenBy(x => x.Name, StringComparer.OrdinalIgnoreCase))
            {
                try
                {
                    string? parent;
                    try { parent = Path.GetDirectoryName(item.FullPath); } catch { parent = null; }
                    if (string.IsNullOrEmpty(parent)) { skipped++; continue; }

                    string newName;
                    if (item.IsDirectory)
                    {
                        newName = CleanTitleForPath(item.Name);
                    }
                    else
                    {
                        string ext = Path.GetExtension(item.Name);
                        string baseName = Path.GetFileNameWithoutExtension(item.Name);
                        newName = CleanTitleForPath(baseName);
                        if (!string.IsNullOrEmpty(ext)) newName += ext;
                    }

                    if (string.IsNullOrWhiteSpace(newName) || string.Equals(newName, item.Name, StringComparison.OrdinalIgnoreCase))
                    {
                        skipped++;
                        continue;
                    }

                    string dest = Path.Combine(parent, newName);
                    dest = EnsureUniquePath(dest, item.IsDirectory);

                    if (item.IsDirectory)
                        await Task.Run(() => Directory.Move(item.FullPath, dest));
                    else
                        await Task.Run(() => File.Move(item.FullPath, dest));

                    renamed++;
                }
                catch
                {
                    failed++;
                }
            }

            AddLog($"File manager rename: {renamed} renamed, {skipped} skipped, {failed} failed.");
            await LoadFileManagerDirectory(FileManagerPath);
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
                bool willTranscode = HandbrakeCheck.IsChecked == true && IsVideoFile(item.SourcePath) && IsHandbrakeAvailable && IsTranscodingEnabled;
                string dest = GetDestinationPath(item, targetDrive, willTranscode);
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
                            item.FileSize = new FileInfo(file).Length;
                            
                            string fileName = Path.GetFileNameWithoutExtension(file);
                            item.Title = fileName;
                            item.Category = GuessCategory(file);

                            if (IsVideoFile(file))
                            {
                                item.SelectedPreset = SelectedGlobalPreset;
                                item.DurationSeconds = EstimateDuration(file);
                            }

                            if (item.Category == Categories.Shows || Regex.IsMatch(fileName, @"[sS]\d+[eE]\d+"))
                            {
                                item.Category = Categories.Shows;
                                if (TryParseSeasonEpisode(fileName, out var season, out var episode, out var idx))
                                {
                                    item.Season = season;
                                    item.Episode = episode;
                                    if (idx > 0 && idx <= fileName.Length)
                                        item.Title = CleanTitleForPath(fileName.Substring(0, idx).Trim(' ', '.', '-', '_'));
                                }
                            }

                            if (!string.IsNullOrEmpty(OMDB_API_KEY) && (item.Category == Categories.Movies || item.Category == Categories.Shows))
                            {
                                var inferredTitle = item.Title;
                                var meta = await FetchOMDBMetadata(inferredTitle, item.Category, item.Season);
                                if (meta != null && ShouldApplyOmdbMetadata(inferredTitle, meta, item.Category))
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

            AppStatus = STATUS_READY;
            AddLog($"Finished adding {ReviewQueue.Count} items.");
        }

        private string GuessCategory(string filePath)
        {
            string ext = Path.GetExtension(filePath).ToLower();
            if (IsVideoFile(filePath)) return Categories.Movies;
            if (ext == ".mp3" || ext == ".flac" || ext == ".m4a") return Categories.Music;
            if (ext == ".jpg" || ext == ".jpeg" || ext == ".png") return Categories.Gallery;
            if (ext == ".pdf" || ext == ".epub" || ext == ".mobi") return Categories.Books;
            return Categories.Files;
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

            string category = (BulkCategoryCombo.SelectedItem as FrameworkElement)?.Tag?.ToString() ?? Categories.Movies;
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
                var fileNameNoExt = "";
                try { fileNameNoExt = Path.GetFileNameWithoutExtension(item.SourcePath) ?? ""; } catch { fileNameNoExt = ""; }

                var inferredTitle = string.IsNullOrWhiteSpace(item.Title) ? fileNameNoExt : item.Title;

                if ((item.Category == Categories.Shows || item.Category == Categories.Movies) && string.IsNullOrEmpty(item.Year))
                {
                    var y = NormalizeYear(fileNameNoExt);
                    if (string.IsNullOrEmpty(y)) y = NormalizeYear(inferredTitle);
                    if (!string.IsNullOrEmpty(y)) item.Year = y;
                }

                if (item.Category == Categories.Shows && (string.IsNullOrEmpty(item.Season) || string.IsNullOrEmpty(item.Episode)))
                {
                    if (TryParseSeasonEpisode(fileNameNoExt, out var s, out var ep, out var idx) ||
                        TryParseSeasonEpisode(inferredTitle, out s, out ep, out idx))
                    {
                        item.Season = s;
                        item.Episode = ep;
                        if (idx > 0 && idx <= inferredTitle.Length)
                            inferredTitle = inferredTitle.Substring(0, idx).Trim(' ', '.', '-', '_');
                    }
                }

                item.Title = CleanTitleForPath(inferredTitle);
            }
            AddLog($"Cleaned titles for {selectedItems.Count} items.");
        }

        private static string CleanTitleForPath(string value)
        {
            if (string.IsNullOrWhiteSpace(value)) return "";

            string clean = value;
            clean = Regex.Replace(clean, @"[\._\-]", " ");
            clean = Regex.Replace(clean, @"(?i)\b(?:www\.)?(?:uindex|unidex)\.(?:org|com|net)\b", " ");
            clean = Regex.Replace(clean, @"(?i)\b(?:www\s*)?(?:uindex|unidex)\s*(?:org|com|net)\b", " ");
            clean = Regex.Replace(clean, @"(?i)^\s*(?:www\s*)?(?:uindex|unidex)\s*(?:org|com|net)\s*", "");
            clean = Regex.Replace(clean, @"\b(1080p|720p|4k|2160p|bluray|web-dl|webdl|webrip|x264|h264|x265|hevc|aac|dts|remux|multi|subs|dual|extended|unrated|director.*cut)\b", " ", RegexOptions.IgnoreCase);
            clean = Regex.Replace(clean, @"\s+", " ").Trim();

            foreach (var ch in Path.GetInvalidFileNameChars())
            {
                clean = clean.Replace(ch, ' ');
            }
            clean = Regex.Replace(clean, @"\s+", " ").Trim();
            clean = clean.TrimEnd('.', ' ');
            return clean;
        }

        private static bool TryParseSeasonEpisode(string fileNameNoExt, out string season, out string episode, out int matchIndex)
        {
            season = "";
            episode = "";
            matchIndex = 0;
            if (string.IsNullOrWhiteSpace(fileNameNoExt)) return false;

            var patterns = new[]
            {
                @"(?i)\bS(?<s>\d{1,2})\s*E(?<e>\d{1,3})\b",
                @"(?i)\b(?<s>\d{1,2})x(?<e>\d{1,3})\b",
                @"(?i)\bseason\W*(?<s>\d{1,2})\W*(?:episode|ep)\W*(?<e>\d{1,3})\b",
            };

            foreach (var pat in patterns)
            {
                var m = Regex.Match(fileNameNoExt, pat);
                if (!m.Success) continue;

                var s = m.Groups["s"].Value;
                var e = m.Groups["e"].Value;

                if (int.TryParse(s, out var sNum)) season = sNum.ToString();
                else season = s.TrimStart('0');
                if (int.TryParse(e, out var eNum)) episode = eNum.ToString();
                else episode = e.TrimStart('0');

                if (string.IsNullOrEmpty(season) || string.IsNullOrEmpty(episode)) continue;
                matchIndex = m.Index;
                return true;
            }

            return false;
        }

        private static string EnsureUniquePath(string desiredPath, bool isDirectory)
        {
            if (string.IsNullOrEmpty(desiredPath)) return desiredPath;

            bool exists;
            try
            {
                exists = isDirectory ? Directory.Exists(desiredPath) : File.Exists(desiredPath);
            }
            catch
            {
                exists = true;
            }
            if (!exists) return desiredPath;

            string? parent;
            try { parent = Path.GetDirectoryName(desiredPath); } catch { parent = null; }
            if (string.IsNullOrEmpty(parent)) return desiredPath;

            string name = isDirectory ? Path.GetFileName(desiredPath) : Path.GetFileNameWithoutExtension(desiredPath);
            string ext = isDirectory ? "" : Path.GetExtension(desiredPath);
            if (string.IsNullOrEmpty(name)) name = "Item";

            for (int i = 1; i < 1000; i++)
            {
                string candidate = Path.Combine(parent, $"{name} ({i}){ext}");
                try
                {
                    bool candidateExists = isDirectory ? Directory.Exists(candidate) : File.Exists(candidate);
                    if (!candidateExists) return candidate;
                }
                catch { }
            }
            return desiredPath;
        }

        private static string? PromptForText(string title, string initialValue)
        {
            var win = new Window
            {
                Title = title,
                Width = 420,
                Height = 160,
                WindowStartupLocation = WindowStartupLocation.CenterOwner,
                ResizeMode = ResizeMode.NoResize,
                Background = System.Windows.Media.Brushes.White,
                Foreground = System.Windows.Media.Brushes.Black
            };

            var root = new Grid { Margin = new Thickness(12) };
            root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

            var label = new TextBlock { Text = "New name", Margin = new Thickness(0, 0, 0, 6) };
            Grid.SetRow(label, 0);
            root.Children.Add(label);

            var box = new TextBox { Text = initialValue, Margin = new Thickness(0, 0, 0, 10) };
            Grid.SetRow(box, 1);
            root.Children.Add(box);

            var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
            var ok = new Button { Content = "OK", Width = 80, Margin = new Thickness(0, 0, 8, 0) };
            var cancel = new Button { Content = "Cancel", Width = 80 };
            buttons.Children.Add(ok);
            buttons.Children.Add(cancel);
            Grid.SetRow(buttons, 2);
            root.Children.Add(buttons);

            string? result = null;
            ok.Click += (_, __) => { result = box.Text; win.DialogResult = true; };
            cancel.Click += (_, __) => { win.DialogResult = false; };
            win.Content = root;
            win.Loaded += (_, __) => { box.Focus(); box.SelectAll(); };
            win.ShowDialog();

            return result;
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

        private string GetDestinationPath(MediaItem item, string targetRoot, bool willTranscode)
        {
            string safeTitle = CleanTitleForPath(item.Title);
            if (string.IsNullOrWhiteSpace(safeTitle)) safeTitle = "Untitled";

            string categoryDir = Path.Combine(targetRoot, item.Category);
            string finalName = safeTitle;

            if (item.Category == Categories.Shows)
            {
                string showDir = Path.Combine(categoryDir, safeTitle);
                string seasonValue = NormalizeNumericString(item.Season, 2);
                string episodeValue = NormalizeNumericString(item.Episode, 2);

                string seasonDir = Path.Combine(showDir, $"Season {seasonValue}");
                if (string.IsNullOrEmpty(seasonValue)) seasonDir = showDir;

                categoryDir = seasonDir;
                if (!string.IsNullOrEmpty(seasonValue) && !string.IsNullOrEmpty(episodeValue))
                    finalName = $"{safeTitle} - S{seasonValue}E{episodeValue}";
                else
                    finalName = safeTitle;
            }
            else if (item.Category == Categories.Movies)
            {
                var year = NormalizeYear(item.Year);
                if (!string.IsNullOrEmpty(year))
                {
                    string movieFolder = $"{safeTitle} ({year})";
                    categoryDir = Path.Combine(categoryDir, movieFolder);
                    finalName = $"{safeTitle} ({year})";
                }
                else
                {
                    categoryDir = Path.Combine(categoryDir, safeTitle);
                    finalName = safeTitle;
                }
            }

            string extension = Path.GetExtension(item.SourcePath);
            if (willTranscode) extension = ".mp4";

            return Path.Combine(categoryDir, finalName + extension);
        }

        private static string NormalizeNumericString(string? value, int width)
        {
            if (string.IsNullOrWhiteSpace(value)) return "";
            var m = Regex.Match(value, @"\d+");
            if (!m.Success) return "";
            if (int.TryParse(m.Value, out var num)) return num.ToString().PadLeft(width, '0');
            return m.Value.PadLeft(width, '0');
        }

        private static string NormalizeYear(string? value)
        {
            if (string.IsNullOrWhiteSpace(value)) return "";
            var m = Regex.Match(value, @"\b(19|20)\d{2}\b");
            return m.Success ? m.Value : "";
        }

        private async Task CreateDirectoryIfNotExists(string path)
        {
            if (string.IsNullOrEmpty(path)) return;
            bool exists = await Task.Run(() => Directory.Exists(path));
            if (!exists)
            {
                AddLog($"Creating directory: {path}");
                await Task.Run(() => Directory.CreateDirectory(path));
            }
        }

        private async Task HandlePosterDownload(MediaItem item, string finalDest, string effectiveTargetPath)
        {
            if (string.IsNullOrEmpty(OMDB_API_KEY) || (item.Category != Categories.Movies && item.Category != Categories.Shows))
                return;

            try
            {
                var meta = await FetchOMDBMetadata(item.Title, item.Category, item.Season);
                if (meta != null && ShouldApplyOmdbMetadata(item.Title, meta, item.Category) && !string.IsNullOrEmpty(meta.Poster) && meta.Poster != "N/A")
                {
                    string safeTitleDir = CleanTitleForPath(item.Title);
                    if (string.IsNullOrWhiteSpace(safeTitleDir)) safeTitleDir = "Untitled";
                    string posterBase;
                    string posterName;

                    if (item.Category == Categories.Shows)
                    {
                        if (!string.IsNullOrEmpty(item.Season))
                        {
                            // Season-specific poster goes in Season folder
                            posterBase = Path.GetDirectoryName(finalDest)!;
                            posterName = "poster";
                        }
                        else
                        {
                            // Show-level poster goes in Show folder
                            posterBase = Path.Combine(effectiveTargetPath, item.Category, safeTitleDir);
                            posterName = "poster";
                        }
                    }
                    else
                    {
                        // Movie poster matches file name in same folder
                        posterBase = Path.GetDirectoryName(finalDest)!;
                        posterName = Path.GetFileNameWithoutExtension(finalDest);
                    }

                    string posterDest = Path.Combine(posterBase, posterName + ".jpg");

                    bool posterExists = await Task.Run(() => File.Exists(posterDest));
                    if (posterExists) return;

                    await CreateDirectoryIfNotExists(posterBase);
                    await DownloadPoster(meta.Poster, posterDest);
                }
            }
            catch (Exception ex)
            {
                AddLog($"Poster download failed: {ex.Message}");
            }
        }

        private async Task<bool> CopyExistingPosterFiles(MediaItem item, string sourcePath, string finalDest, System.Threading.CancellationToken token)
        {
            try
            {
                token.ThrowIfCancellationRequested();
                string? sourceDir = Path.GetDirectoryName(sourcePath);
                string? destDir = Path.GetDirectoryName(finalDest);
                if (string.IsNullOrEmpty(sourceDir) || string.IsNullOrEmpty(destDir)) return false;

                string srcBase = Path.GetFileNameWithoutExtension(sourcePath);
                string destBase = Path.GetFileNameWithoutExtension(finalDest);
                bool copiedAny = false;

                async Task<bool> copyIfExists(string src, string dest)
                {
                    token.ThrowIfCancellationRequested();
                    try
                    {
                        bool exists = await Task.Run(() => File.Exists(src), token);
                        if (!exists) return false;

                        bool destExists = await Task.Run(() => File.Exists(dest), token);
                        if (destExists) return false;

                        await Task.Run(() =>
                        {
                            Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
                            File.Copy(src, dest, overwrite: false);
                        }, token);
                        return true;
                    }
                    catch
                    {
                        return false;
                    }
                }

                if (item.Category == Categories.Movies)
                {
                    var baseCandidates = new[]
                    {
                        Path.Combine(sourceDir, srcBase + ".jpg"),
                        Path.Combine(sourceDir, srcBase + ".jpeg"),
                        Path.Combine(sourceDir, srcBase + ".png"),
                    };

                    foreach (var src in baseCandidates)
                    {
                        string ext = Path.GetExtension(src).ToLowerInvariant();
                        string destExt = ext == ".png" ? ".png" : ".jpg";
                        string dest = Path.Combine(destDir, destBase + destExt);

                        if (await copyIfExists(src, dest))
                        {
                            copiedAny = true;
                            break;
                        }
                    }

                    var folderCandidates = new[]
                    {
                        ("poster.jpg", "poster.jpg"),
                        ("poster.jpeg", "poster.jpeg"),
                        ("poster.png", "poster.png"),
                        ("folder.jpg", "folder.jpg"),
                        ("folder.png", "folder.png"),
                        ("cover.jpg", "cover.jpg"),
                        ("cover.png", "cover.png"),
                    };
                    foreach (var (name, destName) in folderCandidates)
                    {
                        if (await copyIfExists(Path.Combine(sourceDir, name), Path.Combine(destDir, destName)))
                        {
                            copiedAny = true;
                        }
                    }
                }
                else if (item.Category == Categories.Shows)
                {
                    var baseCandidates = new[]
                    {
                        Path.Combine(sourceDir, srcBase + ".jpg"),
                        Path.Combine(sourceDir, srcBase + ".jpeg"),
                        Path.Combine(sourceDir, srcBase + ".png"),
                    };
                    foreach (var src in baseCandidates)
                    {
                        string ext = Path.GetExtension(src).ToLowerInvariant();
                        string destExt = ext == ".png" ? ".png" : ".jpg";
                        string dest = Path.Combine(destDir, destBase + destExt);
                        if (await copyIfExists(src, dest))
                        {
                            copiedAny = true;
                            break;
                        }
                    }

                    var folderCandidates = new[]
                    {
                        "poster.jpg",
                        "poster.jpeg",
                        "poster.png",
                        "folder.jpg",
                        "folder.png",
                        "cover.jpg",
                        "cover.png",
                    };
                    foreach (var name in folderCandidates)
                    {
                        if (await copyIfExists(Path.Combine(sourceDir, name), Path.Combine(destDir, name)))
                        {
                            copiedAny = true;
                        }
                    }

                    try
                    {
                        var srcParent = Directory.GetParent(sourceDir)?.FullName;
                        var destParent = Directory.GetParent(destDir)?.FullName;
                        if (!string.IsNullOrEmpty(srcParent) && !string.IsNullOrEmpty(destParent))
                        {
                            foreach (var name in folderCandidates)
                            {
                                if (await copyIfExists(Path.Combine(srcParent, name), Path.Combine(destParent, name)))
                                {
                                    copiedAny = true;
                                }
                            }
                        }
                    }
                    catch { }
                }

                return copiedAny;
            }
            catch
            {
                return false;
            }
        }

        private async Task ProcessMediaItems(IEnumerable<MediaItem> items, System.Threading.CancellationToken token)
        {
            if (items == null || items.Count() == 0) return;

            string? targetPath = null;
            bool effectiveUseSamba = false;
            long requiredSpace = 0;

            // Calculate total required space first
            if (items != null)
            {
                foreach (var item in items!)
                {
                    if (IsVideoFile(item.SourcePath) && item.SelectedPreset != null && item.SelectedPreset.Bitrate > 0)
                    {
                        double bytes = (item.SelectedPreset.Bitrate * 1024.0 * item.DurationSeconds) / 8.0;
                        requiredSpace += (long)(bytes * 1.1);
                    }
                    else
                    {
                        requiredSpace += item.FileSize;
                    }
                }
            }

            var selectedDrive = DriveList.SelectedItem as DriveInfoModel;

            if (selectedDrive != null && !string.IsNullOrWhiteSpace(selectedDrive.Name))
            {
                targetPath = selectedDrive.Name;
                effectiveUseSamba = targetPath.StartsWith("\\\\");
            }
            else if (UseSamba && !string.IsNullOrWhiteSpace(SambaPath))
            {
                targetPath = SambaPath;
                if (!targetPath.StartsWith("\\\\"))
                    targetPath = "\\\\" + targetPath.TrimStart('\\');

                effectiveUseSamba = targetPath.StartsWith("\\\\");
            }

            if (effectiveUseSamba)
            {
                if (string.IsNullOrWhiteSpace(targetPath))
                {
                    System.Windows.MessageBox.Show("Select a destination or configure a Samba path.", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
                    return;
                }

                // Check for Samba Failover (10% threshold)
                try {
                    long freeBytes, totalBytes, totalFreeBytes;
                    if (GetDiskFreeSpaceEx(targetPath, out freeBytes, out totalBytes, out totalFreeBytes) && totalBytes > 0)
                    {
                        double percentFree = (double)freeBytes / totalBytes;
                        if (percentFree < 0.10)
                        {
                            AddLog($"Samba share is low on space ({percentFree:P1} free). Checking for USB failover...");
                            // Look for a USB drive with enough space
                            var usbDrive = Drives.FirstOrDefault(d =>
                                !string.IsNullOrWhiteSpace(d.Name) &&
                                !d.Name.StartsWith("\\\\") &&
                                d.IsMounted &&
                                d.AvailableFreeSpace > requiredSpace);
                            if (usbDrive != null)
                            {
                                AddLog($"FAILOVER: Switching to USB drive {usbDrive.Name} ({usbDrive.Label}) as fail-safe.");
                                targetPath = usbDrive.Name;
                                effectiveUseSamba = false;
                            }
                            else
                            {
                                AddLog("Failover failed: No USB drive with sufficient space found.");
                            }
                        }
                    }
                } catch (Exception ex) { AddLog($"Failover check error: {ex.Message}"); }
            }
            
            // Disk space check (only for local drives - starts with drive letter like C:\)
            if (targetPath != null && !effectiveUseSamba && Regex.IsMatch(targetPath, @"^[a-zA-Z]:\\"))
            {
                try {
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
            AddLog($"Starting processing for {items!.Count()} items.");

            foreach (var item in items!)
            {
                if (useHandbrake && IsVideoFile(item.SourcePath) && item.SelectedPreset != null && item.SelectedPreset.Bitrate > 0)
                {
                    TranscodeQueue.Add(item.FileName);
                }
            }

            int processedItems = 0;
            string tempDir = Path.Combine(Path.GetTempPath(), "NomadTranscode");
            if (!Directory.Exists(tempDir)) Directory.CreateDirectory(tempDir);

            var tempFilesToClean = new List<string>();

            try
            {
                foreach (var item in items!)
                {
                    token.ThrowIfCancellationRequested();
                    string safeTitle = CleanTitleForPath(item.Title);
                    if (string.IsNullOrWhiteSpace(safeTitle)) safeTitle = "Untitled";
                    string? tempFile = null;

                    try
                    {
                        string renamingInfo = item.Category;
                        if (!string.IsNullOrEmpty(item.Year)) renamingInfo += $" ({item.Year})";
                        AddLog($"Sorting: {item.Title} → {renamingInfo}");
                        
                        item.IsProcessing = true;
                        item.StatusMessage = "Starting...";
                        item.Progress = 0;
                        
                        bool willTranscode = useHandbrake && IsVideoFile(item.SourcePath) && item.SelectedPreset != null && item.SelectedPreset.Bitrate > 0;
                        CurrentStatus = willTranscode ? $"Transcoding: {item.Title}" : $"Processing: {item.Title}";
                        CurrentFileProgress = 0;

                        string finalDest = "";
                        string effectiveTargetPath = targetPath ?? "";
                        
                        if (autoMove && targetPath != null)
                        {
                            if (effectiveUseSamba)
                            {
                                if (!effectiveTargetPath.StartsWith("\\\\")) 
                                    effectiveTargetPath = "\\\\" + effectiveTargetPath.TrimStart('\\');

                                if (!effectiveTargetPath.ToLower().EndsWith("\\" + DATA_SHARE) && !effectiveTargetPath.ToLower().Contains("\\" + DATA_SHARE + "\\"))
                                {
                                    effectiveTargetPath = Path.Combine(effectiveTargetPath, DATA_SHARE);
                                }
                            }

                            finalDest = GetDestinationPath(item, effectiveTargetPath, willTranscode);

                            // Pre-check target path availability before starting long operations
                            var (ready, err) = await EnsurePathReady(effectiveTargetPath);
                            if (!ready)
                            {
                                AddLog($"Target path check failed: {err}");
                                if (!effectiveUseSamba) throw new Exception($"Target drive '{effectiveTargetPath}' is not accessible.");
                            }
                        }

                        if (willTranscode)
                        {
                            tempFile = Path.Combine(tempDir, Guid.NewGuid().ToString() + ".mp4");
                            tempFilesToClean.Add(tempFile);
                            
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
                                    if (finalDir != null) 
                                    {
                                        bool exists = await Task.Run(() => Directory.Exists(finalDir));
                                        if (!exists)
                                        {
                                            AddLog($"Creating directory: {finalDir}");
                                            await Task.Run(() => Directory.CreateDirectory(finalDir));
                                        }
                                    }

                                    _ = await CopyExistingPosterFiles(item, item.SourcePath, finalDest, token);
                                    await HandlePosterDownload(item, finalDest, effectiveTargetPath);

                                    if (finalDest != null)
                                    {
                                        bool destExists = await Task.Run(() => File.Exists(finalDest));
                                        if (destExists) await Task.Run(() => File.Delete(finalDest));
                                    }
                                    
                                    // Retry logic for copy
                                    int retries = 3;
                                    bool copySuccess = false;
                                    while (retries > 0)
                                    {
                                        try {
                                            await CopyFileWithProgress(item, tempFile, finalDest!, token);
                                            copySuccess = true;
                                            break;
                                        } catch (Exception ex) when (retries > 1) {
                                            retries--;
                                            AddLog($"Copy failed, retrying ({retries} left): {ex.Message}");
                                            await Task.Delay(2000, token);
                                            // Re-check path on retry
                                            await EnsurePathReady(effectiveTargetPath);
                                        }
                                    }
                                    
                                    // Delete temp file ONLY after successful transfer
                                    if (copySuccess && File.Exists(tempFile))
                                    {
                                        try { File.Delete(tempFile); tempFilesToClean.Remove(tempFile); } catch { }
                                    }
                                    else if (!copySuccess)
                                    {
                                        throw new Exception("Failed to copy transcoded file to destination after multiple retries.");
                                    }
                                }
                                else
                                {
                                    AddLog($"Transcode complete for {item.Title}");
                                    string localDest = Path.Combine(Path.GetDirectoryName(item.SourcePath)!, safeTitle + ".mp4");
                                    if (File.Exists(localDest)) File.Delete(localDest);
                                    File.Move(tempFile, localDest);
                                    tempFilesToClean.Remove(tempFile);
                                    
                                    // Update source path to the transcoded file for consistency
                                    item.SourcePath = localDest;
                                }
                            }
                            catch (OperationCanceledException) { throw; }
                            catch (Exception ex)
                            {
                                AddLog($"Processing failed for {item.Title}: {ex.Message}");
                                item.StatusMessage = "Error: " + ex.Message;
                                if (tempFile != null && File.Exists(tempFile))
                                {
                                    try { File.Delete(tempFile); tempFilesToClean.Remove(tempFile); } catch { }
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
                            if (finalDir != null) 
                            {
                                bool exists = await Task.Run(() => Directory.Exists(finalDir));
                                if (!exists)
                                {
                                    AddLog($"Creating directory: {finalDir}");
                                    await Task.Run(() => Directory.CreateDirectory(finalDir));
                                }
                            }

                            _ = await CopyExistingPosterFiles(item, item.SourcePath, finalDest, token);
                            await HandlePosterDownload(item, finalDest, effectiveTargetPath);

                            if (finalDest != null)
                            {
                                bool destExists = await Task.Run(() => File.Exists(finalDest));
                                if (destExists) await Task.Run(() => File.Delete(finalDest));
                            }
                            
                            // Retry logic for copy
                            int retries = 3;
                            while (retries > 0)
                            {
                                try {
                                    await CopyFileWithProgress(item, item.SourcePath, finalDest!, token);
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
                        if (DeleteSourceAfterTransfer && finalDest != null)
                        {
                            bool finalExists = await Task.Run(() => File.Exists(finalDest));
                            bool sourceExists = await Task.Run(() => File.Exists(item.SourcePath));
                            
                            if (finalExists && sourceExists)
                            {
                                try 
                                { 
                                    await Task.Run(() => File.Delete(item.SourcePath)); 
                                    AddLog($"Deleted source: {item.FileName}");
                                } 
                                catch (Exception ex) { AddLog($"Failed to delete source: {ex.Message}"); }
                            }
                        }

                        TotalProgress = (double)processedItems / items!.Count() * 100;
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
                
                // Trigger background library scan on the server
                _ = Task.Run(async () => {
                    try {
                        AddLog("Triggering server library scan...");
                        if (!await EnsureAuthenticated(false))
                        {
                            AddLog("Server library scan requires login. Open Nomad Login and sign in.");
                            return;
                        }
                        var response = await PostWithAuthRetry($"{API_BASE}/media/scan", null, false);
                        if (response == null) return;
                        if (response.IsSuccessStatusCode) AddLog("Server library scan started.");
                        else AddLog($"Server library scan trigger failed: {response.StatusCode}");
                    } catch (Exception ex) {
                        AddLog($"Failed to trigger server scan: {ex.Message}");
                    }
                });

                // Final cleanup of any missed temp files
                foreach (var tempFile in tempFilesToClean.ToList())
                {
                    try { if (File.Exists(tempFile)) File.Delete(tempFile); } catch { }
                }
                tempFilesToClean.Clear();

                // Disconnect Samba if we used it
                lock (_sambaConnectionLock)
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
            byte[] buffer = new byte[4 * 1024 * 1024]; // 4MB buffer for better throughput
            long totalBytes = new FileInfo(source).Length;
            long totalRead = 0;
            
            try
            {
                using (var sourceStream = File.OpenRead(source))
                using (var destStream = File.Create(dest))
                {
                    Stopwatch sw = Stopwatch.StartNew();
                    Stopwatch uiSw = Stopwatch.StartNew();
                    int read;
                    double lastReportedProgress = -1;

                    while ((read = await sourceStream.ReadAsync(buffer, 0, buffer.Length, token)) > 0)
                    {
                        token.ThrowIfCancellationRequested();
                        await destStream.WriteAsync(buffer.AsMemory(0, read), token);
                        totalRead += read;
                        
                        double progress = (double)totalRead / totalBytes * 100;
                        
                        // Throttle UI updates to every 250ms or every 1% to prevent flooding the UI thread
                        if (uiSw.ElapsedMilliseconds > 250 || progress - lastReportedProgress > 1.0 || totalRead == totalBytes)
                        {
                            double elapsed = sw.Elapsed.TotalSeconds;
                            double speed = elapsed > 0.1 ? totalRead / 1024.0 / 1024.0 / elapsed : 0;
                            lastReportedProgress = progress;
                            uiSw.Restart();

                            // Thread-safe UI updates with higher priority than Background to ensure responsiveness
                            await Dispatcher.InvokeAsync(() =>
                            {
                                item.Progress = progress;
                                item.StatusMessage = $"Transferring: {progress:F1}% ({speed:F1} MB/s)";
                                CurrentFileProgress = progress;
                                FileProgress = $"{totalRead / 1024 / 1024}MB / {totalBytes / 1024 / 1024}MB ({progress:F1}%)";
                                TransferSpeed = $"{speed:F1} MB/s";
                            }, System.Windows.Threading.DispatcherPriority.Normal);
                        }
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

        private static bool ShouldApplyOmdbMetadata(string inferredTitle, OmdbResult meta, string category)
        {
            if (string.IsNullOrWhiteSpace(inferredTitle)) return false;
            if (meta == null || string.IsNullOrWhiteSpace(meta.Title)) return false;

            if (category != Categories.Shows) return true;

            var a = NormalizeForTitleComparison(inferredTitle);
            var b = NormalizeForTitleComparison(meta.Title);
            if (string.IsNullOrEmpty(a) || string.IsNullOrEmpty(b)) return false;
            if (a == b) return true;

            if (a.Length < 4) return false;

            var sim = GetJaccardSimilarity(a, b);
            return sim >= 0.70;
        }

        private static string NormalizeForTitleComparison(string value)
        {
            if (string.IsNullOrWhiteSpace(value)) return "";
            var s = value.Trim().ToLowerInvariant();
            s = Regex.Replace(s, @"[\._\-]+", " ");
            s = Regex.Replace(s, @"[^\w\s]+", " ");
            s = Regex.Replace(s, @"\s+", " ").Trim();
            return s;
        }

        private static double GetJaccardSimilarity(string a, string b)
        {
            var aWords = new HashSet<string>();
            foreach (Match m in Regex.Matches(a, @"\w+"))
            {
                if (!string.IsNullOrEmpty(m.Value)) aWords.Add(m.Value);
            }

            var bWords = new HashSet<string>();
            foreach (Match m in Regex.Matches(b, @"\w+"))
            {
                if (!string.IsNullOrEmpty(m.Value)) bWords.Add(m.Value);
            }
            if (aWords.Count == 0 || bWords.Count == 0) return 0.0;

            int intersection = 0;
            foreach (var w in aWords)
            {
                if (bWords.Contains(w)) intersection++;
            }

            var union = aWords.Count + bWords.Count - intersection;
            return union <= 0 ? 0.0 : (double)intersection / union;
        }

        private async Task<OmdbResult?> FetchOMDBMetadata(string fileName, string category, string? season = null)
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

                string type = category == Categories.Movies ? "movie" : "series";
                
                // Construct URL
                string url = $"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&t={Uri.EscapeDataString(title)}&type={type}";
                if (!string.IsNullOrEmpty(season)) url += $"&Season={season}";
                else if (!string.IsNullOrEmpty(year)) url += $"&y={year}";
                
                var response = await client.GetStringAsync(url);
                var result = JsonConvert.DeserializeObject<OmdbResult>(response);
                
                // Fallback for shows if season poster fails
                if (result?.Response != "True" && !string.IsNullOrEmpty(season))
                {
                    url = $"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&t={Uri.EscapeDataString(title)}&type={type}";
                    response = await client.GetStringAsync(url);
                    result = JsonConvert.DeserializeObject<OmdbResult>(response);
                }

                if ((result == null || result.Response != "True") && !string.IsNullOrEmpty(year) && string.IsNullOrEmpty(season))
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

        private void OpenTempFolder_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                string tempDir = Path.Combine(Path.GetTempPath(), "NomadTranscode");
                if (!Directory.Exists(tempDir)) Directory.CreateDirectory(tempDir);
                Process.Start("explorer.exe", tempDir);
            }
            catch (Exception ex)
            {
                AddLog($"Error opening temp folder: {ex.Message}");
            }
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

        public class OmdbSearchResponse
    {
        public List<OmdbSearchResult> Search { get; set; } = new List<OmdbSearchResult>();
        public string totalResults { get; set; } = "0";
        public string Response { get; set; } = "False";
    }

    public class OmdbSearchResult
    {
        public string Title { get; set; } = "";
        public string Year { get; set; } = "";
        public string imdbID { get; set; } = "";
        public string Type { get; set; } = "";
        public string Poster { get; set; } = "";
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

    public class FileManagerItem
    {
        public string Name { get; set; } = "";
        public string FullPath { get; set; } = "";
        public bool IsDirectory { get; set; }
        public long SizeBytes { get; set; }
        public DateTime Modified { get; set; }

        public string Type => IsDirectory ? "Folder" : "File";

        public string SizeDisplay
        {
            get
            {
                if (IsDirectory) return "";
                return $"{SizeBytes / 1024 / 1024} MB";
            }
        }

        public string ModifiedDisplay => Modified == DateTime.MinValue ? "" : Modified.ToString("yyyy-MM-dd");
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
        private string _category = MainWindow.Categories.Movies;
        private string _plot = "";
        private string _season = "";
        private string _episode = "";
        private bool _isProcessing;
        private bool _isDuplicate;
        private double _progress;
        private string _statusMessage = "";
        private EncodingPreset? _selectedPreset;
        private double _durationSeconds; // estimated or fetched
        private ObservableCollection<MediaTrack> _audioTracks = new();
        private ObservableCollection<MediaTrack> _subtitleTracks = new();
        private MediaTrack? _selectedAudioTrack;
        private MediaTrack? _selectedSubtitleTrack;

        private string _sourcePath = "";
        private long _fileSize;

        public string SourcePath 
        { 
            get => _sourcePath; 
            set 
            { 
                _sourcePath = value; 
                try 
                { 
                    FileSize = new FileInfo(value).Length; 
                } 
                catch 
                { 
                    FileSize = 0; 
                }
                OnPropertyChanged(); 
                OnPropertyChanged(nameof(FileName)); 
            } 
        }

        public long FileSize 
        { 
            get => _fileSize; 
            set { _fileSize = value; OnPropertyChanged(); OnPropertyChanged(nameof(FileSizeDisplay)); } 
        }

        public string FileName => Path.GetFileName(SourcePath);
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

        public double DurationSeconds { get => _durationSeconds; set { _durationSeconds = value; OnPropertyChanged(); OnPropertyChanged(nameof(EstimatedSizeDisplay)); } }

        public ObservableCollection<MediaTrack> AudioTracks { get => _audioTracks; set { _audioTracks = value; OnPropertyChanged(); } }
        public ObservableCollection<MediaTrack> SubtitleTracks { get => _subtitleTracks; set { _subtitleTracks = value; OnPropertyChanged(); } }
        
        public MediaTrack? SelectedAudioTrack { get => _selectedAudioTrack; set { _selectedAudioTrack = value; OnPropertyChanged(); } }
        public MediaTrack? SelectedSubtitleTrack { get => _selectedSubtitleTrack; set { _selectedSubtitleTrack = value; OnPropertyChanged(); } }

        public string FileSizeDisplay => $"{FileSize / 1024 / 1024} MB";
        
        public string EstimatedSizeDisplay 
        {
            get
            {
                if (SelectedPreset == null || SelectedPreset.Bitrate == 0 || DurationSeconds == 0) return FileSizeDisplay;
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
