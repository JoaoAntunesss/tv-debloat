"""TV Debloat — an interface to clean up an Android TV over ADB (wireless), reversibly.

python main.py          → uses your TV
python main.py --demo   → try it with a simulated TV (needs: pip install pillow)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> None:
    try:
        from ui.app import App
    except ModuleNotFoundError as e:
        if e.name and e.name.startswith("tkinter"):
            print("Tkinter is missing. Linux: sudo apt install python3-tk · macOS: brew install python-tk")
            raise SystemExit(1)
        raise
    app = App()
    if "--demo" in sys.argv:
        from ui.demo import enable_demo

        enable_demo(app)
    app.mainloop()


if __name__ == "__main__":
    main()
