import os

# Directory containing the PNG files
directory = './RP/background/'

for filename in os.listdir(directory):
    if filename.endswith('.png') and '-' in filename:
        # Example: frame_001-12.png -> frame_001.png
        new_filename = filename.split('-')[0] + '.png'
        os.rename(os.path.join(directory, filename), os.path.join(directory, new_filename))
        print(f'Renamed: {filename} -> {new_filename}')