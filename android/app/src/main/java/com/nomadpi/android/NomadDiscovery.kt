package com.nomadpi.android

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import java.util.concurrent.ConcurrentHashMap

/**
 * Lightweight foreground DNS-SD discovery for the _http._tcp service Avahi
 * advertises from Nomad. Manual hostname/IP entry remains available if a
 * vendor Android build suppresses multicast discovery.
 */
class NomadDiscovery(private val context: Context) {
    private val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    private val seen = ConcurrentHashMap.newKeySet<String>()
    private var listener: NsdManager.DiscoveryListener? = null
    private var multicastLock: WifiManager.MulticastLock? = null

    fun start(onServer: (String, String) -> Unit, onError: (String) -> Unit = {}) {
        stop()
        seen.clear()
        try {
            val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
            multicastLock = wifi?.createMulticastLock("nomad-discovery")?.apply {
                setReferenceCounted(false)
                acquire()
            }
        } catch (_: Throwable) {
            multicastLock = null
        }

        val discovery = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) = Unit
            override fun onDiscoveryStopped(serviceType: String) = Unit
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                onError("Discovery could not start ($errorCode)")
                stop()
            }
            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) = Unit

            override fun onServiceLost(serviceInfo: NsdServiceInfo) = Unit

            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                val name = serviceInfo.serviceName.orEmpty()
                if (!name.contains("nomad", ignoreCase = true)) return
                if (!seen.add("$name:${serviceInfo.serviceType}")) return
                @Suppress("DEPRECATION")
                nsd.resolveService(serviceInfo, object : NsdManager.ResolveListener {
                    override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                        seen.remove("$name:${serviceInfo.serviceType}")
                    }

                    @Suppress("DEPRECATION")
                    override fun onServiceResolved(resolved: NsdServiceInfo) {
                        val host = resolved.host?.hostAddress ?: return
                        val port = resolved.port.takeIf { it > 0 } ?: 80
                        val hostForUrl = if (host.contains(':')) "[$host]" else host
                        val url = if (port == 80) "http://$hostForUrl" else "http://$hostForUrl:$port"
                        onServer(resolved.serviceName ?: "Nomad", url)
                    }
                })
            }
        }
        listener = discovery
        try {
            nsd.discoverServices("_http._tcp.", NsdManager.PROTOCOL_DNS_SD, discovery)
        } catch (t: Throwable) {
            onError(t.message ?: "Discovery failed")
            stop()
        }
    }

    fun stop() {
        listener?.let {
            try { nsd.stopServiceDiscovery(it) } catch (_: Throwable) {}
        }
        listener = null
        try {
            if (multicastLock?.isHeld == true) multicastLock?.release()
        } catch (_: Throwable) {}
        multicastLock = null
    }
}
