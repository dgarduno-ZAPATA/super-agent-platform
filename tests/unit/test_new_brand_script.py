from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_new_brand_script_creates_correct_structure(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    script_path = root / "scripts" / "new_brand.py"

    brand_dir = tmp_path / "brand"
    knowledge_dir = brand_dir / "knowledge"
    knowledge_dir.mkdir(parents=True)
    (brand_dir / "brand.yaml").write_text(
        "name: SelecTrucks Zapata\nslug: selectrucks-zapata\n",
        encoding="utf-8",
    )
    (knowledge_dir / "sample.txt").write_text("doc", encoding="utf-8")
    (brand_dir / "prompt.md").write_text("prompt viejo", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(script_path), "testmoto", "TestMoto Bajío"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    generated = tmp_path / "brands" / "testmoto"
    assert generated.exists()
    assert "TestMoto Bajío" in (generated / "brand.yaml").read_text(encoding="utf-8")
    assert "testmoto" in (generated / "brand.yaml").read_text(encoding="utf-8")
    assert (generated / "prompt.md").exists()
    assert not any((generated / "knowledge").iterdir())
