"""The one egress helper the target_australia module uses: the
Accept-Language its sessions send."""


def accept_language(proxy=None):
    """Australian English through a proxy (config.py recommends an Australian
    one), US English on a direct connection."""
    return "en-AU,en;q=0.9" if proxy else "en-US,en;q=0.9"
