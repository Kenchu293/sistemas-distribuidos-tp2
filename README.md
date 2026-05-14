# TP2 — Sistema Distribuido de Gestión de Órdenes

Sistema de microservicios que simula una plataforma de e-commerce, desarrollado con Python, gRPC, RabbitMQ y Docker.

---

## ¿Qué hace este proyecto?

Imaginate una tienda online simplificada. Cuando un usuario quiere comprar un producto, pasan varias cosas al mismo tiempo:

1. Se verifica si hay stock disponible.
2. Se reserva el stock para ese pedido.
3. Se crea la orden de compra.
4. Se envía una notificación de que la orden fue procesada.

Cada una de estas responsabilidades está separada en un **servicio independiente**. Eso es exactamente lo que hace este proyecto: divide la lógica en cuatro microservicios que se comunican entre sí a través de distintos mecanismos.

---

## Arquitectura General

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CLIENTE (HTTP)                               │
└────────────────────────────┬────────────────────────────────────────┘
                             │ POST /orders
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│                      ORDERS SERVICE :8000                          │
│           (Orquestador principal de las órdenes)                   │
└──────────┬───────────────────────────────────┬─────────────────────┘
           │ gRPC (síncrono)                   │ RabbitMQ (asíncrono)
           │ ReserveStock()                    │ Publica en "order_created"
           ▼                                   ▼
┌─────────────────────────┐       ┌──────────────────────────────────┐
│  INVENTORY SERVICE      │       │          RABBITMQ                │
│  :8002 (HTTP)           │       │  :5672 (AMQP)                    │
│  :50051 (gRPC)          │       │  :15672 (Management UI)          │
│                         │       └──────────────────┬───────────────┘
│  Gestiona el stock      │                          │ Consume "order_created"
└─────────────────────────┘                          ▼
                                   ┌──────────────────────────────────┐
┌─────────────────────────┐        │   NOTIFICATIONS SERVICE :8003   │
│   CATALOG SERVICE       │        │                                  │
│   :8001 (HTTP)          │        │   Procesa notificaciones         │
│                         │        │   de órdenes creadas             │
│   Lista de productos    │        └──────────────────────────────────┘
└─────────────────────────┘
```

---

## Los Cuatro Microservicios

### 1. Catalog Service (Puerto 8001)
**¿Qué hace?** Expone el catálogo de productos disponibles.

Es el servicio más simple: tiene una lista de productos y responde consultas sobre ellos. No se comunica con ningún otro servicio.

| Producto | Precio |
|----------|--------|
| Hollow Knight: Silksong | $7 |
| Hunt: Showdown 1896 | $15 |
| ARC Raiders | $40 |
| Age of Empires II: Definitive Edition | $20 |

**Endpoints:**
```
GET  /conexion            → Health check
GET  /productos           → Lista todos los productos
GET  /productos/{id}      → Obtiene un producto por ID
```

---

### 2. Inventory Service (Puertos 8002 y 50051)
**¿Qué hace?** Gestiona el stock de productos y reserva unidades cuando se crea una orden.

Este servicio tiene **dos interfaces**:
- Una **REST API** (puerto 8002) para consultar el stock actual.
- Un **servidor gRPC** (puerto 50051) que recibe pedidos de reserva de stock desde el servicio de órdenes.

**Stock inicial (en memoria):**
```
Producto 1: 5 unidades
Producto 2: 20 unidades
Producto 3: 40 unidades
Producto 4: 12 unidades
```

**Endpoints REST:**
```
GET  /conexion   → Health check
GET  /stock      → Devuelve el stock actual de todos los productos
```

**RPC gRPC:**
```
ReserveStock(product_id, quantity) → { success: bool, message: string }
```
- Si hay suficiente stock: lo decrementa y retorna `success: true`.
- Si no existe el producto o no hay stock suficiente: retorna `success: false`.

---

### 3. Orders Service (Puerto 8000)
**¿Qué hace?** Es el orquestador central. Recibe la solicitud de compra del cliente, coordina la reserva de stock y emite el evento de orden creada.

**Flujo al crear una orden:**
1. Recibe `POST /orders` con `product_id` y `quantity`.
2. Llama a Inventory Service via **gRPC** para reservar el stock (síncrono, espera respuesta).
3. Si el stock no pudo reservarse → devuelve error HTTP 400.
4. Si el stock fue reservado → publica un mensaje en la cola `order_created` de **RabbitMQ**.
5. Retorna confirmación al cliente.

**Endpoints:**
```
GET  /conexion   → Health check
POST /orders     → Crea una nueva orden
```

**Request body:**
```json
{
  "product_id": 1,
  "quantity": 2
}
```

**Response exitoso:**
```json
{
  "order_id": 1,
  "product_id": 1,
  "quantity": 2,
  "status": "created"
}
```

---

### 4. Notifications Service (Puerto 8003)
**¿Qué hace?** Escucha la cola de RabbitMQ y procesa las notificaciones de órdenes creadas.

Corre un hilo en background que consume mensajes de la cola `order_created`. Implementa procesamiento **idempotente**: si un mismo mensaje llega dos veces (lo cual puede pasar en sistemas distribuidos), no lo procesa dos veces.

**Características de confiabilidad:**
- **Idempotencia:** guarda un `set` de IDs de órdenes ya procesadas.
- **Acknowledgment manual:** solo confirma el mensaje a RabbitMQ *después* de procesarlo.
- **Reconexión automática:** si RabbitMQ se cae, reintenta conectar cada 5 segundos.
- **Prefetch = 1:** procesa un mensaje a la vez para distribución justa.

**Endpoints:**
```
GET  /conexion   → Health check
```

---

## Comunicación Entre Servicios

Este proyecto usa **dos patrones de comunicación** diferentes, cada uno elegido según el caso de uso:

### gRPC (Síncrono)
Usado para: Orders Service → Inventory Service

**¿Por qué síncrono?** La reserva de stock es una operación crítica. Si falla, la orden no debe crearse. Por eso Orders Service espera la respuesta de Inventory antes de continuar.

El contrato del servicio está definido en `proto/inventory.proto`:

```protobuf
service InventoryService {
  rpc ReserveStock (ReserveStockRequest) returns (ReserveStockResponse);
}

message ReserveStockRequest {
  int32 product_id = 1;
  int32 quantity   = 2;
}

message ReserveStockResponse {
  bool   success = 1;
  string message = 2;
}
```

### RabbitMQ (Asíncrono)
Usado para: Orders Service → Notifications Service

**¿Por qué asíncrono?** Las notificaciones no son críticas para completar la orden. No tiene sentido que el cliente espere a que se procese la notificación. Con RabbitMQ, Orders Service publica el evento y sigue sin esperar.

**Cola:** `order_created` (durable — sobrevive reinicios de RabbitMQ)

**Formato del mensaje:**
```json
{
  "order_id": 1,
  "product_id": 1,
  "quantity": 2,
  "status": "created"
}
```

---

## Cómo Ejecutar el Proyecto

### Prerequisitos
- [Docker](https://www.docker.com/) y Docker Compose instalados.

### Levantar todos los servicios

```bash
docker-compose up --build
```

Esto levanta RabbitMQ y los cuatro microservicios. La primera vez tarda más por la construcción de las imágenes.

### Verificar que todo está corriendo

```bash
# Health checks de cada servicio
curl http://localhost:8001/conexion   # Catalog
curl http://localhost:8002/conexion   # Inventory
curl http://localhost:8000/conexion   # Orders
curl http://localhost:8003/conexion   # Notifications
```

### Probar el sistema de extremo a extremo

```bash
# 1. Ver el catálogo de productos
curl http://localhost:8001/productos

# 2. Ver el stock actual
curl http://localhost:8002/stock

# 3. Crear una orden (el flujo completo)
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"product_id": 1, "quantity": 2}'

# 4. Verificar que el stock bajó
curl http://localhost:8002/stock
```

### RabbitMQ Management UI

Accedé a `http://localhost:15672` con usuario `guest` / contraseña `guest` para ver las colas y mensajes en tiempo real.

### Detener los servicios

```bash
docker-compose down
```

---

## Estructura del Proyecto

```
sistemas-distribuidos-tp2/
│
├── catalog-service/
│   ├── main.py              # FastAPI app con endpoints de productos
│   ├── requirements.txt
│   └── dockerfile
│
├── inventory-service/
│   ├── main.py              # FastAPI app + servidor gRPC async
│   ├── inventory_pb2.py     # Código generado por protoc
│   ├── inventory_pb2_grpc.py
│   ├── requirements.txt
│   └── Dockerfile
│
├── orders-service/
│   ├── main.py              # FastAPI app + cliente gRPC + publisher RabbitMQ
│   ├── inventory_pb2.py     # Código generado por protoc (mismo que inventory)
│   ├── inventory_pb2_grpc.py
│   ├── requirements.txt
│   └── Dockerfile
│
├── notifications-service/
│   ├── main.py              # FastAPI app + consumer RabbitMQ en background thread
│   ├── requirements.txt
│   └── Dockerfile
│
├── proto/
│   └── inventory.proto      # Definición del contrato gRPC
│
├── k8s/
│   ├── orders-deployment.yaml   # Kubernetes Deployment (2 réplicas)
│   └── orders-service.yaml      # Kubernetes Service (NodePort 30007)
│
└── docker-compose.yml           # Orquestación local de todos los servicios
```

---

## Despliegue en Kubernetes

El directorio `k8s/` contiene manifiestos para desplegar el servicio de órdenes en un cluster de Kubernetes.

### Características del Deployment (`orders-deployment.yaml`)

```yaml
replicas: 2                     # Alta disponibilidad con 2 instancias
resources:
  limits:
    cpu: 500m                   # Máximo medio CPU por pod
    memory: 256Mi               # Máximo 256 MB de memoria
livenessProbe:
  httpGet:
    path: /health               # Reinicia el pod si no responde
readinessProbe:
  httpGet:
    path: /health               # Solo recibe tráfico cuando está listo
```

### Características del Service (`orders-service.yaml`)

```yaml
type: NodePort
port: 80          # Puerto externo
targetPort: 8000  # Puerto del contenedor
nodePort: 30007   # Acceso desde fuera del cluster
```

### Comandos básicos de Kubernetes

```bash
# Aplicar los manifiestos
kubectl apply -f k8s/

# Ver el estado de los pods
kubectl get pods

# Ver los servicios
kubectl get services

# Ver logs de un pod
kubectl logs <pod-name>
```

---

## Stack Tecnológico

| Componente | Tecnología |
|------------|-----------|
| Lenguaje | Python 3.11 |
| Framework Web | FastAPI |
| Servidor ASGI | Uvicorn |
| RPC Síncrono | gRPC + Protocol Buffers |
| Message Broker | RabbitMQ 3.13 |
| Cliente RabbitMQ | Pika |
| Validación de datos | Pydantic |
| Contenerización | Docker |
| Orquestación local | Docker Compose |
| Orquestación producción | Kubernetes |

---

## Puertos de Acceso

| Servicio | Puerto Externo | Puerto Interno | Protocolo |
|---------|----------------|----------------|-----------|
| Catalog Service | 8001 | 8000 | HTTP |
| Inventory Service | 8002 | 8000 | HTTP |
| Inventory Service | 50051 | 50051 | gRPC |
| Orders Service | 8000 | 8000 | HTTP |
| Notifications Service | 8003 | 8000 | HTTP |
| RabbitMQ (AMQP) | 5672 | 5672 | AMQP |
| RabbitMQ (UI) | 15672 | 15672 | HTTP |

---

## Características de Confiabilidad

| Característica | Dónde | Descripción |
|----------------|-------|-------------|
| Idempotencia | Notifications Service | No procesa la misma orden dos veces |
| Persistencia de mensajes | RabbitMQ | `delivery_mode=2` + colas `durable` |
| Acknowledgment manual | Notifications Service | Confirma el mensaje solo después de procesarlo |
| Reconexión automática | Notifications Service | Reintenta conectar cada 5s si RabbitMQ falla |
| Timeout gRPC | Orders Service | 5 segundos máximo para reserva de stock |
| Health checks | Todos | Endpoint `/conexion` en cada servicio |
| Usuarios no-root | Todos | Los contenedores corren como `appuser` |
| Límites de recursos | Kubernetes | CPU y memoria limitados por pod |

---

## Diagrama de Secuencia — Crear una Orden

```
Cliente          Orders         Inventory        RabbitMQ       Notifications
   │                │               │                │               │
   │ POST /orders   │               │                │               │
   │──────────────► │               │                │               │
   │                │ ReserveStock  │                │               │
   │                │ (gRPC)        │                │               │
   │                │──────────────►│                │               │
   │                │               │ Verifica stock │               │
   │                │               │ Decrementa stock               │
   │                │◄──────────────│                │               │
   │                │  success=true │                │               │
   │                │               │  Publica msg   │               │
   │                │──────────────────────────────► │               │
   │                │               │                │ Consume msg   │
   │ 200 OK         │               │                │──────────────►│
   │◄──────────────│               │                │               │
   │  {order_id:1} │               │                │               │
```

---

## Notas de Desarrollo

- Los archivos `inventory_pb2.py` e `inventory_pb2_grpc.py` son **código generado automáticamente** por `protoc` a partir de `proto/inventory.proto`. No se deben editar manualmente.
- El stock y los productos están almacenados **en memoria** (diccionarios Python). Al reiniciar los contenedores, los datos vuelven al estado inicial.
- Los servicios usan `depends_on` en Docker Compose, pero esto solo garantiza que el contenedor *inicia*, no que el servicio *está listo*. El Notifications Service maneja esto con su lógica de reconexión.
