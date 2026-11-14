
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from getpass import getpass
from pathlib import Path
import xml.etree.ElementTree as ET
import shutil
import os

output = Path("provider_guide.xml")
temporary = Path("provider_guide.xml.part")

server = os.environ["XTREAM_SERVER"].rstrip("/")
username = os.environ["XTREAM_USERNAME"]
password = os.environ["XTREAM_PASSWORD"]

url = f"{server}/xmltv.php?{urlencode({'username': username, 'password': password})}"

try:
    print("\nDownloading the provider's live EPG...")
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})

    with urlopen(request, timeout=180) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP status: {response.status}")

        with temporary.open("wb") as file:
            shutil.copyfileobj(response, file)

    print("Download complete.")
    print(f"File size: {temporary.stat().st_size / (1024*1024):.1f} MB")
    print("\nChecking XML and counting entries...")

    channel_count = 0
    programme_count = 0
    root = None

    for event, elem in ET.iterparse(temporary, events=("start", "end")):
        if event == "start" and root is None:
            root = elem
            if root.tag != "tv":
                raise ValueError("Downloaded XML does not have a <tv> root.")

        elif event == "end":
            if elem.tag == "channel":
                channel_count += 1
            elif elem.tag == "programme":
                programme_count += 1

            if elem is not root:
                elem.clear()
                if root is not None:
                    root.clear()

    if channel_count == 0:
        raise ValueError("No channel entries found.")

    os.replace(temporary, output)

    print("\nLIVE EPG DOWNLOAD VERIFIED")
    print("--------------------------")
    print(f"Channels: {channel_count:,}")
    print(f"Programme entries: {programme_count:,}")
    print(f"Saved as: {output.resolve()}")

except Exception as error:
    print("\nERROR:", error)
    print("The existing guide.xml has not been changed.")
    print("Any incomplete download remains in provider_guide.xml.part.")
