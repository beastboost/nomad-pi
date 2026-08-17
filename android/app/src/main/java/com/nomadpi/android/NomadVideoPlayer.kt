package com.nomadpi.android

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.net.Uri
import android.view.WindowManager
import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.outlined.ArrowBack
import androidx.compose.material.icons.outlined.Forward30
import androidx.compose.material.icons.outlined.Replay10
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets
import kotlin.math.max

@Composable
fun NomadVideoPlayer(
    active: ActivePlayback,
    api: NomadApi,
    settings: NomadUiSettings,
    onClose: (positionMs: Long, durationMs: Long) -> Unit,
    onHeartbeat: ((positionMs: Long, durationMs: Long, playing: Boolean) -> Unit)? = null,
) {
    val context = LocalContext.current
    val activity = context.findActivity()
    val player = remember(active.url) {
        ExoPlayer.Builder(context)
            .setSeekBackIncrementMs(10_000)
            .setSeekForwardIncrementMs(30_000)
            .build()
            .apply {
                setMediaItem(MediaItem.fromUri(active.url))
                prepare()
                playWhenReady = true
            }
    }

    var playing by remember { mutableStateOf(false) }
    var controlsVisible by remember { mutableStateOf(true) }
    var settingsOpen by remember { mutableStateOf(false) }
    var position by remember { mutableLongStateOf(0L) }
    var playerDuration by remember { mutableLongStateOf(0L) }
    var serverDuration by remember(active.sessionId) { mutableLongStateOf(0L) }
    var scrubbing by remember { mutableStateOf(false) }
    var scrubPosition by remember { mutableFloatStateOf(0f) }
    var resizeMode by remember(settings.videoResize) { mutableStateOf(settings.videoResize) }
    var closed by remember { mutableStateOf(false) }

    val duration = max(playerDuration, serverDuration)

    fun finish() {
        if (closed) return
        closed = true
        val current = player.currentPosition.coerceAtLeast(0L)
        onClose(current, max(duration, player.duration.takeIf { it != C.TIME_UNSET && it > 0 } ?: 0L))
    }

    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) {
                playing = isPlaying
            }
        }
        player.addListener(listener)
        onDispose {
            if (!closed) {
                val current = player.currentPosition.coerceAtLeast(0L)
                val currentDuration = max(duration, player.duration.takeIf { it != C.TIME_UNSET && it > 0 } ?: 0L)
                onClose(current, currentDuration)
                closed = true
            }
            player.removeListener(listener)
            player.release()
        }
    }

    DisposableEffect(activity, settings.fullscreenVideo, settings.keepScreenAwake) {
        val window = activity?.window
        val insets = window?.let { WindowInsetsControllerCompat(it, it.decorView) }
        if (settings.keepScreenAwake) window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        if (settings.fullscreenVideo) {
            insets?.hide(WindowInsetsCompat.Type.systemBars())
            insets?.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
        onDispose {
            if (settings.keepScreenAwake) window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            if (settings.fullscreenVideo) insets?.show(WindowInsetsCompat.Type.systemBars())
        }
    }

    LaunchedEffect(active.sessionId) {
        val id = active.sessionId ?: return@LaunchedEffect
        serverDuration = withContext(Dispatchers.IO) { api.fetchPlaybackDurationMs(id) }
    }

    LaunchedEffect(player) {
        while (true) {
            position = player.currentPosition.coerceAtLeast(0L)
            playerDuration = player.duration.takeIf { it != C.TIME_UNSET && it > 0 } ?: 0L
            delay(250)
        }
    }

    LaunchedEffect(controlsVisible, playing, settingsOpen) {
        if (controlsVisible && playing && !settingsOpen) {
            delay(3_500)
            controlsVisible = false
        }
    }

    LaunchedEffect(active.url, onHeartbeat, serverDuration) {
        while (onHeartbeat != null) {
            delay(10_000)
            onHeartbeat(
                player.currentPosition.coerceAtLeast(0L),
                max(serverDuration, player.duration.takeIf { it != C.TIME_UNSET && it > 0 } ?: 0L),
                player.isPlaying,
            )
        }
    }

    BackHandler { finish() }

    Box(Modifier.fillMaxSize().background(Color.Black)) {
        AndroidView(
            factory = { ctx ->
                PlayerView(ctx).apply {
                    useController = false
                    this.player = player
                    resizeMode = resizeMode.toResizeMode()
                    setShutterBackgroundColor(android.graphics.Color.BLACK)
                }
            },
            update = {
                it.player = player
                it.resizeMode = resizeMode.toResizeMode()
            },
            modifier = Modifier.fillMaxSize(),
        )

        Box(
            Modifier
                .fillMaxSize()
                .clickable(
                    interactionSource = remember { MutableInteractionSource() },
                    indication = null,
                ) { controlsVisible = !controlsVisible },
        )

        AnimatedVisibility(visible = controlsVisible) {
            Box(Modifier.fillMaxSize()) {
                Box(
                    Modifier
                        .fillMaxWidth()
                        .background(
                            Brush.verticalGradient(
                                listOf(Color.Black.copy(alpha = .82f), Color.Black.copy(alpha = .38f), Color.Transparent),
                            ),
                        )
                        .padding(horizontal = 10.dp, vertical = 12.dp),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        IconButton(onClick = ::finish) {
                            Icon(Icons.Outlined.ArrowBack, "Back", tint = Color.White)
                        }
                        Column(Modifier.weight(1f).padding(horizontal = 8.dp)) {
                            Text(
                                stripMediaExtension(active.title),
                                color = Color.White,
                                fontWeight = FontWeight.Bold,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(
                                if (active.mode.contains("direct", ignoreCase = true)) "Direct Play" else active.mode.replace('_', ' '),
                                color = Color.White.copy(alpha = .7f),
                                style = MaterialTheme.typography.labelSmall,
                            )
                        }
                        IconButton(onClick = { settingsOpen = true }) {
                            Icon(Icons.Outlined.Settings, "Player settings", tint = Color.White)
                        }
                    }
                }

                Row(
                    modifier = Modifier.align(Alignment.Center),
                    horizontalArrangement = Arrangement.spacedBy(28.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    IconButton(
                        onClick = {
                            player.seekTo((player.currentPosition - 10_000).coerceAtLeast(0L))
                            controlsVisible = true
                        },
                        modifier = Modifier.size(58.dp),
                    ) {
                        Icon(Icons.Outlined.Replay10, "Back 10 seconds", tint = Color.White, modifier = Modifier.size(38.dp))
                    }
                    IconButton(
                        onClick = {
                            if (player.isPlaying) player.pause() else player.play()
                            controlsVisible = true
                        },
                        modifier = Modifier.size(76.dp).background(Color.White.copy(alpha = .94f), CircleShape),
                    ) {
                        Icon(
                            if (playing) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                            if (playing) "Pause" else "Play",
                            tint = Color.Black,
                            modifier = Modifier.size(44.dp),
                        )
                    }
                    IconButton(
                        onClick = {
                            val end = duration.takeIf { it > 0 } ?: Long.MAX_VALUE
                            player.seekTo((player.currentPosition + 30_000).coerceAtMost(end))
                            controlsVisible = true
                        },
                        modifier = Modifier.size(58.dp),
                    ) {
                        Icon(Icons.Outlined.Forward30, "Forward 30 seconds", tint = Color.White, modifier = Modifier.size(38.dp))
                    }
                }

                Column(
                    Modifier
                        .align(Alignment.BottomCenter)
                        .fillMaxWidth()
                        .background(
                            Brush.verticalGradient(
                                listOf(Color.Transparent, Color.Black.copy(alpha = .48f), Color.Black.copy(alpha = .88f)),
                            ),
                        )
                        .padding(horizontal = 18.dp, vertical = 18.dp),
                ) {
                    val total = duration.coerceAtLeast(1L)
                    val shownPosition = if (scrubbing) scrubPosition.toLong() else position.coerceAtMost(total)
                    Slider(
                        value = shownPosition.toFloat().coerceIn(0f, total.toFloat()),
                        onValueChange = {
                            scrubbing = true
                            scrubPosition = it
                        },
                        onValueChangeFinished = {
                            if (scrubbing) player.seekTo(scrubPosition.toLong())
                            scrubbing = false
                            controlsVisible = true
                        },
                        valueRange = 0f..total.toFloat(),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text(formatDuration(shownPosition), color = Color.White, style = MaterialTheme.typography.labelMedium)
                        Spacer(Modifier.weight(1f))
                        Text(formatDuration(duration), color = Color.White, style = MaterialTheme.typography.labelMedium)
                    }
                }
            }
        }
    }

    if (settingsOpen) {
        AlertDialog(
            onDismissRequest = { settingsOpen = false },
            title = { Text("Video display") },
            text = {
                Column {
                    Text("Choose how the video fits your screen.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    listOf("fit" to "Fit", "fill" to "Fill", "zoom" to "Zoom").forEach { (value, label) ->
                        TextButton(
                            onClick = {
                                resizeMode = value
                                settingsOpen = false
                                controlsVisible = true
                            },
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text(if (resizeMode == value) "✓  $label" else label)
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { settingsOpen = false }) { Text("Done") }
            },
        )
    }
}

private fun String.toResizeMode(): Int = when (this) {
    "fill" -> AspectRatioFrameLayout.RESIZE_MODE_FILL
    "zoom" -> AspectRatioFrameLayout.RESIZE_MODE_ZOOM
    else -> AspectRatioFrameLayout.RESIZE_MODE_FIT
}

private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}

private fun NomadApi.fetchPlaybackDurationMs(sessionId: String): Long {
    val url = URL(absoluteUrl("/api/playback/sessions/${Uri.encode(sessionId)}"))
    val connection = (url.openConnection() as HttpURLConnection).apply {
        requestMethod = "GET"
        connectTimeout = 3_500
        readTimeout = 5_000
        setRequestProperty("Accept", "application/json")
        token?.takeIf { it.isNotBlank() }?.let { setRequestProperty("Authorization", "Bearer $it") }
        profileId?.let { setRequestProperty("X-Nomad-Profile-ID", it.toString()) }
    }
    return try {
        if (connection.responseCode !in 200..299) return 0L
        val text = connection.inputStream.use { stream ->
            BufferedReader(InputStreamReader(stream, StandardCharsets.UTF_8)).readText()
        }
        val json = JSONObject(text)
        val seconds = json.optDouble("duration", json.optJSONObject("metadata")?.optJSONObject("source")?.optDouble("duration", 0.0) ?: 0.0)
        (seconds.coerceAtLeast(0.0) * 1000.0).toLong()
    } catch (_: Throwable) {
        0L
    } finally {
        connection.disconnect()
    }
}
