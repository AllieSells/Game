from sys import exception
from pypresence import Presence

try:

    CLIENT_ID = "1509269648330194954" # RPC ID

    RPC = Presence(CLIENT_ID)
    RPC.connect()


    def update(state: str = None, details: str = None):
        try:
            RPC.update(state=state, details=details, large_image="logo", large_text="Dungeons of Ærrok")
        except Exception as e:
            print(f"[WARNING]: Failed to update RPC: {e}")

    def get_status():
        try:
            return RPC.get()
        except Exception as e:
            print(f"[WARNING]: Failed to get RPC status: {e}")
            return None
except Exception as e:
    print(f"[WARNING]: Failed to initialize RPC: {e}")