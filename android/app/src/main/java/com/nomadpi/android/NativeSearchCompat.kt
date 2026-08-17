package com.nomadpi.android

import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

@Composable
fun NativeUniversalSearch(api: NomadApi, modifier: Modifier) {
    Box(modifier) { NativeUniversalSearch(api) }
}
