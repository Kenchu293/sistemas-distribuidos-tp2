import json
import pika
import threading
import time
from fastapi import FastAPI

app = FastAPI(title="Notifications Service")

processed_orders = set()


@app.get("/conexion")
def conexion():
    return {
        "status": "ok",
        "service": "notifications"
    }


processed_orders = set()

def callback(ch, method, properties, body):
    data = json.loads(body)
    order_id = data.get("order_id")

    # Idempotencia (Requisito Estación 4)
    if order_id in processed_orders:
        ch.basic_ack(delivery_tag=method.delivery_tag)
        return

    print(f" [x] Notificando pedido: {order_id}")
    processed_orders.add(order_id)
    
    # Confirmación manual (Requisito Estación 4)
    ch.basic_ack(delivery_tag=method.delivery_tag)

def consume_messages():
    while True:
        try:
            conn = pika.BlockingConnection(pika.ConnectionParameters(host="rabbitmq"))
            ch = conn.channel()
            
            # Cola persistente
            ch.queue_declare(queue="order_created", durable=True)
            ch.basic_qos(prefetch_count=1)
            ch.basic_consume(queue="order_created", on_message_callback=callback)

            print(" [*] Esperando mensajes. CTRL+C para salir")
            ch.start_consuming()

        except pika.exceptions.AMQPConnectionError:
            print(" [!] RabbitMQ no disponible, reintentando...")
            time.sleep(5)

@app.on_event("startup")
def startup_event():
    thread = threading.Thread(target=consume_messages, daemon=True)
    thread.start()