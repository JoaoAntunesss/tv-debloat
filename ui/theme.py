"""Modern look (dark, neon accent). Uses sv-ttk if available; otherwise the default look stays."""
from __future__ import annotations

from tkinter import ttk

BG = "#14161c"
CARD = "#1c1f27"
SIDE = "#0f1116"
LINE = "#2a2e3a"
TEXT = "#e8eaf0"
MUTED = "#8b93a7"
ACCENT = "#2ee6a6"      # verde neon
INFO = "#4cc9f0"
WARN = "#ffb454"
DANGER = "#ff6b6b"
VIOLET = "#b794f6"
FONT = ("Segoe UI", 10)

try:
    import sv_ttk
except Exception:  # pragma: no cover
    sv_ttk = None

HAS_THEME = sv_ttk is not None


def apply(root) -> None:
    if sv_ttk is not None:
        try:
            sv_ttk.set_theme("dark")
        except Exception:
            return
    st = ttk.Style(root)
    base = st.lookup("TFrame", "background") or BG
    root.configure(bg=base)
    st.configure("TLabelframe.Label", foreground=ACCENT, font=(FONT[0], 10, "bold"))
    st.configure("Treeview", rowheight=26)
    st.configure("Treeview.Heading", font=(FONT[0], 10, "bold"))
    # notebook without tabs: navigation is the sidebar
    st.layout("Tabless.TNotebook.Tab", [])
    st.configure("Tabless.TNotebook", borderwidth=0, tabmargins=0)


def style_text(widget) -> None:
    """Classic Tk text boxes/lists (they do not follow the ttk theme)."""
    try:
        widget.configure(bg=CARD, fg=TEXT, insertbackground=TEXT, relief="flat", highlightthickness=1,
                         highlightbackground=LINE, highlightcolor=ACCENT, selectbackground="#27407a",
                         selectforeground=TEXT)
    except Exception:
        pass
