# Add project specific ProGuard rules here.
# Keep WebView classes
-keep class android.webkit.** { *; }
-keepclassmembers class * extends android.webkit.WebViewClient { *; }