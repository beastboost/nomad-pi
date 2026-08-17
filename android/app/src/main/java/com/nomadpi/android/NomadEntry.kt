package com.nomadpi.android

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ArrowBack
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.Lan
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Wifi
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

@Composable
fun NomadRoot(vm: NomadViewModel) {
    if (vm.entry == EntryScreen.APP) {
        NomadApp(vm)
        return
    }

    val snackbar = remember { SnackbarHostState() }
    val message = vm.message
    LaunchedEffect(message) {
        if (!message.isNullOrBlank()) {
            snackbar.showSnackbar(message)
            vm.clearMessage()
        }
    }

    androidx.compose.foundation.layout.Box(Modifier.fillMaxSize()) {
        when (vm.entry) {
            EntryScreen.LOADING -> PolishedLoadingScreen()
            EntryScreen.CONNECT -> PolishedConnectScreen(vm)
            EntryScreen.LOGIN -> PolishedLoginScreen(vm)
            EntryScreen.APP -> Unit
        }
        SnackbarHost(
            hostState = snackbar,
            modifier = Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(16.dp),
        )
    }
}

@Composable
private fun PolishedLoadingScreen() {
    Column(
        modifier = Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(28.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        BrandBlock(centered = true)
        Spacer(Modifier.height(28.dp))
        CircularProgressIndicator()
        Text(
            "Starting Nomad…",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 14.dp),
        )
    }
}

@Composable
private fun BrandBlock(centered: Boolean = false) {
    Column(horizontalAlignment = if (centered) Alignment.CenterHorizontally else Alignment.Start) {
        Text(
            "NOMAD",
            style = MaterialTheme.typography.headlineLarge,
            color = MaterialTheme.colorScheme.onBackground,
            fontWeight = FontWeight.Black,
        )
        Text(
            "native for Android",
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.primary,
        )
    }
}

@Composable
private fun PolishedConnectScreen(vm: NomadViewModel) {
    var manual by remember(vm.server) { mutableStateOf(vm.server) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .navigationBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 22.dp, vertical = 24.dp),
    ) {
        BrandBlock()
        Spacer(Modifier.height(34.dp))

        Text(
            "Connect to Nomad",
            style = MaterialTheme.typography.headlineSmall,
            color = MaterialTheme.colorScheme.onBackground,
        )
        Text(
            "Find your server automatically on Wi‑Fi, or enter its address manually.",
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 8.dp, bottom = 22.dp),
        )

        Card(
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surface,
                contentColor = MaterialTheme.colorScheme.onSurface,
            ),
        ) {
            Column(Modifier.fillMaxWidth().padding(16.dp)) {
                OutlinedTextField(
                    value = manual,
                    onValueChange = { manual = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("Server address") },
                    supportingText = { Text("Example: 192.168.1.42:8000") },
                    leadingIcon = { Icon(Icons.Outlined.Lan, null) },
                    singleLine = true,
                )
                Button(
                    onClick = { vm.selectServer(manual) },
                    modifier = Modifier.fillMaxWidth().padding(top = 12.dp).height(54.dp),
                ) {
                    Text("Continue")
                }

                Row(
                    Modifier.fillMaxWidth().padding(top = 10.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    OutlinedButton(
                        onClick = { manual = "http://nomadpi.local" },
                        modifier = Modifier.weight(1f),
                    ) { Text("Local name", maxLines = 1) }
                    OutlinedButton(
                        onClick = { manual = "http://10.42.0.1" },
                        modifier = Modifier.weight(1f),
                    ) { Text("Hotspot", maxLines = 1) }
                }
            }
        }

        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 28.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    "Nearby servers",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    "Verified Nomad servers on this network",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            TextButton(onClick = { vm.startDiscovery() }) {
                Icon(Icons.Outlined.Refresh, null)
                Text("Scan", modifier = Modifier.padding(start = 5.dp))
            }
        }

        if (vm.discovering && vm.discovered.isEmpty()) {
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant,
                    contentColor = MaterialTheme.colorScheme.onSurface,
                ),
            ) {
                Row(
                    Modifier.fillMaxWidth().padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp)
                    Column(Modifier.padding(start = 12.dp)) {
                        Text("Scanning your network", fontWeight = FontWeight.SemiBold)
                        Text("Looking for Nomad…", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }

        vm.discovered.forEach { found ->
            Card(
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp).clickable { vm.selectServer(found.url) },
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant,
                    contentColor = MaterialTheme.colorScheme.onSurface,
                ),
            ) {
                Row(
                    Modifier.fillMaxWidth().padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Outlined.Wifi, null, tint = MaterialTheme.colorScheme.primary)
                    Column(Modifier.padding(start = 12.dp).weight(1f)) {
                        Text(found.name, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(
                            found.url,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                    Text("Connect", color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.SemiBold)
                }
            }
        }

        if (!vm.discovering && vm.discovered.isEmpty()) {
            Card(
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant,
                    contentColor = MaterialTheme.colorScheme.onSurface,
                ),
            ) {
                Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Outlined.Dns, null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    Column(Modifier.padding(start = 12.dp)) {
                        Text("No verified server found yet", fontWeight = FontWeight.SemiBold)
                        Text("Tap Scan, or enter the Pi's IPv4 address above.", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
    }
}

@Composable
private fun PolishedLoginScreen(vm: NomadViewModel) {
    var username by remember { mutableStateOf("admin") }
    var password by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .navigationBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 22.dp, vertical = 18.dp),
    ) {
        IconButton(onClick = { vm.backToConnect() }) {
            Icon(Icons.Outlined.ArrowBack, "Back", tint = MaterialTheme.colorScheme.onSurface)
        }

        Spacer(Modifier.height(10.dp))
        BrandBlock()
        Spacer(Modifier.height(32.dp))

        Text(
            "Sign in",
            style = MaterialTheme.typography.headlineSmall,
            color = MaterialTheme.colorScheme.onBackground,
        )
        Text(
            "Use your Nomad account to access this server.",
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 7.dp, bottom = 18.dp),
        )

        Card(
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surfaceVariant,
                contentColor = MaterialTheme.colorScheme.onSurface,
            ),
        ) {
            Row(Modifier.fillMaxWidth().padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Outlined.Lan, null, tint = MaterialTheme.colorScheme.primary)
                Column(Modifier.padding(start = 11.dp).weight(1f)) {
                    Text("Server", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(vm.server, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
            }
        }

        HorizontalDivider(Modifier.padding(vertical = 20.dp), color = MaterialTheme.colorScheme.outlineVariant)

        OutlinedTextField(
            value = username,
            onValueChange = { username = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Username") },
            leadingIcon = { Icon(Icons.Outlined.Person, null) },
            singleLine = true,
        )
        OutlinedTextField(
            value = password,
            onValueChange = { password = it },
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
            label = { Text("Password") },
            leadingIcon = { Icon(Icons.Outlined.Lock, null) },
            visualTransformation = PasswordVisualTransformation(),
            singleLine = true,
        )
        Button(
            enabled = !vm.busy && password.isNotBlank(),
            onClick = { vm.login(username, password) },
            modifier = Modifier.fillMaxWidth().padding(top = 18.dp).height(54.dp),
        ) {
            if (vm.busy) {
                CircularProgressIndicator(Modifier.size(21.dp), strokeWidth = 2.dp)
            } else {
                Text("Sign in")
            }
        }
    }
}
