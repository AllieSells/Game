"""Separate module for boot screen rendering to match render_gpu_loading_bar pattern."""
import tcod.console


def render_boot_screen(renderer, boot_messages: list[str], window_w: int, window_h: int, console_renderer):
    """Render boot screen exactly like render_gpu_loading_bar."""
    W      = (200, 200, 200)
    DIM    = (100, 100, 100)
    BG     = (0,   0,   0  )
    BAR_BG = (0,   170, 170)
    BAR_FG = (0,   0,   0  )
    SEP    = (160, 160, 160)
    COLS   = 80
    ROWS   = 50
    
    con = tcod.console.Console(COLS, ROWS, order="F")
    con.draw_rect(0, 0, COLS, ROWS, ch=ord(' '), fg=W, bg=BG)
    
    con.draw_rect(0, 0, COLS, 1, ord(' '), fg=BAR_FG, bg=BAR_BG)
    con.print(0, 0, " DOA BIOS v18.23.00", fg=BAR_FG, bg=BAR_BG)
    cr = "(C) 1998 Loxen Inc. "
    con.print(COLS - len(cr), 0, cr, fg=BAR_FG, bg=BAR_BG)
    
    con.print(0, 1, chr(0x2550) * COLS, fg=SEP, bg=BG)
    
    con.print(2, 3, "Dungeons of Aerrok: The Divine Stone", fg=W, bg=BG)
    con.print(2, 4, "BIOS DATE 11/19/98 12:40:36  |  VER: 18.23.00", fg=DIM, bg=BG)
    con.print(2, 5, "CPU: Intel(R) 330 @ 40 MHz  |  SPEED: 40MHz", fg=DIM, bg=BG)
    
    con.print(0, 7, chr(0x2550) * COLS, fg=SEP, bg=BG)
    
    con.print(2, 9, "BOOT LOG:", fg=W, bg=BG)
    for i, msg in enumerate(boot_messages):
        row = 11 + i
        if row >= ROWS - 2:
            break
        con.print(4, row, msg, fg=W, bg=BG)
    
    cursor_row = 11 + len(boot_messages)
    if cursor_row < ROWS - 2:
        con.print(4, cursor_row, chr(0x2588), fg=W, bg=BG)
    
    con.draw_rect(0, ROWS - 1, COLS, 1, ord(' '), fg=BAR_FG, bg=BAR_BG)
    con.print(0, ROWS - 1, "  Loading...", fg=BAR_FG, bg=BAR_BG)
    
    tex = console_renderer.render(con)
    tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
    renderer.copy(tex, dest=(0, 0, window_w, window_h))


