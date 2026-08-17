package com.nomadpi.android

import android.content.Intent
import android.content.res.Configuration
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.weight
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
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
import androidx.compose.material.icons.outlined.ClearAll
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Logout
import androidx.compose.material.icons.outlined.Movie
import androidx.compose.material.icons.outlined.MusicNote
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.PhotoLibrary
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Tv
import androidx.compose.material.icons.outlined.VideoLibrary
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.roundToInt

enum class NativeTab { HOME, LIBRARY, PHOTOS, DOWNLOADS, SETTINGS }

@Composable
fun NomadNativeApp(vm: NomadViewModel) {
    val context = LocalContext.current
    val prefs = remember { NomadUiPreferences(context) }
    val scope = rememberCoroutineScope()
    var uiSettings by remember { mutableStateOf(NomadUiSettings()) }
    var tab by remember { mutableStateOf(NativeTab.HOME) }
    var searchOpen by remember { mutableStateOf(false) }
    var reader by remember { mutableStateOf<NativeReaderSource?>(null) }
    val snackbar = remember { SnackbarHostState() }

    LaunchedEffect(Unit) {
        uiSettings = prefs.load()
    }

    val message = vm.message
    LaunchedEffect(message) {
        if (!message.isNullOrBlank()) {
            snackbar.showSnackbar(message)
            vm.clearMessage()
        }
    }

    vm.playback?.let { active ->
        if (active.audioOnly) {
            NativeMediaPlayer(
                source = NativeMediaSource(active.title, active.url, active.mode, true),
                onClose = { p, d -> vm.closePlayback(p, d) },
                onHeartbeat = if (active.sessionId != null) ({ p, d, playing -> vm.heartbeat(p, d, playing) }) else null,
            )
        } else {
            NomadVideoPlayer(
                active = active,
                api = vm.api,
                settings = uiSettings,
                onClose = { p, d -> vm.closePlayback(p, d) },
                onHeartbeat = if (active.sessionId != null) ({ p, d, playing -> vm.heartbeat(p, d, playing) }) else null,
            )
        }
        return
    }

    reader?.let { source ->
        NativeReader(vm.api, source) { reader = null }
        return
    }

    if (searchOpen) {
        BackHandler { searchOpen = false }
        Scaffold(
            topBar = {
                TopAppBar(
                    title = { Text("Search Nomad", fontWeight = FontWeight.Bold) },
                    navigationIcon = {
                        IconButton(onClick = { searchOpen = false }) {
                            Icon(Icons.Outlined.ArrowBack, "Back")
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
                )
            },
        ) { padding ->
            Box(Modifier.fillMaxSize().padding(padding)) {
                NativeUniversalSearch(vm.api)
            }
        }
        return
    }

    val configuration = LocalConfiguration.current
    val landscape = configuration.orientation == Configuration.ORIENTATION_LANDSCAPE

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("NOMAD", fontWeight = FontWeight.Black)
                        Text(
                            vm.profile?.name ?: vm.session?.username.orEmpty(),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                },
                actions = {
                    IconButton(onClick = { searchOpen = true }) {
                        Icon(Icons.Outlined.Search, "Search")
                    }
                    NativeProfileMenu(vm)
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        },
        bottomBar = {
            if (!landscape) NativeBottomBar(tab) { tab = it }
        },
    ) { padding ->
        if (landscape) {
            Row(Modifier.fillMaxSize().padding(padding)) {
                NativeRail(tab) { tab = it }
                NativeContent(
                    vm = vm,
                    tab = tab,
                    settings = uiSettings,
                    onSettingsChange = { next ->
                        uiSettings = next
                        scope.launch { prefs.save(next) }
                    },
                    onSearch = { searchOpen = true },
                    onRead = { reader = it },
                    modifier = Modifier.weight(1f),
                )
            }
        } else {
            NativeContent(
                vm = vm,
                tab = tab,
                settings = uiSettings,
                onSettingsChange = { next ->
                    uiSettings = next
                    scope.launch { prefs.save(next) }
                },
                onSearch = { searchOpen = true },
                onRead = { reader = it },
                modifier = Modifier.fillMaxSize().padding(padding),
            )
        }
    }
}

@Composable
private fun NativeContent(
    vm: NomadViewModel,
    tab: NativeTab,
    settings: NomadUiSettings,
    onSettingsChange: (NomadUiSettings) -> Unit,
    onSearch: () -> Unit,
    onRead: (NativeReaderSource) -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(modifier.background(MaterialTheme.colorScheme.background)) {
        when (tab) {
            NativeTab.HOME -> NativeHome(vm, onSearch)
            NativeTab.LIBRARY -> NativeLibrary(vm, onRead)
            NativeTab.PHOTOS -> NativePhotos(vm)
            NativeTab.DOWNLOADS -> NativeDownloads(vm)
            NativeTab.SETTINGS -> NativeSettings(vm, settings, onSettingsChange)
        }
        if (vm.busy && vm.playback == null) {
            Card(
                modifier = Modifier.align(Alignment.Center),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = .96f)),
            ) {
                Row(Modifier.padding(horizontal = 18.dp, vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp)
                    Text("Loading…", modifier = Modifier.padding(start = 12.dp), fontWeight = FontWeight.SemiBold)
                }
            }
        }
    }
}

@Composable
private fun NativeBottomBar(selected: NativeTab, onSelect: (NativeTab) -> Unit) {
    NavigationBar(containerColor = MaterialTheme.colorScheme.surface) {
        nativeDestinations().forEach { (tab, label, icon) ->
            NavigationBarItem(
                selected = selected == tab,
                onClick = { onSelect(tab) },
                icon = { Icon(icon, label) },
                label = { Text(label, maxLines = 1) },
            )
        }
    }
}

@Composable
private fun NativeRail(selected: NativeTab, onSelect: (NativeTab) -> Unit) {
    NavigationRail(containerColor = MaterialTheme.colorScheme.surface) {
        Spacer(Modifier.height(8.dp))
        nativeDestinations().forEach { (tab, label, icon) ->
            NavigationRailItem(
                selected = selected == tab,
                onClick = { onSelect(tab) },
                icon = { Icon(icon, label) },
                label = { Text(label) },
            )
        }
    }
}

private fun nativeDestinations() = listOf(
    Triple(NativeTab.HOME, "Home", Icons.Outlined.Home),
    Triple(NativeTab.LIBRARY, "Library", Icons.Outlined.VideoLibrary),
    Triple(NativeTab.PHOTOS, "Photos", Icons.Outlined.PhotoLibrary),
    Triple(NativeTab.DOWNLOADS, "Downloads", Icons.Outlined.Download),
    Triple(NativeTab.SETTINGS, "Settings", Icons.Outlined.Settings),
)

@Composable
private fun NativeProfileMenu(vm: NomadViewModel) {
    var open by remember { mutableStateOf(false) }
    var pinTarget by remember { mutableStateOf<NomadProfile?>(null) }
    var pin by remember { mutableStateOf("") }

    Box {
        IconButton(onClick = { open = true }) {
            Icon(Icons.Outlined.Person, "Profile")
        }
        androidx.compose.material3.DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            vm.profiles.forEach { target ->
                androidx.compose.material3.DropdownMenuItem(
                    text = {
                        Text(
                            target.name + if (target.pinRequired) " · PIN" else "",
                            fontWeight = if (target.id == vm.profile?.id) FontWeight.Bold else FontWeight.Normal,
                        )
                    },
                    onClick = {
                        open = false
                        if (target.id == vm.profile?.id) return@DropdownMenuItem
                        if (target.pinRequired) {
                            pin = ""
                            pinTarget = target
                        } else {
                            vm.switchProfile(target)
                        }
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
                    singleLine = true,
                )
            },
            confirmButton = {
                Button(onClick = { vm.switchProfile(target, pin) { if (it) pinTarget = null } }) {
                    Text("Switch")
                }
            },
            dismissButton = {
                TextButton(onClick = { pinTarget = null }) { Text("Cancel") }
            },
        )
    }
}

@Composable
private fun NativeHome(vm: NomadViewModel, onSearch: () -> Unit) {
    var movies by remember(vm.profile?.id) { mutableStateOf<List<LibraryItem>>(emptyList()) }
    var loading by remember(vm.profile?.id) { mutableStateOf(true) }

    LaunchedEffect(vm.profile?.id) {
        loading = true
        movies = withContext(Dispatchers.IO) { runCatching { vm.api.library("movies", 60) }.getOrDefault(emptyList()) }
        loading = false
        vm.refreshStats()
    }

    val continuing = movies.filter { it.progress > 0 && it.duration > 0 && it.progress < it.duration * .95 }.take(12)
    val recent = movies.take(18)

    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(horizontal = 18.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(22.dp),
    ) {
        item {
            Column {
                Text("Your media", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text(
                    "${vm.profile?.name ?: "Nomad"} · ${vm.server.removePrefix("http://").removePrefix("https://")}",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 3.dp),
                )
            }
        }

        item {
            Card(
                modifier = Modifier.fillMaxWidth().clickable(onClick = onSearch),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
            ) {
                Row(Modifier.fillMaxWidth().padding(18.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Outlined.Search, null, tint = MaterialTheme.colorScheme.onPrimaryContainer)
                    Column(Modifier.padding(start = 14.dp).weight(1f)) {
                        Text("Find anything", fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onPrimaryContainer)
                        Text("Movies, shows and debrid sources", color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = .75f))
                    }
                }
            }
        }

        if (continuing.isNotEmpty()) {
            item { NativeSectionTitle("Continue watching") }
            item {
                LazyRow(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    items(continuing, key = { it.path }) { item ->
                        HomePoster(item, vm, showProgress = true)
                    }
                }
            }
        }

        item { NativeSectionTitle("Recently added") }
        if (loading && recent.isEmpty()) {
            item {
                Box(Modifier.fillMaxWidth().height(180.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
            }
        } else if (recent.isEmpty()) {
            item { Text("No movies in this profile yet.", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        } else {
            item {
                LazyRow(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    items(recent, key = { it.path }) { item -> HomePoster(item, vm, showProgress = false) }
                }
            }
        }
    }
}

@Composable
private fun NativeSectionTitle(text: String) {
    Text(text, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
}

@Composable
private fun HomePoster(item: LibraryItem, vm: NomadViewModel, showProgress: Boolean) {
    Column(Modifier.width(132.dp).clickable { vm.playPath(item.path, item.name, false, item.progress) }) {
        Card(shape = RoundedCornerShape(14.dp)) {
            Box {
                RemoteImage(vm.api.imageUrl(item.poster), Modifier.fillMaxWidth().aspectRatio(2f / 3f), maxDecodePx = 500)
                if (showProgress && item.duration > 0) {
                    LinearProgressIndicator(
                        progress = { (item.progress / item.duration).toFloat().coerceIn(0f, 1f) },
                        modifier = Modifier.fillMaxWidth().align(Alignment.BottomCenter),
                    )
                }
            }
        }
        Text(
            stripMediaExtension(item.name),
            fontWeight = FontWeight.SemiBold,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(top = 7.dp),
        )
    }
}

@Composable
private fun NativeLibrary(vm: NomadViewModel, onRead: (NativeReaderSource) -> Unit) {
    val context = LocalContext.current
    var query by remember { mutableStateOf("") }
    var selectedShow by remember { mutableStateOf<ShowItem?>(null) }

    LaunchedEffect(vm.librarySection, vm.profile?.id) { vm.refreshLibrary() }

    selectedShow?.let { show ->
        BackHandler { selectedShow = null }
        NativeShowDetail(vm, show) { selectedShow = null }
        return
    }

    val sections = LibrarySection.entries
    val selectedIndex = sections.indexOf(vm.librarySection).coerceAtLeast(0)

    Column(Modifier.fillMaxSize()) {
        PrimaryTabRow(selectedTabIndex = selectedIndex) {
            sections.forEach { section ->
                Tab(
                    selected = vm.librarySection == section,
                    onClick = { vm.chooseLibrary(section) },
                    text = { Text(section.nativeLabel()) },
                    icon = {
                        Icon(
                            when (section) {
                                LibrarySection.MOVIES -> Icons.Outlined.Movie
                                LibrarySection.SHOWS -> Icons.Outlined.Tv
                                LibrarySection.MUSIC -> Icons.Outlined.MusicNote
                                LibrarySection.BOOKS -> Icons.Outlined.Book
                            },
                            null,
                        )
                    },
                )
            }
        }

        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            modifier = Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 10.dp),
            placeholder = { Text("Search ${vm.librarySection.nativeLabel().lowercase()}") },
            leadingIcon = { Icon(Icons.Outlined.Search, null) },
            trailingIcon = {
                IconButton(onClick = { vm.refreshLibrary() }) { Icon(Icons.Outlined.Refresh, "Refresh") }
            },
            singleLine = true,
        )

        when (vm.librarySection) {
            LibrarySection.MOVIES -> {
                val list = vm.library.filter { query.isBlank() || it.name.contains(query, true) }
                LazyVerticalGrid(
                    columns = GridCells.Adaptive(132.dp),
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(12.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    items(list, key = { it.path }) { item ->
                        Column(Modifier.clickable { vm.playPath(item.path, item.name, false, item.progress) }) {
                            Card(shape = RoundedCornerShape(14.dp)) {
                                Box {
                                    RemoteImage(vm.api.imageUrl(item.poster), Modifier.fillMaxWidth().aspectRatio(2f / 3f), maxDecodePx = 600)
                                    if (item.duration > 0 && item.progress > 0) {
                                        LinearProgressIndicator(
                                            progress = { (item.progress / item.duration).toFloat().coerceIn(0f, 1f) },
                                            modifier = Modifier.fillMaxWidth().align(Alignment.BottomCenter),
                                        )
                                    }
                                }
                            }
                            Text(stripMediaExtension(item.name), fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 7.dp))
                            item.year?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                        }
                    }
                }
            }

            LibrarySection.SHOWS -> {
                val list = vm.shows.filter { query.isBlank() || it.name.contains(query, true) }
                LazyVerticalGrid(
                    columns = GridCells.Adaptive(132.dp),
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(12.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    items(list, key = { it.name }) { show ->
                        Column(Modifier.clickable { selectedShow = show }) {
                            Card(shape = RoundedCornerShape(14.dp)) {
                                RemoteImage(vm.api.imageUrl(show.poster), Modifier.fillMaxWidth().aspectRatio(2f / 3f), maxDecodePx = 600)
                            }
                            Text(show.name, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 7.dp))
                            Text("${show.seasons.size} seasons", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }

            LibrarySection.MUSIC, LibrarySection.BOOKS -> {
                val list = vm.library.filter { query.isBlank() || it.name.contains(query, true) || it.folder.contains(query, true) }
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(horizontal = 8.dp, vertical = 4.dp)) {
                    items(list, key = { it.path }) { item ->
                        ListItem(
                            headlineContent = { Text(stripMediaExtension(item.name), maxLines = 1, overflow = TextOverflow.Ellipsis) },
                            supportingContent = { if (item.folder.isNotBlank()) Text(item.folder, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                            leadingContent = {
                                Icon(if (vm.librarySection == LibrarySection.MUSIC) Icons.Outlined.MusicNote else Icons.Outlined.Book, null)
                            },
                            trailingContent = {
                                if (vm.librarySection == LibrarySection.MUSIC) Icon(Icons.Filled.PlayArrow, null)
                            },
                            modifier = Modifier.clickable {
                                if (vm.librarySection == LibrarySection.MUSIC) {
                                    vm.playPath(item.path, item.name, true, item.progress)
                                } else {
                                    when (item.path.substringAfterLast('.', "").lowercase()) {
                                        "cbz", "cbr" -> onRead(NativeReaderSource.Comic(item.path, stripMediaExtension(item.name)))
                                        "pdf" -> onRead(NativeReaderSource.Pdf(item.path, stripMediaExtension(item.name)))
                                        else -> runCatching {
                                            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(vm.api.mediaStreamUrl(item.path))))
                                        }
                                    }
                                }
                            },
                        )
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    }
                }
            }
        }
    }
}

private fun LibrarySection.nativeLabel() = when (this) {
    LibrarySection.MOVIES -> "Movies"
    LibrarySection.SHOWS -> "Shows"
    LibrarySection.MUSIC -> "Music"
    LibrarySection.BOOKS -> "Books"
}

@Composable
private fun NativeShowDetail(vm: NomadViewModel, show: ShowItem, onBack: () -> Unit) {
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onBack) { Icon(Icons.Outlined.ArrowBack, "Back") }
                Column(Modifier.weight(1f)) {
                    Text(show.name, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                    Text("${show.seasons.size} seasons", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
        show.seasons.forEach { season ->
            item { Text(season.name, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 8.dp)) }
            items(season.episodes, key = { it.path }) { ep ->
                Card(
                    modifier = Modifier.fillMaxWidth().clickable { vm.playPath(ep.path, ep.name, false, 0.0) },
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
                ) {
                    Row(Modifier.fillMaxWidth().padding(13.dp), verticalAlignment = Alignment.CenterVertically) {
                        Box(
                            Modifier.size(44.dp).background(MaterialTheme.colorScheme.primaryContainer, RoundedCornerShape(22.dp)),
                            contentAlignment = Alignment.Center,
                        ) {
                            Icon(Icons.Filled.PlayArrow, null, tint = MaterialTheme.colorScheme.onPrimaryContainer)
                        }
                        Column(Modifier.padding(start = 13.dp).weight(1f)) {
                            Text(stripMediaExtension(ep.name), fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            Text("Episode ${ep.episodeNumber}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun NativeDownloads(vm: NomadViewModel) {
    LaunchedEffect(vm.profile?.id) { vm.refreshDownloads() }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Downloads", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text("${vm.downloads.size} queue items", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            IconButton(onClick = { vm.refreshDownloads() }) { Icon(Icons.Outlined.Refresh, "Refresh") }
            if (vm.downloads.isNotEmpty()) IconButton(onClick = { vm.clearDownloadQueue() }) { Icon(Icons.Outlined.ClearAll, "Clear queue") }
        }
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(vm.downloads, key = { it.id }) { job ->
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                    Column(Modifier.fillMaxWidth().padding(14.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(job.filename, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                Text("${job.status.replaceFirstChar { it.uppercase() }} · ${job.progress.roundToInt()}%", style = MaterialTheme.typography.bodySmall)
                            }
                            if (job.status.lowercase() !in setOf("completed", "failed", "error", "cancelled")) {
                                IconButton(onClick = { vm.cancelDownload(job.id) }) { Icon(Icons.Outlined.Cancel, "Cancel") }
                            }
                        }
                        LinearProgressIndicator(
                            progress = { (job.progress / 100.0).toFloat().coerceIn(0f, 1f) },
                            modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
                        )
                        job.error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp)) }
                    }
                }
            }
        }
    }
}

@Composable
private fun NativeSettings(vm: NomadViewModel, settings: NomadUiSettings, onChange: (NomadUiSettings) -> Unit) {
    LaunchedEffect(Unit) { vm.refreshStats() }
    val stats = vm.stats

    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(horizontal = 18.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item { Text("Settings", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold) }
        item { Text("Playback", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 8.dp)) }
        item {
            SettingsSwitchRow(
                title = "Fullscreen video",
                subtitle = "Hide Android system bars when a movie or episode starts",
                checked = settings.fullscreenVideo,
                onChecked = { onChange(settings.copy(fullscreenVideo = it)) },
            )
        }
        item {
            SettingsSwitchRow(
                title = "Keep screen awake",
                subtitle = "Prevent the display sleeping during video playback",
                checked = settings.keepScreenAwake,
                onChecked = { onChange(settings.copy(keepScreenAwake = it)) },
            )
        }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                Column(Modifier.fillMaxWidth().padding(15.dp)) {
                    Text("Video sizing", fontWeight = FontWeight.SemiBold)
                    Text("Default framing for the native player", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Row(Modifier.fillMaxWidth().padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf("fit" to "Fit", "fill" to "Fill", "zoom" to "Zoom").forEach { (value, label) ->
                            FilterChip(
                                selected = settings.videoResize == value,
                                onClick = { onChange(settings.copy(videoResize = value)) },
                                label = { Text(label) },
                            )
                        }
                    }
                }
            }
        }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                Column(Modifier.fillMaxWidth().padding(15.dp)) {
                    Text("Native player controls", fontWeight = FontWeight.SemiBold)
                    Text("Rewind 10 seconds · Forward 30 seconds · tap video to hide controls", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
                }
            }
        }

        item { Text("Connection", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 12.dp)) }
        item { SettingsInfo("Server", vm.server) }
        item { SettingsInfo("Profile", vm.profile?.name ?: "—") }
        if (stats != null) {
            item { SettingsInfo("CPU", "${stats.cpuPercent.roundToInt()}%") }
            item { SettingsInfo("Temperature", if (stats.temperature > 0) "${stats.temperature.roundToInt()}°C" else "—") }
            item { SettingsInfo("Storage free", formatBytes(stats.diskFree)) }
        }
        item {
            OutlinedButton(onClick = { vm.refreshStats() }, modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Outlined.Refresh, null)
                Text("Refresh server status", modifier = Modifier.padding(start = 8.dp))
            }
        }
        item {
            OutlinedButton(onClick = { vm.logout() }, modifier = Modifier.fillMaxWidth().padding(top = 6.dp)) {
                Icon(Icons.Outlined.Logout, null)
                Text("Sign out", modifier = Modifier.padding(start = 8.dp))
            }
        }
    }
}

@Composable
private fun SettingsSwitchRow(title: String, subtitle: String, checked: Boolean, onChecked: (Boolean) -> Unit) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Row(
            Modifier.fillMaxWidth().clickable { onChecked(!checked) }.padding(15.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(title, fontWeight = FontWeight.SemiBold)
                Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 3.dp))
            }
            Switch(checked = checked, onCheckedChange = onChecked)
        }
    }
}

@Composable
private fun SettingsInfo(label: String, value: String) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Row(Modifier.fillMaxWidth().padding(15.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
            Text(value, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
    }
}
