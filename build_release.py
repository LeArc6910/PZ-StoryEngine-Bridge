"""브릿지 배포판(Windows exe) 만들기.

필요: pip install pyinstaller openai anthropic google-genai
실행: python build_release.py
결과: ../release/StoryEngineBridge-<버전>-win64.zip (+ SHA256)

onedir 방식으로 묶는다 (onefile 은 실행할 때마다 임시 폴더에 풀어서 백신 오탐이 더 잦다).
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RELEASE = ROOT / "release"
NAME = "StoryEngineBridge"


def version() -> str:
    for line in (HERE / "bridge.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("BRIDGE_VERSION"):
            return line.split("=")[1].strip().strip('"')
    return "0.0.0"


def notices() -> str:
    """번들에 들어간 파이썬 패키지(openai, anthropic, google-genai 와 그 의존성)의 이름·버전·라이선스 목록."""
    import importlib.metadata as md
    import re
    seen, queue, rows = set(), ["openai", "anthropic", "google-genai"], []
    while queue:
        name = queue.pop(0)
        key = name.lower().replace("_", "-")
        if key in seen:
            continue
        seen.add(key)
        try:
            meta = md.metadata(name)
        except md.PackageNotFoundError:
            continue
        lic = meta.get("License-Expression") or ""
        if not lic:
            classifiers = [c.split("::")[-1].strip() for c in (meta.get_all("Classifier") or []) if c.startswith("License")]
            lic = ", ".join(classifiers) or (meta.get("License") or "see package")[:80]
        rows.append(f"| {meta['Name']} | {meta['Version']} | {lic} | {meta.get('Home-page') or ''} |")
        for req in md.requires(name) or []:
            if "extra ==" in req:
                continue
            queue.append(re.split(r"[ ;<>=!~\[(]", req, maxsplit=1)[0])
    rows.sort(key=str.lower)
    lines = [
        "# Third-party notices",
        "",
        "StoryEngine Bridge bundles the following software. Each is used under its own license.",
        "",
        f"- Python {sys.version.split()[0]} (Python Software Foundation License)",
        "- PyInstaller bootloader (GPL-2.0 with a special exception that allows distributing bundled applications)",
        "",
        "| Package | Version | License | Home |",
        "|---|---|---|---|",
    ]
    return "\n".join(lines + rows) + "\n"


def main() -> int:
    try:
        import PyInstaller.__main__ as pyi
    except ImportError:
        print("PyInstaller is not installed: pip install pyinstaller")
        return 1
    for sdk, pkg in (("openai", "openai"), ("anthropic", "anthropic"), ("google.genai", "google-genai")):
        try:
            __import__(sdk)
        except ImportError:
            print(f"{pkg} SDK is not installed: pip install {pkg}")
            return 1

    ver = version()
    build = RELEASE / "build"
    dist = build / "dist"
    shutil.rmtree(build, ignore_errors=True)
    sep = ";" if sys.platform == "win32" else ":"
    pyi.run([
        str(HERE / "bridge.py"),
        "--name", NAME,
        "--onedir", "--console", "--noconfirm", "--clean",
        "--add-data", f"{HERE / 'prompts'}{sep}prompts",
        # 제공자는 설정에 따라 동적으로 import 한다
        "--hidden-import", "setup_wizard",
        "--hidden-import", "providers.mock",
        "--hidden-import", "providers.openai_provider",
        "--hidden-import", "providers.anthropic_provider",
        "--hidden-import", "providers.gemini_provider",
        "--collect-submodules", "google.genai",
        "--paths", str(HERE),
        "--distpath", str(dist),
        "--workpath", str(build / "work"),
        "--specpath", str(build),
    ])

    out = dist / NAME
    for doc in ("README_EN.md", "README_KO.md"):
        shutil.copy2(HERE / "release_docs" / doc, out / doc)
    shutil.copy2(HERE / "config.example.toml", out / "config.example.toml")
    (out / "THIRD_PARTY_NOTICES.md").write_text(notices(), encoding="utf-8")
    # 투명성을 위해 소스도 함께 넣는다 (exe 대신 python bridge.py 로 실행 가능). 개인 설정(config.toml)은 넣지 않는다
    src = out / "source"
    for f in ["bridge.py", "modules.py", "setup_wizard.py", "requirements.txt", "config.example.toml"]:
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERE / f, src / f)
    shutil.copytree(HERE / "providers", src / "providers", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(HERE / "prompts", src / "prompts")
    assert not (out / "config.toml").exists() and not (src / "config.toml").exists(), "config.toml must not be shipped"

    RELEASE.mkdir(exist_ok=True)
    zip_path = RELEASE / f"{NAME}-{ver}-win64.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in out.rglob("*"):
            if f.is_file():
                z.write(f, Path(NAME) / f.relative_to(out))
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (RELEASE / f"{zip_path.name}.sha256").write_text(f"{digest}  {zip_path.name}\n", encoding="ascii")
    print(f"\n{zip_path}\nSHA256 {digest}\nsize {zip_path.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
