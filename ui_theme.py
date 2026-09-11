#!/usr/bin/env python
# coding: utf-8
"""Shared visual system for the Modern and SmallTool desktop apps."""


# A restrained graphite / warm-paper palette with one vermilion brand accent.
# CustomTkinter resolves every (light, dark) tuple automatically.
ACCENT = ('#E63946', '#FF4D6D')
ACCENT_HOVER = ('#D62839', '#E63956')
ACCENT_DIM = ('#FCE8EA', '#33161C')

SUCCESS = ('#2F7D4E', '#4FBA78')
SUCCESS_DIM = ('#E6F1EA', '#15261B')
WARNING = ('#A76812', '#DEA23C')
WARNING_DIM = ('#F7EEDC', '#2A2112')
ERROR_C = ('#E63946', '#FF4D6D')
ERROR_DIM = ('#FCE8EA', '#33161C')

BG_DARK = ('#F5F3EF', '#0D0D11')
BG_CARD = ('#FFFFFF', '#16161B')
BG_CARD_HOVER = ('#F0EEEA', '#22222A')
BG_INPUT = ('#FAF9F7', '#1A1A20')
BG_HEADER = ('#FBFAF8', '#111115')
BG_SECTION = ('#EEEAE5', '#111115')
BG_SIDEBAR = ('#EFEBE6', '#0E0E12')
BG_BADGE = ('#ECE9E4', '#22222A')
BG_OVERLAY = ('#959CAE', '#222432')

TEXT_PRI = ('#1B1817', '#F5F2EF')
TEXT_SEC = ('#68615D', '#B7B0AB')
TEXT_DIM = ('#958E87', '#817A77')
TEXT_LINK = ('#E63946', '#FF4D6D')

BORDER = ('#E1DDD7', '#25252C')
BORDER_HOVER = ('#CEC8C0', '#3A3944')
BORDER_CARD = ('#E6E1DA', '#22222A')
WINDOW_BORDER = ('#D0CCC4', '#3E3D4B')
WINDOW_SHADOW = ('#EAE6DF', '#1C1B24')

WHITE = ('#FFFFFF', '#FFFFFF')
CARD_RADIUS = 10
CONTROL_RADIUS = 8


def color_for_mode(token, mode='dark'):
    """Resolve a CustomTkinter color tuple for plain Tk fallback widgets."""
    if not isinstance(token, (tuple, list)):
        return token
    return token[0 if str(mode).lower() == 'light' else 1]


def browse_columns_for_width(width):
    """Readable browse-card density for the root window width."""
    width = max(0, int(width or 0))
    if width >= 1500:
        return 4
    if width >= 980:
        return 3
    if width >= 480:
        return 2
    return 1


def category_columns_for_width(width):
    """SmallTool category density without clipping long localized labels."""
    return 3 if int(width or 0) >= 1120 else 2


def patch_ctk_scrollable_frame_autohide():
    """Patches CTkScrollableFrame to auto-hide its scrollbar when content fits without scrolling."""
    try:
        import customtkinter as ctk
    except ImportError:
        return

    if getattr(ctk.CTkScrollableFrame, '_autohide_patched', False):
        return

    _orig_init = ctk.CTkScrollableFrame.__init__

    def _patched_init(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        if getattr(self, '_orientation', 'vertical') == 'horizontal':
            def _auto_xset(first, last):
                try:
                    f, l = float(first), float(last)
                    if f <= 0.001 and l >= 0.999:
                        if self._scrollbar.winfo_ismapped():
                            self._scrollbar.grid_remove()
                    else:
                        if not self._scrollbar.winfo_ismapped():
                            self._scrollbar.grid()
                except Exception:
                    pass
                self._scrollbar.set(first, last)
            self._parent_canvas.configure(xscrollcommand=_auto_xset)
        else:
            def _auto_yset(first, last):
                try:
                    f, l = float(first), float(last)
                    if f <= 0.001 and l >= 0.999:
                        if self._scrollbar.winfo_ismapped():
                            self._scrollbar.grid_remove()
                    else:
                        if not self._scrollbar.winfo_ismapped():
                            self._scrollbar.grid()
                except Exception:
                    pass
                self._scrollbar.set(first, last)
            self._parent_canvas.configure(yscrollcommand=_auto_yset)

    ctk.CTkScrollableFrame.__init__ = _patched_init
    ctk.CTkScrollableFrame._autohide_patched = True


patch_ctk_scrollable_frame_autohide()


def patch_ctk_option_menu_theme():
    """Unifies all CTkOptionMenu dropdowns across the software to follow the sleek home page dropdown style."""
    try:
        import tkinter as tk
        import customtkinter as ctk
        import customtkinter.windows.widgets.core_rendering.draw_engine as _draw_engine_mod
    except ImportError:
        return

    if getattr(ctk.CTkOptionMenu, '_theme_patched', False):
        return

    def _custom_draw_dropdown_arrow(self, x_position, y_position, size):
        x_position, y_position, size = round(x_position), round(y_position), round(size)
        requires_recoloring = False
        if not self._canvas.find_withtag('dropdown_arrow'):
            self._canvas.create_line(0, 0, 0, 0, tags='dropdown_arrow', width=max(2, round(size / 5)), joinstyle=tk.ROUND, capstyle=tk.ROUND)
            self._canvas.tag_raise('dropdown_arrow')
            requires_recoloring = True
        w = size * 0.42
        h = size * 0.22
        self._canvas.coords('dropdown_arrow',
                            x_position - w, y_position - h,
                            x_position, y_position + h,
                            x_position + w, y_position - h)
        return requires_recoloring

    _draw_engine_mod.DrawEngine.draw_dropdown_arrow = _custom_draw_dropdown_arrow

    def _custom_om_draw(self, no_color_updates=False):
        ctk.CTkBaseClass._draw(self, no_color_updates)
        left_section_width = self._current_width - self._current_height
        bw = getattr(self, '_border_width', 1)
        bc = getattr(self, '_border_color', BORDER)

        requires_recoloring = self._draw_engine.draw_rounded_rect_with_border_vertical_split(
            self._apply_widget_scaling(self._current_width),
            self._apply_widget_scaling(self._current_height),
            self._apply_widget_scaling(self._corner_radius),
            self._apply_widget_scaling(bw),
            self._apply_widget_scaling(left_section_width))

        requires_recoloring_2 = self._draw_engine.draw_dropdown_arrow(
            self._apply_widget_scaling(self._current_width - (self._current_height / 2)),
            self._apply_widget_scaling(self._current_height / 2),
            self._apply_widget_scaling(self._current_height / 3))

        if no_color_updates is False or requires_recoloring or requires_recoloring_2:
            self._canvas.configure(bg=self._apply_appearance_mode(self._bg_color))

            border_c = self._apply_appearance_mode(bc)
            self._canvas.itemconfig("border_parts_left", outline=border_c, fill=border_c)
            self._canvas.itemconfig("border_parts_right", outline=border_c, fill=border_c)

            self._canvas.itemconfig("inner_parts_left",
                                    outline=self._apply_appearance_mode(self._fg_color),
                                    fill=self._apply_appearance_mode(self._fg_color))
            self._canvas.itemconfig("inner_parts_right",
                                    outline=self._apply_appearance_mode(self._button_color),
                                    fill=self._apply_appearance_mode(self._button_color))

            self._text_label.configure(fg=self._apply_appearance_mode(self._text_color))
            self._text_label.configure(bg=self._apply_appearance_mode(self._fg_color))

            if self._state == tk.DISABLED:
                self._text_label.configure(fg=(self._apply_appearance_mode(self._text_color_disabled)))
                self._canvas.itemconfig("dropdown_arrow",
                                        fill=self._apply_appearance_mode(self._text_color_disabled))
            else:
                self._text_label.configure(fg=self._apply_appearance_mode(self._text_color))
                arrow_c = self._apply_appearance_mode(getattr(self, '_dropdown_arrow_color', ('#AAAAAA', '#555555')))
                self._canvas.itemconfig("dropdown_arrow", fill=arrow_c)

        self._canvas.update_idletasks()

    ctk.CTkOptionMenu._draw = _custom_om_draw

    def _custom_om_on_enter(self, event=0):
        self._close_on_next_click = self._dropdown_menu.is_open()
        if self._hover is True and self._state == tk.NORMAL and len(self._values) > 0:
            fill_col = self._apply_appearance_mode(self._button_hover_color)
            hover_border = self._apply_appearance_mode(BORDER_HOVER)
            self._canvas.itemconfig("border_parts_left", outline=hover_border, fill=hover_border)
            self._canvas.itemconfig("border_parts_right", outline=hover_border, fill=hover_border)
            self._canvas.itemconfig("inner_parts_left", outline=fill_col, fill=fill_col)
            self._canvas.itemconfig("inner_parts_right", outline=fill_col, fill=fill_col)
            self._canvas.itemconfig("dropdown_arrow", fill=self._apply_appearance_mode(ACCENT))

    def _custom_om_on_leave(self, event=0):
        fg_col = self._apply_appearance_mode(self._fg_color)
        btn_col = self._apply_appearance_mode(self._button_color)
        normal_border = self._apply_appearance_mode(getattr(self, '_border_color', BORDER))
        self._canvas.itemconfig("border_parts_left", outline=normal_border, fill=normal_border)
        self._canvas.itemconfig("border_parts_right", outline=normal_border, fill=normal_border)
        self._canvas.itemconfig("inner_parts_left", outline=fg_col, fill=fg_col)
        self._canvas.itemconfig("inner_parts_right", outline=btn_col, fill=btn_col)
        arrow_c = self._apply_appearance_mode(getattr(self, '_dropdown_arrow_color', ('#AAAAAA', '#555555')))
        self._canvas.itemconfig("dropdown_arrow", fill=arrow_c)

    ctk.CTkOptionMenu._on_enter = _custom_om_on_enter
    ctk.CTkOptionMenu._on_leave = _custom_om_on_leave

    _orig_om_init = ctk.CTkOptionMenu.__init__

    def _patched_om_init(self, master, **kwargs):
        kwargs.setdefault('fg_color', BG_CARD)
        kwargs.setdefault('button_color', BG_CARD)
        kwargs.setdefault('button_hover_color', BG_CARD_HOVER)
        kwargs.setdefault('text_color', TEXT_PRI)
        kwargs.setdefault('dropdown_fg_color', BG_CARD)
        kwargs.setdefault('dropdown_hover_color', ACCENT)
        kwargs.setdefault('dropdown_text_color', WHITE)
        kwargs.setdefault('corner_radius', CONTROL_RADIUS)
        kwargs.setdefault('dynamic_resizing', False)
        _orig_om_init(self, master, **kwargs)
        self._border_width = 1
        self._border_color = BORDER

    ctk.CTkOptionMenu.__init__ = _patched_om_init
    ctk.CTkOptionMenu._theme_patched = True


patch_ctk_option_menu_theme()


# ==============================================================================
# Heroicons Vector Engine (4x Supersampling with Lanczos Filter)
# ==============================================================================

_HEROICON_CACHE = {}


def render_heroicon(kind: str, size: int = 16, color='#FF4D6D', stroke_width: float = 1.5):
    """Renders an authentic Heroicons v2 24x24 icon at 4x supersampling with Lanczos resampling.
    Supports:
      - 'bookmark' (outline): exact Heroicons v2 outline bookmark
      - 'bookmark_solid' / 'bookmark_fill': exact Heroicons v2 solid bookmark
      - 'download' / 'arrow_down_tray': clean Heroicons v2 download arrow
      - 'check': checkmark
    Returns a PIL.Image.Image.
    """
    key = (kind, size, color, stroke_width)
    if key in _HEROICON_CACHE:
        return _HEROICON_CACHE[key]

    from PIL import Image, ImageDraw

    scale = 4
    canvas_size = size * scale
    img = Image.new('RGBA', (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    s = canvas_size / 24.0
    sw = max(1.0, stroke_width * s)

    def pt(x, y):
        return (x * s, y * s)

    def draw_lines(points, width=sw, close=False):
        pts = [pt(x, y) for x, y in points]
        if close and pts[0] != pts[-1]:
            pts.append(pts[0])
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i+1]], fill=color, width=int(round(width)), joint='curve')
            r = width / 2.0
            draw.ellipse([pts[i][0]-r, pts[i][1]-r, pts[i][0]+r, pts[i][1]+r], fill=color)
        r = width / 2.0
        draw.ellipse([pts[-1][0]-r, pts[-1][1]-r, pts[-1][0]+r, pts[-1][1]+r], fill=color)

    def draw_polygon(points, fill=color):
        pts = [pt(x, y) for x, y in points]
        draw.polygon(pts, fill=fill)

    # Exact Heroicons v2 24x24 Bookmark coordinates from SVG path:
    # <path stroke-linecap="round" stroke-linejoin="round" d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25 4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0 1 11.186 0Z" />
    bookmark_pts = [
        (4.5, 21.0),
        (4.5, 5.507),
        (4.565, 4.969),
        (4.75, 4.477),
        (5.041, 4.047),
        (5.423, 3.699),
        (5.883, 3.451),
        (6.407, 3.322),
        (12.0, 3.15),
        (17.593, 3.322),
        (18.116, 3.451),
        (18.576, 3.699),
        (18.959, 4.047),
        (19.25, 4.477),
        (19.435, 4.969),
        (19.5, 5.507),
        (19.5, 21.0),
        (12.0, 17.25),
        (4.5, 21.0),
    ]

    if kind in ('bookmark', 'bookmark_outline', 'save'):
        draw_lines(bookmark_pts, width=sw, close=True)
    elif kind in ('bookmark_solid', 'bookmark_fill', 'saved', 'save_solid'):
        draw_polygon(bookmark_pts[:-1], fill=color)
    elif kind in ('download', 'arrow_down_tray'):
        draw_lines([(12.0, 3.5), (12.0, 16.2)], width=sw)
        draw_lines([(7.5, 11.7), (12.0, 16.2), (16.5, 11.7)], width=sw)
        tray_pts = [
            (3.8, 15.5),
            (3.8, 18.5),
            (4.4, 19.8),
            (5.5, 20.5),
            (18.5, 20.5),
            (19.6, 19.8),
            (20.2, 18.5),
            (20.2, 15.5),
        ]
        draw_lines(tray_pts, width=sw)
    elif kind in ('check', 'checkmark'):
        draw_lines([(3.5, 12.5), (9.0, 18.0), (20.5, 6.0)], width=sw * 1.25)
    elif kind in ('refresh', 'reload', 'arrow_path'):
        draw.arc([pt(4.5, 4.5), pt(19.5, 19.5)], start=210, end=40, fill=color, width=int(round(sw)))
        draw.arc([pt(4.5, 4.5), pt(19.5, 19.5)], start=30, end=220, fill=color, width=int(round(sw)))
        draw_lines([(17.5, 2.5), (20.5, 5.5), (17.5, 8.5)], width=sw)
        draw_lines([(6.5, 21.5), (3.5, 18.5), (6.5, 15.5)], width=sw)
    elif kind in ('star', 'star_solid'):
        star_pts = [
            (12.0, 2.5), (14.9, 8.5), (21.5, 9.4), (16.7, 14.1),
            (17.8, 20.6), (12.0, 17.5), (6.2, 20.6), (7.3, 14.1),
            (2.5, 9.4), (9.1, 8.5)
        ]
        draw_polygon(star_pts, fill=color)
    elif kind in ('star_outline',):
        star_pts = [
            (12.0, 2.5), (14.9, 8.5), (21.5, 9.4), (16.7, 14.1),
            (17.8, 20.6), (12.0, 17.5), (6.2, 20.6), (7.3, 14.1),
            (2.5, 9.4), (9.1, 8.5)
        ]
        draw_lines(star_pts, width=sw, close=True)
    else:
        r = 4.0 * s
        draw.ellipse([pt(12 - r, 12 - r), pt(12 + r, 12 + r)], fill=color)

    out = img.resize((size, size), Image.Resampling.LANCZOS)
    _HEROICON_CACHE[key] = out
    return out


_CTK_HEROICON_CACHE = {}


def get_heroicon_image(kind: str, size: int = 16, color=None, stroke_width: float = 1.5, source_size: int = None):
    """Returns a ctk.CTkImage for `kind` ('bookmark', 'bookmark_solid', 'download', 'check').
    If color is not specified, defaults to appropriate theme colors (TEXT_PRI / ACCENT / vibrant green SUCCESS).

    `size` is the logical display size in points. CustomTkinter renders the image at
    ``size * widget_scaling`` on high-DPI displays, so the icon is drawn at a higher native
    resolution (`source_size`, default ``size * 4``) to keep it sharp when scaled down.
    """
    if source_size is None:
        source_size = max(size * 4, 64)
    key = (kind, size, tuple(color) if isinstance(color, (tuple, list)) else color, stroke_width, source_size)
    if key in _CTK_HEROICON_CACHE:
        return _CTK_HEROICON_CACHE[key]

    try:
        import customtkinter as ctk
    except ImportError:
        return None

    if color is None:
        if kind in ('bookmark_solid', 'bookmark_fill', 'saved', 'save_solid'):
            light_c = ACCENT[0]
            dark_c = ACCENT[1]
        elif kind in ('check', 'checkmark'):
            light_c = '#16a34a'
            dark_c = '#22c55e'
        else:
            light_c = TEXT_PRI[0]
            dark_c = TEXT_PRI[1]
    elif isinstance(color, (tuple, list)):
        light_c = color[0]
        dark_c = color[1] if len(color) > 1 else color[0]
    else:
        light_c = color
        dark_c = color

    im_light = render_heroicon(kind, size=source_size, color=light_c, stroke_width=stroke_width)
    im_dark = render_heroicon(kind, size=source_size, color=dark_c, stroke_width=stroke_width)

    ctk_img = ctk.CTkImage(light_image=im_light, dark_image=im_dark, size=(size, size))
    _CTK_HEROICON_CACHE[key] = ctk_img
    return ctk_img



