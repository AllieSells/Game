"""Quick-launch entry point: start directly in the game world."""
import os

# Toggle fast path in main.py startup.
os.environ["DOA_QUICK_START"] = "1"

import main


if __name__ == "__main__":
    main.main()
