"""Lightweight, shared UI for local-first subtitle translation settings."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Callable, Optional

import customtkinter as ctk

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageGrab, ImageTk
except Exception:  # pragma: no cover - backdrop gracefully falls back.
    Image = ImageEnhance = ImageFilter = ImageGrab = ImageTk = None

from locales import T, ui_font
from translation_settings import (
    ANTHROPIC,
    GEMINI,
    LOCAL,
    OPENAI,
    OPENAI_COMPATIBLE,
    TranslationSettings,
    TranslationSettingsError,
    clear_translation_api_key,
    get_translation_settings,
    save_translation_profile,
)
from ui_theme import (
    ACCENT,
    ACCENT_HOVER,
    BG_CARD,
    BG_CARD_HOVER,
    BG_DARK,
    BG_HEADER,
    BG_OVERLAY,
    BG_SIDEBAR,
    BG_INPUT,
    BORDER,
    BORDER_CARD,
    BORDER_HOVER,
    CARD_RADIUS,
    CONTROL_RADIUS,
    SUCCESS,
    TEXT_DIM,
    TEXT_PRI,
    TEXT_SEC,
    WARNING,
    WHITE,
)


_PROVIDER_ORDER = (
    LOCAL,
    OPENAI,
    ANTHROPIC,
    GEMINI,
    OPENAI_COMPATIBLE,
)
_PROVIDER_LABEL_KEYS = {
    LOCAL: "translation_provider_local",
    OPENAI: "translation_provider_openai",
    ANTHROPIC: "translation_provider_anthropic",
    GEMINI: "translation_provider_gemini",
    OPENAI_COMPATIBLE: "translation_provider_compatible",
}
_DIALOG_TEXT_WRAP = 390
_DIALOG_FIELD_HELP_WRAP = 330
_DIALOG_INLINE_WRAP = 390

# OpenAI-compatible providers accept a complete Chat Completions endpoint.
# Models stay editable because availability differs by account and installation.
_COMPATIBLE_PRESETS = {
    "DeepSeek": (
        "https://api.deepseek.com/chat/completions",
        "deepseek-v4-flash",
    ),
    "OpenRouter": (
        "https://openrouter.ai/api/v1/chat/completions",
        "openai/gpt-4.1-mini",
    ),
    "Groq": (
        "https://api.groq.com/openai/v1/chat/completions",
        "llama-3.3-70b-versatile",
    ),
    "Ollama": (
        "http://127.0.0.1:11434/v1/chat/completions",
        "your-installed-model",
    ),
    "LiteLLM": (
        "http://127.0.0.1:4000/v1/chat/completions",
        "your-model",
    ),
}


def provider_display_name(provider: str) -> str:
    """Return a localized, stable display name for a provider id."""
    return T(_PROVIDER_LABEL_KEYS.get(provider, "translation_provider_local"))


def translation_provider_summary(*, short: bool = False) -> str:
    """Describe the selected provider without exposing credentials or URLs."""
    settings = get_translation_settings()
    name = provider_display_name(settings.provider)
    if settings.provider == LOCAL:
        return (
            T("translation_provider_summary_local_short")
            if short
            else T("translation_provider_summary_local")
        )
    if short:
        return name
    if settings.api_key_source == "environment":
        state = T("translation_key_state_environment_short")
    elif settings.api_key_source == "protected":
        state = T("translation_key_state_saved_short")
    elif settings.provider == OPENAI_COMPATIBLE:
        state = T("translation_key_state_optional_short")
    else:
        state = T("translation_key_state_missing_short")
    return T("translation_provider_summary_cloud", provider=name, state=state)


def translation_failure_message(error: object) -> str:
    """Add a localized Local fallback hint without exposing profile details."""
    message = str(error or "").strip()
    try:
        uses_api = get_translation_settings().uses_api
    except Exception:
        uses_api = False
    if not uses_api:
        return message
    hint = T("translation_api_failure_local_hint")
    return f"{message} {hint}".strip()


def _provider_labels() -> list[str]:
    return [provider_display_name(provider) for provider in _PROVIDER_ORDER]


def _provider_from_label(label: str) -> str:
    by_label = {
        provider_display_name(provider): provider
        for provider in _PROVIDER_ORDER
    }
    return by_label.get(str(label or ""), LOCAL)


class ModalOverlay:
    """In-window modal container with dimmed backdrop and solid modal content."""

    def __init__(
        self,
        parent,
        *,
        max_width: int = 540,
        max_height: int = 430,
        on_close: Optional[Callable[[], None]] = None,
    ):
        self.parent = parent
        self.max_width = max_width
        self.max_height = max_height
        self.on_close = on_close
        self._is_closing = False

        parent.update_idletasks()
        pw = max(200, parent.winfo_width())
        ph = max(200, parent.winfo_height())
        mw = min(self.max_width, max(320, pw - 40))
        mh = min(self.max_height, max(280, ph - 40))

        # 1. Blurred, dimmed backdrop snapshot, with a solid fallback.
        self._backdrop_photo = None
        self._backdrop = self._make_backdrop(parent, pw, ph)
        self._backdrop.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        self._backdrop.lift()

        # Swallow all mouse & wheel interactions on backdrop
        self._backdrop.bind("<Button-1>", lambda e: "break")
        self._backdrop.bind("<Button-2>", lambda e: "break")
        self._backdrop.bind("<Button-3>", lambda e: "break")
        self._backdrop.bind("<MouseWheel>", lambda e: "break")

        self.modal = ctk.CTkFrame(
            parent,
            width=mw,
            height=mh,
            fg_color="#141417",
            corner_radius=10,
            border_width=1,
            border_color="#3A3A43",
        )
        self.modal.place(relx=0.5, rely=0.5, anchor="center")
        self.modal.pack_propagate(False)
        self.modal.lift()

        # Responsive resize binding on parent window
        try:
            self._config_bind = parent.bind("<Configure>", lambda e: self._on_parent_resize(), add="+")
        except Exception:
            pass

        # Escape shortcut
        try:
            self._esc_bind = parent.bind("<Escape>", lambda e: self.close(), add="+")
        except Exception:
            pass

    def _make_backdrop(self, parent, width: int, height: int):
        if ImageGrab is None or ImageTk is None:
            return ctk.CTkFrame(
                parent, fg_color=("#0A0A0D", "#0A0A0D"), corner_radius=0)
        try:
            parent.update()
            screen = ImageGrab.grab()
            scale_x = screen.width / max(1, parent.winfo_screenwidth())
            scale_y = screen.height / max(1, parent.winfo_screenheight())
            left = round(parent.winfo_rootx() * scale_x)
            top = round(parent.winfo_rooty() * scale_y)
            right = left + round(width * scale_x)
            bottom = top + round(height * scale_y)
            image = ImageGrab.grab(bbox=(left, top, right, bottom)).convert("RGB")
            if image.size != (width, height):
                resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
                image = image.resize((width, height), resampling)
            image = image.filter(ImageFilter.GaussianBlur(radius=6))
            image = ImageEnhance.Brightness(image).enhance(0.42)
            image = ImageEnhance.Contrast(image).enhance(0.88)
            self._backdrop_photo = ImageTk.PhotoImage(image)
            return tk.Label(
                parent,
                image=self._backdrop_photo,
                bg="#08080A",
                borderwidth=0,
                highlightthickness=0,
            )
        except Exception:
            self._backdrop_photo = None
            return ctk.CTkFrame(
                parent, fg_color=("#0A0A0D", "#0A0A0D"), corner_radius=0)

    def _on_parent_resize(self):
        if self._is_closing or not self.parent or not self.parent.winfo_exists():
            return
        try:
            pw = max(200, self.parent.winfo_width())
            ph = max(200, self.parent.winfo_height())
            mw = min(self.max_width, max(320, pw - 40))
            mh = min(self.max_height, max(280, ph - 40))
            if self._backdrop and self._backdrop.winfo_exists():
                self._backdrop.place_configure(x=0, y=0, relwidth=1.0, relheight=1.0)
            if self.modal and self.modal.winfo_exists():
                self.modal.configure(width=mw, height=mh)
        except Exception:
            pass

    def close(self):
        if self._is_closing:
            return
        self._is_closing = True
        if getattr(self, "on_close", None):
            try:
                self.on_close()
            except Exception:
                pass
        self.destroy()

    def destroy(self):
        if getattr(self, "_backdrop", None) is not None:
            try:
                self._backdrop.destroy()
            except Exception:
                pass
            self._backdrop = None
        if getattr(self, "modal", None) is not None:
            try:
                self.modal.destroy()
            except Exception:
                pass
            self.modal = None

    def winfo_exists(self) -> bool:
        return bool(self.modal and self.modal.winfo_exists())

    def bind(self, *args, **kwargs):
        if self.modal and self.modal.winfo_exists():
            return self.modal.bind(*args, **kwargs)
        return None

    def deiconify(self):
        if self._backdrop and self._backdrop.winfo_exists():
            tk.Misc.lift(self._backdrop)
        if self.modal and self.modal.winfo_exists():
            self.modal.lift()

    def lift(self):
        self.deiconify()

    def focus_force(self):
        if self.modal and self.modal.winfo_exists():
            self.modal.focus_force()


class TranslationSettingsDialog(ModalOverlay):
    """Subtitle translation settings modal dialog powered by ModalOverlay."""

    def __init__(
        self,
        parent,
        *,
        on_saved: Optional[Callable[[], None]] = None,
    ):
        self._on_saved = on_saved
        self._provider = get_translation_settings().provider
        self._key_source = "none"

        super().__init__(parent, max_width=474, max_height=398)

        self._build()
        self._load_provider(self._provider)

    def _build(self):
        font = ui_font()

        header = ctk.CTkFrame(
            self.modal, fg_color="transparent", height=54
        )
        header.pack(fill="x", padx=20, pady=(18, 4))
        header.pack_propagate(False)

        close_btn = ctk.CTkButton(
            header,
            text="x",
            width=28,
            height=28,
            corner_radius=6,
            fg_color="transparent",
            hover_color="#252530",
            text_color=TEXT_PRI,
            font=("Consolas", 15),
            command=self.close,
        )
        close_btn.pack(side="right")

        ctk.CTkLabel(
            header,
            text=T("translation_dialog_title"),
            text_color=TEXT_PRI,
            font=(font, 14, "bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text=T("translation_dialog_subtitle"),
            text_color=TEXT_SEC,
            font=(font, 9),
        ).pack(anchor="w", pady=(6, 0))

        # Content Body
        body = ctk.CTkScrollableFrame(
            self.modal,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BORDER_HOVER,
        )
        body.pack(fill="both", expand=True)
        content = ctk.CTkFrame(body, fg_color="transparent")
        content.pack(fill="x", padx=16, pady=(8, 6))

        source_card = ctk.CTkFrame(
            content,
            fg_color=BG_CARD,
            corner_radius=CARD_RADIUS,
            border_width=1,
            border_color=BORDER_CARD,
        )
        source_card.pack(fill="x")
        ctk.CTkLabel(
            source_card,
            text=T("translation_source_title"),
            text_color=TEXT_PRI,
            font=(font, 13),
        ).pack(anchor="w", padx=18, pady=(15, 8))
        ctk.CTkLabel(
            source_card,
            text=T("translation_source_desc"),
            text_color=TEXT_SEC,
            font=(font, 10),
            wraplength=_DIALOG_TEXT_WRAP,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 14))

        self._provider_var = ctk.StringVar()
        ctk.CTkOptionMenu(
            source_card,
            variable=self._provider_var,
            values=_provider_labels(),
            command=self._on_provider_change,
            height=36,
            corner_radius=CONTROL_RADIUS,
            fg_color=BG_CARD,
            button_color=BG_CARD,
            button_hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI,
            dropdown_fg_color=BG_CARD,
            dropdown_hover_color=ACCENT,
            dropdown_text_color=WHITE,
            font=(font, 10),
            dropdown_font=(font, 11),
        ).pack(fill="x", padx=18, pady=(0, 17))

        self._local_card = ctk.CTkFrame(
            content,
            fg_color=BG_CARD,
            corner_radius=CARD_RADIUS,
            border_width=1,
            border_color=BORDER_CARD,
        )
        ctk.CTkLabel(
            self._local_card,
            text=T("translation_local_title"),
            text_color=TEXT_PRI,
            font=(font, 13),
        ).pack(anchor="w", padx=18, pady=(16, 10))
        ctk.CTkLabel(
            self._local_card,
            text=T("translation_local_desc"),
            text_color=TEXT_SEC,
            font=(font, 10),
            wraplength=_DIALOG_TEXT_WRAP,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 18))

        self._cloud_card = ctk.CTkFrame(
            content,
            fg_color=BG_CARD,
            corner_radius=CARD_RADIUS,
            border_width=1,
            border_color=BORDER_CARD,
        )
        self._cloud_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self._cloud_card,
            text=T("translation_cloud_privacy"),
            text_color=TEXT_PRI,
            font=(font, 10, "bold"),
            wraplength=_DIALOG_TEXT_WRAP,
            justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=18, pady=(16, 4))
        ctk.CTkLabel(
            self._cloud_card,
            text=T("translation_cloud_policy_notice"),
            text_color=WARNING,
            font=(font, 9),
            wraplength=_DIALOG_TEXT_WRAP,
            justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=18, pady=(0, 14))

        self._url_label = ctk.CTkLabel(
            self._cloud_card,
            text=T("translation_base_url_label"),
            text_color=TEXT_SEC,
            font=(font, 10, "bold"),
            width=110,
            anchor="w",
        )
        self._url_label.grid(row=2, column=0, sticky="w", padx=(18, 8), pady=5)
        self._base_url_var = ctk.StringVar()
        self._base_url_entry = ctk.CTkEntry(
            self._cloud_card,
            textvariable=self._base_url_var,
            height=36,
            corner_radius=CONTROL_RADIUS,
            fg_color=BG_INPUT,
            border_color=BORDER,
            border_width=1,
            text_color=TEXT_PRI,
            font=(font, 10),
        )
        self._base_url_entry.grid(
            row=2, column=1, columnspan=2, sticky="ew", padx=(0, 18), pady=5
        )

        ctk.CTkLabel(
            self._cloud_card,
            text=T("translation_model_label"),
            text_color=TEXT_SEC,
            font=(font, 10, "bold"),
            width=110,
            anchor="w",
        ).grid(row=3, column=0, sticky="w", padx=(18, 8), pady=5)
        self._model_var = ctk.StringVar()
        ctk.CTkEntry(
            self._cloud_card,
            textvariable=self._model_var,
            height=36,
            corner_radius=CONTROL_RADIUS,
            fg_color=BG_INPUT,
            border_color=BORDER,
            border_width=1,
            text_color=TEXT_PRI,
            font=(font, 10),
        ).grid(
            row=3, column=1, columnspan=2, sticky="ew", padx=(0, 18), pady=5
        )

        ctk.CTkLabel(
            self._cloud_card,
            text=T("translation_api_key_label"),
            text_color=TEXT_SEC,
            font=(font, 10, "bold"),
            width=110,
            anchor="w",
        ).grid(row=4, column=0, sticky="w", padx=(18, 8), pady=5)
        self._api_key_var = ctk.StringVar()
        self._api_key_entry = ctk.CTkEntry(
            self._cloud_card,
            textvariable=self._api_key_var,
            placeholder_text=T("translation_api_key_placeholder"),
            show="•",
            height=36,
            corner_radius=CONTROL_RADIUS,
            fg_color=BG_INPUT,
            border_color=BORDER,
            border_width=1,
            text_color=TEXT_PRI,
            font=(font, 10),
        )
        self._api_key_entry.grid(
            row=4, column=1, sticky="ew", padx=(0, 8), pady=5
        )
        self._clear_key_btn = ctk.CTkButton(
            self._cloud_card,
            text=T("translation_clear_key"),
            width=78,
            height=34,
            corner_radius=CONTROL_RADIUS,
            fg_color="transparent",
            border_width=1,
            border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER,
            text_color=TEXT_SEC,
            font=(font, 9),
            command=self._clear_key,
        )
        self._clear_key_btn.grid(
            row=4, column=2, sticky="e", padx=(0, 18), pady=5
        )

        self._key_status = ctk.CTkLabel(
            self._cloud_card,
            text="",
            text_color=TEXT_DIM,
            font=(font, 9),
            anchor="w",
            wraplength=_DIALOG_FIELD_HELP_WRAP,
            justify="left",
        )
        self._key_status.grid(
            row=5, column=1, columnspan=2, sticky="w", padx=(0, 18), pady=(0, 7)
        )

        self._compatible_frame = ctk.CTkFrame(
            self._cloud_card, fg_color="transparent"
        )
        self._compatible_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            self._compatible_frame,
            text=T("translation_compatible_preset"),
            text_color=TEXT_SEC,
            font=(font, 10, "bold"),
            width=110,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=5)
        self._preset_var = ctk.StringVar(
            value=T("translation_compatible_custom")
        )
        ctk.CTkOptionMenu(
            self._compatible_frame,
            variable=self._preset_var,
            values=[
                T("translation_compatible_custom"),
                *_COMPATIBLE_PRESETS.keys(),
            ],
            command=self._on_preset,
            height=34,
            corner_radius=CONTROL_RADIUS,
            fg_color=BG_CARD,
            button_color=BG_CARD,
            button_hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI,
            dropdown_fg_color=BG_CARD,
            dropdown_hover_color=ACCENT,
            dropdown_text_color=WHITE,
            font=(font, 10, "bold"),
            dropdown_font=(font, 10),
        ).grid(row=0, column=1, sticky="ew", pady=5)
        ctk.CTkLabel(
            self._compatible_frame,
            text=T("translation_compatible_help"),
            text_color=TEXT_DIM,
            font=(font, 9),
            wraplength=_DIALOG_FIELD_HELP_WRAP,
            justify="left",
        ).grid(row=1, column=1, sticky="w", pady=(0, 6))
        self._compatible_frame.grid(
            row=6, column=0, columnspan=3, sticky="ew", padx=18, pady=(0, 8)
        )

        self._inline_status = ctk.CTkLabel(
            content,
            text="",
            text_color=TEXT_DIM,
            font=(font, 10, "bold"),
            wraplength=_DIALOG_INLINE_WRAP,
            justify="left",
        )
        self._inline_status.pack(anchor="w", pady=(12, 0))

        footer = ctk.CTkFrame(
            self.modal, fg_color="transparent", height=52
        )
        footer.pack(side="bottom", fill="x", padx=20, pady=(10, 18))

        ctk.CTkButton(
            footer,
            text=T("translation_close"),
            width=86,
            height=36,
            corner_radius=8,
            fg_color="transparent",
            border_width=1,
            border_color="#333342",
            hover_color="#22222D",
            text_color=TEXT_PRI,
            font=(font, 11),
            command=self.close,
        ).pack(side="right", padx=(8, 0))

        self._save_btn = ctk.CTkButton(
            footer,
            text=T("translation_save_replace"),
            width=140,
            height=36,
            corner_radius=8,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color=WHITE,
            font=(font, 11, "bold"),
            command=self._save,
        )
        self._save_btn.pack(side="right")

    def _on_provider_change(self, label: str):
        self._load_provider(_provider_from_label(label))

    def _load_provider(self, provider: str):
        self._provider = provider
        settings = get_translation_settings(provider)
        self._key_source = settings.api_key_source
        self._provider_var.set(provider_display_name(provider))
        self._api_key_var.set("")  # Never decrypt a stored key into the UI.
        self._inline_status.configure(text="")

        if provider == LOCAL:
            self._cloud_card.pack_forget()
            self._local_card.pack(
                fill="x", pady=(14, 0), before=self._inline_status)
            self._save_btn.configure(text=T("translation_use_local"))
            return

        self._local_card.pack_forget()
        self._cloud_card.pack(
            fill="x", pady=(14, 0), before=self._inline_status)
        self._save_btn.configure(text=T("translation_save_replace"))

        # Base URL & model defaults
        if provider == OPENAI:
            self._url_label.configure(text=T("translation_base_url_optional"))
            self._base_url_entry.configure(
                placeholder_text="https://api.openai.com/v1 (optional)")
            self._base_url_var.set(settings.base_url or "")
            self._model_var.set(settings.model or "gpt-4o-mini")
            self._compatible_frame.grid_remove()
        elif provider == ANTHROPIC:
            self._url_label.configure(text=T("translation_base_url_optional"))
            self._base_url_entry.configure(
                placeholder_text="https://api.anthropic.com (optional)")
            self._base_url_var.set(settings.base_url or "")
            self._model_var.set(settings.model or "claude-3-5-haiku-latest")
            self._compatible_frame.grid_remove()
        elif provider == GEMINI:
            self._url_label.configure(text=T("translation_base_url_optional"))
            self._base_url_entry.configure(
                placeholder_text="https://generativelanguage.googleapis.com (optional)")
            self._base_url_var.set(settings.base_url or "")
            self._model_var.set(settings.model or "gemini-2.5-flash")
            self._compatible_frame.grid_remove()
        elif provider == OPENAI_COMPATIBLE:
            self._url_label.configure(text=T("translation_base_url_required"))
            self._base_url_entry.configure(
                placeholder_text="https://api.deepseek.com/chat/completions")
            self._base_url_var.set(settings.base_url or "")
            self._model_var.set(settings.model or "deepseek-v4-flash")
            self._compatible_frame.grid(
                row=6, column=0, columnspan=3, sticky="ew", padx=18, pady=(0, 8))
            self._preset_var.set(T("translation_compatible_custom"))

        self._refresh_key_status(settings)

    def _refresh_key_status(self, settings):
        if settings.api_key_source == "environment":
            self._key_status.configure(
                text=T("translation_key_source_env"), text_color=SUCCESS)
        elif settings.api_key_source == "protected":
            self._key_status.configure(
                text=T("translation_key_source_saved"), text_color=SUCCESS)
        elif settings.provider == OPENAI_COMPATIBLE:
            self._key_status.configure(
                text=T("translation_key_source_optional"), text_color=TEXT_DIM)
        else:
            self._key_status.configure(
                text=T("translation_key_source_missing"), text_color=WARNING)

    def _on_preset(self, label: str):
        preset = _COMPATIBLE_PRESETS.get(label)
        if not preset:
            return
        url, model = preset
        self._base_url_var.set(url)
        self._model_var.set(model)

    def _clear_key(self):
        clear_translation_api_key(self._provider)
        settings = get_translation_settings(self._provider)
        self._key_source = settings.api_key_source
        self._api_key_var.set("")
        self._refresh_key_status(settings)
        self._inline_status.configure(
            text=T("translation_key_cleared"), text_color=TEXT_SEC)

    def _save(self):
        candidate_key = self._api_key_var.get().strip()
        if (
            self._provider != LOCAL
            and self._provider != OPENAI_COMPATIBLE
            and not candidate_key
            and self._key_source == "none"
        ):
            messagebox.showerror(
                T("translation_error_title"),
                T("translation_api_key_required"),
                parent=self.modal if getattr(self, "modal", None) else self.parent,
            )
            return
        try:
            settings = save_translation_profile(
                self._provider,
                base_url=self._base_url_var.get(),
                model=self._model_var.get(),
                api_key=(candidate_key if candidate_key else None),
            )
        except TranslationSettingsError as exc:
            messagebox.showerror(
                T("translation_error_title"), str(exc),
                parent=self.modal if getattr(self, "modal", None) else self.parent)
            return
        self._api_key_var.set("")
        self._refresh_key_status(settings)
        self._inline_status.configure(
            text=T("translation_saved_cloud"), text_color=SUCCESS)
        if self._on_saved:
            self._on_saved()
        self.destroy()


def open_translation_settings_dialog(parent, *, on_saved=None):
    """Open one provider settings dialog per parent window."""
    existing = getattr(parent, "_translation_settings_dialog", None)
    try:
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return existing
    except tk.TclError:
        pass

    dialog = TranslationSettingsDialog(parent, on_saved=on_saved)
    parent._translation_settings_dialog = dialog

    def _forget(_event=None):
        if getattr(parent, "_translation_settings_dialog", None) is dialog:
            parent._translation_settings_dialog = None

    dialog.bind("<Destroy>", _forget, add="+")
    return dialog
