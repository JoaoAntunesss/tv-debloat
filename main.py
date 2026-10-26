"""TV Debloat — interface para limpar uma Android TV por ADB (sem fios), de forma reversível."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> None:
    try:
        from ui.app import App
    except ModuleNotFoundError as e:
        if e.name and e.name.startswith("tkinter"):
            print("Falta o Tkinter. Linux: sudo apt install python3-tk · macOS: brew install python-tk")
            raise SystemExit(1)
        raise
    App().mainloop()


if __name__ == "__main__":
    main()
