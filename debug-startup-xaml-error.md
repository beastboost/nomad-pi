# Debug Session: startup-xaml-error

Status: OPEN

## Symptom
- WPF app fails at startup/build with XAML parser/property errors in `MainWindow.xaml`.

## Hypotheses
- Invalid web-style property names were introduced into WPF XAML.
- A control is using a property supported by another control type, not the current one.
- The generated redesign added unsupported attributes in poster-card markup near the Debrid UI.
- There may be multiple invalid XAML properties remaining after the previous fixes.

## Evidence
- `MainWindow.xaml` on current `main` contains valid WPF markup at the reported location: `Border Padding="8"`.
- Local reproduction with `dotnet publish tools/NomadTransferTool/NomadTransferTool.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true` succeeds on current HEAD.
- `tools/NomadTransferTool/generate_xaml.py` still contained stale invalid markup:
  - `Overflow="Hidden"`
  - `StackPanel Grid.Row="1" Padding="8"`
- New runtime evidence showed `StaticResourceExtension` failed during `InitializeComponent()`, before `MainWindow` construction completed.
- `MainWindow.xaml` line 6 used `Background="{StaticResource BackgroundColor}"` on the root `Window`, while `BackgroundColor` is declared later inside `Window.Resources`.
- After changing the root window background to a literal color, both `dotnet build` and `dotnet publish` succeed.

## Fix
- Updated `generate_xaml.py` so it now emits valid WPF markup matching `MainWindow.xaml`.
- Replaced the root `Window` background lookup with a literal `#0D0D0D` to avoid early local-resource resolution.
- Added deeper startup exception formatting in `App.xaml.cs` so future startup failures include inner exception details.

## Verification
- `dotnet publish` passes locally on current HEAD.
