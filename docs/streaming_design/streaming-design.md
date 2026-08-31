# Streaming desde clickstream (solo diseño, no implementado)

---

## Objetivo

Explicar cómo se ingeriría en tiempo real el flujo de clickstream de la
app móvil, sin implementarlo.

## Esquema de evento propuesto (ilustrativo)

```json
{
  "event_id": "a1b2c3d4-...",
  "event_type": "product_view | add_to_cart | purchase",
  "customer_id": 12345,
  "product_id": 678,
  "session_id": "e5f6...",
  "timestamp": "2026-08-20T14:32:10Z",
  "channel": "app"
}
```

## Arquitectura propuesta

![](/Workspace/Users/cornachofrance@gmail.com/andina_market/docs/streaming_design/streaming_architecture.png)

### Consumo directo con Structured Streaming (sin paso intermedio por archivos)

1. La app emite cada evento (vista de producto, agregar al carrito, compra)
   al tópico de **Kafka** en el momento en que ocurre.

2. **Structured Streaming** lee directo del tópico
   (`spark.readStream.format("kafka")`) y escribe en modo streaming a
   `bronze.clickstream_events` (Tabla Delta), con `outputMode("append")` y
   `option("mergeSchema", "true")`.

3. Desde Bronze en adelante, **mismo tratamiento que el resto del
   pipeline**: Silver deduplica por `event_id` y estandariza `event_type`;
   Gold puede alimentar métricas (vista → carrito → compra)
   directamente, sin necesitar un modelo dimensional separado.

**Por qué este camino y no un paso intermedio por archivos (Capture/Kafka
Connect + Auto Loader):** 

`mergeSchema` y `append mode` son propiedades de
**Delta Lake como formato de tabla**, no del mecanismo de ingesta: no se
gana nada de esas dos capacidades por pasar antes por archivos. Consumir
Kafka directo da latencia de segundos (no minutos), evita mantener un
componente adicional (el conector que volcaría Kafka a archivos), y
Structured Streaming maneja el checkpointing de offsets de Kafka de forma
nativa, con la misma garantía de exactly-once que tendría un flujo basado en
archivos.

### Cuándo SÍ tendría sentido un paso intermedio por archivos

Si se necesitara un **archivo crudo permanente** más allá de lo
que Kafka retiene (los tópicos suelen retener solo unos días de historia por
costo). 