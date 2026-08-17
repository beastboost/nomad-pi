package com.nomadpi.android

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.first

private val Context.nomadDataStore by preferencesDataStore(name = "nomad_native")

data class SavedConnection(
    val server: String,
    val token: String,
    val username: String,
    val isAdmin: Boolean,
    val profileId: Int?,
)

class NomadStore(context: Context) {
    private val store = context.applicationContext.nomadDataStore

    private object Keys {
        val server = stringPreferencesKey("server")
        val token = stringPreferencesKey("token")
        val username = stringPreferencesKey("username")
        val admin = booleanPreferencesKey("admin")
        val profile = intPreferencesKey("profile")
    }

    suspend fun load(): SavedConnection? {
        val prefs = store.data.first()
        val server = prefs[Keys.server]?.takeIf { it.isNotBlank() } ?: return null
        val token = prefs[Keys.token]?.takeIf { it.isNotBlank() } ?: return null
        return SavedConnection(
            server = server,
            token = token,
            username = prefs[Keys.username].orEmpty(),
            isAdmin = prefs[Keys.admin] ?: false,
            profileId = prefs[Keys.profile],
        )
    }

    suspend fun save(session: NomadSession, profileId: Int? = null) {
        store.edit { prefs ->
            prefs[Keys.server] = session.server
            prefs[Keys.token] = session.token
            prefs[Keys.username] = session.username
            prefs[Keys.admin] = session.isAdmin
            if (profileId != null) prefs[Keys.profile] = profileId else prefs.remove(Keys.profile)
        }
    }

    suspend fun updateProfile(profileId: Int?) {
        store.edit { prefs ->
            if (profileId != null) prefs[Keys.profile] = profileId else prefs.remove(Keys.profile)
        }
    }

    suspend fun clear() {
        store.edit { it.clear() }
    }
}
