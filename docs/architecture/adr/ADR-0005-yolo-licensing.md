# ADR-0005 — Licencia de YOLO: modelo ONNX propio en vez de Ultralytics AGPL

- **Estado**: Aceptado (decisión de rumbo; se revisa al llegar a Fase 3)
- **Fecha**: 2026-06-22
- **Requisitos**: R-AI · Roadmap Fase 3

## Contexto

The Watcher es un producto **cerrado/comercial** (SIG Systems). El framework Ultralytics YOLO
(v5+) está bajo **AGPL-3.0**, que para software distribuido/en red puede obligar a divulgar el código
fuente. Usar Ultralytics directamente en el producto es un riesgo legal.

Sin embargo, un modelo **exportado a ONNX** es solo un artefacto de formato; ejecutarlo no arrastra la
licencia del framework de entrenamiento. Los runtimes de inferencia permisivos existen:
**ONNX Runtime** (MIT) y su binding Rust **`ort`** (Apache/MIT), con backends **DirectML** (DirectX 12
en Windows) y CUDA.

## Decisión

Para la inferencia del producto **no** se enlazará Ultralytics. Se usará un **modelo en formato ONNX**
(propio o de origen con licencia compatible) servido por **ONNX Runtime** vía el crate Rust **`ort`**
(reusando la cadena PyO3/maturin del motor de segmentos). La exportación a ONNX, si se parte de pesos
Ultralytics, es un paso *one-time* fuera del producto y debe revisarse legalmente caso por caso.

## Consecuencias

- ✅ Inferencia con licencia permisiva, compatible con producto cerrado.
- ✅ GPU en Windows vía DirectML sin depender de CUDA/NVIDIA exclusivamente.
- ✅ Reutiliza la infraestructura Rust ya montada (PyO3/maturin) → menos superficie nueva.
- ➖ Hay que entrenar/obtener el modelo y validar la procedencia de los pesos (no asumir que cualquier
  `.onnx` de un repo AGPL es libre de obligaciones).
- 🔁 Decisión a confirmar al iniciar la Fase 3 con asesoría legal de SIG.
