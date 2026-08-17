package com.nomadpi.android

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.SaveAlt
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun NativeUniversalSearch(api: NomadApi) {
    val extras = remember(api) { NomadExtrasApi(api) }
    val scope = rememberCoroutineScope()
    val capabilities = remember { AndroidCapabilities.detect() }
    var query by remember { mutableStateOf("") }
    var titles by remember { mutableStateOf<List<UniversalTitle>>(emptyList()) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var status by remember { mutableStateOf<String?>(null) }
    var playing by remember { mutableStateOf<ResolvedRemote?>(null) }
    var cleanupToken by remember { mutableStateOf<String?>(null) }
    var season by remember { mutableIntStateOf(1) }
    var episode by remember { mutableIntStateOf(1) }

    fun search() {
        val q = query.trim()
        if (q.isBlank() || loading) return
        loading = true
        error = null
        status = null
        scope.launch {
            try {
                titles = withContext(Dispatchers.IO) { extras.universalSearch(q, season, episode) }
                if (titles.isEmpty()) status = "No matching titles"
            } catch (t: Throwable) {
                error = t.message ?: "Search failed"
            } finally {
                loading = false
            }
        }
    }

    playing?.let { remote ->
        BackHandler {
            cleanupToken?.let { token -> scope.launch(Dispatchers.IO) { runCatching { extras.deleteRemotePlay(token) } } }
            cleanupToken = null
            playing = null
        }
        NativeMediaPlayer(
            source = NativeMediaSource(remote.title, remote.url, "cached remote", false),
            onClose = { _, _ ->
                cleanupToken?.let { token -> scope.launch(Dispatchers.IO) { runCatching { extras.deleteRemotePlay(token) } } }
                cleanupToken = null
                playing = null
            },
        )
        return
    }

    Column(Modifier.fillMaxSize()) {
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            modifier = Modifier.fillMaxWidth().padding(12.dp),
            label = { Text("Find a film or show") },
            leadingIcon = { Icon(Icons.Outlined.Search, null) },
            trailingIcon = {
                if (loading) CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp)
                else TextButton(onClick = ::search) { Text("Search") }
            },
            singleLine = true,
        )
        if (status != null || error != null) {
            Text(
                error ?: status.orEmpty(),
                color = if (error != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
            )
        }
        if (titles.isEmpty() && !loading) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(Icons.Outlined.Search, null, Modifier.size(44.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text("Search Nomad's universal catalogue", color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 10.dp))
                    Text("Cached, device-compatible releases are preferred.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        } else {
            LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                items(titles, key = { "${it.imdbId}:${it.type}" }) { title ->
                    SearchTitleCard(
                        api = api,
                        title = title,
                        season = season,
                        episode = episode,
                        busy = loading,
                        onSeason = { season = it.coerceAtLeast(1) },
                        onEpisode = { episode = it.coerceAtLeast(1) },
                        onLoadReleases = { showAll ->
                            if (loading) return@SearchTitleCard
                            loading = true
                            scope.launch {
                                try {
                                    val updated = withContext(Dispatchers.IO) { extras.universalReleases(title, season, episode, showAll) }
                                    titles = titles.map { if (it.imdbId == title.imdbId && it.type == title.type) updated else it }
                                } catch (t: Throwable) { error = t.message }
                                finally { loading = false }
                            }
                        },
                        onPlay = { release ->
                            if (loading) return@SearchTitleCard
                            loading = true
                            status = "Resolving cached release…"
                            scope.launch {
                                try {
                                    val remote = withContext(Dispatchers.IO) { extras.resolveForPlay(title, release, season, episode) }
                                    cleanupToken = remote.proxyToken
                                    playing = remote
                                    status = null
                                } catch (t: Throwable) { error = t.message; status = null }
                                finally { loading = false }
                            }
                        },
                        onKeep = { release ->
                            if (loading) return@SearchTitleCard
                            loading = true
                            status = "Starting Stream + Keep…"
                            scope.launch {
                                try {
                                    val remote = withContext(Dispatchers.IO) { extras.streamKeep(title, release, capabilities, season, episode) }
                                    cleanupToken = null // job must continue when playback closes
                                    playing = remote
                                    status = "Saving a local copy in the background"
                                } catch (t: Throwable) { error = t.message; status = null }
                                finally { loading = false }
                            }
                        },
                        onDownload = { release ->
                            if (loading) return@SearchTitleCard
                            loading = true
                            status = "Adding to Nomad's download queue…"
                            scope.launch {
                                try {
                                    val id = withContext(Dispatchers.IO) { extras.downloadRelease(title, release, season, episode) }
                                    status = if (id.isBlank()) "Download queued" else "Download queued · $id"
                                } catch (t: Throwable) { error = t.message; status = null }
                                finally { loading = false }
                            }
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun SearchTitleCard(
    api: NomadApi,
    title: UniversalTitle,
    season: Int,
    episode: Int,
    busy: Boolean,
    onSeason: (Int) -> Unit,
    onEpisode: (Int) -> Unit,
    onLoadReleases: (Boolean) -> Unit,
    onPlay: (UniversalRelease) -> Unit,
    onKeep: (UniversalRelease) -> Unit,
    onDownload: (UniversalRelease) -> Unit,
) {
    var expanded by remember(title.imdbId, title.type) { mutableStateOf(true) }
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Row(Modifier.fillMaxWidth().clickable { expanded = !expanded }.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            RemoteImage(title.poster, Modifier.size(76.dp).background(MaterialTheme.colorScheme.surface, RoundedCornerShape(8.dp)), maxDecodePx = 360)
            Column(Modifier.padding(start = 12.dp).weight(1f)) {
                Text(title.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text("${if (title.type == "series") "Series" else "Movie"}${title.year.takeIf { it.isNotBlank() }?.let { " · $it" } ?: ""}", color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text("${title.releases.count { it.cached }} cached · ${title.releases.count { it.compatible }} compatible", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
            }
            Text(if (expanded) "Hide" else "Show", color = MaterialTheme.colorScheme.primary)
        }
        if (expanded) {
            Column(Modifier.padding(horizontal = 14.dp, vertical = 4.dp)) {
                if (title.type == "series") {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Stepper("S", season, onSeason, Modifier.weight(1f))
                        Stepper("E", episode, onEpisode, Modifier.weight(1f))
                        OutlinedButton(onClick = { onLoadReleases(false) }, enabled = !busy) { Text("Load") }
                    }
                }
                if (title.releases.isEmpty()) {
                    OutlinedButton(onClick = { onLoadReleases(false) }, enabled = !busy, modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
                        Text("Load Pi-friendly releases")
                    }
                } else {
                    title.releases.forEach { release ->
                        ReleaseRow(release, busy, onPlay, onKeep, onDownload)
                    }
                    TextButton(onClick = { onLoadReleases(true) }, enabled = !busy, modifier = Modifier.align(Alignment.End)) {
                        Text("Show all releases")
                    }
                }
            }
        }
    }
}

@Composable
private fun Stepper(label: String, value: Int, onValue: (Int) -> Unit, modifier: Modifier = Modifier) {
    Row(modifier, verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
        Text("$label$value", fontWeight = FontWeight.Bold)
        Row {
            TextButton(onClick = { onValue((value - 1).coerceAtLeast(1)) }, contentPadding = PaddingValues(5.dp)) { Text("−") }
            TextButton(onClick = { onValue(value + 1) }, contentPadding = PaddingValues(5.dp)) { Text("+") }
        }
    }
}

@Composable
private fun ReleaseRow(
    release: UniversalRelease,
    busy: Boolean,
    onPlay: (UniversalRelease) -> Unit,
    onKeep: (UniversalRelease) -> Unit,
    onDownload: (UniversalRelease) -> Unit,
) {
    Column(Modifier.fillMaxWidth().padding(vertical = 9.dp)) {
        Text(release.name, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
        val badges = buildList {
            if (release.cached) add("CACHED")
            if (release.directCandidate) add("DIRECT") else if (release.compatible) add("PI SAFE")
            release.quality.takeIf { it.isNotBlank() }?.let(::add)
            release.codec.takeIf { it.isNotBlank() }?.let(::add)
            release.size.takeIf { it.isNotBlank() }?.let(::add)
        }
        Text(badges.joinToString(" · "), style = MaterialTheme.typography.labelSmall, color = if (release.compatible) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
        if (!release.compatible && release.reasons.isNotEmpty()) {
            Text(release.reasons.take(2).joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Row(Modifier.fillMaxWidth().padding(top = 7.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            if (release.cached && release.directCandidate) {
                Button(onClick = { onPlay(release) }, enabled = !busy, contentPadding = PaddingValues(horizontal = 10.dp), modifier = Modifier.weight(1f)) {
                    Icon(Icons.Filled.PlayArrow, null, Modifier.size(18.dp)); Spacer(Modifier.size(3.dp)); Text("Play")
                }
            }
            if (release.compatible) {
                OutlinedButton(onClick = { onKeep(release) }, enabled = !busy, contentPadding = PaddingValues(horizontal = 8.dp), modifier = Modifier.weight(1f)) {
                    Icon(Icons.Outlined.SaveAlt, null, Modifier.size(17.dp)); Spacer(Modifier.size(3.dp)); Text("Keep")
                }
            }
            OutlinedButton(onClick = { onDownload(release) }, enabled = !busy, contentPadding = PaddingValues(horizontal = 8.dp), modifier = Modifier.weight(1f)) {
                Icon(Icons.Outlined.Download, null, Modifier.size(17.dp)); Spacer(Modifier.size(3.dp)); Text("Download")
            }
        }
    }
}
