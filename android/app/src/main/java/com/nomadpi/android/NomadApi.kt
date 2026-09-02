package com.nomadpi.android

import android.media.MediaCodecList
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

class NomadApiException(message: String, val status: Int = 0) : Exception(message)

data class NomadSession(
    val server: String,
    val token: String,
    val username: String,
    val isAdmin: Boolean,
)

data class NomadProfile(
    val id: Int,
    val name: String,
    val avatar: String?,
    val pinRequired: Boolean,
    val isDefault: Boolean,
)

data class LibraryItem(
    val name: String,
    val path: String,
    val folder: String = "",
    val type: String = "",
    val poster: String? = null,
    val year: String? = null,
    val size: Long = 0,
    val progress: Double = 0.0,
    val duration: Double = 0.0,
)

data class ShowEpisode(
    val name: String,
    val path: String,
    val poster: String?,
    val episodeNumber: Int,
)

data class ShowSeason(
    val name: String,
    val poster: String?,
    val episodes: List<ShowEpisode>,
)

data class ShowItem(
    val name: String,
    val poster: String?,
    val seasons: List<ShowSeason>,
)

data class GalleryItem(
    val id: String,
    val name: String,
    val kind: String,
    val takenAt: String?,
    val mtime: Double,
)

data class GalleryResult(
    val profile: NomadProfile?,
    val items: List<GalleryItem>,
)

data class DownloadJob(
    val id: String,
    val filename: String,
    val status: String,
    val progress: Double,
    val speed: Long,
    val downloaded: Long,
    val total: Long,
    val error: String?,
)

data class ServerStats(
    val cpuPercent: Double,
    val memoryPercent: Double,
    val memoryAvailable: Long,
    val diskFree: Long,
    val diskPercent: Double,
    val temperature: Double,
    val uptime: Double,
)

data class PlaybackStart(
    val sessionId: String,
    val mode: String,
    val type: String,
    val playbackUrl: String,
    val reasons: List<String>,
)

data class AndroidCapabilities(
    val containers: List<String>,
    val videoCodecs: List<String>,
    val audioCodecs: List<String>,
    val subtitleFormats: List<String>,
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("containers", JSONArray(containers))
        put("video_codecs", JSONArray(videoCodecs))
        put("audio_codecs", JSONArray(audioCodecs))
        put("subtitle_formats", JSONArray(subtitleFormats))
    }

    companion object {
        fun detect(): AndroidCapabilities {
            val decoders = try {
                MediaCodecList(MediaCodecList.ALL_CODECS).codecInfos
                    .filter { !it.isEncoder }
                    .flatMap { it.supportedTypes.asList() }
                    .map { it.lowercase() }
                    .toSet()
            } catch (_: Throwable) {
                emptySet()
            }

            fun has(type: String) = decoders.contains(type.lowercase())
            val video = mutableListOf<String>()
            if (has("video/avc")) video += "h264"
            if (has("video/hevc")) video += "hevc"
            if (has("video/x-vnd.on2.vp9")) video += "vp9"
            if (has("video/av01")) video += "av1"

            val audio = mutableListOf<String>()
            if (has("audio/mp4a-latm")) audio += "aac"
            if (has("audio/ac3")) audio += "ac3"
            if (has("audio/eac3") || has("audio/eac3-joc")) audio += "eac3"
            if (has("audio/mpeg")) audio += "mp3"
            if (has("audio/flac")) audio += "flac"
            if (has("audio/opus")) audio += "opus"
            if (has("audio/vorbis")) audio += "vorbis"
            if (has("audio/vnd.dts")) audio += "dts"
            if (has("audio/true-hd")) audio += "truehd"

            // Media3 ships extractors for these common progressive containers.
            // Codec support remains device-driven above, so this does not claim
            // that every stream inside a container is playable.
            val containers = listOf("mp4", "mov", "mkv", "webm", "ts", "m2ts")
            return AndroidCapabilities(
                containers = containers,
                videoCodecs = video.distinct(),
                audioCodecs = audio.distinct(),
                subtitleFormats = listOf("webvtt", "vtt", "srt", "ass", "ssa"),
            )
        }
    }
}

class NomadApi(server: String = "http://nomadpi.local") {
    @Volatile var baseUrl: String = normalizeServer(server)
    @Volatile var token: String? = null
    @Volatile var profileId: Int? = null

    // Media URLs are handed to ExoPlayer and the image loader, neither of which
    // routes through requestJson(), so they cannot carry the Authorization
    // header. They used to carry the session token in the query string; the
    // server no longer accepts that, so they carry a short-lived media ticket
    // fetched from /api/auth/media-ticket instead.
    @Volatile private var cachedMediaTicket: String? = null
    @Volatile private var mediaTicketExpiresAt: Long = 0L

    fun configure(server: String, authToken: String?, activeProfile: Int? = null) {
        baseUrl = normalizeServer(server)
        token = authToken
        profileId = activeProfile
        clearMediaTicket()
    }

    private fun clearMediaTicket() {
        cachedMediaTicket = null
        mediaTicketExpiresAt = 0L
    }

    /**
     * Fetch a media ticket if the cached one is missing or close to expiry.
     *
     * This performs network I/O, so it must be called from a background
     * thread. The URL builders below deliberately never call it: they run
     * inside composables, where a blocking request would raise
     * NetworkOnMainThreadException.
     */
    fun ensureMediaTicket(force: Boolean = false): String? {
        if (token.isNullOrBlank()) return null
        val now = System.currentTimeMillis()
        val current = cachedMediaTicket
        if (!force && current != null && now < mediaTicketExpiresAt - 60_000L) return current
        return try {
            val json = requestJson("GET", "/api/auth/media-ticket")
            val issued = json.optString("ticket").takeIf { it.isNotBlank() }
            if (issued != null) {
                synchronized(this) {
                    cachedMediaTicket = issued
                    mediaTicketExpiresAt = now + json.optLong("expires_in", 21600L) * 1000L
                }
            }
            issued
        } catch (e: Exception) {
            null
        }
    }

    /** The cached ticket only. Safe to call from the UI thread. */
    private fun ticketQuery(prefix: String = "&"): String {
        val t = cachedMediaTicket ?: return ""
        return "${prefix}ticket=${enc(t)}"
    }

    fun login(server: String, username: String, password: String): NomadSession {
        baseUrl = normalizeServer(server)
        token = null
        profileId = null
        val body = JSONObject().put("username", username).put("password", password)
        val json = requestJson("POST", "/api/auth/login", body, authenticated = false)
        val authToken = json.optString("token")
        if (authToken.isBlank()) throw NomadApiException("Nomad did not return a session token")
        val user = json.optJSONObject("user") ?: JSONObject()
        token = authToken
        clearMediaTicket()
        // login() already runs on a background thread, so priming the ticket
        // here means the first screen can render artwork without waiting.
        ensureMediaTicket(force = true)
        return NomadSession(
            server = baseUrl,
            token = authToken,
            username = user.optString("username", username),
            isAdmin = user.optBoolean("is_admin", false),
        )
    }

    fun check(): Boolean {
        val json = requestJson("GET", "/api/auth/check")
        return json.optBoolean("authenticated", false)
    }

    fun profiles(): Pair<List<NomadProfile>, NomadProfile?> {
        val json = requestJson("GET", "/api/playback/profiles")
        val list = json.optJSONArray("profiles").toObjectList(::parseProfile)
        val current = json.optJSONObject("current")?.let(::parseProfile)
        profileId = current?.id
        return list to current
    }

    fun switchProfile(id: Int, pin: String? = null): NomadProfile {
        val body = JSONObject().put("profile_id", id)
        if (!pin.isNullOrBlank()) body.put("pin", pin)
        val json = requestJson("POST", "/api/playback/profiles/switch", body)
        val profile = parseProfile(json.getJSONObject("profile"))
        profileId = profile.id
        return profile
    }

    fun library(category: String, limit: Int = 1000): List<LibraryItem> {
        val path = "/api/media/library/${encPathSegment(category)}?limit=$limit"
        val json = requestJson("GET", path)
        return json.optJSONArray("items").toObjectList(::parseLibraryItem)
    }

    fun shows(): List<ShowItem> {
        val json = requestJson("GET", "/api/media/shows/library")
        return json.optJSONArray("shows").toObjectList { show ->
            val seasons = show.optJSONArray("seasons").toObjectList { season ->
                ShowSeason(
                    name = season.optString("name", "Season"),
                    poster = season.optStringOrNull("poster"),
                    episodes = season.optJSONArray("episodes").toObjectList { ep ->
                        ShowEpisode(
                            name = ep.optString("name", "Episode"),
                            path = ep.optString("path"),
                            poster = ep.optStringOrNull("poster"),
                            episodeNumber = ep.optInt("ep_num", 999),
                        )
                    },
                )
            }
            ShowItem(
                name = show.optString("name", "Show"),
                poster = show.optStringOrNull("poster"),
                seasons = seasons,
            )
        }
    }

    fun gallery(limit: Int = 1500): GalleryResult {
        val json = requestJson("GET", "/api/playback/gallery?limit=$limit")
        val items = json.optJSONArray("items").toObjectList { item ->
            GalleryItem(
                id = item.optString("id"),
                name = item.optString("name", "Photo"),
                kind = item.optString("kind", "image"),
                takenAt = item.optStringOrNull("taken_at"),
                mtime = item.optDouble("mtime", 0.0),
            )
        }
        return GalleryResult(json.optJSONObject("profile")?.let(::parseProfile), items)
    }

    fun downloads(): List<DownloadJob> {
        val json = requestJson("GET", "/api/debrid/downloads")
        return json.optJSONArray("downloads").toObjectList { item ->
            DownloadJob(
                id = item.optString("id"),
                filename = item.optString("filename", item.optString("name", "Download")),
                status = item.optString("status", "unknown"),
                progress = item.optDouble("progress", 0.0),
                speed = item.optLong("speed", 0),
                downloaded = item.optLong("size_downloaded", 0),
                total = item.optLong("size_total", 0),
                error = item.optStringOrNull("error"),
            )
        }
    }

    fun cancelDownload(id: String) {
        requestJson("DELETE", "/api/debrid/download/${encPathSegment(id)}")
    }

    fun clearDownloads(): Int {
        return requestJson("POST", "/api/debrid/downloads/clear").optInt("cleared", 0)
    }

    fun serverStats(): ServerStats {
        val json = requestJson("GET", "/api/system/stats")
        return ServerStats(
            cpuPercent = json.optDouble("cpu_percent", json.optDouble("cpu", 0.0)),
            memoryPercent = json.optDouble("memory_percent", json.optDouble("ram_percent", 0.0)),
            memoryAvailable = json.optLong("memory_available", json.optLong("ram_available", 0)),
            diskFree = json.optLong("disk_free", 0),
            diskPercent = json.optDouble("disk_percent", 0.0),
            temperature = json.optDouble("temp", json.optDouble("temperature", 0.0)),
            uptime = json.optDouble("uptime", 0.0),
        )
    }

    fun startPlayback(path: String, capabilities: AndroidCapabilities, position: Double = 0.0): PlaybackStart {
        val body = JSONObject()
            .put("path", path)
            .put("capabilities", capabilities.toJson())
            .put("device_id", "android-${android.os.Build.MODEL.take(80)}")
            .put("quality", "auto")
            .put("position", position.coerceAtLeast(0.0))
        val json = requestJson("POST", "/api/playback/start", body)
        val session = json.optJSONObject("session") ?: JSONObject()
        val plan = json.optJSONObject("plan") ?: JSONObject()
        val playback = json.optJSONObject("playback") ?: JSONObject()
        val reasons = plan.optJSONArray("reasons").toStringList()
        return PlaybackStart(
            sessionId = session.optString("id"),
            mode = plan.optString("mode", session.optString("mode", "unknown")),
            type = playback.optString("type", "direct"),
            playbackUrl = absoluteUrl(playback.optString("url")),
            reasons = reasons,
        )
    }

    fun playbackHeartbeat(sessionId: String, position: Double, duration: Double, state: String) {
        val body = JSONObject()
            .put("position", position.coerceAtLeast(0.0))
            .put("duration", duration.coerceAtLeast(0.0))
            .put("state", state)
        requestJson("POST", "/api/playback/sessions/${encPathSegment(sessionId)}/heartbeat", body)
    }

    fun stopPlayback(sessionId: String) {
        requestJson("DELETE", "/api/playback/sessions/${encPathSegment(sessionId)}")
    }

    fun musicStreamUrl(path: String): String {
        return "$baseUrl/api/playback/music/stream?path=${enc(path)}${ticketQuery()}${profileQuery()}"
    }

    fun mediaStreamUrl(path: String): String {
        return "$baseUrl/api/media/stream?path=${enc(path)}${ticketQuery()}${profileQuery()}"
    }

    fun imageUrl(path: String?): String? {
        if (path.isNullOrBlank()) return null
        if (path.startsWith("http://") || path.startsWith("https://")) return path
        return mediaStreamUrl(path)
    }

    fun galleryItemUrl(id: String): String {
        // Build the query from its parts so a missing ticket cannot produce
        // "...item/abc&profile_id=1" with no leading question mark.
        val parts = mutableListOf<String>()
        cachedMediaTicket?.let { parts += "ticket=${enc(it)}" }
        profileId?.let { parts += "profile_id=$it" }
        val query = if (parts.isEmpty()) "" else "?" + parts.joinToString("&")
        return "$baseUrl/api/playback/gallery/item/${encPathSegment(id)}$query"
    }

    fun absoluteUrl(path: String): String {
        if (path.startsWith("http://") || path.startsWith("https://")) return path
        return baseUrl.trimEnd('/') + "/" + path.trimStart('/')
    }

    private fun profileQuery(prefix: String = "&"): String {
        val id = profileId ?: return ""
        return "$prefix${"profile_id"}=$id"
    }

    private fun parseProfile(json: JSONObject): NomadProfile = NomadProfile(
        id = json.optInt("id"),
        name = json.optString("name", "Profile"),
        avatar = json.optStringOrNull("avatar"),
        pinRequired = json.optBoolean("pin_required", false),
        isDefault = json.optBoolean("is_default", false),
    )

    private fun parseLibraryItem(json: JSONObject): LibraryItem {
        val progress = json.optJSONObject("progress")
        return LibraryItem(
            name = json.optString("title", json.optString("name", "Media")),
            path = json.optString("path"),
            folder = json.optString("folder", ""),
            type = json.optString("type", ""),
            poster = json.optStringOrNull("poster"),
            year = json.optStringOrNull("year"),
            size = json.optLong("size", 0),
            progress = progress?.optDouble("current_time", 0.0) ?: 0.0,
            duration = progress?.optDouble("duration", 0.0) ?: 0.0,
        )
    }

    private fun requestJson(
        method: String,
        path: String,
        body: JSONObject? = null,
        authenticated: Boolean = true,
    ): JSONObject {
        val url = URL(absoluteUrl(path))
        val connection = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 8_000
            readTimeout = 25_000
            useCaches = false
            setRequestProperty("Accept", "application/json")
            setRequestProperty("User-Agent", "NomadAndroid/${BuildConfig.VERSION_NAME}")
            if (authenticated) token?.takeIf { it.isNotBlank() }?.let {
                setRequestProperty("Authorization", "Bearer $it")
            }
            profileId?.let { setRequestProperty("X-Nomad-Profile-ID", it.toString()) }
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                outputStream.use { stream ->
                    stream.write(body.toString().toByteArray(StandardCharsets.UTF_8))
                }
            }
        }

        val status = try { connection.responseCode } catch (e: Exception) {
            connection.disconnect()
            throw NomadApiException("Could not reach $baseUrl: ${e.message ?: "network error"}")
        }
        val input = if (status in 200..299) connection.inputStream else connection.errorStream
        val text = input?.use { stream ->
            BufferedReader(InputStreamReader(stream, StandardCharsets.UTF_8)).readText()
        }.orEmpty()
        connection.disconnect()

        val parsed = if (text.isBlank()) JSONObject() else try {
            JSONObject(text)
        } catch (_: Exception) {
            JSONObject().put("raw", text)
        }
        if (status !in 200..299) {
            throw NomadApiException(extractError(parsed, status), status)
        }
        return parsed
    }

    private fun extractError(json: JSONObject, status: Int): String {
        val detail = json.opt("detail")
        return when (detail) {
            is String -> detail
            is JSONObject -> detail.optString("message", detail.toString())
            is JSONArray -> buildString {
                for (i in 0 until detail.length()) {
                    if (isNotEmpty()) append("; ")
                    val item = detail.opt(i)
                    append(if (item is JSONObject) item.optString("msg", item.toString()) else item.toString())
                }
            }
            else -> json.optString("message", "Nomad request failed ($status)")
        }
    }

    companion object {
        fun normalizeServer(value: String): String {
            var raw = value.trim()
            if (raw.isBlank()) raw = "nomadpi.local"
            if (!raw.startsWith("http://") && !raw.startsWith("https://")) raw = "http://$raw"
            return raw.trimEnd('/')
        }

        private fun enc(value: String): String = URLEncoder.encode(value, StandardCharsets.UTF_8.name())
        private fun encPathSegment(value: String): String = Uri.encode(value)
    }
}

private fun JSONObject.optStringOrNull(key: String): String? {
    if (!has(key) || isNull(key)) return null
    return optString(key).takeIf { it.isNotBlank() && it != "null" && it != "N/A" }
}

private fun <T> JSONArray?.toObjectList(transform: (JSONObject) -> T): List<T> {
    if (this == null) return emptyList()
    val out = ArrayList<T>(length())
    for (i in 0 until length()) {
        val obj = optJSONObject(i) ?: continue
        out += transform(obj)
    }
    return out
}

private fun JSONArray?.toStringList(): List<String> {
    if (this == null) return emptyList()
    return buildList {
        for (i in 0 until length()) {
            optString(i).takeIf { it.isNotBlank() }?.let(::add)
        }
    }
}
