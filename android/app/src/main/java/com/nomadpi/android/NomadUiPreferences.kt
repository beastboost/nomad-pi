package com.nomadpi.android

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.first

private val Context.nomadUiDataStore by preferencesDataStore(name = "nomad_native_ui")

data class NomadUiSettings(
    val fullscreenVideo: Boolean = true,
    val autoLandscapeVideo: Boolean = true,
    val keepScreenAwake: Boolean = true,
    val videoResize: String = "fit",
)

class NomadUiPreferences(context: Context) {
    private val store = context.applicationContext.nomadUiDataStore

    private object Keys {
        val fullscreenVideo = booleanPreferencesKey("fullscreen_video")
        val autoLandscapeVideo = booleanPreferencesKey("auto_landscape_video")
        val keepScreenAwake = booleanPreferencesKey("keep_screen_awake")
        val videoResize = stringPreferencesKey("video_resize")
    }

    suspend fun load(): NomadUiSettings {
        val prefs = store.data.first()
        return NomadUiSettings(
            fullscreenVideo = prefs[Keys.fullscreenVideo] ?: true,
            autoLandscapeVideo = prefs[Keys.autoLandscapeVideo] ?: true,
            keepScreenAwake = prefs[Keys.keepScreenAwake] ?: true,
            videoResize = prefs[Keys.videoResize]?.takeIf { it in setOf("fit", "fill", "zoom") } ?: "fit",
        )
    }

    suspend fun save(value: NomadUiSettings) {
        store.edit { prefs ->
            prefs[Keys.fullscreenVideo] = value.fullscreenVideo
            prefs[Keys.autoLandscapeVideo] = value.autoLandscapeVideo
            prefs[Keys.keepScreenAwake] = value.keepScreenAwake
            prefs[Keys.videoResize] = value.videoResize
        }
    }
}
