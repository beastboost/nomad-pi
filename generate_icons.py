import cairosvg
from PIL import Image
import io
import os

svg_path = 'app/static/icons/icon-512.svg'
output_dir = 'app/static/icons/'

def generate_icon(size, filename, padding=0, background=None):
    # Render SVG to PNG in memory
    # cairosvg.svg2png returns bytes
    png_data = cairosvg.svg2png(url=svg_path, output_width=size, output_height=size)
    img = Image.open(io.BytesIO(png_data))

    if padding > 0 or background:
        # Create a new image with background
        new_size = size
        inner_size = int(size * (1 - padding * 2))

        # Re-render SVG at inner_size
        png_data = cairosvg.svg2png(url=svg_path, output_width=inner_size, output_height=inner_size)
        inner_img = Image.open(io.BytesIO(png_data))

        bg_color = background if background else (0, 0, 0, 0)
        final_img = Image.new('RGBA', (new_size, new_size), bg_color)

        # Center the inner image
        offset = (size - inner_size) // 2
        final_img.paste(inner_img, (offset, offset), inner_img if inner_img.mode == 'RGBA' else None)
        img = final_img

    img.save(os.path.join(output_dir, filename))
    print(f"Generated {filename}")

# Theme color from manifest: #3b82f6 -> (59, 130, 246)
theme_color = (59, 130, 246, 255)

# Standard icons
generate_icon(192, 'icon-192.png')
generate_icon(512, 'icon-512.png')

# Maskable icons (add padding and background)
# 10% padding on each side ensures the icon stays in the safe zone
generate_icon(192, 'maskable-192.png', padding=0.15, background=theme_color)
generate_icon(512, 'maskable-512.png', padding=0.15, background=theme_color)

# Apple touch icon (typically 180x180, often with solid background)
generate_icon(180, 'apple-touch-icon.png', padding=0.1, background=theme_color)
