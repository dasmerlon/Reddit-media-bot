#!/bin/python3
import sys
from mediabot.download import download_media


def main():
    """Commandline entry point."""
    url = sys.argv[1]
    info, media = download_media(url)
    if info is None:
        return

    print(info)
    print(type(media))


main()
