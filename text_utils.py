"""Utility functions for colored text rendering with markup support."""
import re
import tcod
import color


def parse_colored_text(text: str, default_color=color.white) -> list:
    """
    Parse a string with color markup tags and return a list of (text, color) tuples.
    
    Markup format: <color_name>text</color_name> or <#rrggbb>text</#rrggbb>
    
    Supported color names: white, red, green, blue, yellow, cyan, magenta, 
                          gray, light_gray, dark_red, dark_green, dark_blue, etc.
    
    Args:
        text: String with color markup tags
        default_color: Default color for unmarked text
    
    Returns:
        List of (text, color) tuples
        
    Examples:
        parse_colored_text("Hello <red>world</red>!")
        parse_colored_text("<yellow>Gold coins:</yellow> <white>150</white>")
        parse_colored_text("Custom color: <#ff6600>orange text</#ff6600>")
    """
    # Color name mapping
    color_map = {
        'white': color.white,
        'black': color.black,
        'red': color.red,
        'green': color.green,
        'blue': color.blue,
        'yellow': color.yellow,
        'cyan': color.cyan,
        'magenta': color.magenta,
        'gray': color.gray,
        'grey': color.gray,
        'light_gray': color.light_gray,
        'light_grey': color.light_gray,
        'dark_red': color.dark_red,
        'dark_green': color.dark_green,
        'dark_blue': color.dark_blue,
        'orange': (255, 165, 0),
        'purple': (128, 0, 128),
        'brown': (139, 69, 19),
        'pink': (255, 192, 203),
        'lime': (0, 255, 0),
        'gold': (255, 215, 0),
        'silver': (192, 192, 192),
        'teal': (0, 128, 128),
    }
    
    parts = []
    
    # Regex pattern to match color tags
    # Matches both <color_name>text</color_name> and <#rrggbb>text</#rrggbb>
    pattern = r'<(#?[a-zA-Z0-9_#]+)>(.*?)</\1>'
    
    last_end = 0
    
    for match in re.finditer(pattern, text):
        # Add any text before this match with default color
        if match.start() > last_end:
            before_text = text[last_end:match.start()]
            if before_text:
                parts.append((before_text, default_color))
        
        color_spec = match.group(1)
        content = match.group(2)
        
        # Determine the color
        if color_spec.startswith('#'):
            # Hex color
            try:
                hex_color = color_spec[1:]  # Remove the #
                if len(hex_color) == 6:
                    r = int(hex_color[0:2], 16)
                    g = int(hex_color[2:4], 16)
                    b = int(hex_color[4:6], 16)
                    text_color = (r, g, b)
                else:
                    text_color = default_color  # Invalid hex
            except ValueError:
                text_color = default_color  # Invalid hex
        else:
            # Named color
            text_color = color_map.get(color_spec.lower(), default_color)
        
        parts.append((content, text_color))
        last_end = match.end()
    
    # Add any remaining text after the last match
    if last_end < len(text):
        remaining_text = text[last_end:]
        if remaining_text:
            parts.append((remaining_text, default_color))
    
    return parts


def print_colored_markup(console: tcod.Console, x: int, y: int, text: str, default_color=color.white) -> int:
    """
    Print text with color markup directly to console.
    
    Args:
        console: The tcod console to print to
        x: Starting x position
        y: Y position
        text: String with color markup tags
        default_color: Default color for unmarked text
    
    Returns:
        The final x position after all text is printed
        
    Example:
        print_colored_markup(console, 10, 5, "You found <yellow>gold coins</yellow>!")
    """
    parts = parse_colored_text(text, default_color)
    return print_colored_text(console, x, y, parts)


def print_colored_text(console: tcod.Console, x: int, y: int, text_parts: list) -> int:
    """
    Print text with multiple colors on the same line.
    
    Args:
        console: The tcod console to print to
        x: Starting x position
        y: Y position
        text_parts: List of tuples (text, color)
    
    Returns:
        The final x position after all text is printed
        
    Example:
        parts = [
            ("Hello ", color.white),
            ("World", color.blue),
            ("!", color.red)
        ]
        print_colored_text(console, 10, 5, parts)
    """
    current_x = x
    for text, text_color in text_parts:
        console.print(current_x, y, text, fg=text_color)
        current_x += len(text)
    return current_x


def wrap_colored_text(text: str, max_width: int, default_color=color.white) -> list:
    """
    Wrap colored markup text to fit within a specified width.
    
    Args:
        text: String with color markup tags
        max_width: Maximum width for each line
        default_color: Default color for unmarked text
    
    Returns:
        List of lists, where each inner list contains (text, color) tuples for one line
        
    Example:
        lines = wrap_colored_text("This is <red>very long</red> text that needs wrapping", 20)
        for line_parts in lines:
            print_colored_text(console, x, y, line_parts)
            y += 1
    """
    parts = parse_colored_text(text, default_color)
    lines = []
    current_line = []
    current_length = 0
    
    for text_part, text_color in parts:
        words = text_part.split(' ')
        
        for i, word in enumerate(words):
            # Add space before word (except for first word of the part)
            if i > 0:
                if current_length + 1 <= max_width:
                    current_line.append((' ', text_color))
                    current_length += 1
                else:
                    # Start new line
                    lines.append(current_line)
                    current_line = []
                    current_length = 0
            
            # Check if word fits on current line
            if current_length + len(word) <= max_width:
                current_line.append((word, text_color))
                current_length += len(word)
            else:
                # Word doesn't fit, start new line
                if current_line:  # If there's content on current line
                    lines.append(current_line)
                    current_line = []
                    current_length = 0
                
                # Handle very long words that exceed max_width
                while len(word) > max_width:
                    current_line.append((word[:max_width], text_color))
                    lines.append(current_line)
                    word = word[max_width:]
                    current_line = []
                    current_length = 0
                
                if word:  # Add remaining part of word
                    current_line.append((word, text_color))
                    current_length += len(word)
    
    if current_line:
        lines.append(current_line)
    
    return lines


def wrap_colored_text_to_strings(text: str, max_width: int, default_color=color.white) -> list:
    """
    Wrap colored markup text and return list of markup strings ready for print_colored_markup.
    
    This is a convenience function that wraps colored text and reconstructs the markup
    for each wrapped line, suitable for systems that expect markup strings.
    
    Args:
        text: String with color markup tags
        max_width: Maximum width for each line
        default_color: Default color for unmarked text
    
    Returns:
        List of strings with markup tags preserved for each wrapped line
    """
    wrapped_lines = wrap_colored_text(text, max_width, default_color)
    markup_lines = []
    
    for line_parts in wrapped_lines:
        line_markup = ""
        current_color = None
        
        for text_part, text_color in line_parts:
            # If color changed, close previous tag and open new one
            if text_color != current_color:
                if current_color is not None:
                    # Close previous color tag
                    line_markup += f"</{get_color_name(current_color)}>"
                
                if text_color != default_color:
                    # Open new color tag
                    line_markup += f"<{get_color_name(text_color)}>"
                
                current_color = text_color
            
            line_markup += text_part
        
        # Close final color tag if needed
        if current_color is not None and current_color != default_color:
            line_markup += f"</{get_color_name(current_color)}>"
        
        markup_lines.append(line_markup)
    
    return markup_lines


def get_color_name(color_tuple):
    """Get color name from RGB tuple, fallback to hex if not found."""
    # Reverse lookup in color mapping
    color_map = {
        'white': color.white,
        'black': color.black,
        'red': color.red,
        'green': color.green,
        'blue': color.blue,
        'yellow': color.yellow,
        'cyan': color.cyan,
        'magenta': color.magenta,
        'gray': color.gray,
        'grey': color.gray,
        'light_gray': color.light_gray,
        'light_grey': color.light_gray,
        'dark_red': color.dark_red,
        'dark_green': color.dark_green,
        'dark_blue': color.dark_blue,
        'orange': (255, 165, 0),
        'purple': (128, 0, 128),
        'brown': (139, 69, 19),
        'pink': (255, 192, 203),
        'lime': (0, 255, 0),
        'gold': (255, 215, 0),
        'silver': (192, 192, 192),
        'teal': (0, 128, 128),
    }
    
    for name, rgb in color_map.items():
        if rgb == color_tuple:
            return name
    
    # Fallback to hex
    r, g, b = color_tuple
    return f"#{r:02x}{g:02x}{b:02x}"


# Convenience functions for common use cases
def format_health_bar(current: int, maximum: int) -> str:
    """Create colored health bar markup string."""
    if current <= 0:
        health_color = "dark_red"
    elif current <= maximum // 4:
        health_color = "red"
    elif current <= maximum // 2:
        health_color = "yellow"
    else:
        health_color = "green"
    
    return f"HP: <{health_color}>{current}</> / <light_gray>{maximum}</>"


def format_dialogue(speaker: str, message: str, speaker_color="cyan") -> str:
    """Format dialogue with colored speaker name."""
    return f'<{speaker_color}>{speaker}</>: "{message}"'


def format_item_description(item_name: str, description: str, item_color="yellow") -> str:
    """Format item with colored name."""
    return f'<{item_color}>{item_name}</> - <light_gray>{description}</>'


def format_damage(amount: int) -> str:
    """Format damage with appropriate color."""
    if amount <= 0:
        return f"<gray>0</>"
    elif amount <= 5:
        return f"<yellow>{amount}</>"
    elif amount <= 10:
        return f"<orange>{amount}</>"
    else:
        return f"<red>{amount}</>"


def format_currency(amount: int, currency_type="gold") -> str:
    """Format currency with appropriate color."""
    colors = {
        "gold": "gold",
        "silver": "silver", 
        "copper": "#cd7f32",  # Bronze color
        "gems": "magenta"
    }
    color_name = colors.get(currency_type, "yellow")
    return f"<{color_name}>{amount} {currency_type}</>"


# Enhanced convenience functions for dynamic text building

def red(text: str) -> str:
    """Wrap text in red color tags."""
    return f"<red>{text}</red>"

def green(text: str) -> str:
    """Wrap text in green color tags.""" 
    return f"<green>{text}</green>"

def blue(text: str) -> str:
    """Wrap text in blue color tags."""
    return f"<blue>{text}</blue>"

def yellow(text: str) -> str:
    """Wrap text in yellow color tags."""
    return f"<yellow>{text}</yellow>"

def white(text: str) -> str:
    """Wrap text in white color tags."""
    return f"<white>{text}</white>"

def gray(text: str) -> str:
    """Wrap text in gray color tags."""
    return f"<gray>{text}</gray>"

def cyan(text: str) -> str:
    """Wrap text in cyan color tags."""
    return f"<cyan>{text}</cyan>"

def magenta(text: str) -> str:
    """Wrap text in magenta color tags."""
    return f"<magenta>{text}</magenta>"

def orange(text: str) -> str:
    """Wrap text in orange color tags."""
    return f"<orange>{text}</orange>"

def purple(text: str) -> str:
    """Wrap text in purple color tags."""
    return f"<purple>{text}</purple>"

def cyan(text: str) -> str:
    """Wrap text in cyan color tags."""
    return f"<cyan>{text}</cyan>"

def build_colored_text(*args) -> str:
    """Build colored text from multiple parts.
    
    Takes any number of arguments which can be:
    - Plain strings (no color)
    - Tuples of (text, color_name) 
    - Already colored text (with tags)
    
    Examples:
        build_colored_text("Hello ", ("world", "red"), "!")
        # Returns: "Hello <red>world</red>!"
        
        build_colored_text(("Player", "green"), " attacks ", ("Orc", "red"))
        # Returns: "<green>Player</green> attacks <red>Orc</red>"
    """
    result = []
    
    for arg in args:
        if isinstance(arg, tuple) and len(arg) == 2:
            text, color_name = arg
            result.append(f"<{color_name}>{text}</{color_name}>")
        elif isinstance(arg, str):
            result.append(arg)
        else:
            # Convert to string if it's something else
            result.append(str(arg))
    
    return "".join(result)

def colorize(text: str, color_name: str) -> str:
    """Wrap text in the specified color tags.
    
    Args:
        text: The text to colorize
        color_name: Color name (red, green, blue, etc.) or hex code (#ff0000)
    
    Example:
        colorize("Hello", "red") -> "<red>Hello</red>"
        colorize("World", "#00ff00") -> "<#00ff00>World</#00ff00>"
    """
    return f"<{color_name}>{text}</{color_name}>"

def join_colored(*parts, separator: str = "") -> str:
    """Join multiple colored text parts with a separator.
    
    Args:
        *parts: Text parts (strings, tuples of (text, color), or pre-colored text)
        separator: String to insert between parts
        
    Example:
        join_colored(("Player", "green"), ("attacks", "yellow"), ("Orc", "red"), separator=" ")
        # Returns: "<green>Player</green> <yellow>attacks</yellow> <red>Orc</red>"
    """
    colored_parts = []
    
    for part in parts:
        if isinstance(part, tuple) and len(part) == 2:
            text, color_name = part
            colored_parts.append(f"<{color_name}>{text}</{color_name}>")
        elif isinstance(part, str):
            colored_parts.append(part)
        else:
            colored_parts.append(str(part))
    
    return separator.join(colored_parts)
