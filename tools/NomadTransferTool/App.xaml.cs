using System;
using System.Windows;

namespace NomadTransferTool
{
    public partial class App : System.Windows.Application
    {
        protected override void OnStartup(StartupEventArgs e)
        {
            string logFile = System.IO.Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "startup_log.txt");
            try
            {
                System.IO.File.WriteAllText(logFile, $"App Starting at {DateTime.Now}...\n");
                System.IO.File.AppendAllText(logFile, $"Runtime: {System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription}\n");
                System.IO.File.AppendAllText(logFile, $"OS: {System.Runtime.InteropServices.RuntimeInformation.OSDescription}\n");
            }
            catch { }

            AppDomain.CurrentDomain.UnhandledException += (s, ex) =>
            {
                string msg = $"CRITICAL ERROR: {((Exception)ex.ExceptionObject).Message}\n{((Exception)ex.ExceptionObject).StackTrace}";
                try { System.IO.File.AppendAllText(logFile, msg + "\n"); } catch { }
                System.Windows.MessageBox.Show(msg, "Critical Error", MessageBoxButton.OK, MessageBoxImage.Error);
            };

            this.DispatcherUnhandledException += (s, ex) =>
            {
                string msg = $"UI ERROR: {ex.Exception.Message}\n{ex.Exception.StackTrace}";
                try { System.IO.File.AppendAllText(logFile, msg + "\n"); } catch { }
                System.Windows.MessageBox.Show(msg, "UI Error", MessageBoxButton.OK, MessageBoxImage.Error);
                ex.Handled = true;
            };

            try 
            {
                base.OnStartup(e);
                System.IO.File.AppendAllText(logFile, "Base OnStartup completed.\n");

                var mainWindow = new MainWindow();
                mainWindow.Show();
                System.IO.File.AppendAllText(logFile, "MainWindow shown.\n");
            }
            catch (Exception ex)
            {
                string msg = $"STARTUP ERROR: {ex.Message}\n{ex.StackTrace}";
                try { System.IO.File.AppendAllText(logFile, msg + "\n"); } catch { }
                System.Windows.MessageBox.Show(msg, "Startup Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }
    }
}
