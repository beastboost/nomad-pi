package com.nomadpi.android

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Surface
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Nomad's native Android visual system.
 *
 * Keep every Material colour role explicit.  The early prototype painted a
 * dark Box without providing a matching LocalContentColor, which allowed
 * default black text/icons to appear on the dark background on some Material
 * components.  The root Surface below guarantees readable content everywhere.
 */
private val NomadDarkColors = darkColorScheme(
    primary = Color(0xFFA9C7FF),
    onPrimary = Color(0xFF062F63),
    primaryContainer = Color(0xFF173C69),
    onPrimaryContainer = Color(0xFFD6E4FF),

    secondary = Color(0xFFBBC7DC),
    onSecondary = Color(0xFF253141),
    secondaryContainer = Color(0xFF313D4E),
    onSecondaryContainer = Color(0xFFD7E3F8),

    tertiary = Color(0xFF9DDCC0),
    onTertiary = Color(0xFF063827),
    tertiaryContainer = Color(0xFF174F3B),
    onTertiaryContainer = Color(0xFFB9F8DB),

    background = Color(0xFF090B0F),
    onBackground = Color(0xFFF1F3F7),
    surface = Color(0xFF101318),
    onSurface = Color(0xFFF1F3F7),
    surfaceVariant = Color(0xFF1A1F27),
    onSurfaceVariant = Color(0xFFC3C8D1),

    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
    errorContainer = Color(0xFF93000A),
    onErrorContainer = Color(0xFFFFDAD6),

    outline = Color(0xFF8D929B),
    outlineVariant = Color(0xFF43474F),
    inverseSurface = Color(0xFFE2E2E8),
    inverseOnSurface = Color(0xFF2F3035),
    inversePrimary = Color(0xFF315F93),
    scrim = Color.Black,
)

private val NomadTypography = Typography(
    headlineLarge = TextStyle(
        color = NomadDarkColors.onBackground,
        fontWeight = FontWeight.Black,
        fontSize = 36.sp,
        lineHeight = 42.sp,
        letterSpacing = (-0.6).sp,
    ),
    headlineSmall = TextStyle(
        color = NomadDarkColors.onBackground,
        fontWeight = FontWeight.Bold,
        fontSize = 26.sp,
        lineHeight = 32.sp,
        letterSpacing = (-0.2).sp,
    ),
    titleLarge = TextStyle(
        color = NomadDarkColors.onSurface,
        fontWeight = FontWeight.Bold,
        fontSize = 22.sp,
        lineHeight = 28.sp,
    ),
    titleMedium = TextStyle(
        color = NomadDarkColors.onSurface,
        fontWeight = FontWeight.SemiBold,
        fontSize = 17.sp,
        lineHeight = 24.sp,
    ),
    bodyLarge = TextStyle(
        color = NomadDarkColors.onSurface,
        fontSize = 17.sp,
        lineHeight = 25.sp,
    ),
    bodyMedium = TextStyle(
        color = NomadDarkColors.onSurface,
        fontSize = 15.sp,
        lineHeight = 22.sp,
    ),
    bodySmall = TextStyle(
        color = NomadDarkColors.onSurfaceVariant,
        fontSize = 13.sp,
        lineHeight = 18.sp,
    ),
    labelLarge = TextStyle(
        color = NomadDarkColors.onSurface,
        fontWeight = FontWeight.SemiBold,
        fontSize = 15.sp,
        lineHeight = 20.sp,
    ),
    labelMedium = TextStyle(
        color = NomadDarkColors.onSurfaceVariant,
        fontWeight = FontWeight.Medium,
        fontSize = 13.sp,
        lineHeight = 18.sp,
    ),
    labelSmall = TextStyle(
        color = NomadDarkColors.onSurfaceVariant,
        fontWeight = FontWeight.Medium,
        fontSize = 11.sp,
        lineHeight = 16.sp,
    ),
)

private val NomadShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(18.dp),
    large = RoundedCornerShape(24.dp),
    extraLarge = RoundedCornerShape(30.dp),
)

@Composable
fun NomadDesign(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = NomadDarkColors,
        typography = NomadTypography,
        shapes = NomadShapes,
    ) {
        Surface(
            modifier = Modifier.fillMaxSize(),
            color = NomadDarkColors.background,
            contentColor = NomadDarkColors.onBackground,
        ) {
            content()
        }
    }
}
