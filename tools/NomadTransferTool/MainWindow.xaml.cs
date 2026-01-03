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
        private string _appStatus = "Nomad v1.3 - Connected";

        public bool IsTransferring { get => _isTransferring; set { _isTransferring = value; OnPropertyChanged(); } }
        public string CurrentStatus { get => _currentStatus; set { _currentStatus = value; OnPropertyChanged(); } }
        public string TransferSpeed { get => _transferSpeed; set { _transferSpeed = value; OnPropertyChanged(); } }
        public string FileProgress { get => _fileProgress; set { _fileProgress = value; OnPropertyChanged(); } }
        public double TotalProgress { get => _totalProgress; set { _totalProgress = value; OnPropertyChanged(); } }
        public string AppStatus { get => _appStatus; set { _appStatus = value; OnPropertyChanged(); } }

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
            DirectoryInfo dir = new DirectoryInfo(currentDir);
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
        }

        public event PropertyChangedEventHandler? PropertyChanged;
        protected void OnPropertyChanged([CallerMemberName] string name = null) => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));

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
                        AvailableFreeSpace = drive.AvailableFreeSpace
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
                    
                    MessageBox.Show("Drive prepared with standard folders!", "Success", MessageBoxButton.OK, MessageBoxImage.Information);
                }
                catch (Exception ex)
                {
                    MessageBox.Show($"Error preparing drive: {ex.Message}", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
                }
            }
        }

        private void FormatDrive_Click(object sender, RoutedEventArgs e)
        {
            if (DriveList.SelectedItem is DriveInfoModel drive)
            {
                var result = MessageBox.Show($"Are you sure you want to format {drive.Name} ({drive.Label})? ALL DATA WILL BE LOST. We recommend exFAT for compatibility with Pi.", 
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
                        MessageBox.Show("Format complete. Now click 'Prepare Folders'.");
                    }
                    catch (Exception ex)
                    {
                        MessageBox.Show($"Format failed: {ex.Message}");
                    }
                }
            }
        }

        private async void Transfer_Drop(object sender, DragEventArgs e)
        {
            if (e.Data.GetDataPresent(DataFormats.FileDrop))
            {
                string[] files = (string[])e.Data.GetData(DataFormats.FileDrop);
                if (DriveList.SelectedItem is DriveInfoModel drive)
                {
                    string category = (CategoryCombo.SelectedItem as FrameworkElement)?.Tag?.ToString() ?? "files";
                    string destBase = Path.Combine(drive.Name, category);
                    if (!Directory.Exists(destBase)) Directory.CreateDirectory(destBase);

                    IsTransferring = true;
                    TotalProgress = 0;
                    int totalFiles = files.Length;
                    int processedFiles = 0;

                    await Task.Run(async () => {
                        foreach (var file in files)
                        {
                            try
                            {
                                if (!File.Exists(file)) continue;

                                string fileName = Path.GetFileName(file);
                                CurrentStatus = $"Processing: {fileName}";
                                processedFiles++;
                                
                                string finalDest = Path.Combine(destBase, fileName);
                                string? posterUrl = null;

                                if (!string.IsNullOrEmpty(OMDB_API_KEY) && (category == "movies" || category == "shows"))
                                {
                                    var meta = await FetchOMDBMetadata(fileName, category);
                                    if (meta != null)
                                    {
                                        string metaTitle = meta.Title;
                                        string metaYear = meta.Year;
                                        
                                        // Sanitize title for filesystem
                                        string safeTitle = string.Join("_", metaTitle.Split(Path.GetInvalidFileNameChars()));
                                        
                                        if (category == "movies")
                                        {
                                            // Folder name: "Title (Year)"
                                            string folderName = $"{safeTitle} ({metaYear})";
                                            string movieFolder = Path.Combine(destBase, folderName);
                                            Directory.CreateDirectory(movieFolder);
                                            
                                            // File name: "Title (Year).ext" - this is standard for Plex/Emby/Nomad
                                            finalDest = Path.Combine(movieFolder, $"{safeTitle} ({metaYear}){Path.GetExtension(file)}");
                                            posterUrl = meta.Poster;
                                            
                                            if (!string.IsNullOrEmpty(posterUrl) && posterUrl != "N/A")
                                            {
                                                await DownloadPoster(posterUrl, Path.Combine(movieFolder, "poster.jpg"));
                                            }
                                        }
                                        else if (category == "shows")
                                        {
                                            // Show folder name: "Title"
                                            string showFolder = Path.Combine(destBase, safeTitle);
                                            Directory.CreateDirectory(showFolder);
                                            
                                            // Keep original filename for shows (preserves Season/Episode info)
                                            finalDest = Path.Combine(showFolder, fileName);
                                            posterUrl = meta.Poster;
                                            
                                            if (!string.IsNullOrEmpty(posterUrl) && posterUrl != "N/A")
                                            {
                                                await DownloadPoster(posterUrl, Path.Combine(showFolder, "poster.jpg"));
                                            }
                                        }
                                    }
                                }

                                await CopyFileWithProgress(file, finalDest);
                                TotalProgress = (double)processedFiles / totalFiles * 100;
                            }
                            catch (Exception ex)
                            {
                                Dispatcher.Invoke(() => MessageBox.Show($"Error processing {file}: {ex.Message}"));
                            }
                        }
                        
                        CurrentStatus = "Transfer Complete!";
                        FileProgress = "";
                        TransferSpeed = "";
                        await Task.Delay(2000);
                        IsTransferring = false;
                        Dispatcher.Invoke(RefreshDrives);
                    });
                }
                else
                {
                    MessageBox.Show("Please select a target drive first.");
                }
            }
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
                    double speed = totalRead / 1024.0 / 1024.0 / sw.Elapsed.TotalSeconds;
                    
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
                
                // 1. Extract Year (looks for 4 digits in brackets or preceded by dot/space)
                string year = "";
                var yearMatch = Regex.Match(cleanName, @"(?<=[ \.\(\[])(19|20)\d{2}(?=[ \.\)\]]|$)");
                if (yearMatch.Success)
                {
                    year = yearMatch.Value;
                }

                // 2. Clean Title
                // Remove everything after the year if found
                string titlePart = yearMatch.Success ? cleanName.Substring(0, yearMatch.Index) : cleanName;
                
                // Replace dots, underscores, hyphens with spaces
                titlePart = Regex.Replace(titlePart, @"[\._\-]", " ");
                
                // Remove common scene/quality tags
                titlePart = Regex.Replace(titlePart, @"\b(1080p|720p|4k|2160p|bluray|web-dl|x264|h264|x265|hevc|aac|dts|remux|multi|subs|dual|extended|unrated|director.*cut)\b.*", "", RegexOptions.IgnoreCase).Trim();
                
                // Final trim and collapse spaces
                string title = Regex.Replace(titlePart, @"\s+", " ").Trim();
                
                if (string.IsNullOrEmpty(title)) return null;

                string type = category == "movies" ? "movie" : "series";
                string url = $"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&t={Uri.EscapeDataString(title)}&type={type}";
                if (!string.IsNullOrEmpty(year)) url += $"&y={year}";
                
                var response = await client.GetStringAsync(url);
                var result = JsonConvert.DeserializeObject<OmdbResult>(response);
                
                // If we didn't get a result and had a year, try without the year as a fallback
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

        public class OmdbResult
        {
            public string Title { get; set; } = "";
            public string Year { get; set; } = "";
            public string Poster { get; set; } = "";
            public string Response { get; set; } = "";
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
            if (value is bool b && b) return System.Windows.Media.Brushes.LightGreen;
            return System.Windows.Media.Brushes.Gray;
        }
        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture) => throw new NotImplementedException();
    }
}
