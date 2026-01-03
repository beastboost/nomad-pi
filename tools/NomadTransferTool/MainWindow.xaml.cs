using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Management;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows;
using Newtonsoft.Json;

namespace NomadTransferTool
{
    public partial class MainWindow : Window
    {
        private static readonly HttpClient client = new HttpClient();
        private const string API_BASE = "http://localhost:8000/api";
        private string OMDB_API_KEY = "";
        private string mediaServerDataPath = "";

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

        private void OmdbKeyBox_PasswordChanged(object sender, RoutedEventArgs e)
        {
            OMDB_API_KEY = OmdbKeyBox.Password;
            File.WriteAllText("omdb.txt", OMDB_API_KEY);
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
                        IsMounted = CheckIfMounted(drive.Name)
                    };
                    Drives.Add(model);
                    if (model.Name == selectedName) DriveList.SelectedItem = model;
                }
            }
        }

        private bool CheckIfMounted(string driveLetter)
        {
            if (string.IsNullOrEmpty(mediaServerDataPath)) return false;
            string externalDir = Path.Combine(mediaServerDataPath, "external");
            if (!Directory.Exists(externalDir)) return false;

            string folderName = "USB_" + driveLetter.Replace(":\\", "").Replace(":", "");
            string junctionPath = Path.Combine(externalDir, folderName);
            
            return Directory.Exists(junctionPath);
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
                    RefreshDrives();
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
                        // format <drive> /FS:exFAT /Q /V:NOMAD /Y
                        var process = new System.Diagnostics.Process();
                        process.StartInfo.FileName = "cmd.exe";
                        process.StartInfo.Arguments = $"/c format {driveLetter}: /FS:exFAT /Q /V:NOMAD /Y";
                        process.StartInfo.CreateNoWindow = false; // Show window for progress
                        process.StartInfo.UseShellExecute = true;
                        process.StartInfo.Verb = "runas"; // Requires admin
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

        private void MountDrive_Click(object sender, RoutedEventArgs e)
        {
            if (DriveList.SelectedItem is DriveInfoModel drive)
            {
                MountDrive(drive);
                RefreshDrives();
            }
        }

        private void MountDrive(DriveInfoModel drive)
        {
            if (string.IsNullOrEmpty(mediaServerDataPath))
            {
                MessageBox.Show("Could not locate Media Server data directory. Please ensure the tool is in the media server project folder.", "Error", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            string externalDir = Path.Combine(mediaServerDataPath, "external");
            if (!Directory.Exists(externalDir)) Directory.CreateDirectory(externalDir);

            string folderName = "USB_" + drive.Name.Replace(":\\", "").Replace(":", "");
            string junctionPath = Path.Combine(externalDir, folderName);

            if (Directory.Exists(junctionPath)) return;

            // Create junction using mklink /J
            // Requires process start because there's no native .NET way to create junctions easily
            try
            {
                var process = new System.Diagnostics.Process();
                process.StartInfo.FileName = "cmd.exe";
                process.StartInfo.Arguments = $"/c mklink /J \"{junctionPath}\" \"{drive.Name}\"";
                process.StartInfo.CreateNoWindow = true;
                process.StartInfo.UseShellExecute = true; // UseShellExecute true for potential elevation if needed
                process.StartInfo.Verb = "runas"; // Request admin if needed for symlink/junction
                process.Start();
                process.WaitForExit();
                
                TriggerScan();
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Failed to mount drive: {ex.Message}. You may need to run this tool as Administrator.", "Mount Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private async void TriggerScan()
        {
            try
            {
                await client.PostAsync($"{API_BASE}/media/scan", null);
            }
            catch { /* API might be down */ }
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

                    if (string.IsNullOrEmpty(OMDB_API_KEY))
                    {
                        var result = MessageBox.Show("No OMDB API Key found. Files will be copied as-is. Would you like to enter a key first?", "OMDB Key Missing", MessageBoxButton.YesNo);
                        if (result == MessageBoxResult.Yes) return;
                    }

                    await Task.Run(async () => {
                        foreach (var file in files)
                        {
                            try
                            {
                                string fileName = Path.GetFileName(file);
                                string finalDest = Path.Combine(destBase, fileName);
                                string? posterUrl = null;

                                if (!string.IsNullOrEmpty(OMDB_API_KEY) && (category == "movies" || category == "shows"))
                                {
                                    var meta = await FetchOMDBMetadata(fileName, category);
                                    if (meta != null)
                                    {
                                        string title = meta.Title;
                                        string year = meta.Year;
                                        string cleanTitle = string.Join("_", title.Split(Path.GetInvalidFileNameChars()));
                                        
                                        if (category == "movies")
                                        {
                                            string folderName = $"{cleanTitle} ({year})";
                                            string movieFolder = Path.Combine(destBase, folderName);
                                            Directory.CreateDirectory(movieFolder);
                                            finalDest = Path.Combine(movieFolder, $"{cleanTitle} ({year}){Path.GetExtension(file)}");
                                            posterUrl = meta.Poster;
                                            
                                            if (!string.IsNullOrEmpty(posterUrl) && posterUrl != "N/A")
                                            {
                                                await DownloadPoster(posterUrl, Path.Combine(movieFolder, "poster.jpg"));
                                            }
                                        }
                                        else if (category == "shows")
                                        {
                                            string showFolder = Path.Combine(destBase, cleanTitle);
                                            Directory.CreateDirectory(showFolder);
                                            finalDest = Path.Combine(showFolder, fileName); // Keep original filename for episodes usually
                                            posterUrl = meta.Poster;
                                            
                                            if (!string.IsNullOrEmpty(posterUrl) && posterUrl != "N/A")
                                            {
                                                await DownloadPoster(posterUrl, Path.Combine(showFolder, "poster.jpg"));
                                            }
                                        }
                                    }
                                }

                                File.Copy(file, finalDest, true);
                            }
                            catch (Exception ex)
                            {
                                Dispatcher.Invoke(() => MessageBox.Show($"Error processing {file}: {ex.Message}"));
                            }
                        }
                        Dispatcher.Invoke(() => MessageBox.Show("Transfer & Organization Complete!", "Done"));
                        TriggerScan();
                    });
                }
                else
                {
                    MessageBox.Show("Please select a target drive first.");
                }
            }
        }

        private async Task<OmdbResult?> FetchOMDBMetadata(string fileName, string category)
        {
            try
            {
                string title = Path.GetFileNameWithoutExtension(fileName);
                // Basic cleanup
                title = Regex.Replace(title, @"\b(1080p|720p|4k|2160p|bluray|web-dl|x264|h264|x265|hevc|aac|dts)\b.*", "", RegexOptions.IgnoreCase).Trim();
                
                string type = category == "movies" ? "movie" : "series";
                string url = $"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&t={Uri.EscapeDataString(title)}&type={type}";
                
                var response = await client.GetStringAsync(url);
                var result = JsonConvert.DeserializeObject<OmdbResult>(response);
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

        private void Unmount_Click(object sender, RoutedEventArgs e)
        {
             if (DriveList.SelectedItem is DriveInfoModel drive)
             {
                 string folderName = "USB_" + drive.Name.Replace(":\\", "").Replace(":", "");
                 string junctionPath = Path.Combine(mediaServerDataPath, "external", folderName);
                 if (Directory.Exists(junctionPath))
                 {
                     Directory.Delete(junctionPath);
                     RefreshDrives();
                     TriggerScan();
                 }
             }
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
