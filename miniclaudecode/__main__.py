"""支持 `python -m miniclaudecode` 直接启动。"""
from .main import main

if __name__ == "__main__":
    raise SystemExit(main())
