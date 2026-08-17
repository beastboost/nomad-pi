package com.nomadpi.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
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
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.outlined.ArrowBack
import androidx.compose.material.icons.outlined.Cancel
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.ClearAll
import androidx.compose.material.icons.outlined.CloudOff
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.Lan
import androidx.compose.material.icons.outlined.Logout
import androidx.compose.material.icons.outlined.MenuBook
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
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import kotlinx.coroutines.delay
import kotlin.math.roundToInt

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            NomadTheme {
                val vm: NomadViewModel = viewModel()
                NomadRoot(vm)
            }
        }
    }
}

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
private fun NomadTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = NomadColors, content = content)
}

@Composable
private fun NomadRoot(vm: NomadViewModel) {
    val snackbar = remember { SnackbarHostState() }
    val message = vm.message
    LaunchedEffect(message) {
        if (!message.isNullOrBlank()) {
            snackbar.showSnackbar(message)
            vm.clearMessage()
        }
    }

    Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
        when {
            vm.playback != null -> NativePlayerScreen(vm, vm.playback!!)
            vm.entry == EntryScreen.LOADING -> LoadingScreen()
            vm.entry == EntryScreen.CONNECT -> ConnectScreen(vm)
            vm.entry == EntryScreen.LOGIN -> LoginScreen(vm)
            vm.entry == EntryScreen.APP -> MainShell(vm, snackbar)
        }
        if (vm.entry != EntryScreen.APP) {
            SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter).navigationBarsPadding())
        }
    }
}

@Composable
private fun LoadingScreen() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(16.dp)) {
            NomadWordmark()
            CircularProgressIndicator()
        }
    }
}

@Composable
private fun NomadWordmark() {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text("NOMAD", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Black)
        Text("native for Android", color = MaterialTheme.colorScheme.primary)
    }
}

@Composable
private fun ConnectScreen(vm: NomadViewModel) {
    var manual by remember(vm.server) { mutableStateOf(vm.server) }
    Column(
        Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        NomadWordmark()
        Spacer(Modifier.height(38.dp))
        Text("Connect to your Nomad", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text(
            "The app can find Nomad on your LAN, or you can enter a hostname, hotspot gateway, Tailscale address or IP.",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 8.dp, bottom = 18.dp),
        )
        OutlinedTextField(
            value = manual,
            onValueChange = { manual = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Server") },
            leadingIcon = { Icon(Icons.Outlined.Lan, null) },
            singleLine = true,
        )
        Button(
            onClick = { vm.selectServer(manual) },
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp).height(52.dp),
        ) { Text("Continue") }

        Row(Modifier.fillMaxWidth().padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { manual = "http://nomadpi.local" }, modifier = Modifier.weight(1f)) {
                Text("nomadpi.local", maxLines = 1)
            }
            OutlinedButton(onClick = { manual = "http://10.42.0.1" }, modifier = Modifier.weight(1f)) {
                Text("Hotspot", maxLines = 1)
            }
        }

        Spacer(Modifier.height(26.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Nearby", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            TextButton(onClick = { vm.startDiscovery() }) {
                Icon(Icons.Outlined.Refresh, null, Modifier.size(18.dp))
                Spacer(Modifier.width(5.dp))
                Text("Scan")
            }
        }
        if (vm.discovering && vm.discovered.isEmpty()) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 10.dp)) {
                CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                Spacer(Modifier.width(10.dp))
                Text("Looking for Nomad…", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        vm.discovered.forEach { found ->
            Card(
                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp).clickable { vm.selectServer(found.url) },
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
            ) {
                Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Outlined.Wifi, null, tint = MaterialTheme.colorScheme.primary)
                    Column(Modifier.padding(start = 12.dp).weight(1f)) {
                        Text(found.name, fontWeight = FontWeight.SemiBold)
                        Text(found.url, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
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
    Column(
        Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        IconButton(onClick = { vm.backToConnect() }) { Icon(Icons.Outlined.ArrowBack, "Back") }
        Spacer(Modifier.height(8.dp))
        NomadWordmark()
        Spacer(Modifier.height(34.dp))
        Text("Sign in", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text(vm.server, color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(top = 4.dp, bottom = 18.dp))
        OutlinedTextField(
            value = username,
            onValueChange = { username = it },
            label = { Text("Username") },
            leadingIcon = { Icon(Icons.Outlined.Person, null) },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
        )
        OutlinedTextField(
            value = password,
            onValueChange = { password = it },
            label = { Text("Password") },
            visualTransformation = PasswordVisualTransformation(),
            modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
            singleLine = true,
        )
        Button(
            enabled = !vm.busy && password.isNotEmpty(),
            onClick = { vm.login(username, password) },
            modifier = Modifier.fillMaxWidth().padding(top = 16.dp).height(52.dp),
        ) {
            if (vm.busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
            else Text("Sign in")
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MainShell(vm: NomadViewModel, snackbar: SnackbarHostState) {
    Scaffold(
        modifier = Modifier.fillMaxSize(),
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(tabTitle(vm.tab), fontWeight = FontWeight.Bold)
                        Text("${vm.profile?.name ?: vm.session?.username.orEmpty()} · ${vm.server.removePrefix("http://").removePrefix("https://")}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                },
                actions = { ProfileMenu(vm) },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        },
        bottomBar = { BottomNav(vm) },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when (vm.tab) {
                MainTab.HOME -> HomeScreen(vm)
                MainTab.LIBRARY -> LibraryScreen(vm)
                MainTab.PHOTOS -> PhotosScreen(vm)
                MainTab.DOWNLOADS -> DownloadsScreen(vm)
                MainTab.SERVER -> ServerScreen(vm)
            }
            if (vm.busy) {
                LinearProgressIndicator(Modifier.fillMaxWidth().align(Alignment.TopCenter))
            }
        }
    }
}

@Composable
private fun BottomNav(vm: NomadViewModel) {
    NavigationBar(containerColor = MaterialTheme.colorScheme.surface) {
        val items = listOf(
            Triple(MainTab.HOME, "Home", Icons.Outlined.Home),
            Triple(MainTab.LIBRARY, "Library", Icons.Outlined.VideoLibrary),
            Triple(MainTab.PHOTOS, "Photos", Icons.Outlined.PhotoLibrary),
            Triple(MainTab.DOWNLOADS, "Downloads", Icons.Outlined.Download),
            Triple(MainTab.SERVER, "Server", Icons.Outlined.Dns),
        )
        items.forEach { (tab, label, icon) ->
            NavigationBarItem(
                selected = vm.tab == tab,
                onClick = { vm.chooseTab(tab) },
                icon = { Icon(icon, label) },
                label = { Text(label, maxLines = 1) },
            )
        }
    }
}

@Composable
private fun ProfileMenu(vm: NomadViewModel) {
    var open by remember { mutableStateOf(false) }
    var pinTarget by remember { mutableStateOf<NomadProfile?>(null) }
    var pin by remember { mutableStateOf("") }
    Box {
        TextButton(onClick = { open = true }) {
            Icon(Icons.Outlined.Person, null)
            Spacer(Modifier.width(4.dp))
            Text(vm.profile?.name ?: "Profile", maxLines = 1)
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            vm.profiles.forEach { target ->
                DropdownMenuItem(
                    text = {
                        Column {
                            Text(target.name, fontWeight = if (target.id == vm.profile?.id) FontWeight.Bold else FontWeight.Normal)
                            if (target.pinRequired) Text("PIN protected", style = MaterialTheme.typography.labelSmall)
                        }
                    },
                    onClick = {
                        open = false
                        if (target.id == vm.profile?.id) return@DropdownMenuItem
                        if (target.pinRequired) {
                            pin = ""
                            pinTarget = target
                        } else vm.switchProfile(target)
                    },
                )
            }
        }
    }
    pinTarget?.let { target ->
        AlertDialog(
            onDismissRequest = { pinTarget = null },
            title = { Text(target.name) },
            text = {
                OutlinedTextField(
                    value = pin,
                    onValueChange = { if (it.length <= 8) pin = it },
                    label = { Text("Profile PIN") },
                    visualTransformation = PasswordVisualTransformation(),
                    singleLine = true,
                )
            },
            confirmButton = {
                Button(onClick = {
                    vm.switchProfile(target, pin) { ok -> if (ok) pinTarget = null }
                }) { Text("Switch") }
            },
            dismissButton = { TextButton(onClick = { pinTarget = null }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun HomeScreen(vm: NomadViewModel) {
    val stats = vm.stats
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
                Column(Modifier.padding(18.dp)) {
                    Text("Nomad is connected", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                    Text(vm.server, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    if (stats != null) {
                        Row(Modifier.padding(top = 14.dp), horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                            Stat("CPU", "${stats.cpuPercent.roundToInt()}%")
                            Stat("Temp", if (stats.temperature > 0) "${stats.temperature.roundToInt()}°C" else "—")
                            Stat("Free", formatBytes(stats.diskFree))
                        }
                    }
                }
            }
        }
        item { Text("Jump in", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                QuickButton("Movies", Icons.Outlined.Movie, Modifier.weight(1f)) { vm.chooseTab(MainTab.LIBRARY); vm.chooseLibrary(LibrarySection.MOVIES) }
                QuickButton("Shows", Icons.Outlined.Tv, Modifier.weight(1f)) { vm.chooseTab(MainTab.LIBRARY); vm.chooseLibrary(LibrarySection.SHOWS) }
            }
        }
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                QuickButton("Music", Icons.Outlined.MusicNote, Modifier.weight(1f)) { vm.chooseTab(MainTab.LIBRARY); vm.chooseLibrary(LibrarySection.MUSIC) }
                QuickButton("Photos", Icons.Outlined.Image, Modifier.weight(1f)) { vm.chooseTab(MainTab.PHOTOS) }
            }
        }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                Column(Modifier.padding(16.dp)) {
                    Text("Native playback", fontWeight = FontWeight.Bold)
                    Text(
                        "This phone reports its hardware decoders to Nomad. Compatible files direct-play on the phone; the Pi only remuxes or converts audio when it really has to.",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun Stat(label: String, value: String) {
    Column {
        Text(value, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun QuickButton(label: String, icon: androidx.compose.ui.graphics.vector.ImageVector, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Card(modifier.clickable(onClick = onClick), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Column(Modifier.fillMaxWidth().padding(18.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(icon, null, tint = MaterialTheme.colorScheme.primary)
            Text(label, modifier = Modifier.padding(top = 7.dp), fontWeight = FontWeight.SemiBold)
        }
    }
}

@Composable
private fun LibraryScreen(vm: NomadViewModel) {
    var query by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            SectionButton("Movies", vm.librarySection == LibrarySection.MOVIES, Modifier.weight(1f)) { vm.chooseLibrary(LibrarySection.MOVIES) }
            SectionButton("Shows", vm.librarySection == LibrarySection.SHOWS, Modifier.weight(1f)) { vm.chooseLibrary(LibrarySection.SHOWS) }
            SectionButton("Music", vm.librarySection == LibrarySection.MUSIC, Modifier.weight(1f)) { vm.chooseLibrary(LibrarySection.MUSIC) }
            SectionButton("Books", vm.librarySection == LibrarySection.BOOKS, Modifier.weight(1f)) { vm.chooseLibrary(LibrarySection.BOOKS) }
        }
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp),
            placeholder = { Text("Filter this library") },
            leadingIcon = { Icon(Icons.Outlined.Search, null) },
            trailingIcon = { IconButton(onClick = { vm.refreshLibrary() }) { Icon(Icons.Outlined.Refresh, "Refresh") } },
            singleLine = true,
        )

        if (vm.librarySection == LibrarySection.SHOWS) {
            val filtered = vm.shows.filter { query.isBlank() || it.name.contains(query, ignoreCase = true) }
            ShowsList(vm, filtered)
        } else {
            val filtered = vm.library.filter { query.isBlank() || it.name.contains(query, ignoreCase = true) || it.folder.contains(query, ignoreCase = true) }
            when (vm.librarySection) {
                LibrarySection.MOVIES -> MovieGrid(vm, filtered)
                LibrarySection.MUSIC -> MediaList(vm, filtered, Icons.Outlined.MusicNote, canPlay = true)
                LibrarySection.BOOKS -> MediaList(vm, filtered, Icons.Outlined.MenuBook, canPlay = false)
                LibrarySection.SHOWS -> Unit
            }
        }
    }
}

@Composable
private fun SectionButton(label: String, selected: Boolean, modifier: Modifier, onClick: () -> Unit) {
    if (selected) Button(onClick = onClick, modifier = modifier, contentPadding = PaddingValues(horizontal = 8.dp)) { Text(label) }
    else OutlinedButton(onClick = onClick, modifier = modifier, contentPadding = PaddingValues(horizontal = 8.dp)) { Text(label) }
}

@Composable
private fun MovieGrid(vm: NomadViewModel, items: List<LibraryItem>) {
    if (items.isEmpty() && !vm.busy) return EmptyState("No movies found")
    LazyVerticalGrid(
        columns = GridCells.Adaptive(140.dp),
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        items(items, key = { it.path }) { item ->
            Column(Modifier.clickable { vm.play(item) }) {
                RemoteImage(
                    vm.api.imageUrl(item.poster),
                    Modifier.fillMaxWidth().aspectRatio(2f / 3f).background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(12.dp)),
                    maxDecodePx = 600,
                )
                Text(stripExtension(item.name), fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 7.dp))
                val pct = if (item.duration > 0) (item.progress / item.duration).coerceIn(0.0, 1.0) else 0.0
                if (pct > 0) LinearProgressIndicator(progress = { pct.toFloat() }, modifier = Modifier.fillMaxWidth().padding(top = 5.dp))
            }
        }
    }
}

@Composable
private fun ShowsList(vm: NomadViewModel, shows: List<ShowItem>) {
    if (shows.isEmpty() && !vm.busy) return EmptyState("No shows found")
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        items(shows, key = { it.name }) { show -> ShowCard(vm, show) }
    }
}

@Composable
private fun ShowCard(vm: NomadViewModel, show: ShowItem) {
    var expanded by remember(show.name) { mutableStateOf(false) }
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Row(Modifier.fillMaxWidth().clickable { expanded = !expanded }.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            RemoteImage(vm.api.imageUrl(show.poster), Modifier.width(72.dp).aspectRatio(2f / 3f), maxDecodePx = 400)
            Column(Modifier.padding(start = 12.dp).weight(1f)) {
                Text(show.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text("${show.seasons.size} season${if (show.seasons.size == 1) "" else "s"}", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Text(if (expanded) "Hide" else "Episodes", color = MaterialTheme.colorScheme.primary)
        }
        AnimatedVisibility(expanded) {
            Column {
                HorizontalDivider()
                show.seasons.forEach { season ->
                    Text(season.name, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp))
                    season.episodes.forEach { ep ->
                        Row(
                            Modifier.fillMaxWidth().clickable { vm.playEpisode(ep) }.padding(horizontal = 14.dp, vertical = 9.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Icon(Icons.Filled.PlayArrow, null, tint = MaterialTheme.colorScheme.primary)
                            Text(stripExtension(ep.name), modifier = Modifier.padding(start = 10.dp).weight(1f), maxLines = 2, overflow = TextOverflow.Ellipsis)
                            if (ep.episodeNumber != 999) Text("E${ep.episodeNumber}", style = MaterialTheme.typography.labelSmall)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun MediaList(
    vm: NomadViewModel,
    items: List<LibraryItem>,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    canPlay: Boolean,
) {
    if (items.isEmpty() && !vm.busy) return EmptyState("Nothing here yet")
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        items(items, key = { it.path }) { item ->
            Row(
                Modifier.fillMaxWidth().clickable(enabled = canPlay) { if (canPlay) vm.play(item) }.padding(vertical = 10.dp, horizontal = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(icon, null, Modifier.size(28.dp), tint = MaterialTheme.colorScheme.primary)
                Column(Modifier.padding(start = 12.dp).weight(1f)) {
                    Text(stripExtension(item.name), fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(item.folder.ifBlank { item.type }, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                }
                if (canPlay) Icon(Icons.Filled.PlayArrow, "Play")
                else Text("Reader", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.labelSmall)
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.surfaceVariant)
        }
    }
}

@Composable
private fun PhotosScreen(vm: NomadViewModel) {
    val result = vm.photos
    var viewer by remember { mutableIntStateOf(-1) }
    Box(Modifier.fillMaxSize()) {
        if (result == null) {
            if (!vm.busy) EmptyState("Open Photos to load this profile's private library")
        } else if (result.items.isEmpty()) {
            EmptyState("No photos in ${result.profile?.name ?: "this profile"}'s library")
        } else {
            LazyVerticalGrid(
                columns = GridCells.Fixed(3),
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(2.dp),
            ) {
                items(result.items, key = { it.id }) { item ->
                    Box(Modifier.aspectRatio(1f).padding(1.dp).clickable {
                        viewer = result.items.indexOfFirst { it.id == item.id }
                    }) {
                        if (item.kind == "image") {
                            RemoteImage(vm.api.galleryItemUrl(item.id), Modifier.fillMaxSize(), maxDecodePx = 480)
                        } else {
                            Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.surfaceVariant), contentAlignment = Alignment.Center) {
                                Icon(Icons.Filled.PlayArrow, "Video", Modifier.size(42.dp))
                            }
                        }
                    }
                }
            }
        }
        IconButton(onClick = { vm.refreshPhotos() }, modifier = Modifier.align(Alignment.TopEnd).padding(8.dp).background(MaterialTheme.colorScheme.surface.copy(alpha = .75f), RoundedCornerShape(50))) {
            Icon(Icons.Outlined.Refresh, "Refresh")
        }
    }
    if (viewer >= 0 && result != null && viewer < result.items.size) {
        PhotoViewer(vm, result.items, viewer) { viewer = -1 }
    }
}

@Composable
private fun PhotoViewer(vm: NomadViewModel, items: List<GalleryItem>, initial: Int, onClose: () -> Unit) {
    BackHandler(onBack = onClose)
    val state = rememberPagerState(initialPage = initial.coerceIn(0, items.lastIndex)) { items.size }
    Surface(Modifier.fillMaxSize(), color = Color.Black) {
        Box(Modifier.fillMaxSize()) {
            HorizontalPager(state = state, modifier = Modifier.fillMaxSize()) { index ->
                val item = items[index]
                if (item.kind == "image") {
                    RemoteImage(
                        vm.api.galleryItemUrl(item.id),
                        Modifier.fillMaxSize(),
                        contentScale = ContentScale.Fit,
                        maxDecodePx = 2400,
                    )
                } else {
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Icon(Icons.Filled.PlayArrow, null, Modifier.size(64.dp), tint = Color.White)
                            Text("Gallery video", color = Color.White)
                            Text("Video playback is next in the native Photos pass", color = Color.LightGray)
                        }
                    }
                }
            }
            Row(
                Modifier.fillMaxWidth().statusBarsPadding().padding(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = onClose) { Icon(Icons.Outlined.ArrowBack, "Close", tint = Color.White) }
                val current = items[state.currentPage]
                Column(Modifier.weight(1f)) {
                    Text(current.name, color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text("${state.currentPage + 1} / ${items.size}", color = Color.LightGray, style = MaterialTheme.typography.labelSmall)
                }
            }
        }
    }
}

@Composable
private fun DownloadsScreen(vm: NomadViewModel) {
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("${vm.downloads.size} queue item${if (vm.downloads.size == 1) "" else "s"}", modifier = Modifier.weight(1f), color = MaterialTheme.colorScheme.onSurfaceVariant)
            TextButton(onClick = { vm.refreshDownloads() }) { Icon(Icons.Outlined.Refresh, null); Text("Refresh") }
            if (vm.downloads.isNotEmpty()) {
                TextButton(onClick = { vm.clearDownloadQueue() }) { Icon(Icons.Outlined.ClearAll, null); Text("Clear") }
            }
        }
        if (vm.downloads.isEmpty() && !vm.busy) {
            EmptyState("Download queue is empty")
        } else {
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(vm.downloads, key = { it.id }) { job ->
                    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                        Column(Modifier.padding(14.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Column(Modifier.weight(1f)) {
                                    Text(job.filename, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                    Text(downloadStatus(job), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                                if (job.status.lowercase() !in setOf("completed", "failed", "error", "cancelled")) {
                                    IconButton(onClick = { vm.cancelDownload(job.id) }) { Icon(Icons.Outlined.Cancel, "Cancel") }
                                } else if (job.status.lowercase() == "completed") {
                                    Icon(Icons.Outlined.CheckCircle, null, tint = MaterialTheme.colorScheme.primary)
                                }
                            }
                            LinearProgressIndicator(progress = { (job.progress / 100.0).coerceIn(0.0, 1.0).toFloat() }, modifier = Modifier.fillMaxWidth().padding(top = 10.dp))
                            job.error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp)) }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ServerScreen(vm: NomadViewModel) {
    val stats = vm.stats
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Appliance", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            IconButton(onClick = { vm.refreshStats() }) { Icon(Icons.Outlined.Refresh, "Refresh") }
        }
        InfoCard("Address", vm.server)
        InfoCard("Profile", vm.profile?.name ?: "—")
        if (stats != null) {
            InfoCard("CPU", "${stats.cpuPercent.roundToInt()}%")
            InfoCard("Memory", if (stats.memoryPercent > 0) "${stats.memoryPercent.roundToInt()}%" else formatBytes(stats.memoryAvailable) + " available")
            InfoCard("Storage", "${formatBytes(stats.diskFree)} free · ${stats.diskPercent.roundToInt()}% used")
            InfoCard("Temperature", if (stats.temperature > 0) "${stats.temperature.roundToInt()}°C" else "Not reported")
        }
        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
            Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Outlined.Lan, null, tint = MaterialTheme.colorScheme.primary)
                Column(Modifier.padding(start = 12.dp).weight(1f)) {
                    Text("Local-first", fontWeight = FontWeight.Bold)
                    Text("The native app talks directly to this Nomad. No cloud relay is required.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
        OutlinedButton(onClick = { vm.logout() }, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Outlined.Logout, null)
            Spacer(Modifier.width(8.dp))
            Text("Sign out")
        }
    }
}

@Composable
private fun InfoCard(label: String, value: String) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Row(Modifier.fillMaxWidth().padding(16.dp)) {
            Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
            Text(value, fontWeight = FontWeight.SemiBold)
        }
    }
}

@Composable
private fun EmptyState(text: String) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.padding(30.dp)) {
            Icon(Icons.Outlined.CloudOff, null, Modifier.size(38.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(text, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 10.dp))
        }
    }
}

@Composable
private fun NativePlayerScreen(vm: NomadViewModel, active: ActivePlayback) {
    val context = LocalContext.current
    val player = remember(active.url) {
        ExoPlayer.Builder(context).build().apply {
            setMediaItem(MediaItem.fromUri(active.url))
            prepare()
            playWhenReady = true
        }
    }
    var playing by remember { mutableStateOf(true) }
    var position by remember { mutableLongStateOf(0L) }
    var duration by remember { mutableLongStateOf(0L) }

    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) { playing = isPlaying }
        }
        player.addListener(listener)
        onDispose {
            vm.closePlayback(position, duration)
            player.removeListener(listener)
            player.release()
        }
    }
    LaunchedEffect(player) {
        while (true) {
            position = player.currentPosition.coerceAtLeast(0L)
            duration = player.duration.takeIf { it != C.TIME_UNSET && it > 0 } ?: 0L
            delay(500)
        }
    }
    LaunchedEffect(active.sessionId) {
        while (active.sessionId != null) {
            delay(10_000)
            vm.heartbeat(player.currentPosition, player.duration.takeIf { it != C.TIME_UNSET } ?: 0L, player.isPlaying)
        }
    }
    BackHandler { vm.closePlayback(position, duration); player.release() }

    if (!active.audioOnly) {
        Box(Modifier.fillMaxSize().background(Color.Black)) {
            AndroidView(
                factory = { ctx -> PlayerView(ctx).apply { this.player = player; useController = true } },
                update = { it.player = player },
                modifier = Modifier.fillMaxSize(),
            )
            Row(Modifier.fillMaxWidth().statusBarsPadding().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { vm.closePlayback(position, duration); player.release() }) {
                    Icon(Icons.Outlined.ArrowBack, "Close", tint = Color.White)
                }
                Column(Modifier.weight(1f)) {
                    Text(active.title, color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.Bold)
                    Text(active.mode.replace('_', ' '), color = Color.LightGray, style = MaterialTheme.typography.labelSmall)
                }
            }
        }
    } else {
        Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            Column(
                Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Row(Modifier.fillMaxWidth()) {
                    IconButton(onClick = { vm.closePlayback(position, duration); player.release() }) { Icon(Icons.Outlined.ArrowBack, "Close") }
                    Spacer(Modifier.weight(1f))
                    Text("Direct audio", color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(top = 14.dp))
                }
                Spacer(Modifier.weight(.6f))
                Box(
                    Modifier.fillMaxWidth(.72f).aspectRatio(1f).background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(24.dp)),
                    contentAlignment = Alignment.Center,
                ) { Icon(Icons.Outlined.MusicNote, null, Modifier.size(90.dp), tint = MaterialTheme.colorScheme.primary) }
                Text(stripExtension(active.title), style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 28.dp))
                Text("Native Media3 · HTTP Range", color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 6.dp))
                Spacer(Modifier.height(28.dp))
                val fraction = if (duration > 0) (position.toFloat() / duration.toFloat()).coerceIn(0f, 1f) else 0f
                androidx.compose.material3.Slider(
                    value = fraction,
                    onValueChange = { if (duration > 0) player.seekTo((duration * it).toLong()) },
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(Modifier.fillMaxWidth()) {
                    Text(formatTime(position), style = MaterialTheme.typography.labelSmall)
                    Spacer(Modifier.weight(1f))
                    Text(formatTime(duration), style = MaterialTheme.typography.labelSmall)
                }
                Spacer(Modifier.height(20.dp))
                IconButton(
                    onClick = { if (player.isPlaying) player.pause() else player.play() },
                    modifier = Modifier.size(76.dp).background(MaterialTheme.colorScheme.primaryContainer, RoundedCornerShape(50)),
                ) {
                    Icon(if (playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, if (playing) "Pause" else "Play", Modifier.size(42.dp))
                }
                Spacer(Modifier.weight(1f))
            }
        }
    }
}

private fun tabTitle(tab: MainTab) = when (tab) {
    MainTab.HOME -> "Nomad"
    MainTab.LIBRARY -> "Library"
    MainTab.PHOTOS -> "Photos"
    MainTab.DOWNLOADS -> "Downloads"
    MainTab.SERVER -> "Server"
}

private fun stripExtension(value: String): String = value.replace(Regex("\\.[A-Za-z0-9]{2,5}$"), "")

private fun formatBytes(value: Long): String {
    if (value <= 0) return "—"
    val units = arrayOf("B", "KB", "MB", "GB", "TB")
    var size = value.toDouble()
    var unit = 0
    while (size >= 1024 && unit < units.lastIndex) { size /= 1024; unit++ }
    return if (unit == 0) "${size.roundToInt()} ${units[unit]}" else "%.1f %s".format(size, units[unit])
}

private fun formatTime(ms: Long): String {
    val total = (ms.coerceAtLeast(0) / 1000).toInt()
    val h = total / 3600
    val m = (total % 3600) / 60
    val s = total % 60
    return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%d:%02d".format(m, s)
}

private fun downloadStatus(job: DownloadJob): String {
    val speed = if (job.speed > 0) " · ${formatBytes(job.speed)}/s" else ""
    val size = if (job.total > 0) " · ${formatBytes(job.downloaded)} / ${formatBytes(job.total)}" else ""
    return "${job.status.replaceFirstChar { it.uppercase() }} · ${job.progress.roundToInt()}%$speed$size"
}
