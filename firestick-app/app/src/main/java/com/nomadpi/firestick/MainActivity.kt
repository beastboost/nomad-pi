package com.nomadpi.firestick

import android.annotation.SuppressLint
import android.content.Context
import android.content.SharedPreferences
import android.os.Build
import android.os.Bundle
import android.view.KeyEvent
import android.view.View
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import java.io.BufferedReader
import java.io.InputStreamReader

class MainActivity : AppCompatActivity() {
    private lateinit var webView: WebView
    private lateinit var container: FrameLayout
    private val PREFS_NAME = "nomadpi_prefs"
    private val KEY_SERVER_URL = "server_url"
    private var serverUrl: String = "http://localhost:8080" // Default URL

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        // Load server URL from preferences
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        serverUrl = prefs.getString(KEY_SERVER_URL, "http://localhost:8080") ?: "http://localhost:8080"
        
        // Create fullscreen WebView container
        container = FrameLayout(this)
        container.setBackgroundColor(0xFF000000.toInt()) // Black background
        setContentView(container)
        
        // Create WebView
        webView = WebView(this)
        container.addView(webView)
        
        // Configure WebView
        val webSettings = webView.settings
        webSettings.javaScriptEnabled = true
        webSettings.domStorageEnabled = true
        webSettings.databaseEnabled = true
        webSettings.setAppCacheEnabled(true)
        webSettings.cacheMode = WebSettings.LOAD_DEFAULT
        webSettings.loadWithOverviewMode = true
        webSettings.useWideViewPort = true
        webSettings.allowFileAccess = true
        webSettings.allowContentAccess = true
        webSettings.mediaPlaybackRequiresUserGesture = false // Allow autoplay
        
        // Enable remote debugging for debugging
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.KITKAT) {
            WebView.setWebContentsDebuggingEnabled(true)
        }
        
        // Handle page loading
        webView.webChromeClient = WebChromeClient()
        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                // Inject CSS to hide browser chrome on Firestick for immersive experience
                injectFullscreenCSS()
            }
        }
        
        // Load URL (or show setup first time)
        if (serverUrl.isEmpty() || serverUrl == "http://localhost:8080") {
            showSetupDialog()
        } else {
            webView.loadUrl(serverUrl)
        }
        
        // Long press remote menu button shows options
        webView.setOnKeyListener { _, keyCode, event ->
            if (keyCode == KeyEvent.KEYCODE_MENU) {
                showOptionsMenu()
                true
            } else {
                false
            }
        }
    }

    private fun injectFullscreenCSS() {
        // Inject CSS to make experience more app-like
        webView.evaluateJavascript(
            """
            (function() {
                var style = document.createElement('style');
                style.textContent = `
                    body { overflow: hidden; }
                    ::-webkit-scrollbar { display: none; }
                    .hidden { display: none !important; }
                `;
                document.head.appendChild(style);
            })();
            """.trimIndent(), null
        )
    }

    private fun showSetupDialog() {
        val input = android.widget.EditText(this)
        input.hint = "Enter Nomad Pi URL (e.g., http://192.168.1.100:8080)"
        input.inputType = android.text.InputType.TYPE_TEXT_VARIATION_URI
        
        AlertDialog.Builder(this)
            .setTitle("Setup Nomad Pi")
            .setMessage("Enter your Nomad Pi server URL:")
            .setView(input)
            .setPositiveButton("Connect") { _, _ ->
                val url = input.text.toString().trim()
                if (url.isNotEmpty()) {
                    saveServerUrl(url)
                    webView.loadUrl(url)
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showOptionsMenu() {
        val options = arrayOf("Change Server URL", "Reload", "Clear Cache", "Exit")
        AlertDialog.Builder(this)
            .setTitle("Nomad Pi Options")
            .setItems(options) { _, which ->
                when (which) {
                    0 -> showSetupDialog()
                    1 -> webView.reload()
                    2 -> {
                        webView.clearCache(true)
                        android.widget.Toast.makeText(this, "Cache cleared", android.widget.Toast.LENGTH_SHORT).show()
                    }
                    3 -> finish()
                }
            }
            .show()
    }

    private fun saveServerUrl(url: String) {
        serverUrl = url
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putString(KEY_SERVER_URL, url).apply()
    }

    override fun onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack()
        } else {
            super.onBackPressed()
        }
    }

    override fun onPause() {
        webView.onPause()
        super.onPause()
    }

    override fun onResume() {
        webView.onResume()
        super.onResume()
    }
}