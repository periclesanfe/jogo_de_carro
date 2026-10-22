"""Build the browser version (pygbag 0.9.3) as a static site in build/www:

    index.html          redirects to the current build; serve it with Cache-Control: no-cache
    current             that build's TREE, the one the server's /jogar sends players to (jogo-deploy writes
                        its own on the VPS)
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
# pygbag sizes the canvas to its buffer's aspect, starting while the buffer is still 1x1 (a square), and the
# gray page is the template's. CSS sizes it instead: 16:9, as large as the window allows, centred by pygbag's
# own inset:0;margin:auto, while SDL keeps drawing 1280x720 (app.py: no RESIZABLE on the web).
# Nearest-neighbour only when that scales up: scaling down, it drops the thin strokes of the small text.
FIT = (
    "<style>body{background:#0b0d18!important;overflow:hidden}"
    "#canvas{width:min(100vw,100dvh*16/9)!important;height:min(100dvh,100vw*9/16)!important;outline:none}"
    "@media (min-width:1280px) and (min-height:720px){#canvas{image-rendering:pixelated}}</style>"
)
# A CSS-scaled canvas gets its pointer coordinates scaled twice: emscripten maps them to the buffer for any
# canvas whose getContext("2d") is null (ours holds WebGL), and SDL2 maps them again by the CSS size. So
# getContext("2d") on our canvas answers {} where it would answer null, and only SDL scales.
MOUSE = (
    "<script>{const g=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext="
    'function(t,...a){return g.call(this,t,...a)||(t=="2d"&&this.id=="canvas"?{}:null)}}</script>'
)
# A loading screen in the site's look over pygbag's (its English text hidden), until web/main.py removes
# it as the game draws its first frame. Its bar follows the template's own milestones: the runtime's download
# (#progress counts main.data's decoded bytes against its gzipped length, so it ends near 148: *.4 makes
# ~60%), "Running..." in #status, Python up (#canvas made visible), the game's code in (#infobox hidden).
# Before the first of them, or with no length to count against, the bar is indeterminate.
# No "click to start" (--ume_block 0): the game starts in a suspended AudioContext that SDL resumes on the
# first keydown, mousedown or touchstart only, and a touchstart cannot (a tap's touchend can): any key or tap
# resumes it.
LOADER = (
    "<style>#infobox,#transfer{display:none!important}"
    "#loader{position:fixed;inset:0;z-index:9;display:flex;flex-direction:column;align-items:center;"
    "justify-content:center;gap:18px;padding:16px;text-align:center;color:#949cb4;"
    "background:radial-gradient(ellipse 120% 60% at 50% 0,#2a2e4a,#1a1c2c 70%) #1a1c2c;"
    'font:700 17px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}'
    "#loader img{image-rendering:pixelated}"
    "#loader h1{margin:0;font-size:clamp(2rem,10vw,3.3rem);font-weight:900;line-height:1.05;"
    "white-space:nowrap;background:linear-gradient(180deg,#ffe678 20%,#f77622);-webkit-background-clip:text;"
    "background-clip:text;color:transparent;filter:drop-shadow(0 4px 0 rgba(0,0,0,.35))}"
    "#bar{width:min(320px,100%);height:12px;border-radius:6px;background:#0b0d18;overflow:hidden}"
    "#bar i{display:block;height:100%;width:var(--p,30%);border-radius:inherit;background:#ffcd3c;"
    "transition:width .3s}"
    "#bar:not([aria-valuenow]) i{animation:wait 1s ease-in-out infinite alternate}"
    "@keyframes wait{to{margin-left:70%}}"
    "@media (prefers-reduced-motion:reduce){#bar i{transition:none}"
    "#bar:not([aria-valuenow]) i{animation:none;width:100%;opacity:.4}}</style>"
    '<div id=loader><img src=favicon.png alt="" width=96 height=96><h1>JOGO DE CARRO</h1>'
    '<div id=bar role=progressbar aria-label="Carregando o jogo"><i></i></div>'
    "<p id=msg role=status>Baixando o motor…</p></div>"
    '<script>{const $=document.getElementById.bind(document),bar=$("bar"),msg=$("msg");let at=0;'
    'new MutationObserver(()=>{const v=$("infobox").style.display=="none"?85:$("canvas").style.visibility?70:'
    '/^Down/.test($("status").textContent)?$("progress").getAttribute("value")*.4:62;if(v<=at)return;at=v;'
    'bar.setAttribute("aria-valuenow",at|0);bar.style.setProperty("--p",at+"%");'
    'const t=at<60?"Baixando o motor…":at<85?"Preparando a pista…":"Aquecendo os pneus…";'
    "if(msg.textContent!=t)msg.textContent=t}).observe(document.body,"
    '{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:["value","style"]});'
    'for(const e of["keydown","pointerup","touchend"])'
    "addEventListener(e,()=>window.Module?.SDL2?.audioContext?.resume(),true)}</script>"
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
        pygbag += ["--can_close", "1"]  # no "leave this page?" prompt when SITE navigates away
        pygbag += ["--ume_block", "0"]  # no "click to start": LOADER resumes the audio on any key or tap
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
        html = html.replace(RUNTIME_TAG, PYGPI + FIT + MOUSE + RUNTIME_TAG)
        html = html.replace('lang="en-us"', 'lang="pt-BR"', 1)  # LOADER's language, for screen readers
        (dest / "index.html").write_text(html.replace("</body>", LOADER + "</body>"), "utf-8")
        for name in ("jogo.tar.gz", "favicon.png"):
            shutil.copy(web / name, dest)
    url = f"jogo/{tree}/"
    (OUT / "current").write_text(tree + "\n")
    (OUT / "index.html").write_text(
        f'<!doctype html><meta http-equiv="refresh" content="0; url={url}"><a href="{url}">Jogar</a>\n'
    )
    print(dest)


if __name__ == "__main__":
    main()
