#!/usr/bin/env python3
"""
Uso: python scripts/new_brand.py <slug> <nombre>
Ejemplo: python scripts/new_brand.py testmoto "TestMoto Bajío"
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 3:
        print("Uso: python scripts/new_brand.py <slug> <nombre>")
        sys.exit(1)

    slug = sys.argv[1].strip()
    name = " ".join(sys.argv[2:]).strip()
    if not slug or not name:
        print("Uso: python scripts/new_brand.py <slug> <nombre>")
        sys.exit(1)

    brand_src = Path("brand")
    brand_dst = Path("brands") / slug

    if not brand_src.exists():
        print("Error: no existe brand/")
        sys.exit(1)
    if brand_dst.exists():
        print(f"Error: ya existe brands/{slug}/")
        sys.exit(1)

    brand_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(brand_src, brand_dst)

    yaml_path = brand_dst / "brand.yaml"
    if yaml_path.exists():
        content = yaml_path.read_text(encoding="utf-8")
        content = content.replace("SelecTrucks Zapata", name)
        content = content.replace("selectrucks-zapata", slug)
        yaml_path.write_text(content, encoding="utf-8")

    knowledge_dir = brand_dst / "knowledge"
    if knowledge_dir.exists():
        for file_path in knowledge_dir.iterdir():
            if file_path.is_file():
                file_path.unlink()

    prompt_path = brand_dst / "prompt.md"
    prompt_path.write_text(
        f"# Identidad\n"
        f"Eres [NOMBRE_AGENTE], asesor comercial de {name}.\n\n"
        f"## Instrucciones\n"
        f"- Responde en español mexicano profesional\n"
        f"- Máximo 3 oraciones por mensaje\n"
        f"- No prometas precios ni disponibilidad sin validar\n\n"
        f"[PERSONALIZAR ANTES DE USAR]\n",
        encoding="utf-8",
    )

    print(f"Marca creada en: brands/{slug}/")
    print("\nPróximos pasos:")
    print(f"1. Edita brands/{slug}/brand.yaml")
    print(f"2. Edita brands/{slug}/prompt.md")
    print(f"3. Agrega documentos en brands/{slug}/knowledge/")
    print(f"4. Configura BRAND_PATH=brands/{slug}/ en las env vars del deploy")
    print("5. Deploy")


if __name__ == "__main__":
    main()
