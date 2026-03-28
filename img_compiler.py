from PIL import Image, ImageDraw, ImageFilter

def generate_classic_crt_overlay(
    width, height,
    scanline_thickness=1, scanline_gap=2, scanline_alpha=64,
    vignette_strength=0.5,
    filename="crt_overlay.png"
):
    """
    Generate a classic CRT overlay PNG with:
    - Horizontal scanlines
    - Soft vignette (bevel/darkening at edges)
    - No colored grille
    """
    # Create transparent base
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Draw scanlines
    y = 0
    while y < height:
        draw.rectangle([0, y, width, y + scanline_thickness - 1], fill=(0, 0, 0, scanline_alpha))
        y += scanline_thickness + scanline_gap
    # Create vignette mask
    vignette = Image.new("L", (width, height), 0)
    vign_draw = ImageDraw.Draw(vignette)
    vign_draw.ellipse(
        [int(width * 0.08), int(height * 0.08), int(width * 0.92), int(height * 0.92)],
        fill=int(255 * (1 - vignette_strength)), outline=0
    )
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=min(width, height) // 10))
    # Invert vignette for edge darkening
    vignette = Image.eval(vignette, lambda px: 255 - px)
    # Apply vignette as alpha mask
    r, g, b, a = img.split()
    a = Image.composite(a, vignette, vignette)
    img = Image.merge("RGBA", (r, g, b, a))
    img.save(filename)
    print(f"Saved: {filename}")

# Example usage:
generate_classic_crt_overlay(
    width=800, height=600,
    scanline_thickness=1, scanline_gap=2, scanline_alpha=64,
    vignette_strength=0.5,
    filename="crt_overlay.png"
)