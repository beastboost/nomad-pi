package com.nomadpi.android

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.ArrowBack
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Folder
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun NativePhotos(vm: NomadViewModel) {
    val extras = remember(vm.api) { NomadExtrasApi(vm.api) }
    val scope = rememberCoroutineScope()
    var albums by remember { mutableStateOf(PhotoAlbums(emptyList(), emptyMap())) }
    var selectedAlbum by remember { mutableStateOf("") }
    var selected by remember { mutableStateOf<Set<String>>(emptySet()) }
    var viewerIndex by remember { mutableIntStateOf(-1) }
    var createAlbum by remember { mutableStateOf(false) }
    var moveDialog by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    var actionBusy by remember { mutableStateOf(false) }
    var galleryVideo by remember { mutableStateOf<GalleryItem?>(null) }

    fun reloadAlbums() {
        scope.launch {
            albums = withContext(Dispatchers.IO) { runCatching { extras.albums() }.getOrElse { PhotoAlbums(emptyList(), emptyMap()) } }
            if (selectedAlbum.isNotBlank() && albums.albums.none { it.name == selectedAlbum }) selectedAlbum = ""
        }
    }

    LaunchedEffect(vm.profile?.id) {
        vm.refreshPhotos()
        reloadAlbums()
        selected = emptySet()
        selectedAlbum = ""
    }

    galleryVideo?.let { video ->
        NativeMediaPlayer(
            NativeMediaSource(video.name, vm.api.galleryItemUrl(video.id), "private gallery", false),
            onClose = { _, _ -> galleryVideo = null },
        )
        return
    }

    val all = vm.photos?.items.orEmpty()
    val visible = if (selectedAlbum.isBlank()) all else all.filter { albums.itemAlbums[it.id] == selectedAlbum }

    if (viewerIndex >= 0 && viewerIndex < visible.size) {
        PhotoPager(vm, visible, viewerIndex, onClose = { viewerIndex = -1 }, onVideo = { galleryVideo = it })
        return
    }

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(vm.photos?.profile?.name ?: vm.profile?.name ?: "Photos", fontWeight = FontWeight.Bold)
                Text("${visible.size} items · private library", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (selected.isNotEmpty()) {
                TextButton(onClick = { moveDialog = true }) { Icon(Icons.Outlined.Folder, null); Text("Album") }
                TextButton(onClick = { confirmDelete = true }) { Icon(Icons.Outlined.Delete, null); Text("Delete") }
            } else {
                IconButton(onClick = { vm.refreshPhotos(); reloadAlbums() }) { Icon(Icons.Outlined.Refresh, "Refresh") }
            }
        }
        LazyRow(
            contentPadding = PaddingValues(horizontal = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(7.dp),
        ) {
            item {
                FilterChip(selected = selectedAlbum.isBlank(), onClick = { selectedAlbum = ""; selected = emptySet() }, label = { Text("All") })
            }
            items(albums.albums.size) { index ->
                val album = albums.albums[index]
                FilterChip(
                    selected = selectedAlbum == album.name,
                    onClick = { selectedAlbum = album.name; selected = emptySet() },
                    label = { Text("${album.name} ${album.count}") },
                )
            }
            item {
                FilterChip(selected = false, onClick = { createAlbum = true }, label = { Icon(Icons.Outlined.Add, null, Modifier.size(17.dp)); Text("Album") })
            }
        }

        if (visible.isEmpty() && !vm.busy) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(if (selectedAlbum.isBlank()) "No photos yet" else "This album is empty", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        } else {
            LazyVerticalGrid(
                columns = GridCells.Fixed(3),
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(2.dp),
            ) {
                items(visible, key = { it.id }) { item ->
                    val isSelected = selected.contains(item.id)
                    Box(
                        Modifier.aspectRatio(1f).padding(1.dp).combinedClickable(
                            onLongClick = { selected = selected + item.id },
                            onClick = {
                                if (selected.isNotEmpty()) {
                                    selected = if (isSelected) selected - item.id else selected + item.id
                                } else if (item.kind == "video") {
                                    galleryVideo = item
                                } else {
                                    viewerIndex = visible.indexOfFirst { it.id == item.id }
                                }
                            },
                        ),
                    ) {
                        if (item.kind == "image") {
                            RemoteImage(vm.api.galleryItemUrl(item.id), Modifier.fillMaxSize(), maxDecodePx = 520)
                        } else {
                            Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.surfaceVariant), contentAlignment = Alignment.Center) {
                                Icon(Icons.Filled.PlayArrow, "Video", Modifier.size(38.dp))
                            }
                        }
                        if (isSelected) {
                            Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = .25f)))
                            Icon(
                                Icons.Filled.CheckCircle,
                                "Selected",
                                tint = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.align(Alignment.TopEnd).padding(6.dp).size(28.dp).background(Color.Black.copy(alpha = .45f), CircleShape),
                            )
                        }
                    }
                }
            }
        }
    }

    if (selected.isNotEmpty()) BackHandler { selected = emptySet() }

    if (createAlbum) {
        var name by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { createAlbum = false },
            title = { Text("New album") },
            text = { OutlinedTextField(name, { name = it.take(120) }, label = { Text("Album name") }, singleLine = true) },
            confirmButton = {
                Button(enabled = name.trim().isNotEmpty() && !actionBusy, onClick = {
                    actionBusy = true
                    scope.launch {
                        runCatching { withContext(Dispatchers.IO) { extras.createAlbum(name) } }
                        createAlbum = false
                        actionBusy = false
                        reloadAlbums()
                    }
                }) { Text("Create") }
            },
            dismissButton = { TextButton(onClick = { createAlbum = false }) { Text("Cancel") } },
        )
    }

    if (moveDialog) {
        AlertDialog(
            onDismissRequest = { moveDialog = false },
            title = { Text("Move ${selected.size} items") },
            text = {
                Column {
                    OutlinedButton(onClick = {
                        moveDialog = false; actionBusy = true
                        scope.launch {
                            runCatching { withContext(Dispatchers.IO) { extras.movePhotos(selected, "") } }
                            selected = emptySet(); actionBusy = false; vm.refreshPhotos(); reloadAlbums()
                        }
                    }, modifier = Modifier.fillMaxWidth()) { Text("All photos · no album") }
                    albums.albums.forEach { album ->
                        OutlinedButton(onClick = {
                            moveDialog = false; actionBusy = true
                            scope.launch {
                                runCatching { withContext(Dispatchers.IO) { extras.movePhotos(selected, album.name) } }
                                selected = emptySet(); actionBusy = false; vm.refreshPhotos(); reloadAlbums()
                            }
                        }, modifier = Modifier.fillMaxWidth().padding(top = 6.dp)) { Text(album.name) }
                    }
                }
            },
            confirmButton = {},
            dismissButton = { TextButton(onClick = { moveDialog = false }) { Text("Cancel") } },
        )
    }

    if (confirmDelete) {
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            title = { Text("Delete ${selected.size} items?") },
            text = { Text("This permanently deletes the selected items from this profile's private photo library.") },
            confirmButton = {
                Button(enabled = !actionBusy, onClick = {
                    confirmDelete = false; actionBusy = true
                    scope.launch {
                        runCatching { withContext(Dispatchers.IO) { extras.deletePhotos(selected) } }
                        selected = emptySet(); actionBusy = false; vm.refreshPhotos(); reloadAlbums()
                    }
                }) { Text("Delete") }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("Cancel") } },
        )
    }

    if (actionBusy) {
        Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = .24f)), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
    }
}

@Composable
private fun PhotoPager(
    vm: NomadViewModel,
    items: List<GalleryItem>,
    initial: Int,
    onClose: () -> Unit,
    onVideo: (GalleryItem) -> Unit,
) {
    BackHandler(onBack = onClose)
    val pager = rememberPagerState(initialPage = initial.coerceIn(0, items.lastIndex)) { items.size }
    Box(Modifier.fillMaxSize().background(Color.Black)) {
        HorizontalPager(pager, Modifier.fillMaxSize()) { index ->
            val item = items[index]
            if (item.kind == "image") {
                RemoteImage(vm.api.galleryItemUrl(item.id), Modifier.fillMaxSize(), ContentScale.Fit, maxDecodePx = 2600)
            } else {
                Box(Modifier.fillMaxSize().combinedClickable(onClick = { onVideo(item) }, onLongClick = {}), contentAlignment = Alignment.Center) {
                    Icon(Icons.Filled.PlayArrow, "Play", Modifier.size(74.dp), tint = Color.White)
                }
            }
        }
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onClose) { Icon(Icons.Outlined.ArrowBack, "Close", tint = Color.White) }
            val item = items[pager.currentPage]
            Column(Modifier.weight(1f)) {
                Text(item.name, color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.Bold)
                Text("${pager.currentPage + 1} / ${items.size}", color = Color.LightGray, style = MaterialTheme.typography.labelSmall)
            }
        }
    }
}
