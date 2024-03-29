"""Media download and download info extraction logic."""
import json
import os
import pprint
import random
import secrets
import string
from urllib.request import Request, urlopen

import yt_dlp
from yt_dlp.utils import sanitize_filename

from mediabot import log
from mediabot.link_handling import (
    info_from_gfycat,
    info_from_giphy,
    info_from_imgur,
    info_from_ireddit,
    info_from_vreddit,
    info_from_youtube,
)

headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:68.0) Gecko/20100101 Firefox/68.0",
}


class Info:
    """Class representing information about a media file."""

    url = None
    type = None
    extension = None
    caption = None
    title = None
    youtube = False
    youtube_url = None

    def __init__(self):
        self.youtube = False


def handle_reddit_web_url(url):
    """Download media from reddit from a given web url."""
    log("\nGet media info from reddit")
    info = Info()
    info.youtube_url = url
    if not url.endswith(".json"):
        url += ".json"
    info.json_url = url

    # Get the json information from reddit
    log(f"--- Download Json: {url}")
    request = Request(url, headers=headers)
    response = urlopen(request)
    data = response.read().decode("utf-8")
    payload = json.loads(data)

    # Extract the media information from the payload
    try:
        info = get_media_info(payload, info)
    except Exception as e:
        log(f"--- Got exception: {e}")
        raise e

    # Check if we got some kind of info
    if info is None:
        return None, None

    log("--- Got media info:")
    log(f"--- {pprint.pformat(info)}")

    log("Get media:")
    info, media = download_media(info)

    return info, media


def get_media_info(payload, info):
    """Get the information of the media from the payload."""
    data = payload[0]["data"]["children"][0]["data"]
    if "crosspost_parent_list" in data:
        data = data["crosspost_parent_list"][0]

    info.title = data["title"]

    # Reddit hosted images
    if data["domain"] == "i.redd.it":
        return info_from_ireddit(info, data["url"])

    # Reddit hosted videos
    elif data["domain"] == "v.redd.it":
        return info_from_vreddit(info, data["media"]["reddit_video"]["fallback_url"])

    # Gfycat videos
    elif data["domain"] == "gfycat.com":
        return info_from_gfycat(info, data["url"])

    # Giphy videos
    elif data["domain"] == "media.giphy.com":
        return info_from_giphy(info, data["url"])

    # Youtube video
    elif data["domain"] == "youtu.be":
        return info_from_youtube(info, data["url"])

    # Imgur
    elif data["domain"] in ["i.imgur.com", "imgur.com"]:
        return info_from_imgur(info, data["url"])

    log("--- Failed to detect media type")
    return None


def download_media(info):
    """Get the actual media by the given info."""
    # If we are supposed to use youtube-dl, try using it.
    # Videos with sound or youtube videos can be downloaded
    # more easily with youtube-dl
    if info.type == "video" and info.youtube:
        log("--- Try youtube-dl")
        info, media = download_youtube_media(info)
        # We got some media return it
        if media is not None:
            return info, media

        # If youtube-dl failed, continue and try a direct download
        log("--- youtube-dl failed")

    elif info.type == "audio" and info.youtube:
        log("--- Try music download via youtube-dl")
        info, media = download_youtube_music(info)
        # We got some media return it
        if media is not None:
            return info, media

        # Fail hard if this fails
        log("--- Music download via youtube-dl failed")
        return None, None

    log(f"--- Downloading media directly: {info.url}")
    request = Request(info.url, headers=headers)
    response = urlopen(request)
    media = response.read()

    # Convert GIFs to mp4.
    if info.extension == "gif":
        log("--- Found GIF. Convert to mp4")
        temp_dir = "/tmp/redditbot/"

        if not os.path.exists(temp_dir):
            os.mkdir(temp_dir)

        source_file = (
            temp_dir
            + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
            + ".gif"
        )
        target_file = (
            temp_dir
            + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
            + ".mp4"
        )
        # Write the file to disk so we can work on it with ffmpeg.
        with open(source_file, "wb") as file:
            file.write(media)

        # Convert it to mp4
        os.system(
            f'ffmpeg -i {source_file} -movflags faststart -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" {target_file}'
        )

        # Read converted file
        with open(target_file, "rb") as file:
            media = file.read()

        os.remove(target_file)
        info.extension = "mp4"

    return info, media


def download_youtube_media(info):
    """Try to download a clip via youtube-dl."""
    random_hash = secrets.token_hex(nbytes=8)
    hash = "reddit_" + random_hash
    options = {
        "outtmpl": f"/tmp/{hash}_%(title)s.%(ext)s",
        "quiet": True,
        "restrictfilenames": True,
    }
    # Try to download the media with youtube-dl
    log(f"--- Downloading via youtube: {info.youtube_url}")
    try:
        ydl = yt_dlp.YoutubeDL(options)
        yd_info = ydl.extract_info(info.youtube_url)

        # Remove invalid chars that are removed from the title by youtube
        title = sanitize_filename(yd_info["title"], True)
        info.extension = yd_info["ext"]

        path = f"/tmp/{hash}_{title}.{yd_info['ext']}"

        # youtube-dl might produce mkv containers, if the downloaded formats don't match
        # However there's no indicator that this is happening.
        # Check if the target file doesn't exist as mp4, but rather as mkv.
        # If that's the case, convert to mp4 via ffmpeg
        mkv_path = f"/tmp/{hash}_{title}.mkv"
        if not os.path.exists(path) and os.path.exists(mkv_path):
            path = f"/tmp/{hash}_{title}.mp4"
            os.system(f"ffmpeg -i '{mkv_path}' -c copy '{path}'")
            os.remove(mkv_path)
            info.extension = "mp4"

        # Read in RAM and remove the oiginal file
        with open(path, "rb") as file:
            media = file.read()
        os.remove(path)

        log("--- Got media")
        return info, media

    except Exception as e:
        log("--- Failed to use youtube-dl")
        print(e)
        return info, None


def download_youtube_music(info):
    """Try to extract the audio of a clip via youtube-dl."""
    random_hash = secrets.token_hex(nbytes=8)
    hash = "reddit_" + random_hash
    options = {
        "outtmpl": f"/tmp/{hash}_%(title)s.%(ext)s",
        "quiet": True,
        "format": "bestaudio",
        "restrictfilenames": True,
    }
    # Try to download the media with youtube-dl
    log(f"--- Downloading song ia youtube: {info.youtube_url}")
    try:
        ydl = yt_dlp.YoutubeDL(options)
        yd_info = ydl.extract_info(info.youtube_url)

        # Remove invalid chars that are removed from the title by youtube
        title = sanitize_filename(yd_info["title"], True)

        # Convert the webm to mp3
        temp_path = f"/tmp/{hash}_{title}.{yd_info['ext']}"
        target_path = f"/tmp/{hash}_{title}.mp3"
        os.system(f"ffmpeg -i '{temp_path}' -q:a 0 -map a '{target_path}'")

        info.extension = "mp3"

        # Read in RAM and remove the oiginal files
        with open(target_path, "rb") as file:
            media = file.read()
        os.remove(temp_path)
        os.remove(target_path)

        log("--- Got media")
        return info, media

    except Exception as e:
        log("--- Failed to use youtube-dl")
        print(e)
        return info, None
