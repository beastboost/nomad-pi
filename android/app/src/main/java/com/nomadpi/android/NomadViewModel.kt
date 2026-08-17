package com.nomadpi.android

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class EntryScreen { LOADING, CONNECT, LOGIN, APP }
enum class MainTab { HOME, LIBRARY, PHOTOS, DOWNLOADS, SERVER }
enum class LibrarySection { MOVIES, SHOWS, MUSIC, BOOKS }

data class ActivePlayback(
    val title: String,
    val path: String,
    val url: String,
    val sessionId: String? = null,
    val mode: String = "direct",
    val audioOnly: Boolean = false,
)

data class DiscoveredNomad(val name: String, val url: String)

class NomadViewModel(application: Application) : AndroidViewModel(application) {
    val api = NomadApi()
    private val store = NomadStore(application)
    private val discovery = NomadDiscovery(application)
    private val capabilities = AndroidCapabilities.detect()

    var entry by mutableStateOf(EntryScreen.LOADING)
        private set
    var server by mutableStateOf("http://nomadpi.local")
        private set
    var session by mutableStateOf<NomadSession?>(null)
        private set
    var profiles by mutableStateOf<List<NomadProfile>>(emptyList())
        private set
    var profile by mutableStateOf<NomadProfile?>(null)
        private set
    var discovered by mutableStateOf<List<DiscoveredNomad>>(emptyList())
        private set
    var discovering by mutableStateOf(false)
        private set
    var tab by mutableStateOf(MainTab.HOME)
        private set
    var librarySection by mutableStateOf(LibrarySection.MOVIES)
        private set
    var library by mutableStateOf<List<LibraryItem>>(emptyList())
        private set
    var shows by mutableStateOf<List<ShowItem>>(emptyList())
        private set
    var photos by mutableStateOf<GalleryResult?>(null)
        private set
    var downloads by mutableStateOf<List<DownloadJob>>(emptyList())
        private set
    var stats by mutableStateOf<ServerStats?>(null)
        private set
    var playback by mutableStateOf<ActivePlayback?>(null)
        private set
    var busy by mutableStateOf(false)
        private set
    var message by mutableStateOf<String?>(null)
        private set

    init {
        viewModelScope.launch { restore() }
    }

    private suspend fun restore() {
        val saved = store.load()
        if (saved == null) {
            entry = EntryScreen.CONNECT
            startDiscovery()
            return
        }
        server = saved.server
        api.configure(saved.server, saved.token, saved.profileId)
        val valid = runCatching { withContext(Dispatchers.IO) { api.check() } }.getOrDefault(false)
        if (!valid) {
            store.clear()
            api.configure(saved.server, null)
            entry = EntryScreen.LOGIN
            return
        }
        session = NomadSession(saved.server, saved.token, saved.username, saved.isAdmin)
        entry = EntryScreen.APP
        refreshProfiles()
        refreshHome()
    }

    fun selectServer(value: String) {
        server = NomadApi.normalizeServer(value)
        api.configure(server, null)
        entry = EntryScreen.LOGIN
        stopDiscovery()
    }

    fun backToConnect() {
        api.configure(server, null)
        entry = EntryScreen.CONNECT
        startDiscovery()
    }

    fun login(username: String, password: String) {
        if (busy) return
        busy = true
        message = null
        viewModelScope.launch {
            try {
                val loggedIn = withContext(Dispatchers.IO) { api.login(server, username.trim(), password) }
                session = loggedIn
                store.save(loggedIn)
                entry = EntryScreen.APP
                refreshProfiles()
                refreshHome()
            } catch (t: Throwable) {
                message = t.message ?: "Login failed"
            } finally {
                busy = false
            }
        }
    }

    fun logout() {
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    // Logout is best-effort. Clearing the local token must never be blocked by LAN loss.
                    val connection = java.net.URL(api.absoluteUrl("/api/auth/logout")).openConnection() as java.net.HttpURLConnection
                    connection.requestMethod = "POST"
                    api.token?.let { connection.setRequestProperty("Authorization", "Bearer $it") }
                    connection.connectTimeout = 2_500
                    connection.readTimeout = 2_500
                    runCatching { connection.responseCode }
                    connection.disconnect()
                }
            }
            store.clear()
            session = null
            profile = null
            profiles = emptyList()
            api.configure(server, null)
            entry = EntryScreen.LOGIN
        }
    }

    fun startDiscovery() {
        if (discovering) return
        discovered = emptyList()
        discovering = true
        discovery.start(
            onServer = { name, url ->
                viewModelScope.launch {
                    val item = DiscoveredNomad(name, url)
                    if (discovered.none { it.url == url }) discovered = discovered + item
                }
            },
            onError = { error ->
                viewModelScope.launch {
                    discovering = false
                    message = error
                }
            },
        )
        viewModelScope.launch {
            delay(8_000)
            discovering = false
            discovery.stop()
        }
    }

    fun stopDiscovery() {
        discovery.stop()
        discovering = false
    }

    fun chooseTab(value: MainTab) {
        tab = value
        when (value) {
            MainTab.HOME -> refreshHome()
            MainTab.LIBRARY -> refreshLibrary()
            MainTab.PHOTOS -> refreshPhotos()
            MainTab.DOWNLOADS -> refreshDownloads()
            MainTab.SERVER -> refreshStats()
        }
    }

    fun chooseLibrary(value: LibrarySection) {
        librarySection = value
        refreshLibrary()
    }

    fun refreshProfiles() = launchLoad(silent = true) {
        val (list, current) = api.profiles()
        withContext(Dispatchers.Main) {
            profiles = list
            profile = current
            current?.id?.let {
                api.profileId = it
                viewModelScope.launch { store.updateProfile(it) }
            }
        }
    }

    fun switchProfile(target: NomadProfile, pin: String? = null, onDone: (Boolean) -> Unit = {}) {
        if (busy) return
        busy = true
        message = null
        viewModelScope.launch {
            try {
                val selected = withContext(Dispatchers.IO) { api.switchProfile(target.id, pin) }
                profile = selected
                store.updateProfile(selected.id)
                library = emptyList()
                shows = emptyList()
                photos = null
                downloads = emptyList()
                refreshHome()
                onDone(true)
            } catch (t: Throwable) {
                message = t.message ?: "Could not switch profile"
                onDone(false)
            } finally {
                busy = false
            }
        }
    }

    fun refreshHome() = launchLoad(silent = true) {
        val s = runCatching { api.serverStats() }.getOrNull()
        withContext(Dispatchers.Main) { if (s != null) stats = s }
    }

    fun refreshStats() = launchLoad(silent = true) {
        val s = api.serverStats()
        withContext(Dispatchers.Main) { stats = s }
    }

    fun refreshLibrary() = launchLoad {
        when (librarySection) {
            LibrarySection.SHOWS -> {
                val result = api.shows()
                withContext(Dispatchers.Main) {
                    shows = result
                    library = emptyList()
                }
            }
            else -> {
                val category = when (librarySection) {
                    LibrarySection.MOVIES -> "movies"
                    LibrarySection.MUSIC -> "music"
                    LibrarySection.BOOKS -> "books"
                    LibrarySection.SHOWS -> "shows"
                }
                val result = api.library(category)
                withContext(Dispatchers.Main) {
                    library = result
                    shows = emptyList()
                }
            }
        }
    }

    fun refreshPhotos() = launchLoad {
        val result = api.gallery()
        withContext(Dispatchers.Main) { photos = result }
    }

    fun refreshDownloads() = launchLoad(silent = true) {
        val result = api.downloads()
        withContext(Dispatchers.Main) { downloads = result }
    }

    fun cancelDownload(id: String) = launchLoad(silent = true) {
        api.cancelDownload(id)
        val result = api.downloads()
        withContext(Dispatchers.Main) { downloads = result }
    }

    fun clearDownloadQueue() = launchLoad(silent = true) {
        val active = api.downloads().filterNot { it.status.lowercase() in setOf("completed", "failed", "error", "cancelled") }
        for (job in active) runCatching { api.cancelDownload(job.id) }
        api.clearDownloads()
        withContext(Dispatchers.Main) { downloads = api.downloads() }
    }

    fun play(item: LibraryItem) {
        playPath(item.path, item.name, audioOnly = librarySection == LibrarySection.MUSIC, resume = item.progress)
    }

    fun playEpisode(item: ShowEpisode) {
        playPath(item.path, item.name, audioOnly = false, resume = 0.0)
    }

    fun playPath(path: String, title: String, audioOnly: Boolean, resume: Double = 0.0) {
        if (busy) return
        busy = true
        message = null
        viewModelScope.launch {
            try {
                val active = withContext(Dispatchers.IO) {
                    if (audioOnly) {
                        ActivePlayback(
                            title = title,
                            path = path,
                            url = api.musicStreamUrl(path),
                            sessionId = null,
                            mode = "direct_audio",
                            audioOnly = true,
                        )
                    } else {
                        val started = api.startPlayback(path, capabilities, resume)
                        ActivePlayback(
                            title = title,
                            path = path,
                            url = started.playbackUrl,
                            sessionId = started.sessionId.takeIf { it.isNotBlank() },
                            mode = started.mode,
                            audioOnly = false,
                        )
                    }
                }
                playback = active
            } catch (t: Throwable) {
                message = t.message ?: "Playback could not start"
            } finally {
                busy = false
            }
        }
    }

    fun closePlayback(positionMs: Long = 0, durationMs: Long = 0) {
        val active = playback
        playback = null
        val sessionId = active?.sessionId ?: return
        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                api.playbackHeartbeat(
                    sessionId,
                    positionMs.coerceAtLeast(0) / 1000.0,
                    durationMs.coerceAtLeast(0) / 1000.0,
                    "stopped",
                )
            }
            runCatching { api.stopPlayback(sessionId) }
        }
    }

    fun heartbeat(positionMs: Long, durationMs: Long, playing: Boolean) {
        val sessionId = playback?.sessionId ?: return
        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                api.playbackHeartbeat(
                    sessionId,
                    positionMs.coerceAtLeast(0) / 1000.0,
                    durationMs.coerceAtLeast(0) / 1000.0,
                    if (playing) "playing" else "paused",
                )
            }
        }
    }

    fun clearMessage() { message = null }

    private fun launchLoad(silent: Boolean = false, block: suspend () -> Unit) {
        viewModelScope.launch {
            if (!silent) busy = true
            if (!silent) message = null
            try {
                withContext(Dispatchers.IO) { block() }
            } catch (t: Throwable) {
                message = t.message ?: "Nomad request failed"
            } finally {
                if (!silent) busy = false
            }
        }
    }

    override fun onCleared() {
        discovery.stop()
        super.onCleared()
    }
}
