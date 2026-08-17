package com.nomadpi.android

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.LruCache
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL
import kotlin.math.max

private object NomadImageCache {
    private val cache = object : LruCache<String, Bitmap>(32 * 1024) {
        override fun sizeOf(key: String, value: Bitmap): Int = value.byteCount / 1024
    }

    fun get(key: String): Bitmap? = cache.get(key)
    fun put(key: String, bitmap: Bitmap) { cache.put(key, bitmap) }
}

@Composable
fun RemoteImage(
    url: String?,
    modifier: Modifier = Modifier,
    contentScale: ContentScale = ContentScale.Crop,
    maxDecodePx: Int = 900,
) {
    val bitmap by produceState<Bitmap?>(initialValue = url?.let(NomadImageCache::get), url, maxDecodePx) {
        if (url.isNullOrBlank()) {
            value = null
            return@produceState
        }
        NomadImageCache.get(url)?.let {
            value = it
            return@produceState
        }
        value = withContext(Dispatchers.IO) { loadSampledBitmap(url, maxDecodePx) }
        value?.let { NomadImageCache.put(url, it) }
    }

    Box(modifier = modifier.background(MaterialTheme.colorScheme.surfaceVariant), contentAlignment = Alignment.Center) {
        if (bitmap != null) {
            Image(
                bitmap = bitmap!!.asImageBitmap(),
                contentDescription = null,
                contentScale = contentScale,
                modifier = Modifier.fillMaxSize(),
            )
        } else {
            Icon(Icons.Outlined.Image, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

private fun loadSampledBitmap(url: String, maxPx: Int): Bitmap? {
    val connection = (URL(url).openConnection() as HttpURLConnection).apply {
        connectTimeout = 8_000
        readTimeout = 20_000
        useCaches = true
        setRequestProperty("User-Agent", "NomadAndroid")
    }
    return try {
        val bytes = connection.inputStream.use { it.readBytes() }
        if (bytes.isEmpty()) return null
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        var sample = 1
        val longest = max(bounds.outWidth, bounds.outHeight)
        while (longest / sample > maxPx * 2) sample *= 2
        val options = BitmapFactory.Options().apply {
            inSampleSize = sample.coerceAtLeast(1)
            inPreferredConfig = Bitmap.Config.RGB_565
        }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)
    } catch (_: Throwable) {
        null
    } finally {
        connection.disconnect()
    }
}
