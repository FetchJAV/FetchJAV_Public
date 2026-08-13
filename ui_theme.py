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
    if width >= 1400:
        return 4
    if width >= 750:
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


