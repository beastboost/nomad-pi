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
- New runtime evidence from the startup dialog showed:
  - `System.InvalidOperationException: The calling thread cannot access this object because a different thread owns it.`
  - stack points to `MainWindow.RefreshDrives()` at the first access to `DriveList.SelectedItem`.
- `RefreshDrives()` is called by a timer/background callback, so direct reads/writes to `DriveList` and `Drives` must happen on the dispatcher thread.
- Runtime screenshot showed HandBrake download failing with `401 (Unauthorized)`.
- `DownloadHandbrake()` was using the shared app `HttpClient`, which also carries Nomad auth state and is reused across unrelated requests.
- Runtime screenshot also showed Debrid torrent loading failing on JSON conversion: value `"8.87 GB"` could not be converted to `System.Int64`.
- `DebridTorrentResult.Size` was typed as `long` with default deserialization, which only works when the API returns raw numeric bytes.
- Runtime screenshot then showed another Debrid JSON conversion failure: `seeders` could be `null`, but the client model expected a non-null `int`.
- User also reported the redesigned tool only exposed one Debrid key field even though the backend has separate provider key endpoints for `rd`, `ad`, and `tb`.
- Web playback path on the Pi only auto-prepared an H.264-compatible stream for iOS/Safari MKV cases, leaving common ARM/Linux stutter cases on direct browser playback.

## Fix
- Updated `generate_xaml.py` so it now emits valid WPF markup matching `MainWindow.xaml`.
- Replaced the root `Window` background lookup with a literal `#0D0D0D` to avoid early local-resource resolution.
- Added deeper startup exception formatting in `App.xaml.cs` so future startup failures include inner exception details.
- Updated `RefreshDrives()` so UI-bound reads and writes are wrapped in `Dispatcher.InvokeAsync`, while the actual drive enumeration stays off the UI thread.
- Updated `DownloadHandbrake()` to use a dedicated GitHub `HttpClient` with its own headers, instead of the shared authenticated app client.
- Added `FlexibleSizeConverter` and applied it to `DebridTorrentResult.Size` so string sizes like `"8.87 GB"` deserialize correctly.
- Added `FlexibleIntConverter` and applied it to `DebridTorrentResult.Seeders` so `null` and string values deserialize safely.
- Added separate provider-specific Debrid key storage, save actions, and status display for Real-Debrid, AllDebrid, and TorBox in the Transfer Tool UI.
- Added selected-provider key editing in the Debrid tab and per-provider key rows in Settings, each linked to the correct `/debrid/{provider}/key` endpoint.
- Broadened browser playback compatibility logic so Pi/ARM devices and HEVC-style files prefer the existing H.264/AAC transcode path instead of raw direct playback.

## Verification
- `dotnet publish` passes locally on current HEAD.
