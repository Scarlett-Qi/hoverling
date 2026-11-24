"""Check public GitHub releases when the user requests it."""
import http.client
import re
import threading
import urllib.error
import urllib.request

from . import __version__

REPOSITORY = "Scarlett-Qi/hoverling"
RELEASES = f"https://github.com/{REPOSITORY}/releases"
LATEST_URL = RELEASES + "/latest"
VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def release_result(url, installed=__version__):
    prefix = RELEASES + "/tag/"
    if not url.startswith(prefix):
        raise ValueError("Expected the project’s release page")
    tag = url[len(prefix):]
    latest = VERSION.fullmatch(tag.removeprefix("v"))
    base, separator, _ = installed.partition("-")
    current = VERSION.fullmatch(base)
    if not latest or not current:
        raise ValueError("Unrecognized version")
    remote = tuple(map(int, latest.groups()))
    local = tuple(map(int, current.groups()))
    if remote > local or (remote == local and separator):
        return f"查看新版 v{latest[0]}", url
    return ("已是最新版" if remote == local else "暂无更新"), None


def check_update():
    # GitHub redirects /latest to the tag of the release marked Latest.
    request = urllib.request.Request(LATEST_URL, method="HEAD", headers={"User-Agent": f"HoverLing/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return release_result(response.geturl())
    except urllib.error.HTTPError as error:
        with error:
            if error.code == 429 or (error.code == 403 and error.headers.get("X-RateLimit-Remaining") == "0"):
                return "请求受限，稍后重试", None
        return "检查失败，点此重试", None
    except (OSError, http.client.HTTPException, ValueError):
        return "检查失败，点此重试", None


def start_update_check(dispatch, finished):
    def work():
        message, url = check_update()
        dispatch(finished, message, url)

    threading.Thread(target=work, name="hoverling-update", daemon=True).start()
