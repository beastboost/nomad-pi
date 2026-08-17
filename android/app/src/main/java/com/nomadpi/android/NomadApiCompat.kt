package com.nomadpi.android

/** Compatibility helper retained while discovery is being iterated separately. */
fun NomadApi.imageUrl(path: String?): String? {
    if (path.isNullOrBlank()) return null
    if (path.startsWith("http://") || path.startsWith("https://")) return path
    return mediaStreamUrl(path)
}
