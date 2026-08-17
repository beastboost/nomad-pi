package com.nomadpi.android

import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.nio.charset.StandardCharsets


data class UniversalRelease(
    val name: String,
    val infoHash: String,
    val fileIndex: Int?,
    val quality: String,
    val size: String,
    val source: String,
    val codec: String,
    val details: String,
    val cached: Boolean,
    val compatible: Boolean,
    val directCandidate: Boolean,
    val reasons: List<String>,
)

data class UniversalTitle(
    val imdbId: String,
    val title: String,
    val year: String,
    val type: String,
    val poster: String?,
    val releases: List<UniversalRelease>,
)

data class ResolvedRemote(
    val title: String,
    val filename: String,
    val url: String,
    val proxyToken: String? = null,
)

data class PhotoAlbum(val name: String, val count: Int)
data class PhotoAlbums(val albums: List<PhotoAlbum>, val itemAlbums: Map<String, String>)
data class ComicBook(val title: String, val pages: List<String>)

private data class DirectSource(val filename: String, val url: String)

/** Native-only convenience layer over Nomad's existing server APIs. */
class NomadExtrasApi(private val api: NomadApi) {
    fun universalSearch(query: String, season: Int = 1, episode: Int = 1): List<UniversalTitle> {
        val json = request("GET", "/api/debrid/universal/search?q=${enc(query.trim())}&season=$season&episode=$episode")
        return json.optJSONArray("titles").objects(::parseTitle)
    }

    fun universalReleases(title: UniversalTitle, season: Int = 1, episode: Int = 1, showAll: Boolean = false): UniversalTitle {
        val path = "/api/debrid/universal/releases?imdb_id=${enc(title.imdbId)}" +
            "&media_type=${enc(title.type)}&season=${season.coerceAtLeast(1)}&episode=${episode.coerceAtLeast(1)}" +
            "&include_heavy=${if (showAll) "true" else "false"}&limit=${if (showAll) 24 else 10}"
        val json = request("GET", path)
        return title.copy(releases = parseReleases(json.optJSONArray("releases")))
    }

    fun resolveForPlay(title: UniversalTitle, release: UniversalRelease, season: Int = 1, episode: Int = 1): ResolvedRemote {
        val source = resolveDirectSource(title, release, season, episode)
        val proxy = request(
            "POST", "/api/debrid/universal/play",
            JSONObject().put("url", source.url).put("filename", source.filename),
        )
        val url = proxy.optJSONObject("playback")?.optString("url").orEmpty()
        if (url.isBlank()) throw NomadApiException("Nomad did not create a remote playback URL")
        return ResolvedRemote(
            title = title.title,
            filename = source.filename,
            url = api.absoluteUrl(url),
            proxyToken = proxy.optString("token").takeIf { it.isNotBlank() },
        )
    }

    fun deleteRemotePlay(token: String) {
        request("DELETE", "/api/debrid/universal/play/${seg(token)}")
    }

    fun downloadRelease(title: UniversalTitle, release: UniversalRelease, season: Int = 1, episode: Int = 1): String {
        val source = resolveDirectSource(title, release, season, episode)
        val clean = request(
            "POST", "/api/debrid/clean-filename",
            JSONObject()
                .put("filename", source.filename)
                .put("title", title.title)
                .put("year", title.year)
                .put("media_type", title.type)
                .put("season", season)
                .put("episode", episode),
        ).optString("clean_filename", source.filename)
        return request(
            "POST", "/api/debrid/download",
            JSONObject()
                .put("url", source.url)
                .put("filename", clean)
                .put("category", if (title.type == "series") "shows" else "movies")
                .put("is_show", title.type == "series"),
        ).optString("download_id")
    }

    fun streamKeep(title: UniversalTitle, release: UniversalRelease, capabilities: AndroidCapabilities, season: Int = 1, episode: Int = 1): ResolvedRemote {
        val source = resolveDirectSource(title, release, season, episode)
        val json = request(
            "POST", "/api/playback/stream-keep/start",
            JSONObject()
                .put("url", source.url)
                .put("filename", source.filename)
                .put("provider", "debrid")
                .put("category", if (title.type == "series") "shows" else "movies")
                .put("is_show", title.type == "series")
                .put("position", 0)
                .put("capabilities", capabilities.toJson())
                .put("metadata", JSONObject().put("title", title.title).put("season", season).put("episode", episode)),
        )
        val playback = json.optJSONObject("playback") ?: JSONObject()
        val url = playback.optString("url")
        if (url.isBlank()) throw NomadApiException("Stream + Keep did not return a playback URL")
        return ResolvedRemote(
            title = title.title,
            filename = source.filename,
            url = api.absoluteUrl(url),
            proxyToken = json.optJSONObject("job")?.optString("id")?.takeIf { it.isNotBlank() },
        )
    }

    fun albums(): PhotoAlbums {
        val json = request("GET", "/api/playback/gallery/albums")
        val albums = json.optJSONArray("albums").objects { item -> PhotoAlbum(item.optString("name"), item.optInt("count", 0)) }
        val mapping = mutableMapOf<String, String>()
        val objectMap = json.optJSONObject("item_albums") ?: JSONObject()
        val keys = objectMap.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            mapping[key] = objectMap.optString(key)
        }
        return PhotoAlbums(albums, mapping)
    }

    fun createAlbum(name: String) {
        request("POST", "/api/playback/gallery/albums", JSONObject().put("name", name.trim()))
    }

    fun movePhotos(ids: Collection<String>, album: String) {
        request("POST", "/api/playback/gallery/move", JSONObject().put("item_ids", JSONArray(ids.toList())).put("album", album))
    }

    fun deletePhotos(ids: Collection<String>): Int = request(
        "POST", "/api/playback/gallery/bulk-delete",
        JSONObject().put("item_ids", JSONArray(ids.toList())),
    ).optInt("deleted", 0)

    fun comic(path: String): ComicBook {
        val json = request("GET", "/api/media/books/comic/pages?path=${enc(path)}")
        val raw = json.optJSONArray("pages") ?: JSONArray()
        val pages = buildList {
            for (i in 0 until raw.length()) {
                when (val value = raw.opt(i)) {
                    is String -> value.takeIf { it.isNotBlank() }?.let(::add)
                    is JSONObject -> value.optString("path").takeIf { it.isNotBlank() }?.let(::add)
                }
            }
        }
        return ComicBook(json.optString("title", path.substringAfterLast('/')), pages)
    }

    fun saveReaderProgress(path: String, page: Int, total: Int) {
        val percent = if (total > 0) ((page + 1).toDouble() / total * 100.0).coerceIn(0.0, 100.0) else 0.0
        request(
            "POST", "/api/playback/reader/progress",
            JSONObject().put("path", path).put("position", JSONObject().put("page", page).put("total", total)).put("percent", percent),
        )
    }

    fun readerPage(path: String): Int = request(
        "GET", "/api/playback/reader/progress?path=${enc(path)}",
    ).optJSONObject("progress")?.optJSONObject("position")?.optInt("page", 0) ?: 0

    private fun resolveDirectSource(title: UniversalTitle, release: UniversalRelease, season: Int, episode: Int): DirectSource {
        if (release.infoHash.isBlank()) throw NomadApiException("Release has no info hash")
        val magnet = request(
            "POST", "/api/debrid/magnet",
            JSONObject()
                .put("info_hash", release.infoHash)
                .put("title", title.title)
                .put("year", title.year)
                .put("media_type", title.type)
                .put("season", season.coerceAtLeast(1))
                .put("episode", episode.coerceAtLeast(1)),
        )
        val files = magnet.optJSONArray("files") ?: JSONArray()
        val links = magnet.optJSONArray("links") ?: JSONArray()
        val provider = magnet.optString("provider")
        val chosen = chooseFile(files, links, release.fileIndex, provider, season, episode)
        if (chosen.first.isBlank()) throw NomadApiException("Provider returned no media link")
        val unrestricted = request("POST", "/api/debrid/unrestrict", JSONObject().put("link", chosen.first))
        val url = unrestricted.optString("url")
        if (url.isBlank()) throw NomadApiException("Provider did not return a media URL")
        val filename = chosen.second.ifBlank { unrestricted.optString("filename", release.name) }
            .substringAfterLast('/').substringAfterLast('\\').ifBlank { "media.mp4" }
        return DirectSource(filename, url)
    }

    /**
     * Torrentio's fileIdx is authoritative when the provider preserves the
     * original torrent order (notably RD). For normalized AD/TB file lists or
     * missing indices, explicit SxxEyy / Season.xx.Episode.yy naming wins.
     */
    private fun chooseFile(
        files: JSONArray,
        links: JSONArray,
        preferredIndex: Int?,
        provider: String,
        season: Int,
        episode: Int,
    ): Pair<String, String> {
        val video = Regex("\\.(mp4|mkv|m4v|webm|avi|mov|ts|m2ts|mts|wmv|mpg|mpeg)(?:$|[?#])", RegexOption.IGNORE_CASE)

        if (provider == "rd" && preferredIndex != null && preferredIndex in 0 until files.length()) {
            val file = files.optJSONObject(preferredIndex)
            val name = file?.let { it.optString("path", it.optString("name")) }.orEmpty()
            val link = links.optString(preferredIndex)
            if (name.isNotBlank() && video.containsMatchIn(name) && link.isNotBlank()) return link to name
        }

        val seasonEpisodePatterns = listOf(
            Regex("(?i)(?:^|[^A-Za-z0-9])S0*${season}E0*${episode}(?:[^0-9]|$)"),
            Regex("(?i)Season[ ._-]*0*${season}[ ._-]*(?:Episode|Ep)[ ._-]*0*${episode}(?:[^0-9]|$)"),
            Regex("(?i)(?:^|[^0-9])0*${season}x0*${episode}(?:[^0-9]|$)"),
        )
        var selectedOrdinal = 0
        var biggestLink = ""
        var biggestName = ""
        var biggestSize = -1L
        for (i in 0 until files.length()) {
            val file = files.optJSONObject(i) ?: continue
            if (file.has("selected") && !file.optBoolean("selected", true)) continue
            val name = file.optString("path", file.optString("name"))
            val link = links.optString(selectedOrdinal)
            val size = file.optLong("bytes", file.optLong("size", 0))
            if (video.containsMatchIn(name) && link.isNotBlank()) {
                if (seasonEpisodePatterns.any { it.containsMatchIn(name) }) return link to name
                if (size > biggestSize) {
                    biggestSize = size
                    biggestLink = link
                    biggestName = name
                }
            }
            selectedOrdinal++
        }
        return biggestLink to biggestName
    }

    private fun parseTitle(json: JSONObject): UniversalTitle = UniversalTitle(
        imdbId = json.optString("imdb_id"),
        title = json.optString("title", "Title"),
        year = json.optString("year"),
        type = json.optString("type", "movie"),
        poster = json.optString("poster").takeIf { it.isNotBlank() && it != "null" },
        releases = parseReleases(json.optJSONObject("release_set")?.optJSONArray("releases")),
    )

    private fun parseReleases(array: JSONArray?): List<UniversalRelease> = array.objects { item ->
        UniversalRelease(
            name = item.optString("name", "Release"),
            infoHash = item.optString("info_hash", item.optString("hash")),
            fileIndex = if (item.has("file_idx") && !item.isNull("file_idx")) item.optInt("file_idx") else null,
            quality = item.optString("quality"),
            size = item.optString("size"),
            source = item.optString("source"),
            codec = item.optString("codec"),
            details = item.optString("details"),
            cached = item.optBoolean("cached", false),
            compatible = item.optBoolean("lite_compatible", false),
            directCandidate = item.optBoolean("lite_direct_candidate", false),
            reasons = item.optJSONArray("lite_reasons").strings(),
        )
    }

    private fun request(method: String, path: String, body: JSONObject? = null): JSONObject {
        val connection = (URL(api.absoluteUrl(path)).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 10_000
            readTimeout = 60_000
            useCaches = false
            setRequestProperty("Accept", "application/json")
            setRequestProperty("User-Agent", "NomadAndroid/${BuildConfig.VERSION_NAME}")
            api.token?.takeIf { it.isNotBlank() }?.let { setRequestProperty("Authorization", "Bearer $it") }
            api.profileId?.let { setRequestProperty("X-Nomad-Profile-ID", it.toString()) }
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                outputStream.use { it.write(body.toString().toByteArray(StandardCharsets.UTF_8)) }
            }
        }
        val status = try { connection.responseCode } catch (e: Exception) {
            connection.disconnect()
            throw NomadApiException("Could not reach ${api.baseUrl}: ${e.message ?: "network error"}")
        }
        val stream = if (status in 200..299) connection.inputStream else connection.errorStream
        val text = stream?.use { BufferedReader(InputStreamReader(it, StandardCharsets.UTF_8)).readText() }.orEmpty()
        connection.disconnect()
        val json = if (text.isBlank()) JSONObject() else runCatching { JSONObject(text) }.getOrElse { JSONObject().put("raw", text) }
        if (status !in 200..299) throw NomadApiException(errorText(json, status), status)
        return json
    }

    private fun errorText(json: JSONObject, status: Int): String {
        return when (val detail = json.opt("detail")) {
            is String -> detail
            is JSONObject -> detail.optString("message", detail.toString())
            is JSONArray -> (0 until detail.length()).joinToString("; ") { i ->
                val value = detail.opt(i)
                if (value is JSONObject) value.optString("msg", value.toString()) else value.toString()
            }
            else -> json.optString("message", "Nomad request failed ($status)")
        }
    }

    private fun enc(value: String): String = URLEncoder.encode(value, StandardCharsets.UTF_8.name())
    private fun seg(value: String): String = Uri.encode(value)
}

private inline fun <T> JSONArray?.objects(transform: (JSONObject) -> T): List<T> {
    if (this == null) return emptyList()
    return buildList {
        for (i in 0 until length()) optJSONObject(i)?.let { add(transform(it)) }
    }
}

private fun JSONArray?.strings(): List<String> {
    if (this == null) return emptyList()
    return buildList {
        for (i in 0 until length()) optString(i).takeIf { it.isNotBlank() }?.let(::add)
    }
}
