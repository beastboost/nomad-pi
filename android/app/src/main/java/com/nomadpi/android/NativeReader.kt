package com.nomadpi.android

import android.graphics.Bitmap
import android.graphics.pdf.PdfRenderer
import android.os.ParcelFileDescriptor
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ArrowBack
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import kotlin.math.max

sealed class NativeReaderSource {
    data class Comic(val path: String, val title: String) : NativeReaderSource()
    data class Pdf(val path: String, val title: String) : NativeReaderSource()
}

@Composable
fun NativeReader(
    api: NomadApi,
    source: NativeReaderSource,
    onClose: () -> Unit,
) {
    BackHandler(onBack = onClose)
    when (source) {
        is NativeReaderSource.Comic -> NativeComicReader(api, source, onClose)
        is NativeReaderSource.Pdf -> NativePdfReader(api, source, onClose)
    }
}

@Composable
private fun NativeComicReader(api: NomadApi, source: NativeReaderSource.Comic, onClose: () -> Unit) {
    val extras = remember(api) { NomadExtrasApi(api) }
    val book by produceState<ComicBook?>(initialValue = null, source.path) {
        value = withContext(Dispatchers.IO) { runCatching { extras.comic(source.path) }.getOrNull() }
    }
    val comic = book
    if (comic == null) {
        ReaderLoading(source.title, onClose)
        return
    }
    if (comic.pages.isEmpty()) {
        ReaderError(source.title, "No comic pages were extracted.", onClose)
        return
    }
    val initial by produceState(initialValue = 0, source.path) {
        value = withContext(Dispatchers.IO) { runCatching { extras.readerPage(source.path) }.getOrDefault(0) }
    }
    val pager = rememberPagerState(initialPage = initial.coerceIn(0, comic.pages.lastIndex)) { comic.pages.size }
    LaunchedEffect(pager.currentPage) {
        withContext(Dispatchers.IO) {
            runCatching { extras.saveReaderProgress(source.path, pager.currentPage, comic.pages.size) }
        }
    }

    Surface(Modifier.fillMaxSize(), color = Color(0xFF070809)) {
        Box(Modifier.fillMaxSize()) {
            HorizontalPager(pager, Modifier.fillMaxSize()) { page ->
                RemoteImage(
                    url = api.mediaStreamUrl(comic.pages[page]),
                    modifier = Modifier.fillMaxSize(),
                    contentScale = ContentScale.Fit,
                    maxDecodePx = 2600,
                )
            }
            ReaderTopBar(
                title = comic.title.ifBlank { source.title },
                subtitle = "${pager.currentPage + 1} / ${comic.pages.size}",
                onClose = onClose,
            )
        }
    }
}

@Composable
private fun NativePdfReader(api: NomadApi, source: NativeReaderSource.Pdf, onClose: () -> Unit) {
    val context = androidx.compose.ui.platform.LocalContext.current
    var error by remember(source.path) { mutableStateOf<String?>(null) }
    val pdfFile by produceState<File?>(initialValue = null, source.path) {
        value = withContext(Dispatchers.IO) {
            runCatching {
                val target = File(context.cacheDir, "nomad-pdf-${source.path.hashCode().toUInt()}.pdf")
                if (!target.isFile || target.length() == 0L) {
                    downloadFile(api.mediaStreamUrl(source.path), target)
                }
                target
            }.onFailure { error = it.message ?: "Could not download PDF" }.getOrNull()
        }
    }
    if (error != null) {
        ReaderError(source.title, error!!, onClose)
        return
    }
    val file = pdfFile
    if (file == null) {
        ReaderLoading(source.title, onClose)
        return
    }

    val holder = remember(file.absolutePath) { runCatching { PdfHolder(file) }.getOrNull() }
    if (holder == null) {
        ReaderError(source.title, "Android could not open this PDF.", onClose)
        return
    }
    DisposableEffect(holder) { onDispose { holder.close() } }
    if (holder.pageCount <= 0) {
        ReaderError(source.title, "This PDF has no renderable pages.", onClose)
        return
    }
    val pager = rememberPagerState(initialPage = 0) { holder.pageCount }

    Surface(Modifier.fillMaxSize(), color = Color(0xFF070809)) {
        Box(Modifier.fillMaxSize()) {
            HorizontalPager(pager, Modifier.fillMaxSize()) { page ->
                val bitmap by produceState<Bitmap?>(initialValue = null, page) {
                    value = withContext(Dispatchers.IO) { holder.render(page, 1600) }
                }
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    if (bitmap == null) CircularProgressIndicator()
                    else Image(bitmap!!.asImageBitmap(), null, Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
                }
            }
            ReaderTopBar(source.title, "${pager.currentPage + 1} / ${holder.pageCount}", onClose)
        }
    }
}

@Composable
private fun ReaderTopBar(title: String, subtitle: String, onClose: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().statusBarsPadding().background(Color.Black.copy(alpha = .58f)).padding(6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = onClose) { Icon(Icons.Outlined.ArrowBack, "Close", tint = Color.White) }
        Column(Modifier.weight(1f)) {
            Text(title, color = Color.White, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(subtitle, color = Color.LightGray, style = MaterialTheme.typography.labelSmall)
        }
    }
}

@Composable
private fun ReaderLoading(title: String, onClose: () -> Unit) {
    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                CircularProgressIndicator()
                Text("Opening $title…", modifier = Modifier.padding(top = 12.dp))
            }
            IconButton(onClick = onClose, modifier = Modifier.align(Alignment.TopStart).statusBarsPadding()) {
                Icon(Icons.Outlined.ArrowBack, "Close")
            }
        }
    }
}

@Composable
private fun ReaderError(title: String, message: String, onClose: () -> Unit) {
    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Column(Modifier.padding(28.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Text(title, fontWeight = FontWeight.Bold)
                Text(message, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(top = 8.dp))
            }
            IconButton(onClick = onClose, modifier = Modifier.align(Alignment.TopStart).statusBarsPadding()) {
                Icon(Icons.Outlined.ArrowBack, "Close")
            }
        }
    }
}

private class PdfHolder(file: File) {
    private val descriptor = ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
    private val renderer = PdfRenderer(descriptor)
    val pageCount: Int get() = renderer.pageCount

    @Synchronized
    fun render(index: Int, targetWidth: Int): Bitmap? {
        if (index !in 0 until renderer.pageCount) return null
        renderer.openPage(index).use { page ->
            val width = targetWidth.coerceAtLeast(600)
            val scale = width.toFloat() / page.width.toFloat().coerceAtLeast(1f)
            val height = max(1, (page.height * scale).toInt())
            // PdfRenderer explicitly requires an ARGB destination bitmap.
            val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
            bitmap.eraseColor(android.graphics.Color.WHITE)
            page.render(bitmap, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
            return bitmap
        }
    }

    fun close() {
        runCatching { renderer.close() }
        runCatching { descriptor.close() }
    }
}

private fun downloadFile(url: String, destination: File) {
    val tmp = File(destination.parentFile, destination.name + ".part")
    val connection = (URL(url).openConnection() as HttpURLConnection).apply {
        connectTimeout = 10_000
        readTimeout = 60_000
        useCaches = false
    }
    try {
        if (connection.responseCode !in 200..299) error("Server returned HTTP ${connection.responseCode}")
        tmp.outputStream().use { out -> connection.inputStream.use { input -> input.copyTo(out, 512 * 1024) } }
        if (!tmp.renameTo(destination)) {
            tmp.copyTo(destination, overwrite = true)
            tmp.delete()
        }
    } finally {
        connection.disconnect()
        if (tmp.exists() && destination.exists()) tmp.delete()
    }
}
