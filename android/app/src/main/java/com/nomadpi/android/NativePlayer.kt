package com.nomadpi.android

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.outlined.ArrowBack
import androidx.compose.material.icons.outlined.MusicNote
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import kotlinx.coroutines.delay


data class NativeMediaSource(
    val title: String,
    val url: String,
    val mode: String,
    val audioOnly: Boolean = false,
)

@Composable
fun NativeMediaPlayer(
    source: NativeMediaSource,
    onClose: (positionMs: Long, durationMs: Long) -> Unit,
    onHeartbeat: ((positionMs: Long, durationMs: Long, playing: Boolean) -> Unit)? = null,
) {
    val context = LocalContext.current
    val player = remember(source.url) {
        ExoPlayer.Builder(context).build().apply {
            setMediaItem(MediaItem.fromUri(source.url))
            prepare()
            playWhenReady = true
        }
    }
    var playing by remember { mutableStateOf(false) }
    var position by remember { mutableLongStateOf(0L) }
    var duration by remember { mutableLongStateOf(0L) }
    var closed by remember { mutableStateOf(false) }

    fun finish() {
        if (closed) return
        closed = true
        position = player.currentPosition.coerceAtLeast(0L)
        duration = player.duration.takeIf { it != C.TIME_UNSET && it > 0 } ?: 0L
        onClose(position, duration)
    }

    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) { playing = isPlaying }
        }
        player.addListener(listener)
        onDispose {
            if (!closed) {
                val p = player.currentPosition.coerceAtLeast(0L)
                val d = player.duration.takeIf { it != C.TIME_UNSET && it > 0 } ?: 0L
                onClose(p, d)
                closed = true
            }
            player.removeListener(listener)
            player.release()
        }
    }

    LaunchedEffect(player) {
        while (true) {
            position = player.currentPosition.coerceAtLeast(0L)
            duration = player.duration.takeIf { it != C.TIME_UNSET && it > 0 } ?: 0L
            delay(400)
        }
    }
    LaunchedEffect(source.url, onHeartbeat) {
        while (onHeartbeat != null) {
            delay(10_000)
            onHeartbeat(
                player.currentPosition.coerceAtLeast(0L),
                player.duration.takeIf { it != C.TIME_UNSET && it > 0 } ?: 0L,
                player.isPlaying,
            )
        }
    }
    BackHandler { finish() }

    if (source.audioOnly) {
        Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            Column(
                Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    IconButton(onClick = ::finish) { Icon(Icons.Outlined.ArrowBack, "Close") }
                    Spacer(Modifier.weight(1f))
                    Text(source.mode.replace('_', ' '), color = MaterialTheme.colorScheme.primary)
                }
                Spacer(Modifier.weight(.6f))
                Box(
                    Modifier.fillMaxWidth(.72f).aspectRatio(1f)
                        .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(28.dp)),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(Icons.Outlined.MusicNote, null, Modifier.size(96.dp), tint = MaterialTheme.colorScheme.primary)
                }
                Text(
                    stripMediaExtension(source.title),
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 28.dp),
                )
                Text("Media3 · native decoder", color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 6.dp))
                Spacer(Modifier.height(28.dp))
                val fraction = if (duration > 0) (position.toFloat() / duration.toFloat()).coerceIn(0f, 1f) else 0f
                Slider(
                    value = fraction,
                    onValueChange = { if (duration > 0) player.seekTo((duration * it).toLong()) },
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(Modifier.fillMaxWidth()) {
                    Text(formatDuration(position), style = MaterialTheme.typography.labelSmall)
                    Spacer(Modifier.weight(1f))
                    Text(formatDuration(duration), style = MaterialTheme.typography.labelSmall)
                }
                Spacer(Modifier.height(18.dp))
                Row(horizontalArrangement = Arrangement.Center) {
                    IconButton(
                        onClick = { if (player.isPlaying) player.pause() else player.play() },
                        modifier = Modifier.size(78.dp).background(MaterialTheme.colorScheme.primaryContainer, RoundedCornerShape(50)),
                    ) {
                        Icon(if (playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, if (playing) "Pause" else "Play", Modifier.size(42.dp))
                    }
                }
                Spacer(Modifier.weight(1f))
            }
        }
    } else {
        Box(Modifier.fillMaxSize().background(Color.Black)) {
            AndroidView(
                factory = { ctx -> PlayerView(ctx).apply { this.player = player; useController = true } },
                update = { it.player = player },
                modifier = Modifier.fillMaxSize(),
            )
            Row(
                Modifier.fillMaxWidth().statusBarsPadding().padding(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = ::finish) { Icon(Icons.Outlined.ArrowBack, "Close", tint = Color.White) }
                Column(Modifier.weight(1f)) {
                    Text(source.title, color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.Bold)
                    Text(source.mode.replace('_', ' '), color = Color.LightGray, style = MaterialTheme.typography.labelSmall)
                }
            }
        }
    }
}

fun stripMediaExtension(value: String): String = value.replace(Regex("\\.[A-Za-z0-9]{2,5}$"), "")

fun formatDuration(ms: Long): String {
    val total = (ms.coerceAtLeast(0) / 1000).toInt()
    val h = total / 3600
    val m = (total % 3600) / 60
    val s = total % 60
    return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%d:%02d".format(m, s)
}
