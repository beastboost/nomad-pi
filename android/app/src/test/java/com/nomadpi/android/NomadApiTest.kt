package com.nomadpi.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class NomadApiTest {
    @Test
    fun normalizeServerKeepsNomadLocalCanonical() {
        assertEquals("http://nomadpi.local", NomadApi.normalizeServer("nomadpi.local"))
        assertEquals("http://10.42.0.1", NomadApi.normalizeServer("10.42.0.1/"))
        assertEquals("https://nomad.example", NomadApi.normalizeServer("https://nomad.example/"))
    }

    @Test
    fun androidCapabilitiesDoNotInventVideoCodecs() {
        val caps = AndroidCapabilities(emptyList(), emptyList(), listOf("aac"), emptyList())
        assertFalse(caps.videoCodecs.contains("h264"))
        assertEquals("aac", caps.audioCodecs.single())
    }
}
