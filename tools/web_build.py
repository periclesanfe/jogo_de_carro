"""Build the browser version (pygbag 0.9.3) as a static site in build/www:

    index.html          redirects to the current build; serve it with Cache-Control: no-cache
    jogo/<TREE>/        index.html, jogo.tar.gz (the game) and favicon.png; CI's gate adds golden.txt
    cdn/                pygbag's runtime, fetched from upstream and checked against web/cdn.lock, plus .gz
                        copies

TREE names everything the build is made of, so every path but the top index.html can be cached forever:
``git rev-parse HEAD:src/jogo_de_carro HEAD:web HEAD:tools/web_build.py | git hash-object --stdin``, as CI
and ops/jogo-deploy compute it ("dev" while those differ from HEAD). Needs ``pip install pygbag==0.9.3`` and
ffmpeg.

    python tools/web_build.py
"""

import gzip
import hashlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "www"
PYGBAG = "0.9.3"
UPSTREAM = "https://pygame-web.github.io/cdn/"
RUNTIME_TAG = f'<script src="/cdn/{PYGBAG}/pythons.js"'
INPUTS = ("src/jogo_de_carro", "web", "tools/web_build.py")
# pygbag fetches wheels from GitHub whatever --cdn says unless PYGPI is set, and it reads env only from the
# page's URL: pythons.js takes what follows its last "?" (before the last "#"), split on "&", and the last
# PYGPI wins. So ours goes last and the fragment is dropped: a "#?PYGPI=..." would move that last "?".
PYGPI = (
    '<script>history.replaceState(null,"",location.pathname'
    '+(location.search?location.search+"&":"?")+"PYGPI=/cdn/")</script>'
)


def git(*args: str, stdin: str | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, input=stdin, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def mirror(cdn: Path) -> None:
    """pygbag's runtime byte for byte as web/cdn.lock pins it (files already there and intact are kept)."""
    for line in (ROOT / "web" / "cdn.lock").read_text().splitlines():
        digest, rel = line.split()
        path = cdn / rel
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            continue
        data = urllib.request.urlopen(UPSTREAM + rel, timeout=60).read()
        if hashlib.sha256(data).hexdigest() != digest:
            sys.exit(f"{UPSTREAM}{rel} does not match web/cdn.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    for path in cdn.rglob("*"):  # for servers that send precompressed files (the runtime is 20 MB raw)
        if path.suffix in (".wasm", ".data", ".js"):
            path.with_name(path.name + ".gz").write_bytes(gzip.compress(path.read_bytes(), 9, mtime=0))


def main() -> None:
    if version("pygbag") != PYGBAG:
        sys.exit(f"needs pygbag=={PYGBAG}, found {version('pygbag')}")
    if git("status", "--porcelain", "--", *INPUTS):
        tree = "dev"  # not what HEAD holds: never deployable
    else:
        tree = git("hash-object", "--stdin", stdin=git("rev-parse", *(f"HEAD:{i}" for i in INPUTS)) + "\n")
    mirror(OUT / "cdn")
    dest = OUT / "jogo" / tree
    with tempfile.TemporaryDirectory() as tmp:
        app = Path(tmp) / "jogo"  # the folder names the bundle: jogo.tar.gz
        pkg = app / "jogo_de_carro"
        shutil.copytree(ROOT / "src" / "jogo_de_carro", pkg, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(ROOT / "web" / "main.py", app)
        (pkg / "_build.py").write_text(f'BUILD = "{tree}"\n')
        for wav in pkg.rglob("*.wav"):  # browsers need OGG; ffmpeg's own vorbis encoder is stereo only
            ogg = ["-c:a", "vorbis", "-strict", "-2", "-ac", "2", "-q:a", "3", wav.with_suffix(".ogg")]
            subprocess.run(["ffmpeg", "-loglevel", "error", "-i", wav, *ogg], check=True)
            wav.unlink()
        # --no_opt: on Linux pygbag would otherwise re-encode the audio and pngquant the sprites (the masks!)
        pygbag = ["--build", "--no_opt", "--title", "Jogo de Carro", "--cdn", f"/cdn/{PYGBAG}/"]
        pygbag += ["--template", OUT / "cdn" / PYGBAG / "default.tmpl", "--icon", pkg / "assets" / "icon.png"]
        done = subprocess.run(
            [sys.executable, "-m", "pygbag", *pygbag, app], cwd=app, capture_output=True, text=True
        )
        web = app / "build" / "web"
        html = (web / "index.html").read_text("utf-8") if (web / "index.html").is_file() else ""
        if done.returncode or html.count(RUNTIME_TAG) != 1:  # a bad template gives no index.html and exit 0
            sys.exit(f"{done.stdout}{done.stderr}\npygbag failed: no index.html loading {RUNTIME_TAG}>")
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True)
        (dest / "index.html").write_text(html.replace(RUNTIME_TAG, PYGPI + RUNTIME_TAG), "utf-8")
        for name in ("jogo.tar.gz", "favicon.png"):
            shutil.copy(web / name, dest)
    url = f"jogo/{tree}/"
    (OUT / "index.html").write_text(
        f'<!doctype html><meta http-equiv="refresh" content="0; url={url}"><a href="{url}">Jogar</a>\n'
    )
    print(dest)


if __name__ == "__main__":
    main()
