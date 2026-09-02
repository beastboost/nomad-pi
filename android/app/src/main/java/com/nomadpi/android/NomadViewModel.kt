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
import java.net.HttpURLConnection
import java.net.URL

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

    var entry by mutableStateOf(EntryScreen.LOADING); private set
    var server by mutableStateOf("http://nomadpi.local"); private set
    var session by mutableStateOf<NomadSession?>(null); private set
    var profiles by mutableStateOf<List<NomadProfile>>(emptyList()); private set
    var profile by mutableStateOf<NomadProfile?>(null); private set
    var discovered by mutableStateOf<List<DiscoveredNomad>>(emptyList()); private set
    var discovering by mutableStateOf(false); private set
    var tab by mutableStateOf(MainTab.HOME); private set
    var librarySection by mutableStateOf(LibrarySection.MOVIES); private set
    var library by mutableStateOf<List<LibraryItem>>(emptyList()); private set
    var shows by mutableStateOf<List<ShowItem>>(emptyList()); private set
    var photos by mutableStateOf<GalleryResult?>(null); private set
    var downloads by mutableStateOf<List<DownloadJob>>(emptyList()); private set
    var stats by mutableStateOf<ServerStats?>(null); private set
    var playback by mutableStateOf<ActivePlayback?>(null); private set
    var busy by mutableStateOf(false); private set
    var message by mutableStateOf<String?>(null); private set

    init { viewModelScope.launch { restore() } }

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
        // A restored session has a token but no media ticket, and artwork and
        // playback URLs are unusable without one.
        if (valid) runCatching { withContext(Dispatchers.IO) { api.ensureMediaTicket() } }
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

    fun login(username: String, password: String) = request(showBusy = true) {
        val loggedIn = withContext(Dispatchers.IO) { api.login(server, username.trim(), password) }
        session = loggedIn
        store.save(loggedIn)
        entry = EntryScreen.APP
        refreshProfiles()
        refreshHome()
    }

    fun logout() {
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                runCatching {
                    val connection = URL(api.absoluteUrl("/api/auth/logout")).openConnection() as HttpURLConnection
                    connection.requestMethod = "POST"
                    connection.connectTimeout = 2_500
                    connection.readTimeout = 2_500
                    api.token?.let { connection.setRequestProperty("Authorization", "Bearer $it") }
                    runCatching { connection.responseCode }
                    connection.disconnect()
                }
            }
            store.clear()
            session = null
            profile = null
            profiles = emptyList()
            library = emptyList()
            shows = emptyList()
            photos = null
            downloads = emptyList()
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
            onError = { text -> viewModelScope.launch { discovering = false; message = text } },
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

    fun refreshProfiles() = request {
        val result = withContext(Dispatchers.IO) { api.profiles() }
        profiles = result.first
        profile = result.second
        result.second?.id?.let {
            api.profileId = it
            store.updateProfile(it)
        }
    }

    fun switchProfile(target: NomadProfile, pin: String? = null, onDone: (Boolean) -> Unit = {}) {
        if (busy) return
        request(showBusy = true, onFailure = { onDone(false) }) {
            val selected = withContext(Dispatchers.IO) { api.switchProfile(target.id, pin) }
            profile = selected
            store.updateProfile(selected.id)
            library = emptyList()
            shows = emptyList()
            photos = null
            downloads = emptyList()
            refreshHome()
            onDone(true)
        }
    }

    fun refreshHome() = request {
        val value = withContext(Dispatchers.IO) { runCatching { api.serverStats() }.getOrNull() }
        if (value != null) stats = value
    }

    fun refreshStats() = request {
        stats = withContext(Dispatchers.IO) { api.serverStats() }
    }

    fun refreshLibrary() = request(showBusy = true) {
        if (librarySection == LibrarySection.SHOWS) {
            shows = withContext(Dispatchers.IO) { api.shows() }
            library = emptyList()
        } else {
            val category = when (librarySection) {
                LibrarySection.MOVIES -> "movies"
                LibrarySection.MUSIC -> "music"
                LibrarySection.BOOKS -> "books"
                LibrarySection.SHOWS -> "shows"
            }
            library = withContext(Dispatchers.IO) { api.library(category) }
            shows = emptyList()
        }
    }

    fun refreshPhotos() = request(showBusy = true) {
        photos = withContext(Dispatchers.IO) { api.gallery() }
    }

    fun refreshDownloads() = request {
        downloads = withContext(Dispatchers.IO) { api.downloads() }
    }

    fun cancelDownload(id: String) = request {
        downloads = withContext(Dispatchers.IO) {
            api.cancelDownload(id)
            api.downloads()
        }
    }

    fun clearDownloadQueue() = request {
        downloads = withContext(Dispatchers.IO) {
            val current = api.downloads()
            val terminal = setOf("completed", "failed", "error", "cancelled")
            current.filterNot { it.status.lowercase() in terminal }.forEach { runCatching { api.cancelDownload(it.id) } }
            api.clearDownloads()
            api.downloads()
        }
    }

    fun play(item: LibraryItem) {
        playPath(item.path, item.name, audioOnly = librarySection == LibrarySection.MUSIC, resume = item.progress)
    }

    fun playEpisode(item: ShowEpisode) {
        playPath(item.path, item.name, audioOnly = false, resume = 0.0)
    }

    fun playPath(path: String, title: String, audioOnly: Boolean, resume: Double = 0.0) {
        if (busy) return
        request(showBusy = true) {
            playback = withContext(Dispatchers.IO) {
                if (audioOnly) {
                    ActivePlayback(title, path, api.musicStreamUrl(path), null, "direct_audio", true)
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
        }
    }

    fun closePlayback(positionMs: Long = 0, durationMs: Long = 0) {
        val active = playback
        playback = null
        val id = active?.sessionId ?: return
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { api.playbackHeartbeat(id, positionMs / 1000.0, durationMs / 1000.0, "stopped") }
            runCatching { api.stopPlayback(id) }
        }
    }

    fun heartbeat(positionMs: Long, durationMs: Long, playing: Boolean) {
        val id = playback?.sessionId ?: return
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { api.playbackHeartbeat(id, positionMs / 1000.0, durationMs / 1000.0, if (playing) "playing" else "paused") }
        }
    }

    fun clearMessage() { message = null }

    private fun request(
        showBusy: Boolean = false,
        onFailure: (() -> Unit)? = null,
        block: suspend () -> Unit,
    ) {
        viewModelScope.launch {
            if (showBusy) busy = true
            if (showBusy) message = null
            try {
                block()
            } catch (t: Throwable) {
                message = t.message ?: "Nomad request failed"
                onFailure?.invoke()
            } finally {
                if (showBusy) busy = false
            }
        }
    }

    override fun onCleared() {
        discovery.stop()
        super.onCleared()
    }
}
