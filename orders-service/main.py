import json
import grpc
import pika
import inventory_pb2
import inventory_pb2_grpc
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


app = FastAPI(title="Orders Service")

class OrderRequest(BaseModel):
    product_id: int
    quantity: int

@app.get("/conexion")
def conexion():
    return {"status": "ok", "service": "orders"}

async def reserve_stock(product_id: int, quantity: int):
    async with grpc.aio.insecure_channel("inventory-service:50051") as channel:
        stub = inventory_pb2_grpc.InventoryServiceStub(channel)

        response = await stub.ReserveStock(
            inventory_pb2.ReserveStockRequest(
                product_id=product_id,
                quantity=quantity
            ),
            timeout=5
        )

        return response

def publish_order_event(order_data: dict):
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host="rabbitmq")
    )
    channel = connection.channel()

    channel.queue_declare(queue="order_created", durable=True)

    channel.basic_publish(
        exchange="",
        routing_key="order_created",
        body=json.dumps(order_data),
        properties=pika.BasicProperties(
            delivery_mode=2
        )
    )

    connection.close()

@app.post("/orders")
async def create_order(order: OrderRequest):
    try:
        stock_response = await reserve_stock(
            order.product_id,
            order.quantity
        )
    except grpc.aio.AioRpcError:
        raise HTTPException(
            status_code=503,
            detail="No se pudo conectar con inventory-service"
        )

    if not stock_response.success:
        raise HTTPException(
            status_code=400,
            detail=stock_response.message
        )

    order_data = {
        "order_id": 1,
        "product_id": order.product_id,
        "quantity": order.quantity,
        "status": "created"
    }

    publish_order_event(order_data)

    return {
        "message": "Pedido Hecho correctamente",
        "inventory_message": stock_response.message,
        "order": order_data
    }