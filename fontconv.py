from PIL import Image, ImageDraw, ImageFont

font = ImageFont.truetype("Ac437_Wyse700b_2y.ttf", 16)

cols, rows = 16, 16
tile_size = 16

# BLACK background now
img = Image.new("RGB", (cols*tile_size, rows*tile_size), (0,0,0))
draw = ImageDraw.Draw(img)

# 🔥 THIS is the important part
cp437_bytes = bytes(range(256)).decode("cp437")

for i, ch in enumerate(cp437_bytes):
    x = (i % cols) * tile_size
    y = (i // cols) * tile_size
    draw.text((x, y), ch, font=font, fill=(255,255,255))

img.save("wyse_cp437_16x16.png")