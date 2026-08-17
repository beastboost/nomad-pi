package com.nomadpi.android

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.outlined.ArrowBack
import androidx.compose.material.icons.outlined.Book
import androidx.compose.material.icons.outlined.Cancel
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.ClearAll
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Lan
import androidx.compose.material.icons.outlined.Logout
import androidx.compose.material.icons.outlined.Movie
import androidx.compose.material.icons.outlined.MusicNote
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.PhotoLibrary
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Tv
import androidx.compose.material.icons.outlined.VideoLibrary
import androidx.compose.material.icons.outlined.Wifi
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlin.math.roundToInt

private val NomadColors = darkColorScheme(
    primary = Color(0xFFAFC4FF),
    onPrimary = Color(0xFF10224E),
    primaryContainer = Color(0xFF263B70),
    secondary = Color(0xFFBFC6DA),
    background = Color(0xFF0B0D10),
    surface = Color(0xFF111419),
    surfaceVariant = Color(0xFF1A1E25),
    onSurface = Color(0xFFF2F4F7),
    onSurfaceVariant = Color(0xFFB9C0CA),
    error = Color(0xFFFFB4AB),
)

@Composable
fun NomadTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = NomadColors, content = content)
}

@Composable
fun NomadApp(vm: NomadViewModel) {
    val snackbar = remember { SnackbarHostState() }
    var searchOpen by remember { mutableStateOf(false) }
    var reader by remember { mutableStateOf<NativeReaderSource?>(null) }

    val message = vm.message
    LaunchedEffect(message) {
        if (!message.isNullOrBlank()) {
            snackbar.showSnackbar(message)
            vm.clearMessage()
        }
    }

    vm.playback?.let { active ->
        NativeMediaPlayer(
            source = NativeMediaSource(active.title, active.url, active.mode, active.audioOnly),
            onClose = { p, d -> vm.closePlayback(p, d) },
            onHeartbeat = if (active.sessionId != null) ({ p, d, playing -> vm.heartbeat(p, d, playing) }) else null,
        )
        return
    }

    reader?.let { source ->
        NativeReader(vm.api, source) { reader = null }
        return
    }

    if (searchOpen && vm.entry == EntryScreen.APP) {
        BackHandler { searchOpen = false }
        Scaffold(
            topBar = {
                @OptIn(ExperimentalMaterial3Api::class)
                TopAppBar(
                    title = { Text("Find anything", fontWeight = FontWeight.Bold) },
                    navigationIcon = { IconButton(onClick = { searchOpen = false }) { Icon(Icons.Outlined.ArrowBack, "Back") } },
                    colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
                )
            },
        ) { padding -> NativeUniversalSearch(vm.api, Modifier.fillMaxSize().padding(padding)) }
        return
    }

    Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
        when (vm.entry) {
            EntryScreen.LOADING -> LoadingScreen()
            EntryScreen.CONNECT -> ConnectScreen(vm)
            EntryScreen.LOGIN -> LoginScreen(vm)
            EntryScreen.APP -> MainShell(vm, snackbar, onSearch = { searchOpen = true }, onRead = { reader = it })
        }
        if (vm.entry != EntryScreen.APP) SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter).navigationBarsPadding())
    }
}

@Composable
private fun LoadingScreen() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Wordmark()
            CircularProgressIndicator()
        }
    }
}

@Composable
private fun Wordmark() {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text("NOMAD", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Black)
        Text("native for Android", color = MaterialTheme.colorScheme.primary)
    }
}

@Composable
private fun ConnectScreen(vm: NomadViewModel) {
    var manual by remember(vm.server) { mutableStateOf(vm.server) }
    Column(
        Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Wordmark()
        Spacer(Modifier.height(38.dp))
        Text("Connect to your Nomad", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text("Discover it on the LAN or enter nomadpi.local, the hotspot gateway, a Tailscale address or an IP.", color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 8.dp, bottom = 18.dp))
        OutlinedTextField(manual, { manual = it }, Modifier.fillMaxWidth(), label = { Text("Server") }, leadingIcon = { Icon(Icons.Outlined.Lan, null) }, singleLine = true)
        Button(onClick = { vm.selectServer(manual) }, modifier = Modifier.fillMaxWidth().padding(top = 12.dp).height(52.dp)) { Text("Continue") }
        Row(Modifier.fillMaxWidth().padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton({ manual = "http://nomadpi.local" }, Modifier.weight(1f)) { Text("nomadpi.local", maxLines = 1) }
            OutlinedButton({ manual = "http://10.42.0.1" }, Modifier.weight(1f)) { Text("Hotspot") }
        }
        Spacer(Modifier.height(24.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Nearby", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            TextButton(onClick = { vm.startDiscovery() }) { Icon(Icons.Outlined.Refresh, null); Text("Scan") }
        }
        if (vm.discovering && vm.discovered.isEmpty()) {
            Row(Modifier.padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp); Spacer(Modifier.width(10.dp)); Text("Looking for Nomad…")
            }
        }
        vm.discovered.forEach { found ->
            Card(Modifier.fillMaxWidth().padding(vertical = 4.dp).clickable { vm.selectServer(found.url) }, colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Outlined.Wifi, null, tint = MaterialTheme.colorScheme.primary)
                    Column(Modifier.padding(start = 12.dp).weight(1f)) { Text(found.name, fontWeight = FontWeight.SemiBold); Text(found.url, style = MaterialTheme.typography.bodySmall) }
                    Text("Connect", color = MaterialTheme.colorScheme.primary)
                }
            }
        }
    }
}

@Composable
private fun LoginScreen(vm: NomadViewModel) {
    var username by remember { mutableStateOf("admin") }
    var password by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(24.dp), verticalArrangement = Arrangement.Center) {
        IconButton(onClick = { vm.backToConnect() }) { Icon(Icons.Outlined.ArrowBack, "Back") }
        Wordmark(); Spacer(Modifier.height(32.dp))
        Text("Sign in", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text(vm.server, color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(top = 4.dp, bottom = 16.dp))
        OutlinedTextField(username, { username = it }, Modifier.fillMaxWidth(), label = { Text("Username") }, leadingIcon = { Icon(Icons.Outlined.Person, null) }, singleLine = true)
        OutlinedTextField(password, { password = it }, Modifier.fillMaxWidth().padding(top = 10.dp), label = { Text("Password") }, visualTransformation = PasswordVisualTransformation(), singleLine = true)
        Button(enabled = !vm.busy && password.isNotBlank(), onClick = { vm.login(username, password) }, modifier = Modifier.fillMaxWidth().padding(top = 16.dp).height(52.dp)) {
            if (vm.busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp) else Text("Sign in")
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MainShell(vm: NomadViewModel, snackbar: SnackbarHostState, onSearch: () -> Unit, onRead: (NativeReaderSource) -> Unit) {
    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(tabTitle(vm.tab), fontWeight = FontWeight.Bold)
                        Text("${vm.profile?.name ?: vm.session?.username.orEmpty()} · ${vm.server.removePrefix("http://").removePrefix("https://")}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                },
                actions = {
                    IconButton(onClick = onSearch) { Icon(Icons.Outlined.Search, "Find anything") }
                    ProfileMenu(vm)
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        },
        bottomBar = { BottomNav(vm) },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when (vm.tab) {
                MainTab.HOME -> HomeScreen(vm, onSearch)
                MainTab.LIBRARY -> LibraryScreen(vm, onRead)
                MainTab.PHOTOS -> NativePhotos(vm)
                MainTab.DOWNLOADS -> DownloadsScreen(vm)
                MainTab.SERVER -> ServerScreen(vm)
            }
            if (vm.busy) LinearProgressIndicator(Modifier.fillMaxWidth().align(Alignment.TopCenter))
        }
    }
}

@Composable
private fun BottomNav(vm: NomadViewModel) {
    NavigationBar(containerColor = MaterialTheme.colorScheme.surface) {
        listOf(
            Triple(MainTab.HOME, "Home", Icons.Outlined.Home),
            Triple(MainTab.LIBRARY, "Library", Icons.Outlined.VideoLibrary),
            Triple(MainTab.PHOTOS, "Photos", Icons.Outlined.PhotoLibrary),
            Triple(MainTab.DOWNLOADS, "Downloads", Icons.Outlined.Download),
            Triple(MainTab.SERVER, "Server", Icons.Outlined.Dns),
        ).forEach { (tab, label, icon) ->
            NavigationBarItem(selected = vm.tab == tab, onClick = { vm.chooseTab(tab) }, icon = { Icon(icon, label) }, label = { Text(label, maxLines = 1) })
        }
    }
}

@Composable
private fun ProfileMenu(vm: NomadViewModel) {
    var open by remember { mutableStateOf(false) }
    var pinTarget by remember { mutableStateOf<NomadProfile?>(null) }
    var pin by remember { mutableStateOf("") }
    Box {
        IconButton(onClick = { open = true }) { Icon(Icons.Outlined.Person, vm.profile?.name ?: "Profile") }
        DropdownMenu(open, onDismissRequest = { open = false }) {
            vm.profiles.forEach { target ->
                DropdownMenuItem(
                    text = { Text("${target.name}${if (target.pinRequired) " · PIN" else ""}", fontWeight = if (target.id == vm.profile?.id) FontWeight.Bold else FontWeight.Normal) },
                    onClick = {
                        open = false
                        if (target.id == vm.profile?.id) return@DropdownMenuItem
                        if (target.pinRequired) { pin = ""; pinTarget = target } else vm.switchProfile(target)
                    },
                )
            }
        }
    }
    pinTarget?.let { target ->
        AlertDialog(
            onDismissRequest = { pinTarget = null },
            title = { Text(target.name) },
            text = { OutlinedTextField(pin, { if (it.length <= 8) pin = it }, label = { Text("Profile PIN") }, visualTransformation = PasswordVisualTransformation(), singleLine = true) },
            confirmButton = { Button(onClick = { vm.switchProfile(target, pin) { if (it) pinTarget = null } }) { Text("Switch") } },
            dismissButton = { TextButton(onClick = { pinTarget = null }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun HomeScreen(vm: NomadViewModel, onSearch: () -> Unit) {
    val stats = vm.stats
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(18.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
                Column(Modifier.padding(18.dp)) {
                    Text("Nomad is connected", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                    Text(vm.server, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    if (stats != null) Row(Modifier.padding(top = 14.dp), horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                        Stat("CPU", "${stats.cpuPercent.roundToInt()}%")
                        Stat("Temp", if (stats.temperature > 0) "${stats.temperature.roundToInt()}°C" else "—")
                        Stat("Free", formatBytes(stats.diskFree))
                    }
                }
            }
        }
        item {
            Button(onClick = onSearch, modifier = Modifier.fillMaxWidth().height(54.dp)) { Icon(Icons.Outlined.Search, null); Spacer(Modifier.width(8.dp)); Text("Find anything") }
        }
        item { Text("Libraries", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Quick("Movies", Icons.Outlined.Movie, Modifier.weight(1f)) { vm.chooseTab(MainTab.LIBRARY); vm.chooseLibrary(LibrarySection.MOVIES) }
                Quick("Shows", Icons.Outlined.Tv, Modifier.weight(1f)) { vm.chooseTab(MainTab.LIBRARY); vm.chooseLibrary(LibrarySection.SHOWS) }
            }
        }
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Quick("Music", Icons.Outlined.MusicNote, Modifier.weight(1f)) { vm.chooseTab(MainTab.LIBRARY); vm.chooseLibrary(LibrarySection.MUSIC) }
                Quick("Photos", Icons.Outlined.PhotoLibrary, Modifier.weight(1f)) { vm.chooseTab(MainTab.PHOTOS) }
            }
        }
    }
}

@Composable private fun Stat(label: String, value: String) { Column { Text(value, fontWeight = FontWeight.Bold); Text(label, style = MaterialTheme.typography.labelSmall) } }

@Composable
private fun Quick(label: String, icon: androidx.compose.ui.graphics.vector.ImageVector, modifier: Modifier, action: () -> Unit) {
    Card(modifier.clickable(onClick = action), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Column(Modifier.fillMaxWidth().padding(18.dp), horizontalAlignment = Alignment.CenterHorizontally) { Icon(icon, null, tint = MaterialTheme.colorScheme.primary); Text(label, modifier = Modifier.padding(top = 7.dp), fontWeight = FontWeight.SemiBold) }
    }
}

@Composable
private fun LibraryScreen(vm: NomadViewModel, onRead: (NativeReaderSource) -> Unit) {
    val context = LocalContext.current
    var query by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 6.dp), horizontalArrangement = Arrangement.spacedBy(5.dp)) {
            LibraryChip("Movies", vm.librarySection == LibrarySection.MOVIES, Modifier.weight(1f)) { vm.chooseLibrary(LibrarySection.MOVIES) }
            LibraryChip("Shows", vm.librarySection == LibrarySection.SHOWS, Modifier.weight(1f)) { vm.chooseLibrary(LibrarySection.SHOWS) }
            LibraryChip("Music", vm.librarySection == LibrarySection.MUSIC, Modifier.weight(1f)) { vm.chooseLibrary(LibrarySection.MUSIC) }
            LibraryChip("Books", vm.librarySection == LibrarySection.BOOKS, Modifier.weight(1f)) { vm.chooseLibrary(LibrarySection.BOOKS) }
        }
        OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth().padding(horizontal = 10.dp), placeholder = { Text("Filter library") }, leadingIcon = { Icon(Icons.Outlined.Search, null) }, trailingIcon = { IconButton(onClick = { vm.refreshLibrary() }) { Icon(Icons.Outlined.Refresh, "Refresh") } }, singleLine = true)

        if (vm.librarySection == LibrarySection.SHOWS) {
            val list = vm.shows.filter { query.isBlank() || it.name.contains(query, true) }
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(list, key = { it.name }) { show -> ShowRow(vm, show) }
            }
        } else if (vm.librarySection == LibrarySection.MOVIES) {
            val list = vm.library.filter { query.isBlank() || it.name.contains(query, true) }
            LazyVerticalGrid(GridCells.Adaptive(140.dp), Modifier.fillMaxSize(), contentPadding = PaddingValues(10.dp), horizontalArrangement = Arrangement.spacedBy(9.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                items(list, key = { it.path }) { item ->
                    Column(Modifier.clickable { vm.play(item) }) {
                        RemoteImage(vm.api.imageUrl(item.poster), Modifier.fillMaxWidth().aspectRatio(2f / 3f), maxDecodePx = 600)
                        Text(stripMediaExtension(item.name), fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 6.dp))
                    }
                }
            }
        } else {
            val list = vm.library.filter { query.isBlank() || it.name.contains(query, true) || it.folder.contains(query, true) }
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(10.dp)) {
                items(list, key = { it.path }) { item ->
                    Row(
                        Modifier.fillMaxWidth().clickable {
                            if (vm.librarySection == LibrarySection.MUSIC) vm.play(item)
                            else {
                                when (extension(item.path)) {
                                    "cbz", "cbr" -> onRead(NativeReaderSource.Comic(item.path, stripMediaExtension(item.name)))
                                    "pdf" -> onRead(NativeReaderSource.Pdf(item.path, stripMediaExtension(item.name)))
                                    else -> {
                                        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(vm.api.mediaStreamUrl(item.path))).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                        runCatching { context.startActivity(intent) }
                                    }
                                }
                            }
                        }.padding(vertical = 12.dp, horizontal = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(if (vm.librarySection == LibrarySection.MUSIC) Icons.Outlined.MusicNote else Icons.Outlined.Book, null, tint = MaterialTheme.colorScheme.primary)
                        Column(Modifier.padding(start = 12.dp).weight(1f)) { Text(stripMediaExtension(item.name), fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis); Text(item.folder, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                        Icon(if (vm.librarySection == LibrarySection.MUSIC) Icons.Filled.PlayArrow else Icons.Outlined.Book, null)
                    }
                    HorizontalDivider(color = MaterialTheme.colorScheme.surfaceVariant)
                }
            }
        }
    }
}

@Composable
private fun LibraryChip(label: String, selected: Boolean, modifier: Modifier, action: () -> Unit) {
    if (selected) Button(onClick = action, modifier = modifier, contentPadding = PaddingValues(horizontal = 5.dp)) { Text(label) }
    else OutlinedButton(onClick = action, modifier = modifier, contentPadding = PaddingValues(horizontal = 5.dp)) { Text(label) }
}

@Composable
private fun ShowRow(vm: NomadViewModel, show: ShowItem) {
    var expanded by remember(show.name) { mutableStateOf(false) }
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Row(Modifier.fillMaxWidth().clickable { expanded = !expanded }.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            RemoteImage(vm.api.imageUrl(show.poster), Modifier.width(68.dp).aspectRatio(2f / 3f), maxDecodePx = 360)
            Column(Modifier.padding(start = 12.dp).weight(1f)) { Text(show.name, fontWeight = FontWeight.Bold); Text("${show.seasons.size} seasons", color = MaterialTheme.colorScheme.onSurfaceVariant) }
            Text(if (expanded) "Hide" else "Episodes", color = MaterialTheme.colorScheme.primary)
        }
        if (expanded) Column {
            show.seasons.forEach { season ->
                Text(season.name, fontWeight = FontWeight.Bold, modifier = Modifier.padding(12.dp))
                season.episodes.forEach { ep ->
                    Row(Modifier.fillMaxWidth().clickable { vm.playEpisode(ep) }.padding(horizontal = 14.dp, vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Filled.PlayArrow, null, tint = MaterialTheme.colorScheme.primary); Text(stripMediaExtension(ep.name), Modifier.padding(start = 9.dp).weight(1f), maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }
    }
}

@Composable
private fun DownloadsScreen(vm: NomadViewModel) {
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("${vm.downloads.size} queue items", modifier = Modifier.weight(1f), color = MaterialTheme.colorScheme.onSurfaceVariant)
            IconButton(onClick = { vm.refreshDownloads() }) { Icon(Icons.Outlined.Refresh, "Refresh") }
            if (vm.downloads.isNotEmpty()) IconButton(onClick = { vm.clearDownloadQueue() }) { Icon(Icons.Outlined.ClearAll, "Clear queue") }
        }
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(horizontal = 10.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
            items(vm.downloads, key = { it.id }) { job ->
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                    Column(Modifier.padding(13.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) { Text(job.filename, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis); Text("${job.status} · ${job.progress.roundToInt()}%", style = MaterialTheme.typography.bodySmall) }
                            if (job.status.lowercase() !in setOf("completed", "failed", "error", "cancelled")) IconButton(onClick = { vm.cancelDownload(job.id) }) { Icon(Icons.Outlined.Cancel, "Cancel") }
                            else if (job.status.lowercase() == "completed") Icon(Icons.Outlined.CheckCircle, null, tint = MaterialTheme.colorScheme.primary)
                        }
                        LinearProgressIndicator(progress = { (job.progress / 100.0).coerceIn(0.0, 1.0).toFloat() }, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                        job.error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 5.dp)) }
                    }
                }
            }
        }
    }
}

@Composable
private fun ServerScreen(vm: NomadViewModel) {
    val stats = vm.stats
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) { Text("Appliance", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f)); IconButton(onClick = { vm.refreshStats() }) { Icon(Icons.Outlined.Refresh, "Refresh") } }
        Info("Address", vm.server)
        Info("Profile", vm.profile?.name ?: "—")
        if (stats != null) {
            Info("CPU", "${stats.cpuPercent.roundToInt()}%")
            Info("Memory", if (stats.memoryPercent > 0) "${stats.memoryPercent.roundToInt()}%" else formatBytes(stats.memoryAvailable) + " available")
            Info("Storage", "${formatBytes(stats.diskFree)} free · ${stats.diskPercent.roundToInt()}% used")
            Info("Temperature", if (stats.temperature > 0) "${stats.temperature.roundToInt()}°C" else "—")
        }
        OutlinedButton(onClick = { vm.logout() }, modifier = Modifier.fillMaxWidth()) { Icon(Icons.Outlined.Logout, null); Spacer(Modifier.width(7.dp)); Text("Sign out") }
    }
}

@Composable private fun Info(label: String, value: String) { Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) { Row(Modifier.fillMaxWidth().padding(15.dp)) { Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f)); Text(value, fontWeight = FontWeight.SemiBold) } } }

private fun tabTitle(tab: MainTab) = when (tab) { MainTab.HOME -> "Nomad"; MainTab.LIBRARY -> "Library"; MainTab.PHOTOS -> "Photos"; MainTab.DOWNLOADS -> "Downloads"; MainTab.SERVER -> "Server" }
private fun extension(path: String): String = path.substringAfterLast('.', "").lowercase()
fun formatBytes(value: Long): String { if (value <= 0) return "—"; val units = arrayOf("B", "KB", "MB", "GB", "TB"); var size = value.toDouble(); var u = 0; while (size >= 1024 && u < units.lastIndex) { size /= 1024; u++ }; return if (u == 0) "${size.roundToInt()} ${units[u]}" else "%.1f %s".format(size, units[u]) }
