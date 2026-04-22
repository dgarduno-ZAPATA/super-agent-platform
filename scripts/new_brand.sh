#!/usr/bin/env bash
set -euo pipefail

# Uso: ./scripts/new_brand.sh <slug> <nombre>
# Ejemplo: ./scripts/new_brand.sh testmoto "TestMoto Bajío"

SLUG="${1:-}"
NAME="${2:-}"

if [[ -z "$SLUG" || -z "$NAME" ]]; then
  echo "Uso: $0 <slug> <nombre>"
  exit 1
fi

if [[ ! -d "brand" ]]; then
  echo "Error: no existe la carpeta brand/ en el directorio actual"
  exit 1
fi

TARGET_DIR="brands/$SLUG"
if [[ -e "$TARGET_DIR" ]]; then
  echo "Error: ya existe $TARGET_DIR/"
  exit 1
fi

echo "Creando nueva marca: $NAME ($SLUG)"

mkdir -p "brands"
cp -r "brand" "$TARGET_DIR"

if [[ -f "$TARGET_DIR/brand.yaml" ]]; then
  sed -i "s/SelecTrucks Zapata/$NAME/g" "$TARGET_DIR/brand.yaml"
  sed -i "s/selectrucks-zapata/$SLUG/g" "$TARGET_DIR/brand.yaml"
fi

if [[ -d "$TARGET_DIR/knowledge" ]]; then
  find "$TARGET_DIR/knowledge" -type f -delete
fi

cat > "$TARGET_DIR/prompt.md" <<EOF
# Identidad
Eres [NOMBRE_AGENTE], asesor comercial de $NAME.

## Instrucciones
- Responde en español mexicano profesional
- Máximo 3 oraciones por mensaje
- No prometas precios ni disponibilidad sin validar

[PERSONALIZAR ANTES DE USAR]
EOF

echo "Marca creada en: $TARGET_DIR/"
echo ""
echo "Próximos pasos:"
echo "1. Edita $TARGET_DIR/brand.yaml con los datos reales"
echo "2. Edita $TARGET_DIR/prompt.md con la identidad del agente"
echo "3. Agrega documentos en $TARGET_DIR/knowledge/"
echo "4. Configura BRAND_PATH=$TARGET_DIR/ en las env vars del deploy"
echo "5. Haz deploy"
