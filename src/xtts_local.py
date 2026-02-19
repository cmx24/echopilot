# src/xtts_local.py
import sys, os

def main():
    print("XTTS Local - packaged app")
    if len(sys.argv) > 1:
        print("Args:", sys.argv[1:])
    ffmpeg_path = os.path.join(os.getcwd(), "ffmpeg", "ffmpeg.exe")
    if os.path.exists(ffmpeg_path):
        print("ffmpeg found at", ffmpeg_path)
    else:
        print("ffmpeg not found. Place ffmpeg.exe in the ffmpeg folder or install ffmpeg on PATH.")
    try:
        import platform
        print("Python", platform.python_version(), "on", platform.system())
    except Exception as e:
        print("Runtime check failed:", e)

if __name__ == "__main__":
    main()
