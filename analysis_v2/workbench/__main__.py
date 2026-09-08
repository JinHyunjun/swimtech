"""Start with: python -m analysis_v2.workbench"""
import argparse
from pathlib import Path


def main() -> None:
    import uvicorn
    from .app import create_app
    parser = argparse.ArgumentParser(description="SwimMate local video review lab")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=Path("tmp/analysis_v2/workbench"))
    args = parser.parse_args()
    # Deliberately no --host option: videos and labels are private local data.
    uvicorn.run(create_app(args.data_dir), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
